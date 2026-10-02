"""
Módulo de Divisão Geral de Modelos (General Split).
Inspirado na seção 2.3 do Hi3D ("General Split com granularidade low, medium, high").

Propósito:
- Particiona modelos de formato geométrico, mecânico ou arbitrário para que
  100% das peças resultantes caibam com precisão dentro do volume útil da mesa
  de impressão do usuário [Wx, Wy, Wz].
- Utiliza Decomposição Recursiva no Espaço (BSP - Binary Space Partitioning),
  priorizando secções transversais de menor área (gargalos naturais) detectadas
  via scan de geometria, e aplicando bisseção equilibrada quando o objeto for uniforme.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import trimesh

from app.mesh.natural_cuts import SuggestedCutPlane, SuggestedSplitPlan, scan_cross_sections, find_local_minima

logger = logging.getLogger(__name__)

_AXIS_NAMES = ["X", "Y", "Z"]
_AXIS_NORMALS = [
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
]


@dataclass
class GeneralSplitResult:
    fits: bool
    cut_planes: list[SuggestedCutPlane] = field(default_factory=list)
    piece_count: int = 1
    granularity: str = "auto"


def suggest_general_split(
    mesh: trimesh.Trimesh,
    plate_dims: dict[str, float],
    granularity: Literal["auto", "low", "medium", "high"] = "auto",
    max_cuts: int = 8,
) -> GeneralSplitResult:
    """
    Calcula os planos de corte necessários para que qualquer objeto arbitrário
    caiba no volume útil da mesa de impressão.

    Args:
        mesh: Malha trimesh centrada na origem.
        plate_dims: Dicionário com 'x', 'y', 'z' em mm.
        granularity:
            - 'auto' / 'low': Cortes mínimos estritamente necessários para caber.
            - 'medium': Margem de segurança de 10% nas bordas da mesa.
            - 'high': Segmentação modular em peças menores para impressão ágil.
        max_cuts: Limite de planos de corte sugeridos.

    Returns:
        GeneralSplitResult com fits=True (se já couber) ou lista de cut_planes sugeridos.
    """
    plate_x = float(plate_dims["x"])
    plate_y = float(plate_dims["y"])
    plate_z = float(plate_dims["z"])

    # Fatores de margem por granularidade
    factor_map = {
        "auto": 1.0,
        "low": 1.0,
        "medium": 0.90,  # 10% margem de segurança
        "high": 0.75,    # 25% margem para peças menores modulares
    }
    factor = factor_map.get(granularity, 1.0)
    target_limits = [plate_x * factor, plate_y * factor, plate_z * factor]

    extents = mesh.extents
    if all(float(extents[i]) <= target_limits[i] for i in range(3)):
        logger.info("Modelo já cabe na mesa com granularidade '%s'.", granularity)
        return GeneralSplitResult(fits=True, cut_planes=[], piece_count=1, granularity=granularity)

    logger.info(
        "General Split: modelo [%.1f, %.1f, %.1f]mm excede mesa [%.1f, %.1f, %.1f]mm (fator %.2f)",
        *extents,
        *target_limits,
        factor,
    )

    # Fila de peças para decomposição recursiva (BSP)
    # Cada item é uma tupla: (sub_mesh, bounds_min, bounds_max)
    active_pieces: list[trimesh.Trimesh] = [mesh]
    suggested_planes: list[SuggestedCutPlane] = []

    iteration = 0
    while iteration < max_cuts:
        iteration += 1

        # Encontrar a peça com a maior razão de excedência
        worst_piece_idx = -1
        worst_ratio = 1.0
        worst_axis = 0

        for idx, piece in enumerate(active_pieces):
            p_extents = piece.extents
            for ax in range(3):
                ratio = float(p_extents[ax]) / target_limits[ax]
                if ratio > worst_ratio:
                    worst_ratio = ratio
                    worst_piece_idx = idx
                    worst_axis = ax

        # Se nenhuma peça excede os limites, terminamos com sucesso!
        if worst_piece_idx == -1 or worst_ratio <= 1.001:
            break

        target_piece = active_pieces.pop(worst_piece_idx)
        p_bounds = target_piece.bounds
        p_min = float(p_bounds[0][worst_axis])
        p_max = float(p_bounds[1][worst_axis])
        p_span = p_max - p_min
        ax_name = _AXIS_NAMES[worst_axis]
        ax_normal = np.array(_AXIS_NORMALS[worst_axis], dtype=np.float64)

        # 1. Procurar gargalos naturais no terço central da peça [35% a 65%]
        scan_dir = ax_normal
        cross_data = scan_cross_sections(target_piece, scan_dir, n_slices=25)
        minima = find_local_minima(cross_data, min_prominence_ratio=0.12)

        best_cut_pos: float | None = None
        source = "suggested_grid_fallback"
        label = f"Divisão Geral {ax_name}-{iteration}"

        # Filtrar mínimos que fiquem no terço central
        mid_min = p_min + 0.30 * p_span
        mid_max = p_min + 0.70 * p_span

        valid_minima = [
            cross_data[m] for m in minima
            if mid_min <= cross_data[m][0] <= mid_max
        ]

        if valid_minima:
            # Escolher o mínimo de menor área
            valid_minima.sort(key=lambda item: item[1])
            best_cut_pos = float(valid_minima[0][0])
            source = "suggested_natural"
            label = f"Gargalo Geral {ax_name}-{iteration}"

        if best_cut_pos is None:
            # Bisseção equilibrada
            best_cut_pos = (p_min + p_max) / 2.0
            source = "suggested_grid_fallback"
            label = f"Bisseção {ax_name}-{iteration}"

        # Construir plano de corte
        origin = [0.0, 0.0, 0.0]
        # Preservar o centro da peça nos outros dois eixos
        p_center = target_piece.bounding_box.centroid
        for a in range(3):
            origin[a] = float(p_center[a])
        origin[worst_axis] = best_cut_pos

        cut_plane = SuggestedCutPlane(
            normal=list(_AXIS_NORMALS[worst_axis]),
            origin=origin,
            label=label,
            source=source,
        )
        suggested_planes.append(cut_plane)

        # Seccionar a peça para continuar o particionamento recursivo
        try:
            from app.mesh.cutter import _trimesh_to_manifold, _manifold_to_trimesh
            m = _trimesh_to_manifold(target_piece)
            top_m, bot_m = m.split_by_plane(cut_plane.normal, float(best_cut_pos))
            t_mesh = _manifold_to_trimesh(top_m)
            b_mesh = _manifold_to_trimesh(bot_m)

            if len(t_mesh.vertices) > 0 and len(b_mesh.vertices) > 0:
                active_pieces.append(t_mesh)
                active_pieces.append(b_mesh)
            else:
                # Se falhar o split na malha, simular apenas com a peça original
                active_pieces.append(target_piece)
                break
        except Exception as exc:
            logger.warning("Falha ao simular partição BSP: %s", exc)
            active_pieces.append(target_piece)
            break

    total_pieces = len(suggested_planes) + 1
    logger.info(
        "General Split finalizado: %d planos sugeridos, gerando %d peças (granularity=%s).",
        len(suggested_planes),
        total_pieces,
        granularity,
    )

    return GeneralSplitResult(
        fits=False,
        cut_planes=suggested_planes,
        piece_count=total_pieces,
        granularity=granularity,
    )
