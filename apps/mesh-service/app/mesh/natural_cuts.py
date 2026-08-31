"""
Deteccao automatica de pontos naturais de corte para divisao de malhas 3D.

Secao 6.4 do AGENTS.md - passos 3a e 3b:

3a. Varrer o modelo com trimesh.section em 18 direcoes (3 eixos principais +
    6 diagonais de face + 4 diagonais 3D + 5 diagonais rasas), calcular a area
    da seccao transversal em cada posicao e identificar minimos locais ("gargalos")
    — candidatos de corte com alta chance de coincidir com juncoes naturais do objeto.

3b. Selecao gulosa que escolhe o menor conjunto de cortes priorizando candidatos de menor
    area. Fallback em grade para pecas sem gargalo natural suficiente.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import trimesh

logger = logging.getLogger(__name__)

_v2 = 1.0 / math.sqrt(2)
_v3 = 1.0 / math.sqrt(3)
_v5a = 2.0 / math.sqrt(5)   # componente maior em diagonais rasas
_v5b = 1.0 / math.sqrt(5)   # componente menor em diagonais rasas

# 18 direcoes de varredura distribuidas uniformemente:
#   - 3 eixos principais (X, Y, Z)
#   - 6 diagonais de face (XY, YZ, XZ nos dois sinais)
#   - 4 diagonais 3D (todas as combinacoes de ±X±Y±Z / sqrt(3))
#   - 5 diagonais rasas (vies maior em 1 eixo) para capturar membros inclinados
_SCAN_DIRECTIONS: list[np.ndarray] = [
    # Eixos principais
    np.array([1.0, 0.0, 0.0]),
    np.array([0.0, 1.0, 0.0]),
    np.array([0.0, 0.0, 1.0]),
    # Diagonais de face (planos XY, YZ, XZ)
    np.array([_v2,  _v2,  0.0]),
    np.array([_v2, -_v2,  0.0]),
    np.array([_v2,  0.0,  _v2]),
    np.array([_v2,  0.0, -_v2]),
    np.array([0.0,  _v2,  _v2]),
    np.array([0.0,  _v2, -_v2]),
    # Diagonais 3D (quatro octantes — suficiente por simetria)
    np.array([_v3,  _v3,  _v3]),
    np.array([_v3,  _v3, -_v3]),
    np.array([_v3, -_v3,  _v3]),
    np.array([_v3, -_v3, -_v3]),
    # Diagonais rasas (vies em X — membros com mais extensao horizontal)
    np.array([_v5a,  _v5b,  0.0]),
    np.array([_v5a, -_v5b,  0.0]),
    # Diagonais rasas (vies em Y — membros com mais extensao vertical)
    np.array([_v5b,  _v5a,  0.0]),
    np.array([0.0,   _v5a,  _v5b]),
    # Diagonal rasa (vies em Z — plataformas / caudas horizontais)
    np.array([_v5b,  0.0,   _v5a]),
]

_N_SLICES: int = 40
_MIN_PROMINENCE_RATIO: float = 0.15


@dataclass
class CutCandidate:
    axis: int
    position: float
    area_mm2: float


@dataclass
class SuggestedCutPlane:
    normal: list[float]
    origin: list[float]
    label: str
    source: str


@dataclass
class SuggestedSplitPlan:
    fits: bool
    cut_planes: list[SuggestedCutPlane] = field(default_factory=list)


def scan_cross_sections(
    mesh: trimesh.Trimesh,
    direction: np.ndarray,
    n_slices: int = _N_SLICES,
) -> list[tuple[float, float]]:
    """Varre o modelo ao longo de direction e retorna pares (posicao, area_mm2)."""
    direction = np.asarray(direction, dtype=np.float64)
    norm = float(np.linalg.norm(direction))
    if norm < 1e-9:
        return []
    direction = direction / norm

    projections: np.ndarray = mesh.vertices @ direction
    proj_min = float(projections.min())
    proj_max = float(projections.max())

    if proj_max - proj_min < 1.0:
        return []

    positions = np.linspace(proj_min, proj_max, n_slices + 2)[1:-1]

    results: list[tuple[float, float]] = []
    for pos in positions:
        origin_3d = direction * float(pos)
        try:
            section = mesh.section(plane_origin=origin_3d, plane_normal=direction)
            if section is None:
                continue
            path2d, _ = section.to_2D()
            area = float(path2d.area)
            if area > 1e-6:
                results.append((float(pos), area))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Seccao em %.2fmm falhou: %s", pos, exc)

    return results


def find_local_minima(
    data: list[tuple[float, float]],
    min_prominence_ratio: float = _MIN_PROMINENCE_RATIO,
) -> list[int]:
    """Detecta indices de minimos locais na curva de area das seccoes transversais."""
    if len(data) < 3:
        return []

    areas = [d[1] for d in data]
    area_range = max(areas) - min(areas)

    if area_range < 1e-6:
        return []

    prominence_threshold = min_prominence_ratio * area_range
    minima: list[int] = []

    for i in range(1, len(areas) - 1):
        if areas[i] < areas[i - 1] and areas[i] < areas[i + 1]:
            left_max = max(areas[:i])
            right_max = max(areas[i + 1:])
            prominence = min(left_max, right_max) - areas[i]
            if prominence >= prominence_threshold:
                minima.append(i)

    return minima


def detect_natural_cut_candidates(
    mesh: trimesh.Trimesh,
    n_slices: int = _N_SLICES,
) -> list[list[CutCandidate]]:
    """
    Varre 9 direcoes e retorna candidatos de corte projetados por eixo [X, Y, Z].
    Cada sublista esta ordenada por area crescente (gargalos menores primeiro).
    """
    bounds = mesh.bounds
    candidates_per_axis: list[list[CutCandidate]] = [[], [], []]

    for direction in _SCAN_DIRECTIONS:
        cross_data = scan_cross_sections(mesh, direction, n_slices=n_slices)
        if not cross_data:
            continue

        minima_indices = find_local_minima(cross_data)
        for idx in minima_indices:
            pos_along_dir, area = cross_data[idx]
            origin_3d = direction * pos_along_dir

            for axis_idx in range(3):
                pos_on_axis = float(origin_3d[axis_idx])
                ax_min = float(bounds[0][axis_idx])
                ax_max = float(bounds[1][axis_idx])

                if ax_min < pos_on_axis < ax_max:
                    candidates_per_axis[axis_idx].append(
                        CutCandidate(axis=axis_idx, position=pos_on_axis, area_mm2=area)
                    )

    for axis_idx in range(3):
        candidates_per_axis[axis_idx].sort(key=lambda c: c.area_mm2)

    return candidates_per_axis


def _compute_pieces(
    axis_min: float,
    axis_max: float,
    cut_positions: list[float],
) -> list[tuple[float, float]]:
    boundaries = sorted([axis_min] + cut_positions + [axis_max])
    return [(boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)]


def _greedy_cuts_for_axis(
    axis_min: float,
    axis_max: float,
    plate_dim: float,
    candidates: list[tuple[float, float]],
) -> list[tuple[float, str]]:
    """
    Selecao gulosa de cortes ao longo de um unico eixo.
    candidates: lista de (posicao_mm, area_mm2) ordenada por area crescente.
    Retorna lista de (posicao_mm, source) ordenada por posicao.
    """
    cuts: list[tuple[float, str]] = []

    for pos, _area in candidates:
        pieces = _compute_pieces(axis_min, axis_max, [c[0] for c in cuts])
        if all(hi - lo <= plate_dim for lo, hi in pieces):
            break

        splits_large_piece = any(
            lo <= pos <= hi and hi - lo > plate_dim
            for lo, hi in pieces
        )
        if splits_large_piece:
            cuts.append((pos, "suggested_natural"))

    pieces = _compute_pieces(axis_min, axis_max, [c[0] for c in cuts])
    for lo, hi in pieces:
        if hi - lo > plate_dim:
            n_parts = math.ceil((hi - lo) / plate_dim)
            part_size = (hi - lo) / n_parts
            for i in range(1, n_parts):
                cuts.append((lo + i * part_size, "suggested_grid_fallback"))

    return sorted(cuts, key=lambda c: c[0])


_AXIS_NAMES = ["X", "Y", "Z"]
_AXIS_NORMALS = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def suggest_cuts(
    mesh: trimesh.Trimesh,
    plate_dims: dict[str, float],
) -> SuggestedSplitPlan:
    """
    Gera sugestoes de corte automaticas para que o modelo caiba na mesa.

    O mesh deve estar centrado na origem (bounding box center = [0,0,0]).
    Retorna SuggestedSplitPlan com fits=True (sem planos) ou com planos sugeridos
    incluindo campo source ("suggested_natural" ou "suggested_grid_fallback").
    """
    extents = mesh.extents
    bounds = mesh.bounds

    plate_x = float(plate_dims["x"])
    plate_y = float(plate_dims["y"])
    plate_z = float(plate_dims["z"])

    fits = (
        float(extents[0]) <= plate_x
        and float(extents[1]) <= plate_y
        and float(extents[2]) <= plate_z
    )

    if fits:
        logger.info("Modelo ja cabe na mesa - nenhum corte sugerido.")
        return SuggestedSplitPlan(fits=True)

    logger.info(
        "Modelo nao cabe: extents=[%.1f, %.1f, %.1f]mm  plate=[%.1f, %.1f, %.1f]mm",
        float(extents[0]), float(extents[1]), float(extents[2]),
        plate_x, plate_y, plate_z,
    )

    logger.info("Varrendo %d direcoes para deteccao de gargalos...", len(_SCAN_DIRECTIONS))
    candidates_per_axis = detect_natural_cut_candidates(mesh)
    logger.info(
        "Candidatos: X=%d Y=%d Z=%d",
        len(candidates_per_axis[0]),
        len(candidates_per_axis[1]),
        len(candidates_per_axis[2]),
    )

    _plate_per_axis = [plate_x, plate_y, plate_z]
    all_planes: list[SuggestedCutPlane] = []

    for axis_idx in range(3):
        plate_dim = _plate_per_axis[axis_idx]
        axis_extent = float(extents[axis_idx])

        if axis_extent <= plate_dim:
            continue

        axis_min = float(bounds[0][axis_idx])
        axis_max = float(bounds[1][axis_idx])
        axis_name = _AXIS_NAMES[axis_idx]
        candidates = [(c.position, c.area_mm2) for c in candidates_per_axis[axis_idx]]

        cuts = _greedy_cuts_for_axis(
            axis_min=axis_min,
            axis_max=axis_max,
            plate_dim=plate_dim,
            candidates=candidates,
        )

        for cut_num, (pos, source) in enumerate(cuts, start=1):
            origin = [0.0, 0.0, 0.0]
            origin[axis_idx] = pos
            label = (
                f"Gargalo {axis_name}-{cut_num}"
                if source == "suggested_natural"
                else f"Divisao {axis_name}-{cut_num} (grade)"
            )
            all_planes.append(
                SuggestedCutPlane(
                    normal=list(_AXIS_NORMALS[axis_idx]),
                    origin=origin,
                    label=label,
                    source=source,
                )
            )

        logger.info(
            "Eixo %s: %d corte(s) - %s",
            axis_name, len(cuts),
            ", ".join(f"{p:.1f}mm ({s})" for p, s in cuts),
        )

    return SuggestedSplitPlan(fits=False, cut_planes=all_planes)
