"""
plate_packer.py — Empacota pecas separadas por cor em mesas de trabalho.

Algoritmo:
1. Para cada peca, verifica se cabe na mesa (bounding box < volume da mesa).
2. Pecas que nao cabem sao subdivididas (grade) e colocadas em mesas separadas.
3. Agrupa pecas que cabem juntas na mesma mesa usando um bin-packing simples.
4. Retorna layout: lista de mesas, cada uma com suas pecas e posicoes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import trimesh

logger = logging.getLogger(__name__)


@dataclass
class PlatePlacement:
    """Posicionamento de uma peca em uma mesa."""
    piece_index: int          # Indice da peca no ColorSplitResult.pieces
    extruder_index: int       # Qual extruder/cor
    color_hex: str
    mesh: trimesh.Trimesh
    position: np.ndarray      # [x, y, z] — posicao do canto min da bbox na mesa
    rotation_deg: float = 0.0  # Rotacao Z opcional para melhor encaixe
    packed_meshes: list[trimesh.Trimesh] = field(default_factory=list)
    fits_in_plate: bool = True
    extents_mm: list[float] = field(default_factory=list)


@dataclass  
class PrintPlate:
    """Uma mesa de trabalho com as pecas a serem impressas juntas."""
    plate_index: int          # 0-based
    placements: list[PlatePlacement] = field(default_factory=list)
    plate_x_mm: float = 256.0
    plate_y_mm: float = 256.0
    plate_z_mm: float = 256.0

    @property
    def is_empty(self) -> bool:
        return len(self.placements) == 0


@dataclass
class PackResult:
    plates: list[PrintPlate]
    oversized_pieces: list[int]  # indices de pecas que nao cabem mesmo separadas


def _fits_in_plate(mesh: trimesh.Trimesh, plate_x: float, plate_y: float, plate_z: float) -> bool:
    """Verifica se a bounding box da malha cabe na mesa (com 5mm de margem)."""
    margin = 5.0
    extents = mesh.extents
    return (
        extents[0] <= plate_x - margin and
        extents[1] <= plate_y - margin and
        extents[2] <= plate_z - margin
    )


def pack_components_2d(
    meshes: list[trimesh.Trimesh],
    plate_x: float,
    plate_y: float,
    plate_z: float,
    margin: float = 6.0,
    spacing: float = 8.0,
    snap_to_floor: bool = True,
) -> tuple[list[trimesh.Trimesh], bool, list[float]]:
    """
    Arranja componentes na mesa de trabalho (plano XY).
    Cada componente:
      1. Se snap_to_floor=True: assenta na base (min_z -> 0)
      2. Centraliza na sua própria origem XY
      3. Rotaciona 90 graus no plano XY se ajudar a caber melhor
      4. Posiciona em 'shelves' (linhas) no plano XY
    Centraliza o layout total no centro da mesa (plate_x/2, plate_y/2).
    Retorna:
      - lista de malhas já posicionadas e assentadas
      - fits_in_plate: bool indicando se coube na mesa
      - extents: [layout_w, layout_d, max_z]
    """
    if not meshes:
        return [], True, [0.0, 0.0, 0.0]

    items = []
    for m in meshes:
        mc = m.copy()
        if snap_to_floor:
            min_z = float(mc.vertices[:, 2].min())
            mc.vertices[:, 2] -= min_z
        min_xy = mc.vertices[:, :2].min(axis=0)
        max_xy = mc.vertices[:, :2].max(axis=0)
        center_xy = (min_xy + max_xy) / 2.0
        mc.vertices[:, :2] -= center_xy
        ew = float(max_xy[0] - min_xy[0])
        ed = float(max_xy[1] - min_xy[1])
        ez = (
            float(mc.vertices[:, 2].max())
            if snap_to_floor
            else float(mc.vertices[:, 2].max()) - float(mc.vertices[:, 2].min())
        )
        items.append({'mesh': mc, 'ew': ew, 'ed': ed, 'ez': ez})

    # Ordenar por área de projeção XY decrescente
    items.sort(key=lambda it: it['ew'] * it['ed'], reverse=True)
    usable_w = plate_x - 2 * margin
    usable_d = plate_y - 2 * margin

    current_x = 0.0
    current_y = 0.0
    row_max_h = 0.0
    all_fit = True

    for it in items:
        ew, ed, ez = it['ew'], it['ed'], it['ez']
        if ez > (plate_z - margin):
            all_fit = False

        # Rotação de 90 graus se couber melhor
        if ew > usable_w and ed <= usable_w:
            it['mesh'].vertices[:, [0, 1]] = it['mesh'].vertices[:, [1, 0]]
            it['mesh'].vertices[:, 0] *= -1
            ew, ed = ed, ew
            it['ew'], it['ed'] = ew, ed
        elif ed > usable_d and ew <= usable_d:
            it['mesh'].vertices[:, [0, 1]] = it['mesh'].vertices[:, [1, 0]]
            it['mesh'].vertices[:, 0] *= -1
            ew, ed = ed, ew
            it['ew'], it['ed'] = ew, ed

        if current_x + ew > usable_w and current_x > 0:
            current_x = 0.0
            current_y += row_max_h + spacing
            row_max_h = 0.0

        if (current_y + ed > usable_d) or (ew > usable_w):
            all_fit = False

        cx = margin + current_x + ew / 2.0
        cy = margin + current_y + ed / 2.0
        row_max_h = max(row_max_h, ed)
        current_x += ew + spacing
        it['cx'] = cx
        it['cy'] = cy

    min_x = min(it['cx'] - it['ew'] / 2.0 for it in items)
    max_x = max(it['cx'] + it['ew'] / 2.0 for it in items)
    min_y = min(it['cy'] - it['ed'] / 2.0 for it in items)
    max_y = max(it['cy'] + it['ed'] / 2.0 for it in items)
    layout_w = max_x - min_x
    layout_d = max_y - min_y

    shift_x = (plate_x - layout_w) / 2.0 - min_x
    shift_y = (plate_y - layout_d) / 2.0 - min_y

    packed_meshes = []
    for it in items:
        mc = it['mesh']
        mc.vertices[:, 0] += it['cx'] + shift_x
        mc.vertices[:, 1] += it['cy'] + shift_y
        packed_meshes.append(mc)

    extents = [layout_w, layout_d, max(it['ez'] for it in items)]
    return packed_meshes, all_fit, extents


def pack_pieces_to_plates(
    pieces: list,  # list[ColorPiece]
    plate_x_mm: float,
    plate_y_mm: float,
    plate_z_mm: float,
    snap_to_floor: bool = True,
) -> PackResult:
    """
    Distribui as pecas separadas por cor em mesas de impressao.
    
    Cada peca de cor diferente vai para sua propria mesa (comportamento Split3MF).
    Reposiciona sub-componentes (asas, garras, etc.) para que caibam na mesa
    e assentem na base (Z=0).
    """
    plates: list[PrintPlate] = []
    oversized: list[int] = []

    for i, piece in enumerate(pieces):
        sub_list = piece.sub_meshes if piece.sub_meshes else [piece.mesh]

        if snap_to_floor:
            packed_meshes, fits, extents = pack_components_2d(
                sub_list,
                plate_x_mm,
                plate_y_mm,
                plate_z_mm,
                snap_to_floor=True,
            )
        else:
            # Mantem posicao original sem snap e sem reposicionamento
            fits = _fits_in_plate(piece.mesh, plate_x_mm, plate_y_mm, plate_z_mm)
            packed_meshes = [piece.mesh]
            extents = list(piece.mesh.extents)

        if not fits:
            logger.warning(
                f"Peca {i} ({piece.filament.color_hex}) nao cabe na mesa "
                f"({np.round(extents, 1)} > {[plate_x_mm, plate_y_mm, plate_z_mm]})"
            )
            oversized.append(i)

        plate = PrintPlate(
            plate_index=len(plates),
            plate_x_mm=plate_x_mm,
            plate_y_mm=plate_y_mm,
            plate_z_mm=plate_z_mm,
        )

        pos = np.array([plate_x_mm / 2.0, plate_y_mm / 2.0, 0.0])

        placement = PlatePlacement(
            piece_index=i,
            extruder_index=piece.extruder_index,
            color_hex=piece.filament.color_hex,
            mesh=piece.mesh,
            position=pos,
            packed_meshes=packed_meshes,
            fits_in_plate=fits,
            extents_mm=extents,
        )
        plate.placements.append(placement)
        plates.append(plate)

        logger.info(
            f"Peca {i} ({piece.filament.color_hex}) -> Mesa {plate.plate_index + 1}, "
            f"fits={fits}, extents={np.round(extents, 1)}"
        )

    return PackResult(plates=plates, oversized_pieces=oversized)
