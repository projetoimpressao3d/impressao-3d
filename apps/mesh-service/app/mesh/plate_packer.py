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


def _bottom_center_position(mesh: trimesh.Trimesh, plate_x: float, plate_y: float, plate_z: float) -> np.ndarray:
    """Retorna a posicao para centralizar a peca na mesa com base na plataforma de impressao."""
    extents = mesh.extents
    # Centralizar em X e Y, assentar na base (Z=0)
    x = (plate_x - extents[0]) / 2.0
    y = (plate_y - extents[1]) / 2.0
    z = 0.0
    return np.array([x, y, z])


def pack_pieces_to_plates(
    pieces: list,  # list[ColorPiece]
    plate_x_mm: float,
    plate_y_mm: float,
    plate_z_mm: float,
) -> PackResult:
    """
    Distribui as pecas separadas por cor em mesas de impressao.
    
    Cada peca de cor diferente vai para sua propria mesa (comportamento Split3MF).
    Se uma peca nao cabe em uma mesa, e marcada como oversized.
    
    Para versao futura: implementar bin-packing para multiplas pecas por mesa.
    """
    plates: list[PrintPlate] = []
    oversized: list[int] = []

    for i, piece in enumerate(pieces):
        mesh = piece.mesh

        if not _fits_in_plate(mesh, plate_x_mm, plate_y_mm, plate_z_mm):
            logger.warning(
                f"Peca {i} ({piece.filament.color_hex}) nao cabe na mesa "
                f"({np.round(mesh.extents, 1)} > {[plate_x_mm, plate_y_mm, plate_z_mm]})"
            )
            oversized.append(i)
            # Ainda cria uma mesa para ela (usuario precisa subdividir manualmente)
        
        plate = PrintPlate(
            plate_index=len(plates),
            plate_x_mm=plate_x_mm,
            plate_y_mm=plate_y_mm,
            plate_z_mm=plate_z_mm,
        )

        # Centralizar peca na mesa
        pos = _bottom_center_position(mesh, plate_x_mm, plate_y_mm, plate_z_mm)
        
        placement = PlatePlacement(
            piece_index=i,
            extruder_index=piece.extruder_index,
            color_hex=piece.filament.color_hex,
            mesh=mesh,
            position=pos,
        )
        plate.placements.append(placement)
        plates.append(plate)

        logger.info(
            f"Peca {i} ({piece.filament.color_hex}) -> Mesa {plate.plate_index + 1}, "
            f"pos={np.round(pos, 1)}, extents={np.round(mesh.extents, 1)}"
        )

    return PackResult(plates=plates, oversized_pieces=oversized)
