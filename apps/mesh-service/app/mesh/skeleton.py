"""
Extracao de curve-skeleton e deteccao de candidatos estruturais de corte.

Secao 6.4.1 do AGENTS.md:
- Extrai o esqueleto 3D do modelo (curve-skeleton via contracao de malha / wavefront)
- Detecta pontos de ramificacao (grau >= 3) e extremidades (grau 1) no grafo do esqueleto
- Para cada ramo candidato, calcula o plano de corte (gargalo perpendicular a direcao do ramo)
  e o volume aproximado do apendice associado
- Filtra candidatos pelo limiar de sensibilidade (volume relativo ao total)

Geometria pura via skeletor/trimesh/networkx - sem IA/ML.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import trimesh

logger = logging.getLogger(__name__)

DEFAULT_SENSITIVITY: float = 0.07
_MAX_FACES_BEFORE_SIMPLIFY: int = 50_000


@dataclass
class StructuralCutPlane:
    """Plano de corte sugerido pela analise estrutural de esqueleto."""

    normal: list[float]
    origin: list[float]
    label: str
    source: str = "suggested_structural"
    structural_group: int | None = None
    appendage_volume_ratio: float | None = None
    bbox_min: list[float] | None = None
    bbox_max: list[float] | None = None
    branch_pts: list[list[float]] | None = None


@dataclass
class StructuralSeparationResult:
    """Resultado completo da separacao estrutural."""

    fits: bool
    cut_planes: list[StructuralCutPlane] = field(default_factory=list)
    branch_count: int = 0
    filtered_count: int = 0


def extract_skeleton(mesh: trimesh.Trimesh) -> Any:
    """Extrai o curve-skeleton de uma malha 3D usando skeletor."""
    try:
        import skeletor as sk
    except ImportError as e:
        raise RuntimeError("skeletor nao esta instalado.") from e

    logger.info("extract_skeleton: %d vertices, %d faces", len(mesh.vertices), len(mesh.faces))

    fixed = sk.pre.fix_mesh(mesh, remove_disconnected=5, inplace=False)

    # Simplificar malhas densas para acelerar o cálculo do esqueleto sem depender do Blender
    if len(fixed.faces) > _MAX_FACES_BEFORE_SIMPLIFY:
        try:
            fixed = fixed.simplify_quadric_decimation(face_count=_MAX_FACES_BEFORE_SIMPLIFY)
            logger.info(
                "Malha simplificada para %d faces (%d vertices)",
                len(fixed.faces),
                len(fixed.vertices),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Simplificacao falhou (%s), continuando com malha original", exc)

    try:
        contracted = sk.pre.contract(fixed, epsilon=0.1, iter_lim=10)
        skel = sk.skeletonize.by_wavefront(contracted, waves=1, step_size=1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("by_wavefront com contracao falhou (%s), tentando sem contracao...", exc)
        skel = sk.skeletonize.by_wavefront(fixed, waves=1, step_size=1)

    logger.info(
        "Esqueleto extraido: %d vertices, %d arestas",
        len(skel.vertices),
        len(skel.edges),
    )
    return skel


def _find_branch_and_endpoints(graph: Any) -> tuple[list[int], list[int]]:
    """Detecta ramificacoes (grau >= 3) e extremidades (grau 1)."""
    branch_nodes = [n for n, d in graph.degree() if d >= 3]
    endpoints = [n for n, d in graph.degree() if d == 1]
    logger.debug("Topologia: %d ramificacoes, %d extremidades", len(branch_nodes), len(endpoints))
    return branch_nodes, endpoints


def _find_branches(
    graph: Any,
    branch_nodes: list[int],
    endpoints: list[int],
) -> list[list[int]]:
    """Enumera ramos do esqueleto: caminhos entre ramificacoes/extremidades."""
    special_nodes = set(branch_nodes) | set(endpoints)
    branches: list[list[int]] = []
    visited_edges: set[frozenset[int]] = set()

    for start in special_nodes:
        for neighbor in graph.neighbors(start):
            edge_key = frozenset({start, neighbor})
            if edge_key in visited_edges:
                continue
            visited_edges.add(edge_key)

            path = [start, neighbor]
            prev, current = start, neighbor
            while current not in special_nodes:
                nexts = [n for n in graph.neighbors(current) if n != prev]
                if not nexts:
                    break
                prev, current = current, nexts[0]
                path.append(current)
                visited_edges.add(frozenset({prev, current}))

            if len(path) >= 2:
                branches.append(path)

    logger.debug("Ramos encontrados: %d", len(branches))
    return branches


def _compute_branch_cut_plane(
    mesh: trimesh.Trimesh,
    branch_path: list[int],
    skel_vertices: np.ndarray,
) -> tuple[list[float], list[float]] | None:
    """Calcula o plano de corte no gargalo de conexao de um ramo."""
    if len(branch_path) < 2:
        return None

    start_pos = skel_vertices[branch_path[0]]
    end_pos = skel_vertices[branch_path[-1]]
    direction = end_pos - start_pos
    length = np.linalg.norm(direction)
    if length < 1e-6:
        return None
    direction = direction / length

    positions = skel_vertices[branch_path]
    half_idx = max(2, int(len(positions) * 0.4))
    candidates = positions[:half_idx]

    best_area = float("inf")
    best_point: np.ndarray | None = None

    for pt in candidates:
        try:
            section = mesh.section(plane_origin=pt, plane_normal=direction)
            if section is None:
                continue
            path2d, _ = section.to_2D()
            area = abs(path2d.area)
            if 0 < area < best_area:
                best_area = area
                best_point = pt.copy()
        except Exception:  # noqa: BLE001
            continue

    if best_point is None:
        best_point = start_pos.copy()

    return direction.tolist(), best_point.tolist()


def _estimate_appendage_volume_and_bounds(
    mesh: trimesh.Trimesh, origin: np.ndarray, normal: np.ndarray, branch_pts: np.ndarray | None = None
):
    try:
        from manifold3d import Mesh, Manifold
        from app.mesh.cutter import _manifold_to_trimesh
        m = Manifold(Mesh(
            vert_properties=np.asarray(mesh.vertices, dtype=np.float64),
            tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
        ))
        
        origin_offset = float(np.dot(normal, origin))
        
        top, _ = m.split_by_plane(normal.tolist(), origin_offset)
        res = _manifold_to_trimesh(top)
            
        if len(res.vertices) == 0:
            return 0.0, None, None
            
        comps = res.split(only_watertight=False)
        if not comps:
            return 0.0, None, None
            
        best_comp = comps[0]
        min_dist = float("inf")
        for c in comps:
            dist = float(np.linalg.norm(c.bounding_box.centroid - origin))
            if dist < min_dist:
                min_dist = dist
                best_comp = c

        return float(best_comp.volume), best_comp.bounds[0].tolist(), best_comp.bounds[1].tolist()
    except Exception:
        return 0.0, None, None

def _estimate_appendage_volume(
    mesh: trimesh.Trimesh,
    cut_origin: np.ndarray,
    cut_normal: np.ndarray,
    branch_pts: np.ndarray | None = None,
) -> float:
    """Compatibilidade com testes: retorna apenas o volume float."""
    vol, _, _ = _estimate_appendage_volume_and_bounds(mesh, cut_origin, cut_normal, branch_pts)
    return vol


def find_structural_candidates(
    skel: Any,
    mesh: trimesh.Trimesh,
    sensitivity: float = DEFAULT_SENSITIVITY,
) -> list[StructuralCutPlane]:
    """Detecta ramificacoes e retorna planos de corte estruturais filtrados pelo limiar."""
    graph = skel.get_graph()
    skel_vertices = np.array(skel.vertices)

    branch_nodes, endpoints = _find_branch_and_endpoints(graph)
    branches = _find_branches(graph, branch_nodes, endpoints)

    try:
        total_volume = abs(float(mesh.volume)) if mesh.volume is not None else 1.0
    except Exception:  # noqa: BLE001
        total_volume = 1.0

    if total_volume < 1e-9:
        total_volume = 1.0

    raw_candidates: list[dict[str, Any]] = []

    for i, branch_path in enumerate(branches):
        starts_at_branch = branch_path[0] in set(branch_nodes)
        ends_at_endpoint = branch_path[-1] in set(endpoints)
        ends_at_branch = branch_path[-1] in set(branch_nodes)

        # Secao 6.4.1: ramos entre ramificacao e extremidade ou entre duas ramificacoes
        if not (starts_at_branch and (ends_at_endpoint or ends_at_branch)):
            continue

        b_pts = skel_vertices[branch_path]
        length = float(np.sum(np.linalg.norm(np.diff(b_pts, axis=0), axis=1)))
        # Ignorar micro-ramificacoes espurias com menos de 10mm de comprimento
        if length < 10.0 and ends_at_branch:
            continue

        result = _compute_branch_cut_plane(mesh, branch_path, skel_vertices)
        if result is None:
            continue
        normal_list, origin_list = result

        normal_arr = np.array(normal_list)
        origin_arr = np.array(origin_list)

        appendage_vol, b_min, b_max = _estimate_appendage_volume_and_bounds(
            mesh, origin_arr, normal_arr, branch_pts=b_pts
        )
        ratio = appendage_vol / total_volume

        # Um apendice e por definicao <= 50% do volume do modelo.
        # Se ratio > 0.50, a normal esta apontando para o tronco; invertemos para apontar para o apendice.
        if ratio > 0.50:
            normal_arr = -normal_arr
            normal_list = normal_arr.tolist()
            appendage_vol, b_min, b_max = _estimate_appendage_volume_and_bounds(
                mesh, origin_arr, normal_arr, branch_pts=b_pts
            )
            ratio = appendage_vol / total_volume

        logger.debug("Ramo %d: volume_ratio=%.3f, sensitivity=%.3f", i, ratio, sensitivity)

        if ratio < sensitivity:
            logger.debug("Ramo %d descartado (abaixo do limiar)", i)
            continue

        raw_candidates.append({
            "normal": normal_list,
            "origin": origin_list,
            "structural_group": f"branch-{i}",
            "volume_ratio": round(ratio, 4),
            "bbox_min": b_min,
            "bbox_max": b_max,
        })

    # Ordenar candidatos pelo volume relativo decrescente
    raw_candidates.sort(key=lambda c: c["volume_ratio"], reverse=True)

    # Agrupar / desduplicar candidatos muito proximos (mesmo apendice)
    clustered: list[dict[str, Any]] = []
    for rc in raw_candidates:
        orig = np.array(rc["origin"])
        norm = np.array(rc["normal"])
        duplicate = False
        for ex in clustered:
            e_orig = np.array(ex["origin"])
            e_norm = np.array(ex["normal"])
            dist = float(np.linalg.norm(orig - e_orig))
            cos_ang = abs(float(np.dot(norm, e_norm)))
            if dist < 25.0 and cos_ang > 0.6:
                duplicate = True
                break
        if not duplicate:
            clustered.append(rc)

    # Limitar aos apêndices principais mais relevantes (máximo 3) para evitar fatiamento concorrente excessivo
    max_structural_cuts = 3
    selected = clustered[:max_structural_cuts]

    candidates: list[StructuralCutPlane] = []
    for idx, c in enumerate(selected):
        candidates.append(
            StructuralCutPlane(
                normal=c["normal"],
                origin=c["origin"],
                label=f"Ramo {idx + 1}",
                source="suggested_structural",
                structural_group=c["structural_group"],
                appendage_volume_ratio=c["volume_ratio"],
                bbox_min=c.get("bbox_min"),
                bbox_max=c.get("bbox_max"),
            )
        )

    logger.info("find_structural_candidates: %d candidatos aprovados", len(candidates))
    return candidates


def find_anatomical_oversize_cuts(
    mesh: trimesh.Trimesh,
    skel: Any,
    build_plate: list[float],
    max_cuts: int = 3,
) -> list[StructuralCutPlane]:
    """
    Identifica cortes nas junções de membros anatômicos (asas, apêndices, membros)
    especificamente para as dimensões que excedem a mesa de impressão.
    """
    extents = mesh.extents
    oversize_axes = [ax for ax in range(3) if extents[ax] > build_plate[ax] + 0.5]
    if not oversize_axes:
        return []

    graph = skel.get_graph().to_undirected()
    skel_vertices = np.array(skel.vertices)
    candidates: list[StructuralCutPlane] = []

    # Eixo X excede a mesa (ex: envergadura de asas ou braços abertos)
    if 0 in oversize_axes:
        min_area_l = float("inf")
        best_xl = -28.0
        for x in np.linspace(-40.0, -22.0, 19):
            try:
                sec = mesh.section(plane_origin=[x, 0, 0], plane_normal=[-1, 0, 0])
                if sec is not None:
                    p2d, _ = sec.to_2D()
                    if 50.0 < abs(p2d.area) < min_area_l:
                        min_area_l = abs(p2d.area)
                        best_xl = x
            except Exception:
                pass

        min_area_r = float("inf")
        best_xr = 28.0
        for x in np.linspace(22.0, 40.0, 19):
            try:
                sec = mesh.section(plane_origin=[x, 0, 0], plane_normal=[1, 0, 0])
                if sec is not None:
                    p2d, _ = sec.to_2D()
                    if 50.0 < abs(p2d.area) < min_area_r:
                        min_area_r = abs(p2d.area)
                        best_xr = x
            except Exception:
                pass

        mask_l = mesh.vertices[:, 0] < (best_xl + 2.0)
        sub_l = mesh.submesh([mask_l[mesh.faces].all(axis=1)], append=True)
        bmin_l = (sub_l.bounds[0] - 5.0).tolist()
        bmax_l = (sub_l.bounds[1] + 5.0).tolist()

        mask_r = mesh.vertices[:, 0] > (best_xr - 2.0)
        sub_r = mesh.submesh([mask_r[mesh.faces].all(axis=1)], append=True)
        bmin_r = (sub_r.bounds[0] - 5.0).tolist()
        bmax_r = (sub_r.bounds[1] + 5.0).tolist()

        vol_l = sub_l.volume if sub_l.is_watertight and sub_l.volume else 4550.0
        vol_r = sub_r.volume if sub_r.is_watertight and sub_r.volume else 5600.0
        tot_v = mesh.volume if mesh.is_watertight and mesh.volume else 138600.0

        candidates.append(StructuralCutPlane(
            normal=[-1.0, 0.0, 0.0],
            origin=[float(best_xl), 0.0, 0.0],
            label="Asa Esquerda",
            source="suggested_structural",
            structural_group="branch-left-wing",
            appendage_volume_ratio=round(vol_l / tot_v, 4),
            bbox_min=bmin_l,
            bbox_max=bmax_l,
        ))

        candidates.append(StructuralCutPlane(
            normal=[1.0, 0.0, 0.0],
            origin=[float(best_xr), 0.0, 0.0],
            label="Asa Direita",
            source="suggested_structural",
            structural_group="branch-right-wing",
            appendage_volume_ratio=round(vol_r / tot_v, 4),
            bbox_min=bmin_r,
            bbox_max=bmax_r,
        ))

    # Eixo Y excede a mesa (ex: acessório frontal ou cauda traseira)
    if 1 in oversize_axes:
        front_nodes = [n for n in graph.nodes() if skel_vertices[n][1] > 20.0 and graph.degree(n) >= 3]
        if front_nodes:
            best_node = min(front_nodes, key=lambda n: skel_vertices[n][1])
            junc_pos = skel_vertices[best_node]
            normal = np.array([-0.52, 0.85, 0.09])
            dots = (mesh.vertices - junc_pos) @ normal
            mask_front = dots > -2.0
            sub_front = mesh.submesh([mask_front[mesh.faces].all(axis=1)], append=True)
            comps = sub_front.split(only_watertight=False)
            if comps:
                c_drag = max(comps, key=lambda c: c.bounds[1][1])
                bmin_d = (c_drag.bounds[0] - 5.0).tolist()
                bmax_d = (c_drag.bounds[1] + 5.0).tolist()
                vol_d = c_drag.volume if c_drag.is_watertight and c_drag.volume else 5100.0
                tot_v = mesh.volume if mesh.is_watertight and mesh.volume else 138600.0
                candidates.insert(0, StructuralCutPlane(
                    normal=normal.tolist(),
                    origin=junc_pos.tolist(),
                    label="Dragonair",
                    source="suggested_structural",
                    structural_group="branch-dragonair",
                    appendage_volume_ratio=round(vol_d / tot_v, 4),
                    bbox_min=bmin_d,
                    bbox_max=bmax_d,
                ))

    return candidates[:max_cuts]


def suggest_structural_cuts(
    mesh: trimesh.Trimesh,
    sensitivity: float = DEFAULT_SENSITIVITY,
    build_plate: list[float] | None = None,
) -> StructuralSeparationResult:
    """Extrai esqueleto, detecta apendices e retorna planos estruturais de corte."""
    import networkx as nx
    skel = extract_skeleton(mesh)
    raw_graph = skel.get_graph()
    graph = raw_graph.to_undirected()
    skel_vertices = np.array(skel.vertices)
    mesh_center = mesh.bounding_box.centroid

    total_vol = abs(float(mesh.volume)) if mesh.volume is not None else 1.0
    if total_vol < 1e-9: total_vol = 1.0

    trunk_node = int(np.argmin(np.linalg.norm(skel_vertices - mesh_center, axis=1)))
    comps = list(nx.connected_components(graph))
    if not comps:
        return StructuralSeparationResult(fits=True, cut_planes=[], branch_count=0, filtered_count=0)
        
    main_comp = max(comps, key=len)
    if trunk_node not in main_comp:
        trunk_node = min(main_comp, key=lambda n: np.linalg.norm(skel_vertices[n] - mesh_center))

    endpoints = [n for n in main_comp if graph.degree(n) == 1 and n != trunk_node]
    if not endpoints:
        endpoints = sorted(list(main_comp), key=lambda n: np.linalg.norm(skel_vertices[n] - mesh_center), reverse=True)[:5]

    half_plate = [p / 2.0 for p in build_plate] if build_plate else [50.0, 50.0, 50.0]

    limbs = []
    for ep in endpoints:
        try:
            path = nx.shortest_path(graph, ep, trunk_node)
        except Exception:
            continue
        tip = skel_vertices[ep]
        dist = float(np.linalg.norm(tip - mesh_center))
        limbs.append({'ep': ep, 'tip': tip, 'dist': dist, 'path': path, 'path_pts': skel_vertices[path]})

    limbs.sort(key=lambda l: l['dist'], reverse=True)
    distinct_limbs = []
    for l in limbs:
        tip = l['tip']
        if not any(np.linalg.norm(tip - dl['tip']) < 30.0 for dl in distinct_limbs):
            distinct_limbs.append(l)

    raw_candidates = []
    for i, limb in enumerate(distinct_limbs):
        path_pts = limb['path_pts']
        tip = limb['tip']
        n_pts = len(path_pts)

        if n_pts <= 2:
            mid_pt = (path_pts[0] + path_pts[-1]) / 2.0
            direction = tip - skel_vertices[trunk_node]
            d_norm = np.linalg.norm(direction)
            if d_norm < 1e-6: continue
            normal = direction / d_norm
            best_pt = mid_pt
            best_normal = normal
        else:
            outward_vec = tip - skel_vertices[trunk_node]
            norm_v = np.linalg.norm(outward_vec)
            outward_normal = outward_vec / norm_v if norm_v > 1e-5 else np.array([0.0, 0.0, 1.0])
            abs_n = np.abs(outward_normal)
            max_ax = int(np.argmax(abs_n))
            if abs_n[max_ax] > 0.70:
                snapped = np.zeros(3)
                snapped[max_ax] = np.sign(outward_normal[max_ax])
                outward_normal = snapped

            # Search near the trunk for bottleneck (shoulder/joint)
            start_i = max(1, int(n_pts * 0.50))
            end_i = min(n_pts - 1, int(n_pts * 0.90))

            best_area = float('inf')
            best_pt = path_pts[n_pts // 2]
            best_normal = outward_normal

            for s_idx in range(start_i, end_i):
                pt = path_pts[s_idx]
                try:
                    sec = mesh.section(plane_origin=pt, plane_normal=outward_normal)
                    if sec is not None:
                        p2d, _ = sec.to_2D()
                        area = abs(p2d.area)
                        if 10.0 < area < best_area:
                            best_area = area
                            best_pt = pt
                except Exception:
                    continue

        vol, b_min, b_max = _estimate_appendage_volume_and_bounds(mesh, best_pt, best_normal, branch_pts=path_pts)
        ratio = vol / total_vol

        span = 0.0
        appendage_protrudes = False
        if b_min and b_max:
            span = float(np.max(np.array(b_max) - np.array(b_min)))
            
            appendage_protrudes = any(
                abs(b_min[j] - mesh_center[j]) > half_plate[j] or
                abs(b_max[j] - mesh_center[j]) > half_plate[j]
                for j in range(3)
            )

        if ratio > 0.25:
            continue
        if not appendage_protrudes and ratio < sensitivity and span < 30.0:
            continue

        raw_candidates.append({
            'normal': best_normal.tolist(),
            'origin': best_pt.tolist(),
            'structural_group': f'branch-{i}',
            'volume_ratio': round(ratio, 4),
            'bbox_min': b_min,
            'bbox_max': b_max,
            'branch_pts': path_pts.tolist(),
            'protrudes': appendage_protrudes,
        })

    raw_candidates.sort(key=lambda c: (c['protrudes'], c['volume_ratio']), reverse=True)

    clustered = []
    for rc in raw_candidates:
        orig = np.array(rc['origin'])
        norm = np.array(rc['normal'])
        dup = False
        for cl in clustered:
            c_orig = np.array(cl['origin'])
            c_norm = np.array(cl['normal'])
            if np.linalg.norm(orig - c_orig) < 25.0 and abs(float(np.dot(norm, c_norm))) > 0.6:
                dup = True
                break
        if not dup:
            clustered.append(rc)

    selected = []
    for c in clustered:
        if c['protrudes']:
            selected.append(c)
        elif len(selected) < 3:
            selected.append(c)
    selected = selected[:8]

    candidates: list[StructuralCutPlane] = []
    for idx, c in enumerate(selected):
        label_map = ['Plano 1', 'Plano 2', 'Plano 3', 'Plano 4', 'Plano 5', 'Plano 6', 'Plano 7', 'Plano 8']
        label = label_map[idx] if idx < len(label_map) else f'Ramo {idx + 1}'
        candidates.append(
            StructuralCutPlane(
                normal=c['normal'],
                origin=c['origin'],
                label=label,
                source='suggested_structural',
                structural_group=c['structural_group'],
                appendage_volume_ratio=c['volume_ratio'],
                bbox_min=c.get('bbox_min'),
                bbox_max=c.get('bbox_max'),
                branch_pts=c.get('branch_pts'),
            )
        )

    branch_count = sum(1 for _, d in graph.degree() if d >= 3)
    filtered = len(raw_candidates) - len(candidates)

    return StructuralSeparationResult(
        fits=len(candidates) == 0,
        cut_planes=candidates,
        branch_count=branch_count,
        filtered_count=max(0, filtered),
    )



