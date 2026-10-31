"""
Pinos de encaixe na interface entre cores diferentes (modelos 3MF pintados).

Em um 3MF pintado, cada cor é extraída como uma "casca" aberta que compartilha exatamente
os vértices de borda com a cor vizinha. Esses laços de borda são justamente as interfaces
de montagem entre as peças coloridas: depois do capping, a tampa da cor A coincide com a
tampa da cor B.

Pipeline (100% geometria — sem IA):
1. `find_color_interfaces` — ANTES do capping, encontra os laços de borda de cada
   componente e identifica a cor vizinha que compartilha a maior parte dos vértices.
   Ajusta um plano médio ao laço (SVD), projeta em 2D e usa `polylabel` (Círculo Máximo
   Inscrito) para posicionar o pino longe das bordas.
2. `apply_color_interface_pins` — DEPOIS do capping, para cada interface valida
   volumetricamente (manifold3d) qual lado comporta o furo com parede mínima, une o pino
   macho à peça menor e subtrai o furo fêmea (com folga) da peça hospedeira.

Interfaces pequenas, muito curvas ou finas demais para o furo são ignoradas — nesses
casos as peças continuam apenas encostadas (colagem), sem risco de perfurar a superfície.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

import manifold3d as m3d
import numpy as np
import trimesh
from scipy.spatial import cKDTree
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import polylabel

from app.mesh import connector_config as cfg

logger = logging.getLogger(__name__)

_SHARED_VERTEX_EPS_MM = 1e-3
_PROBE_INSIDE_MIN_FRACTION = 0.97
_PIN_ROOT_MIN_FRACTION = 0.55
_PIN_ROOT_EMBED_MM = 1.0


@dataclass
class ColorInterface:
    """Interface candidata entre o componente `owner` e a cor vizinha `partner_piece`."""

    owner_piece: int
    owner_component: int
    partner_piece: int
    center: np.ndarray          # ponto 3D no plano médio da interface (polylabel)
    normal: np.ndarray          # normal unitária do plano médio (sentido arbitrário)
    inscribed_radius: float     # raio do maior círculo inscrito (mm)
    area: float                 # área da interface projetada (mm²)
    loop_points: np.ndarray     # vértices da borda (para localizar o componente vizinho)


@dataclass
class InterfacePinReport:
    pins_created: int
    pins_by_piece: dict[int, int]
    interfaces_found: int


# ---------------------------------------------------------------------------
# Helpers geométricos
# ---------------------------------------------------------------------------


def _boundary_loops(mesh: trimesh.Trimesh) -> list[np.ndarray]:
    """Laços de borda (arestas usadas por uma única face), vetorizado."""
    faces = np.asarray(mesh.faces)
    if len(faces) == 0:
        return []
    directed = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    sorted_e = np.sort(directed, axis=1)
    _, inverse, counts = np.unique(sorted_e, axis=0, return_inverse=True, return_counts=True)
    boundary = directed[counts[inverse.ravel()] == 1]
    if len(boundary) == 0:
        return []

    nxt: dict[int, list[int]] = defaultdict(list)
    for a, b in boundary:
        nxt[int(a)].append(int(b))

    used: set[tuple[int, int]] = set()
    loops: list[np.ndarray] = []
    for a, b in boundary:
        a, b = int(a), int(b)
        if (a, b) in used:
            continue
        loop = [a]
        used.add((a, b))
        cur = b
        guard = 0
        while cur != a and guard < len(boundary) + 2:
            guard += 1
            loop.append(cur)
            cands = [n for n in nxt[cur] if (cur, n) not in used]
            if not cands:
                break
            used.add((cur, cands[0]))
            cur = cands[0]
        if cur == a and len(loop) >= 3:
            loops.append(np.asarray(loop, dtype=np.int64))
    return loops


def _plane_fit(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    """Plano médio por SVD. Retorna (centróide, u, v, n, desvio_máximo)."""
    c = points.mean(axis=0)
    d = points - c
    _, _, vt = np.linalg.svd(d, full_matrices=False)
    u, v, n = vt[0], vt[1], vt[2]
    deviation = float(np.max(np.abs(d @ n))) if len(d) else 0.0
    return c, u, v, n, deviation


def _largest_polygon(poly: Polygon | MultiPolygon) -> Polygon | None:
    if isinstance(poly, Polygon):
        return None if poly.is_empty else poly
    if isinstance(poly, MultiPolygon) and len(poly.geoms) > 0:
        return max(poly.geoms, key=lambda g: g.area)
    return None


def _segments_for_shape(pin_shape: str) -> int:
    if pin_shape == "hex":
        return 6
    if pin_shape == "triangle":
        return 3
    return 32


def _rot_z_to(direction: np.ndarray) -> np.ndarray:
    """Matriz 3x3 que leva +Z até `direction`."""
    z = np.array([0.0, 0.0, 1.0])
    d = direction / np.linalg.norm(direction)
    c = float(np.dot(z, d))
    if c > 1.0 - 1e-9:
        return np.eye(3)
    if c < -1.0 + 1e-9:
        return np.diag([1.0, -1.0, -1.0])
    v = np.cross(z, d)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))


def _cylinder(
    start: np.ndarray,
    direction: np.ndarray,
    length: float,
    r_low: float,
    r_high: float,
    segments: int,
) -> m3d.Manifold:
    R = _rot_z_to(direction)
    affine = np.hstack([R, np.asarray(start, dtype=np.float64).reshape(3, 1)]).tolist()
    return m3d.Manifold.cylinder(
        height=float(length),
        radius_low=float(r_low),
        radius_high=float(r_high),
        circular_segments=int(segments),
        center=False,
    ).transform(affine)


def _inside_fraction(host: m3d.Manifold, probe: m3d.Manifold) -> float:
    vol = probe.volume()
    if vol <= 1e-9:
        return 0.0
    return float((host ^ probe).volume() / vol)


def _to_manifold(mesh: trimesh.Trimesh) -> m3d.Manifold | None:
    try:
        m = m3d.Manifold(
            m3d.Mesh(
                vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
                tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
            )
        )
        if m.status() == m3d.Error.NoError and m.volume() > 0:
            return m
    except Exception as exc:  # noqa: BLE001
        logger.info("Componente não convertido para manifold: %s", exc)
    return None


def _to_trimesh(m: m3d.Manifold) -> trimesh.Trimesh:
    out = m.to_mesh()
    return trimesh.Trimesh(
        vertices=np.asarray(out.vert_properties)[:, :3].astype(np.float64),
        faces=np.asarray(out.tri_verts, dtype=np.int64),
        process=False,
    )


# ---------------------------------------------------------------------------
# 1. Detecção (antes do capping)
# ---------------------------------------------------------------------------


def find_color_interfaces(component_meshes: list[list[trimesh.Trimesh]]) -> list[ColorInterface]:
    """
    Encontra interfaces entre cores a partir das cascas ABERTAS de cada cor.

    Args:
        component_meshes: para cada cor (peça), a lista de componentes conexos abertos.
    """
    n_pieces = len(component_meshes)
    if n_pieces < 2:
        return []

    piece_trees: list[cKDTree | None] = []
    for comps in component_meshes:
        verts = [c.vertices for c in comps if len(c.vertices) > 0]
        piece_trees.append(cKDTree(np.vstack(verts)) if verts else None)

    interfaces: list[ColorInterface] = []
    placed: dict[tuple[int, int], list[np.ndarray]] = defaultdict(list)

    for pi, comps in enumerate(component_meshes):
        for ci, comp in enumerate(comps):
            proc = trimesh.Trimesh(vertices=comp.vertices, faces=comp.faces, process=True)
            for loop in _boundary_loops(proc):
                pts = proc.vertices[loop]
                if len(pts) < 6:
                    continue

                best_partner, best_share = -1, 0.0
                for pk, tree in enumerate(piece_trees):
                    if pk == pi or tree is None:
                        continue
                    dist, _ = tree.query(pts, k=1)
                    share = float(np.mean(dist <= _SHARED_VERTEX_EPS_MM))
                    if share > best_share:
                        best_partner, best_share = pk, share
                if best_partner < 0 or best_share < cfg.COLOR_INTERFACE_MIN_PARTNER_SHARE:
                    continue

                c, u, v, n, deviation = _plane_fit(pts)
                if deviation > cfg.COLOR_INTERFACE_MAX_PLANE_DEVIATION_MM:
                    continue

                d = pts - c
                pts2d = np.column_stack([d @ u, d @ v])
                try:
                    poly = _largest_polygon(Polygon(pts2d).buffer(0))
                except Exception:  # noqa: BLE001
                    poly = None
                if poly is None or poly.area < cfg.COLOR_INTERFACE_MIN_AREA_MM2:
                    continue

                label_pt = polylabel(poly, tolerance=0.1)
                r_max = float(poly.exterior.distance(label_pt))
                for hole in poly.interiors:
                    r_max = min(r_max, float(hole.distance(label_pt)))
                if r_max < cfg.COLOR_INTERFACE_MIN_INSCRIBED_RADIUS_MM:
                    continue

                center = c + float(label_pt.x) * u + float(label_pt.y) * v
                pair = (min(pi, best_partner), max(pi, best_partner))
                if len(placed[pair]) >= cfg.COLOR_INTERFACE_MAX_PINS_PER_PAIR:
                    continue
                # A mesma interface é vista pelos dois lados (A→B e B→A): deduplicar.
                if any(np.linalg.norm(center - p) < max(4.0, r_max) for p in placed[pair]):
                    continue
                placed[pair].append(center)

                interfaces.append(
                    ColorInterface(
                        owner_piece=pi,
                        owner_component=ci,
                        partner_piece=best_partner,
                        center=center,
                        normal=n / np.linalg.norm(n),
                        inscribed_radius=r_max,
                        area=float(poly.area),
                        loop_points=pts,
                    )
                )

    logger.info("Interfaces entre cores candidatas a pino: %d", len(interfaces))
    return interfaces


# ---------------------------------------------------------------------------
# 2. Aplicação (depois do capping)
# ---------------------------------------------------------------------------


def _locate_component(comps: list[trimesh.Trimesh], points: np.ndarray) -> int:
    best, best_share = -1, 0.0
    for idx, comp in enumerate(comps):
        if len(comp.vertices) == 0:
            continue
        dist, _ = cKDTree(comp.vertices).query(points, k=1)
        share = float(np.mean(dist <= 0.05))
        if share > best_share:
            best, best_share = idx, share
    return best if best_share >= 0.3 else -1


def apply_color_interface_pins(
    closed_components: list[list[trimesh.Trimesh]],
    interfaces: list[ColorInterface],
    tolerance_mm: float,
    pin_shape: str = cfg.DEFAULT_PIN_SHAPE,
) -> InterfacePinReport:
    """
    Insere pino macho + furo fêmea em cada interface viável. Modifica
    `closed_components` in-place (apenas os componentes que receberam conectores).
    """
    segments = _segments_for_shape(pin_shape)
    r_min, r_max_pin = cfg.COLOR_INTERFACE_PIN_RADIUS_RANGE_MM
    h_min, h_max = cfg.COLOR_INTERFACE_PIN_HEIGHT_RANGE_MM
    wall = cfg.COLOR_INTERFACE_MIN_WALL_MM

    cache: dict[tuple[int, int], m3d.Manifold | None] = {}
    dirty: set[tuple[int, int]] = set()
    pins_by_piece: dict[int, int] = defaultdict(int)
    created = 0

    def manifold_of(key: tuple[int, int]) -> m3d.Manifold | None:
        if key not in cache:
            cache[key] = _to_manifold(closed_components[key[0]][key[1]])
        return cache[key]

    for itf in interfaces:
        a_key = (itf.owner_piece, itf.owner_component)
        b_comp = _locate_component(closed_components[itf.partner_piece], itf.loop_points)
        if b_comp < 0 or a_key[1] >= len(closed_components[a_key[0]]):
            continue
        b_key = (itf.partner_piece, b_comp)

        ma, mb = manifold_of(a_key), manifold_of(b_key)
        if ma is None or mb is None:
            continue

        r_pin = float(np.clip(itf.inscribed_radius * 0.45, r_min, r_max_pin))
        r_sock = r_pin + tolerance_mm
        if r_sock + wall > itf.inscribed_radius:
            r_sock = itf.inscribed_radius - wall
            r_pin = r_sock - tolerance_mm
        if r_pin < r_min:
            continue
        h_pin = float(np.clip(r_pin * 2.2, h_min, h_max))
        h_sock = h_pin + 0.5

        # Tenta furo no maior volume primeiro (mais material para hospedar o encaixe).
        options: list[tuple[tuple[int, int], tuple[int, int]]] = (
            [(a_key, b_key), (b_key, a_key)]
            if mb.volume() >= ma.volume()
            else [(b_key, a_key), (a_key, b_key)]
        )

        applied = False
        for pin_key, host_key in options:
            m_pin_owner, m_host = manifold_of(pin_key), manifold_of(host_key)
            if m_pin_owner is None or m_host is None:
                continue
            for sign in (1.0, -1.0):
                d = itf.normal * sign
                # Furo (com parede mínima ao redor e no fundo) precisa caber dentro da hospedeira.
                probe = _cylinder(itf.center, d, h_sock + wall, r_sock + wall, r_sock + wall, segments)
                if _inside_fraction(m_host, probe) < _PROBE_INSIDE_MIN_FRACTION:
                    continue
                # A raiz do pino precisa estar ancorada na peça dona do pino.
                root = _cylinder(
                    itf.center - d * _PIN_ROOT_EMBED_MM, d, _PIN_ROOT_EMBED_MM, r_pin, r_pin, segments
                )
                if _inside_fraction(m_pin_owner, root) < _PIN_ROOT_MIN_FRACTION:
                    continue

                pin = _cylinder(
                    itf.center - d * _PIN_ROOT_EMBED_MM,
                    d,
                    h_pin + _PIN_ROOT_EMBED_MM,
                    r_pin,
                    r_pin * 0.85,
                    segments,
                )
                socket = _cylinder(itf.center - d * 0.3, d, h_sock + 0.3, r_sock, r_sock, segments)
                new_owner = m_pin_owner + pin
                new_host = m_host - socket
                if new_owner.volume() <= 0 or new_host.volume() <= 0:
                    continue

                cache[pin_key] = new_owner
                cache[host_key] = new_host
                dirty.update({pin_key, host_key})
                pins_by_piece[pin_key[0]] += 1
                pins_by_piece[host_key[0]] += 1
                created += 1
                applied = True
                logger.info(
                    "Pino entre cores: cor %d -> cor %d r_pin=%.2f h=%.1f área=%.0fmm²",
                    pin_key[0] + 1,
                    host_key[0] + 1,
                    r_pin,
                    h_pin,
                    itf.area,
                )
                break
            if applied:
                break

    for key in dirty:
        m = cache.get(key)
        if m is not None:
            closed_components[key[0]][key[1]] = _to_trimesh(m)

    return InterfacePinReport(
        pins_created=created,
        pins_by_piece=dict(pins_by_piece),
        interfaces_found=len(interfaces),
    )
