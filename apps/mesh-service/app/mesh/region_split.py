"""
Fatiamento anatomico de UMA cor ("Split-to-Print").

Pipeline:
  1. make_watertight: capping (earcut) -> validacao manifold3d. Se falhar,
     remalhamento por voxel (somente nesse caso).
  2. segment_regions: segmentacao volumetrica (voxel + distance transform)
     em tronco + apendices (asas, cauda, membros) + cabeca (pescoco = secao
     minima na parte superior do tronco).
  3. Cortes localizados: cada apendice e removido com uma regiao limitada
     (meio-espaco do plano de juncao ∩ mascara dilatada do apendice), entao o
     corte da asa nao atravessa o corpo.
  4. fit_to_plate: testa orientacoes; se nada couber, bissecciona (tronco:
     horizontal, na secao de menor area entre 35% e 65%) recursivamente.
  5. Orienta cada peca com a maior face de corte para baixo, assenta em Z=0.

Sem fallbacks silenciosos: falhas viram RegionSplitError ou avisos em `warnings`.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import trimesh
from scipy import ndimage as ndi

import manifold3d as m3d

from app.mesh.capper import close_color_piece

logger = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]


class RegionSplitError(RuntimeError):
    """Falha explicita do pipeline de fatiamento."""


# ---------------------------------------------------------------------------
# Conversoes
# ---------------------------------------------------------------------------


def to_manifold(mesh: trimesh.Trimesh) -> m3d.Manifold:
    mm = m3d.Mesh(
        vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
        tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
    )
    return m3d.Manifold(mm)


def to_trimesh(m: m3d.Manifold) -> trimesh.Trimesh:
    mesh = m.to_mesh()
    return trimesh.Trimesh(
        vertices=np.asarray(mesh.vert_properties)[:, :3].astype(np.float64),
        faces=np.asarray(mesh.tri_verts, dtype=np.int64),
        process=False,
    )


def _rot_to(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Matriz 3x3 que gira o vetor src para dst."""
    a = src / np.linalg.norm(src)
    b = dst / np.linalg.norm(dst)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        if c > 0:
            return np.eye(3)
        perp = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
        axis = np.cross(a, perp)
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))


def _rot_z(deg: float) -> np.ndarray:
    t = math.radians(deg)
    return np.array([[math.cos(t), -math.sin(t), 0], [math.sin(t), math.cos(t), 0], [0, 0, 1.0]])


def _affine(R: np.ndarray, t: np.ndarray | None = None) -> list:
    t = np.zeros(3) if t is None else t
    return np.hstack([R, t.reshape(3, 1)]).tolist()


# ---------------------------------------------------------------------------
# 1. Malha estanque
# ---------------------------------------------------------------------------


@dataclass
class VoxelModel:
    solid: np.ndarray       # bool grid
    origin: np.ndarray      # coordenada do canto do voxel [0,0,0]
    pitch: float

    def centers(self, mask: np.ndarray) -> np.ndarray:
        idx = np.argwhere(mask)
        return self.origin + (idx + 0.5) * self.pitch


def voxelize_solid(mesh: trimesh.Trimesh, pitch: float, close_iters: int = 2) -> VoxelModel:
    """Voxeliza uma malha possivelmente aberta: casca amostrada + flood fill
    do exterior apos dilatacao (fecha frestas de ate ~2*close_iters voxels)."""
    pad = close_iters + 4
    n = int(min(6e6, max(2e5, mesh.area / (pitch * pitch) * 6)))
    pts, _ = trimesh.sample.sample_surface(mesh, n, seed=1)
    pts = np.vstack([pts, mesh.vertices])
    origin = mesh.bounds[0] - pad * pitch
    idx = np.floor((pts - origin) / pitch).astype(int)
    shape = idx.max(0) + pad + 1
    shell = np.zeros(shape, bool)
    shell[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    d = ndi.binary_dilation(shell, iterations=close_iters)
    lab, _ = ndi.label(~d)
    exterior = lab == lab[0, 0, 0]
    solid = ~ndi.binary_dilation(exterior, iterations=close_iters)
    return VoxelModel(solid=solid, origin=origin, pitch=pitch)


def _mask_to_mesh(mask: np.ndarray, origin: np.ndarray, pitch: float, sigma: float = 0.8) -> trimesh.Trimesh:
    from skimage.measure import marching_cubes

    padded = np.pad(mask, 2).astype(np.float32)
    if sigma > 0:
        padded = ndi.gaussian_filter(padded, sigma)
    verts, faces, _, _ = marching_cubes(padded, level=0.5, allow_degenerate=False)
    verts = origin + (verts - 2 + 0.5) * pitch
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def _largest_valid(m: m3d.Manifold) -> m3d.Manifold:
    return m


def make_watertight(mesh: trimesh.Trimesh, cap_method: str = "earcut", voxel_pitch: float | None = None) -> tuple[m3d.Manifold, bool, list[str]]:
    """Retorna (manifold, usou_voxel, avisos). Lanca RegionSplitError se falhar."""
    warnings: list[str] = []
    capped = close_color_piece(mesh, method=cap_method)
    try:
        m = to_manifold(capped)
        if m.status() == m3d.Error.NoError and m.volume() > 0:
            return m, False, warnings
    except Exception as exc:  # pragma: no cover
        logger.info("manifold do capping falhou: %s", exc)

    pitch = voxel_pitch or float(np.clip(capped.extents.max() / 300.0, 0.35, 0.8))
    vm = voxelize_solid(capped, pitch)
    if vm.solid.sum() < 10:
        raise RegionSplitError("Remalhamento por voxel nao gerou volume (malha muito aberta).")
    remesh = _mask_to_mesh(vm.solid, vm.origin, vm.pitch)
    m = to_manifold(remesh)
    if m.status() != m3d.Error.NoError:
        raise RegionSplitError(f"Malha nao ficou estanque nem apos remalhamento por voxel ({m.status()}).")
    warnings.append(
        f"O capping nao gerou malha estanque; foi aplicado remalhamento por voxel ({pitch:.2f} mm). "
        "Detalhes menores que isso podem ser suavizados."
    )
    return m, True, warnings


# ---------------------------------------------------------------------------
# 2. Segmentacao anatomica
# ---------------------------------------------------------------------------


@dataclass
class Region:
    label: str
    mask: np.ndarray            # voxels (grid de segmentacao)
    plane_origin: np.ndarray
    plane_normal: np.ndarray    # aponta PARA o apendice (para fora do tronco)


@dataclass
class Segmentation:
    vm: VoxelModel
    trunk_mask: np.ndarray
    regions: list[Region]
    warnings: list[str] = field(default_factory=list)


def _interface_plane(vm: VoxelModel, part: np.ndarray, body: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    iface = part & ndi.binary_dilation(body, iterations=2)
    pts = vm.centers(iface)
    if len(pts) < 6:
        return None
    c = pts.mean(0)
    part_c = vm.centers(part).mean(0)
    _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
    n = vt[2]
    out = part_c - c
    if np.linalg.norm(out) > 1e-6:
        if np.dot(n, out) < 0:
            n = -n
        # mistura com a direcao para fora (planos de interface ruidosos)
        o = out / np.linalg.norm(out)
        if abs(np.dot(n, o)) < 0.5:
            n = o
    return c, n / np.linalg.norm(n)


def _classify(vm: VoxelModel, part: np.ndarray, trunk_c: np.ndarray, trunk_ext: np.ndarray, vol_frac: float) -> str:
    pts = vm.centers(part)
    c = pts.mean(0)
    d = (c - trunk_c) / np.maximum(trunk_ext / 2.0, 1e-6)
    sv = np.linalg.svd(pts - c, compute_uv=False)
    flat = sv[2] / max(sv[0], 1e-6)
    side = "Esquerda" if c[0] < trunk_c[0] else "Direita"
    side_m = "Esquerdo" if c[0] < trunk_c[0] else "Direito"
    ax = int(np.argmax(np.abs(d)))
    if ax == 0:
        if flat < 0.35 and vol_frac > 0.03 and d[2] > -0.3:
            return f"Asa {side}"
        if d[2] < -0.3:
            return f"Perna {side}"
        return f"Braço {side_m}"
    if ax == 2 and d[2] < 0:
        return f"Perna {side}" if abs(d[0]) > 0.15 else "Base"
    if ax == 2 and d[2] > 0:
        return "Cabeça"
    # eixo Y: cauda costuma ser o maior apendice traseiro/baixo
    if d[2] < 0.3:
        return "Cauda"
    return "Apêndice"


def _section_areas(mask: np.ndarray, axis: int = 2) -> np.ndarray:
    other = tuple(i for i in range(3) if i != axis)
    return mask.sum(axis=other)


def segment_regions(mesh_m: m3d.Manifold, seg_pitch: float = 1.0, template: str = "creature") -> Segmentation:
    tm = to_trimesh(mesh_m)
    vm = voxelize_solid(tm, seg_pitch, close_iters=1)
    S = vm.solid
    total = int(S.sum())
    warnings: list[str] = []
    dt = ndi.distance_transform_edt(S)
    dmax = float(dt.max())
    min_part = max(int(0.01 * total), 50)

    best = None
    for frac in (0.22, 0.26, 0.18, 0.30, 0.34, 0.14):
        rad = max(2.0, frac * dmax)
        core = dt > rad
        lab, n = ndi.label(core)
        if n == 0:
            continue
        sizes = ndi.sum(core, lab, range(1, n + 1))
        core = lab == (int(np.argmax(sizes)) + 1)
        r = int(math.ceil(rad))
        body = ndi.binary_dilation(core, iterations=r + 2) & S
        rest = S & ~body
        lab2, n2 = ndi.label(rest)
        parts = []
        if n2:
            s2 = ndi.sum(rest, lab2, range(1, n2 + 1))
            for i in np.argsort(-s2):
                if s2[i] < min_part:
                    break
                parts.append(lab2 == (i + 1))
        score = len(parts)
        if best is None or score > best[0]:
            best = (score, body, parts, rad)
        if score >= 4:
            break
    if best is None:
        raise RegionSplitError("Segmentacao falhou: nao foi possivel encontrar um nucleo (tronco).")
    _, body, parts, rad = best
    logger.info("Segmentacao: raio do nucleo %.1f vox, %d apendices", rad, len(parts))

    # Partes pequenas descartadas voltam ao tronco
    assigned = np.zeros_like(S)
    for p in parts:
        assigned |= p
    trunk = S & ~assigned

    trunk_pts = vm.centers(trunk)
    trunk_c = trunk_pts.mean(0)
    trunk_ext = trunk_pts.max(0) - trunk_pts.min(0)

    regions: list[Region] = []
    used_labels: dict[str, int] = {}
    for p in parts:
        # cada apendice: a interface com o tronco
        plane = _interface_plane(vm, p, trunk)
        if plane is None:
            trunk |= p
            continue
        lbl = _classify(vm, p, trunk_c, trunk_ext, p.sum() / total)
        if lbl in used_labels:
            used_labels[lbl] += 1
            lbl = f"{lbl} {used_labels[lbl]}"
        else:
            used_labels[lbl] = 1
        regions.append(Region(lbl, p, plane[0], plane[1]))

    # Cabeca: se nenhum apendice foi rotulado como cabeca, procura o pescoco
    if not any(r.label.startswith("Cabeça") for r in regions):
        areas = _section_areas(trunk, 2).astype(float)
        nz = np.nonzero(areas)[0]
        if len(nz) > 10:
            z0, z1 = nz[0], nz[-1]
            h = z1 - z0
            lo, hi = int(z0 + 0.55 * h), int(z0 + 0.9 * h)
            if hi > lo + 2:
                sm = ndi.uniform_filter1d(areas, 3)
                k = lo + int(np.argmin(sm[lo:hi]))
                below_max = sm[z0:k].max() if k > z0 else 0
                above_max = sm[k + 1 : z1 + 1].max() if k < z1 else 0
                # pescoco real: secao bem menor que o corpo e que a cabeca
                if sm[k] < 0.75 * below_max and sm[k] < 0.85 * above_max:
                    head = trunk.copy()
                    head[:, :, : k + 1] = False
                    lab, n = ndi.label(head)
                    if n:
                        s = ndi.sum(head, lab, range(1, n + 1))
                        head = lab == (int(np.argmax(s)) + 1)
                        zc = vm.origin[2] + (k + 1) * vm.pitch
                        hp = vm.centers(head)
                        org = np.array([hp[:, 0].mean(), hp[:, 1].mean(), zc])
                        regions.append(Region("Cabeça", head, org, np.array([0, 0, 1.0])))
                        trunk = trunk & ~head
        if not any(r.label.startswith("Cabeça") for r in regions):
            warnings.append("Cabeça não identificada (sem pescoço claro); ela permanece no tronco.")

    if not regions:
        warnings.append("Nenhum apêndice anatômico encontrado; será usada apenas a bissecção até caber na mesa.")
    return Segmentation(vm=vm, trunk_mask=trunk, regions=regions, warnings=warnings)


# ---------------------------------------------------------------------------
# 3. Cortes localizados
# ---------------------------------------------------------------------------


@dataclass
class Piece:
    label: str
    manifold: m3d.Manifold
    cut_normals: list[tuple[np.ndarray, float]] = field(default_factory=list)  # (normal externa da face, area)


def _halfspace_box(origin: np.ndarray, normal: np.ndarray, size: float) -> m3d.Manifold:
    """Cubo enorme do lado +normal do plano."""
    box = m3d.Manifold.cube([size, size, size], center=True).translate([0, 0, size / 2.0])
    R = _rot_to(np.array([0, 0, 1.0]), normal)
    return box.transform(_affine(R, origin))


def _section_area(m: m3d.Manifold, origin: np.ndarray, normal: np.ndarray) -> float:
    R = _rot_to(normal, np.array([0, 0, 1.0]))
    mm = m.transform(_affine(R, -R @ origin))
    try:
        return float(mm.slice(0.0).area())
    except Exception:
        return 0.0


def _add_connector(a: m3d.Manifold, b: m3d.Manifold, origin: np.ndarray, normal: np.ndarray,
                   tol: float, shape: str) -> tuple[m3d.Manifold, m3d.Manifold, bool]:
    """Pino em `a` (lado -normal, tronco) entrando em `b` (lado +normal).
    So aplica se o pino couber inteiro na secao."""
    R = _rot_to(np.array([0, 0, 1.0]), normal)
    Rinv = R.T
    local = a.transform(_affine(Rinv, -Rinv @ origin))
    try:
        cs = local.slice(-0.01)
    except Exception:
        return a, b, False
    area = float(cs.area())
    if area < 30:
        return a, b, False
    radius = float(np.clip(0.3 * math.sqrt(area / math.pi), 1.5, 5.0))
    segs = 6 if shape == "hex" else (3 if shape == "triangle" else 32)
    # centro: centroide da secao; testa se o circulo cabe
    polys = cs.to_polygons()
    allp = np.vstack([np.asarray(p) for p in polys])
    centers = [allp.mean(0)]
    # alternativa: ponto mais interno via grade
    bb_min, bb_max = allp.min(0), allp.max(0)
    gx = np.linspace(bb_min[0], bb_max[0], 12)
    gy = np.linspace(bb_min[1], bb_max[1], 12)
    centers += [np.array([x, y]) for x in gx for y in gy]
    height = float(np.clip(radius * 2.2, 4.0, 10.0))
    for ctr in centers:
        circ = m3d.CrossSection.circle(radius * 1.15, segs)
        circ = circ.translate([float(ctr[0]), float(ctr[1])])
        if abs((cs ^ circ).area() - circ.area()) > 0.02 * circ.area():
            continue
        # o pino deve caber tambem dentro de b
        pin = m3d.Manifold.cylinder(height, radius, radius, segs, True).translate([float(ctr[0]), float(ctr[1]), 0])
        hole = m3d.Manifold.cylinder(height + 2 * tol, radius + tol, radius + tol, segs, True).translate([float(ctr[0]), float(ctr[1]), 0])
        to_world = _affine(R, origin)
        pin_w = pin.transform(to_world)
        hole_w = hole.transform(to_world)
        if abs((b ^ hole_w).volume() - hole_w.volume() / 2.0) > 0.08 * hole_w.volume():
            continue  # buraco sairia pela parede de b
        new_b = b - hole_w
        new_a = a + (pin_w - _halfspace_box(origin, -normal, 1e4))  # metade do pino que sai de a
        # mantem a metade inferior dentro de a (ja e solido); une
        return new_a, new_b, True
    return a, b, False


def _cut_region(body: m3d.Manifold, region_m: m3d.Manifold, origin: np.ndarray, normal: np.ndarray) -> tuple[m3d.Manifold, m3d.Manifold]:
    cutter = region_m ^ _halfspace_box(origin, normal, 1e4)
    part = body ^ cutter
    rest = body - cutter
    return part, rest


def _largest_component(m: m3d.Manifold) -> tuple[m3d.Manifold, m3d.Manifold]:
    comps = m.decompose()
    if len(comps) <= 1:
        return m, m3d.Manifold()
    comps = sorted(comps, key=lambda c: -c.volume())
    others = m3d.Manifold.batch_boolean(comps[1:], m3d.OpType.Add) if len(comps) > 2 else comps[1]
    return comps[0], others


def cut_regions(mesh_m: m3d.Manifold, seg: Segmentation, connectors: bool, tol: float, pin_shape: str,
                progress: ProgressFn | None = None) -> tuple[Piece, list[Piece], list[str]]:
    vm = seg.vm
    warnings: list[str] = []
    body = mesh_m
    trunk_normals: list[tuple[np.ndarray, float]] = []
    pieces: list[Piece] = []
    total_vol = mesh_m.volume()
    for i, reg in enumerate(seg.regions):
        if progress:
            progress(i / max(len(seg.regions), 1), f"Cortando {reg.label}")
        dil = ndi.binary_dilation(reg.mask, iterations=3) & ~ndi.binary_erosion(seg.trunk_mask, iterations=4)
        dil |= reg.mask
        region_mesh = _mask_to_mesh(dil, vm.origin, vm.pitch, sigma=0.6)
        region_m = to_manifold(region_mesh)
        if region_m.status() != m3d.Error.NoError:
            warnings.append(f"Região '{reg.label}' inválida; não foi cortada.")
            continue
        part, rest = _cut_region(body, region_m, reg.plane_origin, reg.plane_normal)
        if part.is_empty() or part.volume() < 0.005 * total_vol:
            warnings.append(f"Corte de '{reg.label}' gerou volume desprezível; mantido no tronco.")
            continue
        main, extra = _largest_component(part)
        if not extra.is_empty():
            rest = rest + extra
        rest_main, rest_extra = _largest_component(rest)
        if not rest_extra.is_empty():
            # fragmentos soltos do tronco que ficaram isolados -> anexa ao apendice se tocarem
            main = main + rest_extra
            main, extra2 = _largest_component(main)
            rest_main = rest_main + extra2 if not extra2.is_empty() else rest_main
        area = _section_area(main, reg.plane_origin + reg.plane_normal * 0.05, reg.plane_normal)
        has_conn = False
        if connectors:
            try:
                rest_main, main, has_conn = _add_connector(rest_main, main, reg.plane_origin, reg.plane_normal, tol, pin_shape)
            except Exception as exc:
                logger.info("conector falhou em %s: %s", reg.label, exc)
        body = rest_main
        pieces.append(Piece(reg.label, main, [(-reg.plane_normal, area)]))
        trunk_normals.append((reg.plane_normal, area))
    trunk = Piece("Tronco", body, trunk_normals)
    return trunk, pieces, warnings


# ---------------------------------------------------------------------------
# 4. Garantia da mesa
# ---------------------------------------------------------------------------


def _candidate_rotations(m: m3d.Manifold, preferred: list[np.ndarray]) -> list[tuple[np.ndarray, bool]]:
    dirs: list[tuple[np.ndarray, bool]] = [(p, True) for p in preferred]
    for v in ([0, 0, -1], [0, 0, 1], [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0]):
        dirs.append((np.array(v, float), False))
    try:
        pts = np.asarray(m.to_mesh().vert_properties)[:, :3]
        pts = pts[:: max(1, len(pts) // 5000)]
        _, _, vt = np.linalg.svd(pts - pts.mean(0), full_matrices=False)
        for v in vt:
            dirs.append((v, False))
            dirs.append((-v, False))
    except Exception:
        pass
    return dirs


def find_orientation(m: m3d.Manifold, plate: tuple[float, float, float], margin: float,
                     preferred_down: list[np.ndarray]) -> tuple[np.ndarray, bool] | None:
    """Retorna (R, usou_face_de_corte) ou None. R gira a peca para o frame de impressao."""
    pts = np.asarray(m.to_mesh().vert_properties)[:, :3]
    if len(pts) > 20000:
        pts = pts[:: len(pts) // 20000]
    try:
        hull = trimesh.Trimesh(pts).convex_hull.vertices if False else pts
    except Exception:
        hull = pts
    px, py, pz = (plate[0] - margin, plate[1] - margin, plate[2] - margin)
    best = None
    for d, is_cut in _candidate_rotations(m, preferred_down):
        R0 = _rot_to(d, np.array([0, 0, -1.0]))
        for ang in range(0, 180, 15):
            R = _rot_z(ang) @ R0
            q = hull @ R.T
            ext = q.max(0) - q.min(0)
            ok = (ext[0] <= px and ext[1] <= py) or (ext[0] <= py and ext[1] <= px)
            if ok and ext[2] <= pz:
                if is_cut:
                    return R, True
                score = ext[2]
                if best is None or score < best[0]:
                    best = (score, R)
        if best is not None and not is_cut and d is preferred_down:
            pass
    if best is None:
        return None
    return best[1], False


def _bisect(m: m3d.Manifold, axis: np.ndarray) -> tuple[m3d.Manifold, m3d.Manifold, np.ndarray, float]:
    """Corta perpendicular a `axis` na secao de menor area entre 35% e 65%."""
    axis = axis / np.linalg.norm(axis)
    pts = np.asarray(m.to_mesh().vert_properties)[:, :3]
    proj = pts @ axis
    lo, hi = proj.min(), proj.max()
    best = None
    for f in np.linspace(0.35, 0.65, 13):
        off = lo + f * (hi - lo)
        a = _section_area(m, axis * off, axis)
        if a <= 0:
            continue
        # leve preferencia pelo meio
        score = a * (1 + 0.6 * abs(f - 0.5))
        if best is None or score < best[0]:
            best = (score, off, a)
    if best is None:
        off, area = (lo + hi) / 2, 0.0
    else:
        _, off, area = best
    pos, neg = m.split_by_plane(axis.tolist(), float(off))
    return pos, neg, axis * off, area


def fit_pieces(pieces: list[Piece], plate: tuple[float, float, float], margin: float, connectors: bool,
               tol: float, pin_shape: str, max_depth: int = 4) -> tuple[list[tuple[Piece, np.ndarray, bool]], list[str]]:
    out: list[tuple[Piece, np.ndarray, bool]] = []
    warnings: list[str] = []

    def rec(p: Piece, depth: int):
        prefs = [n for n, _ in sorted(p.cut_normals, key=lambda t: -t[1])]
        res = find_orientation(p.manifold, plate, margin, prefs[:1])
        if res is not None:
            out.append((p, res[0], True))
            return
        if depth >= max_depth:
            warnings.append(f"'{p.label}' não coube na mesa após {max_depth} bissecções.")
            out.append((p, np.eye(3), False))
            return
        bb = p.manifold.bounding_box()
        ext = np.array(bb[3:]) - np.array(bb[:3])
        is_trunk = p.label.startswith("Tronco")
        if is_trunk or ext[2] >= ext.max() * 0.999:
            axis = np.array([0, 0, 1.0])  # horizontal (cintura)
            names = ("superior", "inferior")
        else:
            axis = np.eye(3)[int(np.argmax(ext))]
            names = ("A", "B")
        pos, neg, origin, area = _bisect(p.manifold, axis)
        if pos.is_empty() or neg.is_empty():
            warnings.append(f"Bissecção de '{p.label}' falhou.")
            out.append((p, np.eye(3), False))
            return
        if connectors:
            try:
                neg, pos, _ = _add_connector(neg, pos, origin, axis, tol, pin_shape)
            except Exception as exc:
                logger.info("conector bissecao falhou: %s", exc)
        base = p.label
        pa = Piece(f"{base} {names[0]}", pos, [(n, a) for n, a in p.cut_normals if np.dot(n, axis) <= 0.5] + [(-axis, area)])
        pb = Piece(f"{base} {names[1]}", neg, [(n, a) for n, a in p.cut_normals if np.dot(n, -axis) <= 0.5] + [(axis, area)])
        rec(pa, depth + 1)
        rec(pb, depth + 1)

    for p in pieces:
        rec(p, 0)
    return out, warnings


# ---------------------------------------------------------------------------
# Orquestrador
# ---------------------------------------------------------------------------


@dataclass
class SplitPieceResult:
    label: str
    mesh: trimesh.Trimesh       # ja orientado, centralizado em XY e com base em Z=0
    fits_in_plate: bool
    is_watertight: bool
    extents_mm: list[float]


@dataclass
class RegionSplitResult:
    pieces: list[SplitPieceResult]
    warnings: list[str]
    used_voxel_remesh: bool
    timings: dict[str, float]


def split_color_piece(mesh: trimesh.Trimesh, plate: tuple[float, float, float], *, margin: float = 2.0,
                      cap_method: str = "earcut", connectors: bool = True, connector_tolerance_mm: float = 0.2,
                      connector_pin_shape: str = "hex", template: str = "creature",
                      progress: ProgressFn | None = None) -> RegionSplitResult:
    import time

    def prog(f: float, msg: str):
        if progress:
            progress(f, msg)

    timings: dict[str, float] = {}
    t = time.time()
    prog(0.05, "Reparando malha (capping estanque)")
    m, used_voxel, warnings = make_watertight(mesh, cap_method)
    timings["watertight"] = time.time() - t

    t = time.time()
    prog(0.25, "Segmentando regiões anatômicas")
    seg = segment_regions(m, template=template)
    warnings += seg.warnings
    timings["segment"] = time.time() - t

    t = time.time()
    prog(0.4, "Cortando apêndices")
    trunk, parts, w = cut_regions(
        m, seg, connectors, connector_tolerance_mm, connector_pin_shape,
        progress=lambda f, s: prog(0.4 + 0.25 * f, s),
    )
    warnings += w
    timings["cut"] = time.time() - t

    t = time.time()
    prog(0.7, "Garantindo que cada peça caiba na mesa")
    fitted, w = fit_pieces([trunk] + parts, plate, margin, connectors, connector_tolerance_mm, connector_pin_shape)
    warnings += w
    timings["fit"] = time.time() - t

    results: list[SplitPieceResult] = []
    for p, R, fits in fitted:
        tm = to_trimesh(p.manifold.transform(_affine(R)))
        tm.merge_vertices()
        b = tm.bounds
        tm.apply_translation([-(b[0][0] + b[1][0]) / 2, -(b[0][1] + b[1][1]) / 2, -b[0][2]])
        ext = tm.extents
        fits = fits and ext[0] <= plate[0] and ext[1] <= plate[1] and ext[2] <= plate[2]
        results.append(SplitPieceResult(
            label=p.label, mesh=tm, fits_in_plate=bool(fits), is_watertight=bool(tm.is_watertight),
            extents_mm=[round(float(e), 1) for e in ext],
        ))
    prog(0.85, "Peças prontas")
    return RegionSplitResult(pieces=results, warnings=warnings, used_voxel_remesh=used_voxel, timings=timings)
