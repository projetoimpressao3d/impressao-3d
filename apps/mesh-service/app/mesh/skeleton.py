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
_MAX_VERTICES_BEFORE_SIMPLIFY: int = 50_000


@dataclass
class StructuralCutPlane:
    """Plano de corte sugerido pela analise estrutural de esqueleto."""

    normal: list[float]
    origin: list[float]
    label: str
    source: str = "suggested_structural"
    structural_group: str = "trunk"
    appendage_volume_ratio: float = 0.0


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

    if len(fixed.vertices) > _MAX_VERTICES_BEFORE_SIMPLIFY:
        target_ratio = _MAX_VERTICES_BEFORE_SIMPLIFY / len(fixed.vertices)
        fixed = sk.pre.simplify(fixed, ratio=target_ratio)
        logger.info("Malha simplificada para %d vertices", len(fixed.vertices))

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


def _estimate_appendage_volume(
    mesh: trimesh.Trimesh,
    cut_origin: np.ndarray,
    cut_normal: np.ndarray,
) -> float:
    """Estima o volume do apendice no lado positivo do plano de corte."""
    try:
        dots = (mesh.vertices - cut_origin) @ cut_normal
        face_dots = dots[mesh.faces]
        appendage_mask = (face_dots >= 0).all(axis=1)
        n_appendage_faces = appendage_mask.sum()
        if n_appendage_faces == 0:
            return 0.0
        volume_ratio = n_appendage_faces / len(mesh.faces)
        total_volume = abs(float(mesh.volume)) if mesh.volume is not None else 1.0
        return volume_ratio * total_volume
    except Exception:  # noqa: BLE001
        return 0.0


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

    candidates: list[StructuralCutPlane] = []

    for i, branch_path in enumerate(branches):
        starts_at_branch = branch_path[0] in set(branch_nodes)
        ends_at_endpoint = branch_path[-1] in set(endpoints)
        if not (starts_at_branch and ends_at_endpoint):
            continue

        result = _compute_branch_cut_plane(mesh, branch_path, skel_vertices)
        if result is None:
            continue
        normal_list, origin_list = result

        normal_arr = np.array(normal_list)
        origin_arr = np.array(origin_list)

        appendage_vol = _estimate_appendage_volume(mesh, origin_arr, normal_arr)
        ratio = appendage_vol / total_volume

        logger.debug("Ramo %d: volume_ratio=%.3f, sensitivity=%.3f", i, ratio, sensitivity)

        if ratio < sensitivity:
            logger.debug("Ramo %d descartado (abaixo do limiar)", i)
            continue

        label_num = len(candidates) + 1
        candidates.append(
            StructuralCutPlane(
                normal=normal_list,
                origin=origin_list,
                label=f"Ramo {label_num}",
                source="suggested_structural",
                structural_group=f"branch-{i}",
                appendage_volume_ratio=round(ratio, 4),
            )
        )

    candidates.sort(key=lambda c: c.appendage_volume_ratio, reverse=True)
    logger.info("find_structural_candidates: %d candidatos aprovados", len(candidates))
    return candidates


def suggest_structural_cuts(
    mesh: trimesh.Trimesh,
    sensitivity: float = DEFAULT_SENSITIVITY,
) -> StructuralSeparationResult:
    """Extrai esqueleto, detecta apendices e retorna planos estruturais de corte."""
    skel = extract_skeleton(mesh)
    candidates = find_structural_candidates(skel, mesh, sensitivity)
    graph = skel.get_graph()
    branch_count = sum(1 for _, d in graph.degree() if d >= 3)
    all_candidates = find_structural_candidates(skel, mesh, 0.0)
    filtered = len(all_candidates) - len(candidates)

    return StructuralSeparationResult(
        fits=len(candidates) == 0,
        cut_planes=candidates,
        branch_count=branch_count,
        filtered_count=max(0, filtered),
    )
