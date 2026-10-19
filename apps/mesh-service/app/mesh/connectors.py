"""
Módulo de geração automática de conectores mecânicos (Interlock Connectors)
e fatiamento planar com tampamento construtivo + reintegração espacial de fragmentos.

Funcionalidades:
- Posicionamento matemático via Polo de Inacessibilidade (`shapely.ops.polylabel` /
  Círculo Máximo Inscrito) em cada polígono fechado da seção de corte, garantindo
  que o pino nunca caia em cavidades ocas (ex: barriga removida) nem fure paredes.
- Geração construtiva 2D/3D do pino macho (chanfrado) e furo fêmea (com folga
  paramétrica de tolerância + reservatório de fundo) diretamente na tampa planar,
  funcionando em 100% dos cortes mesmo quando a malha possui bordas não-manifold
  em regiões distantes.
- Agrupamento espacial por `cKDTree` e reintegração automática de pontas/protrusões
  secundárias que cruzam planos de corte infinitos, eliminando "pontos flutuando no ar".
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

import numpy as np
import trimesh
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import linemerge, polygonize, polylabel, unary_union

if TYPE_CHECKING:
    from manifold3d import Manifold

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE_MM: float = 0.2
MIN_INTERFACE_AREA_MM2: float = 18.0
MIN_INSCRIBED_RADIUS_MM: float = 1.40


def split_spatially_disconnected(
    mesh: trimesh.Trimesh,
    gap_mm: float = 1.2,
    min_speckle_faces: int = 35,
) -> list[trimesh.Trimesh]:
    """
    Agrupa componentes de `mesh.split(only_watertight=False)` por proximidade espacial 3D (`cKDTree`):
    - Componentes que tocam ou estão a <= `gap_mm` do componente principal (ex: tampas planares,
      pinos de encaixe, remendos de cor) permanecem fundidos ao componente principal.
    - Micro-respingos de pintura isolados no espaço (< `min_speckle_faces` e distantes > `gap_mm`)
      são descartados.
    - Retorna a lista de grupos espacialmente independentes ordenados por número de faces (decrescente).
    """
    if len(mesh.faces) == 0:
        return []

    raw_comps = sorted(mesh.split(only_watertight=False), key=lambda c: len(c.faces), reverse=True)
    if len(raw_comps) <= 1:
        return [mesh]

    clusters: list[list[trimesh.Trimesh]] = [[raw_comps[0]]]
    cluster_trees: list[cKDTree] = [cKDTree(raw_comps[0].vertices)]

    for comp in raw_comps[1:]:
        attached = False
        for c_idx, tree in enumerate(cluster_trees):
            dists, _ = tree.query(comp.vertices, k=1)
            if float(np.min(dists)) <= gap_mm:
                clusters[c_idx].append(comp)
                attached = True
                break
        if not attached:
            if len(comp.faces) >= min_speckle_faces:
                clusters.append([comp])
                cluster_trees.append(cKDTree(comp.vertices))

    result: list[trimesh.Trimesh] = []
    for cl in clusters:
        merged = cl[0] if len(cl) == 1 else trimesh.util.concatenate(cl)
        result.append(merged)

    result.sort(key=lambda m: len(m.faces), reverse=True)
    if result and mesh.metadata:
        result[0].metadata.update(mesh.metadata)
    return result


def _rotation_matrix_from_z_to_dir(target_dir: np.ndarray) -> np.ndarray:
    """Calcula matriz 4x4 de rotação que alinha o vetor [0, 0, 1] com target_dir."""
    z = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    target = np.asarray(target_dir, dtype=np.float64)
    norm = float(np.linalg.norm(target))
    if norm < 1e-9:
        return np.eye(4)
    target = target / norm

    dot = float(np.dot(z, target))
    if dot > 0.999999:
        return np.eye(4)
    if dot < -0.999999:
        R = np.eye(4)
        R[1, 1] = -1.0
        R[2, 2] = -1.0
        return R

    axis = np.cross(z, target)
    axis_norm = float(np.linalg.norm(axis))
    if axis_norm < 1e-9:
        return np.eye(4)
    axis = axis / axis_norm
    angle = np.arccos(np.clip(dot, -1.0, 1.0))
    return trimesh.transformations.rotation_matrix(angle, axis)


def _plane_basis(plane_normal: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Retorna base ortonormal destra (u, v, n) onde u x v = n."""
    n = np.asarray(plane_normal, dtype=np.float64)
    n_norm = float(np.linalg.norm(n))
    if n_norm < 1e-10:
        n = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    else:
        n = n / n_norm

    ref = np.array([1.0, 0.0, 0.0], dtype=np.float64) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0], dtype=np.float64)
    u = ref - np.dot(ref, n) * n
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    v /= np.linalg.norm(v)
    return u, v, n


def extract_2d_polygons_from_segments(
    lines3d: np.ndarray,
    o: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
) -> list[Polygon]:
    """Converte segmentos 3D no plano (o, u, v) em polígonos Shapely 2D fechados."""
    if lines3d is None or len(lines3d) == 0:
        return []

    d = lines3d - o
    pts2d = np.stack([d @ u, d @ v], axis=-1)
    pts2d = np.round(pts2d, 2)

    segs = [
        LineString([p[0], p[1]])
        for p in pts2d
        if float(np.linalg.norm(p[0] - p[1])) > 1e-3
    ]
    if not segs:
        return []

    merged = linemerge(segs)
    lines_list = [merged] if isinstance(merged, LineString) else list(getattr(merged, "geoms", []))

    closed_rings: list[Polygon] = []
    for ls in lines_list:
        coords = list(ls.coords)
        if len(coords) >= 3:
            if not ls.is_ring:
                coords.append(coords[0])
            if len(coords) >= 4 and coords[0] == coords[-1]:
                try:
                    p = Polygon(coords).buffer(0)
                    if not p.is_empty:
                        if isinstance(p, Polygon):
                            closed_rings.append(p)
                        elif isinstance(p, MultiPolygon):
                            closed_rings.extend(g for g in p.geoms if not g.is_empty)
                except Exception:
                    pass

    polys = list(polygonize(segs)) + closed_rings
    if not polys:
        return []

    try:
        unioned = unary_union(polys).buffer(0)
    except Exception:
        return [p for p in polys if isinstance(p, Polygon) and p.area >= 1.0]

    if isinstance(unioned, Polygon):
        res = [unioned] if not unioned.is_empty else []
    elif isinstance(unioned, MultiPolygon):
        res = [g for g in unioned.geoms if not g.is_empty]
    else:
        res = []

    return [p for p in res if p.area >= 1.0]


def _make_pin_polygon_2d(cx: float, cy: float, radius: float, pin_shape: str) -> Polygon:
    """Cria o polígono 2D do pino/furo centrado em (cx, cy)."""
    if pin_shape == "triangle":
        segs = 3
    elif pin_shape == "hex":
        segs = 6
    else:
        segs = 24
    angles = np.linspace(0.0, 2.0 * np.pi, segs, endpoint=False)
    pts = np.column_stack([cx + radius * np.cos(angles), cy + radius * np.sin(angles)])
    return Polygon(pts)


def _triangulate_2d_to_3d(
    geom_2d: Polygon | MultiPolygon,
    o: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    normal_sign: float,
) -> trimesh.Trimesh:
    """Triangula um Polygon/MultiPolygon 2D e projeta para 3D no plano com normal (normal_sign * n)."""
    polys: list[Polygon] = []
    if isinstance(geom_2d, Polygon):
        if not geom_2d.is_empty:
            polys.append(geom_2d)
    elif isinstance(geom_2d, MultiPolygon):
        polys.extend(g for g in geom_2d.geoms if isinstance(g, Polygon) and not g.is_empty)

    meshes: list[trimesh.Trimesh] = []
    for poly in polys:
        if poly.area < 0.5:
            continue
        try:
            v2d, f2d = trimesh.creation.triangulate_polygon(poly, engine="earcut")
        except Exception:
            try:
                v2d, f2d = trimesh.creation.triangulate_polygon(Polygon(poly.exterior.coords), engine="earcut")
            except Exception:
                continue
        if len(v2d) < 3 or len(f2d) == 0:
            continue
        v3d = o + np.outer(v2d[:, 0], u) + np.outer(v2d[:, 1], v)
        f3d = f2d if normal_sign > 0 else f2d[:, ::-1]
        meshes.append(trimesh.Trimesh(vertices=v3d, faces=f3d, process=False))

    if not meshes:
        return trimesh.Trimesh()
    return trimesh.util.concatenate(meshes)


def _build_frustum_shell_3d(
    cx: float,
    cy: float,
    r_base: float,
    r_tip: float,
    z_end: float,
    pin_shape: str,
    o: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    n: np.ndarray,
    is_cavity: bool,
) -> trimesh.Trimesh:
    """
    Constrói a malha 3D lateral + tampa de fundo de um pino macho (is_cavity=False)
    ou de um furo fêmea (is_cavity=True) que parte de z=0 até z=z_end ao longo de n.
    """
    if pin_shape == "triangle":
        segs = 3
    elif pin_shape == "hex":
        segs = 6
    else:
        segs = 24

    angles = np.linspace(0.0, 2.0 * np.pi, segs, endpoint=False)
    cos_a = np.cos(angles)
    sin_a = np.sin(angles)

    base_2d = np.column_stack([cx + r_base * cos_a, cy + r_base * sin_a])
    tip_2d = np.column_stack([cx + r_tip * cos_a, cy + r_tip * sin_a])

    base_3d = o + np.outer(base_2d[:, 0], u) + np.outer(base_2d[:, 1], v)
    tip_3d = o + np.outer(tip_2d[:, 0], u) + np.outer(tip_2d[:, 1], v) + z_end * n
    tip_center_3d = (o + cx * u + cy * v + z_end * n).reshape(1, 3)

    verts = np.vstack([base_3d, tip_3d, tip_center_3d])
    c_idx = 2 * segs
    faces = []

    flip = (z_end < 0) ^ is_cavity

    for i in range(segs):
        nxt = (i + 1) % segs
        b0, b1 = i, nxt
        t0, t1 = segs + i, segs + nxt
        if not flip:
            faces.append([b0, b1, t1])
            faces.append([b0, t1, t0])
            faces.append([t0, t1, c_idx])
        else:
            faces.append([b0, t1, b1])
            faces.append([b0, t0, t1])
            faces.append([t0, c_idx, t1])

    return trimesh.Trimesh(vertices=verts, faces=np.array(faces, dtype=np.int64), process=False)


def _estimate_local_depth(
    half_mesh: trimesh.Trimesh,
    cx: float,
    cy: float,
    r_check: float,
    o: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    n: np.ndarray,
) -> float:
    """Estima a profundidade disponível na peça ao redor de (cx, cy) perpendicular ao plano de corte."""
    if len(half_mesh.vertices) == 0:
        return 0.0
    d = half_mesh.vertices - o
    x = d @ u
    y = d @ v
    z = np.abs(d @ n)
    dist2 = (x - cx) ** 2 + (y - cy) ** 2
    mask = dist2 <= (r_check + 6.0) ** 2
    if not np.any(mask):
        return float(z.max()) if len(z) else 0.0
    return float(z[mask].max())


def slice_and_cap_with_connectors(
    mesh: trimesh.Trimesh,
    plane_origin: list[float] | np.ndarray,
    plane_normal: list[float] | np.ndarray,
    generate_connectors: bool = True,
    tolerance_mm: float = DEFAULT_TOLERANCE_MM,
    pin_shape: str = "hex",
    reintegrate_grazed_islands: bool = True,
) -> tuple[trimesh.Trimesh, trimesh.Trimesh, int]:
    """
    Fatia `mesh` pelo plano `(plane_origin, plane_normal)`, reintegra pontas secundárias
    decepadas acidentalmente pelo plano infinito, fecha as interfaces de corte com tampas
    planares 2D e adiciona conectores macho/fêmea via `polylabel` (Círculo Máximo Inscrito).

    Retorna:
        (top_mesh, bottom_mesh, num_pins_created)
    """
    o = np.asarray(plane_origin, dtype=np.float64)
    u, v, n = _plane_basis(np.asarray(plane_normal, dtype=np.float64))

    top_open = trimesh.intersections.slice_mesh_plane(mesh, plane_normal=n, plane_origin=o, cap=False)
    bottom_open = trimesh.intersections.slice_mesh_plane(mesh, plane_normal=-n, plane_origin=o, cap=False)

    if len(top_open.vertices) == 0 or len(bottom_open.vertices) == 0:
        return top_open, bottom_open, 0

    # Reintegrar pontas secundárias ("pontos flutuando") usando agrupamento espacial 3D (`cKDTree`)
    if reintegrate_grazed_islands:
        top_clusters = split_spatially_disconnected(top_open, gap_mm=1.2, min_speckle_faces=30)
        bot_clusters = split_spatially_disconnected(bottom_open, gap_mm=1.2, min_speckle_faces=30)

        if len(top_clusters) > 1 or len(bot_clusters) > 1:
            main_top = top_clusters[0] if top_clusters else top_open
            main_bot = bot_clusters[0] if bot_clusters else bottom_open
            main_top_faces = len(main_top.faces)
            main_bot_faces = len(main_bot.faces)

            tree_main_top = cKDTree(main_top.vertices) if len(main_top.vertices) else None
            tree_main_bot = cKDTree(main_bot.vertices) if len(main_bot.vertices) else None

            kept_top = [main_top]
            kept_bot = [main_bot]
            moved_to_bot = []
            moved_to_top = []

            for tc in top_clusters[1:]:
                # Se a ilha toca o componente principal do lado oposto (bottom) ou é uma ponta menor (< 25%)
                dist_to_bot = float(np.min(tree_main_bot.query(tc.vertices, k=1)[0])) if tree_main_bot else float("inf")
                if dist_to_bot <= 1.5 or len(tc.faces) < 0.25 * main_top_faces:
                    moved_to_bot.append(tc)
                else:
                    kept_top.append(tc)

            for bc in bot_clusters[1:]:
                dist_to_top = float(np.min(tree_main_top.query(bc.vertices, k=1)[0])) if tree_main_top else float("inf")
                if dist_to_top <= 1.5 or len(bc.faces) < 0.25 * main_bot_faces:
                    moved_to_top.append(bc)
                else:
                    kept_bot.append(bc)

            top_open = trimesh.util.concatenate(kept_top + moved_to_top)
            bottom_open = trimesh.util.concatenate(kept_bot + moved_to_bot)

    lines3d = trimesh.intersections.mesh_plane(mesh, plane_normal=n, plane_origin=o)
    if lines3d is not None and len(lines3d) > 0 and len(top_open.vertices) > 0 and len(bottom_open.vertices) > 0:
        # Manter apenas os segmentos cujas extremidades pertencem à fronteira entre top_open e bottom_open
        tree_top = cKDTree(top_open.vertices)
        tree_bot = cKDTree(bottom_open.vertices)
        d_top = np.minimum(tree_top.query(lines3d[:, 0, :], k=1)[0], tree_top.query(lines3d[:, 1, :], k=1)[0])
        d_bot = np.minimum(tree_bot.query(lines3d[:, 0, :], k=1)[0], tree_bot.query(lines3d[:, 1, :], k=1)[0])
        valid_seg = (d_top <= 1.5) & (d_bot <= 1.5)
        lines3d = lines3d[valid_seg]

    polys_2d = extract_2d_polygons_from_segments(lines3d, o, u, v)
    if not polys_2d:
        return top_open, bottom_open, 0

    top_caps: list[trimesh.Trimesh] = []
    bot_caps: list[trimesh.Trimesh] = []
    pins_created = 0

    polys_2d = sorted(polys_2d, key=lambda p: p.area, reverse=True)

    for poly in polys_2d:
        added_pin = False
        if generate_connectors and pins_created < 2 and poly.area >= MIN_INTERFACE_AREA_MM2:
            try:
                pt = polylabel(poly, tolerance=0.1)
                r_max = float(poly.boundary.distance(pt))
                if r_max >= MIN_INSCRIBED_RADIUS_MM:
                    cx, cy = float(pt.x), float(pt.y)
                    r_pin = float(np.clip(r_max * 0.52, 1.05, 4.8))
                    r_sock = r_pin + float(tolerance_mm)
                    if r_sock > r_max - 0.30:
                        r_sock = r_max - 0.30
                        r_pin = r_sock - float(tolerance_mm)

                    if r_pin >= 0.95:
                        depth_bot = _estimate_local_depth(bottom_open, cx, cy, r_max + 5.0, o, u, v, n)
                        depth_top = _estimate_local_depth(top_open, cx, cy, r_max + 5.0, o, u, v, n)
                        avail_depth = max(depth_bot, depth_top)

                        if avail_depth >= 3.2:
                            target_h = float(np.clip(r_pin * 1.9, 3.8, 9.5))
                            socket_in_bottom = depth_bot >= depth_top
                            max_h_sock = (depth_bot if socket_in_bottom else depth_top) * 0.72
                            h_sock = float(np.clip(target_h + 0.5, 3.5, max(3.6, max_h_sock)))
                            h_pin = h_sock - 0.5

                            pin_poly = _make_pin_polygon_2d(cx, cy, r_pin, pin_shape)
                            sock_poly = _make_pin_polygon_2d(cx, cy, r_sock, pin_shape)

                            if socket_in_bottom:
                                top_ring = poly.difference(pin_poly)
                                bot_ring = poly.difference(sock_poly)
                                top_caps.append(_triangulate_2d_to_3d(top_ring, o, u, v, normal_sign=-1.0))
                                bot_caps.append(_triangulate_2d_to_3d(bot_ring, o, u, v, normal_sign=+1.0))

                                pin_mesh = _build_frustum_shell_3d(
                                    cx, cy, r_pin, r_pin * 0.85, -h_pin, pin_shape, o, u, v, n, is_cavity=False
                                )
                                sock_mesh = _build_frustum_shell_3d(
                                    cx, cy, r_sock, r_sock, -h_sock, pin_shape, o, u, v, n, is_cavity=True
                                )
                                top_caps.append(pin_mesh)
                                bot_caps.append(sock_mesh)
                            else:
                                top_ring = poly.difference(sock_poly)
                                bot_ring = poly.difference(pin_poly)
                                top_caps.append(_triangulate_2d_to_3d(top_ring, o, u, v, normal_sign=-1.0))
                                bot_caps.append(_triangulate_2d_to_3d(bot_ring, o, u, v, normal_sign=+1.0))

                                pin_mesh = _build_frustum_shell_3d(
                                    cx, cy, r_pin, r_pin * 0.85, +h_pin, pin_shape, o, u, v, n, is_cavity=False
                                )
                                sock_mesh = _build_frustum_shell_3d(
                                    cx, cy, r_sock, r_sock, +h_sock, pin_shape, o, u, v, n, is_cavity=True
                                )
                                bot_caps.append(pin_mesh)
                                top_caps.append(sock_mesh)

                            pins_created += 1
                            added_pin = True
                            logger.info(
                                "Conector polylabel criado: shape=%s r_pin=%.2fmm h_pin=%.1fmm r_max=%.2fmm area=%.1fmm2",
                                pin_shape,
                                r_pin,
                                h_pin,
                                r_max,
                                poly.area,
                            )
            except Exception as pin_err:
                logger.warning("Falha ao construir pino polylabel no polígono: %s", pin_err)

        if not added_pin:
            top_caps.append(_triangulate_2d_to_3d(poly, o, u, v, normal_sign=-1.0))
            bot_caps.append(_triangulate_2d_to_3d(poly, o, u, v, normal_sign=+1.0))

    top_final = trimesh.util.concatenate([top_open] + [c for c in top_caps if len(c.faces) > 0])
    top_final.merge_vertices()

    bot_final = trimesh.util.concatenate([bottom_open] + [c for c in bot_caps if len(c.faces) > 0])
    bot_final.merge_vertices()

    return top_final, bot_final, pins_created


def add_interlock_connector(
    top_manifold: "Manifold",
    bottom_manifold: "Manifold",
    reference_mesh: trimesh.Trimesh,
    plane_origin: list[float] | np.ndarray,
    plane_normal: list[float] | np.ndarray,
    tolerance_mm: float = DEFAULT_TOLERANCE_MM,
    pin_shape: Literal["hex", "triangle", "cylinder"] = "hex",
) -> tuple["Manifold", "Manifold"]:
    """
    Adiciona conector macho/fêmea entre dois objetos `manifold3d.Manifold`
    posicionando o pino via `polylabel` (Círculo Máximo Inscrito) de cada polígono.
    """
    from manifold3d import Manifold

    origin_arr = np.asarray(plane_origin, dtype=np.float64)
    normal_arr = np.asarray(plane_normal, dtype=np.float64)
    n_len = float(np.linalg.norm(normal_arr))
    if n_len < 1e-9:
        return top_manifold, bottom_manifold
    normal_arr = normal_arr / n_len

    try:
        sec = reference_mesh.section(plane_origin=origin_arr, plane_normal=normal_arr)
        if sec is None:
            return top_manifold, bottom_manifold

        p2d, to_3D = sec.to_2D()
        polys = sorted(list(getattr(p2d, "polygons_full", [])), key=lambda p: p.area, reverse=True)
        if not polys:
            return top_manifold, bottom_manifold

        if pin_shape == "triangle":
            circ_segs = 3
        elif pin_shape == "hex":
            circ_segs = 6
        else:
            circ_segs = 0

        cur_top = top_manifold
        cur_bot = bottom_manifold
        added = 0

        for poly in polys[:2]:
            if poly.area < MIN_INTERFACE_AREA_MM2:
                continue
            pt = polylabel(poly, tolerance=0.1)
            r_max = float(poly.boundary.distance(pt))
            if r_max < MIN_INSCRIBED_RADIUS_MM:
                continue

            r_pin = float(np.clip(r_max * 0.52, 1.5, 5.0))
            r_socket = min(r_pin + float(tolerance_mm), r_max - 0.35)
            r_pin = r_socket - float(tolerance_mm)
            if r_pin < 1.2:
                continue

            h_pin = float(np.clip(r_pin * 1.9, 4.0, 10.0))
            h_socket = h_pin + 0.5

            c_3d = trimesh.transformations.transform_points([[float(pt.x), float(pt.y), 0.0]], to_3D)[0]
            rot = _rotation_matrix_from_z_to_dir(-normal_arr)
            rot[:3, 3] = c_3d

            m_male_pin = Manifold.cylinder(
                height=h_pin,
                radius_low=r_pin,
                radius_high=r_pin * 0.85,
                circular_segments=circ_segs,
                center=False,
            ).transform(rot[:3, :].tolist())

            m_female_socket = Manifold.cylinder(
                height=h_socket,
                radius_low=r_socket,
                radius_high=r_socket,
                circular_segments=circ_segs,
                center=False,
            ).transform(rot[:3, :].tolist())

            cand_top = cur_top + m_male_pin
            cand_bot = cur_bot - m_female_socket
            if cand_top.volume() > 0 and cand_bot.volume() > 0:
                cur_top = cand_top
                cur_bot = cand_bot
                added += 1

        if added > 0:
            logger.info("Conectores Manifold polylabel adicionados: %d", added)
        return cur_top, cur_bot

    except Exception as exc:
        logger.warning("Erro ao gerar conector mecânico Manifold: %s", exc)
        return top_manifold, bottom_manifold
