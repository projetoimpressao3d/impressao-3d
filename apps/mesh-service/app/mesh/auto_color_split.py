"""
Pipeline automático de "Separação por cores" (com ou sem pinos de encaixe).

Executa, sem nenhuma ação manual do usuário:
1. Fechamento (capping) de cada componente de cada cor.
2. (opcional) Pinos de encaixe nas interfaces entre cores diferentes (modelos pintados).
3. Divisão automática (`fit_to_plate`) de cada componente que não cabe na mesa,
   com pinos nas faces de corte quando `generate_connectors=True`.
4. Distribuição das peças resultantes em mesas (uma cor por mesa — impressão com 1 bico),
   agrupando várias peças da mesma cor na mesma mesa quando couberem.

Todo o processamento é síncrono/CPU-bound; o router chama esta função em thread separada.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import trimesh

from app.mesh.capper import close_color_piece
from app.mesh.color_interface_pins import apply_color_interface_pins, find_color_interfaces
from app.mesh.color_splitter import ColorSplitResult
from app.mesh.fit_to_plate import _fits_plate, _orient_piece_to_fit_if_needed, fit_to_plate
from app.mesh.plate_packer import pack_components_2d

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, str], None]

_PACK_MARGIN_MM = 2.0
_PACK_SPACING_MM = 5.0


@dataclass
class AutoPart:
    mesh: trimesh.Trimesh
    label: str
    has_connectors: bool
    is_subdivided: bool


@dataclass
class AutoPlate:
    extruder_number: int
    color_hex: str
    meshes: list[trimesh.Trimesh]          # já posicionadas na mesa e assentadas em Z=0
    part_labels: list[str]
    fits_in_plate: bool
    extents_mm: list[float]
    has_connectors: bool
    is_subdivided: bool
    plate_index_in_color: int = 1


@dataclass
class AutoSplitOutcome:
    plates: list[AutoPlate]
    total_parts: int
    interface_pins: int
    subdivided_colors: list[int] = field(default_factory=list)


def _noop(_: int, __: str) -> None:
    return None


def _close(mesh: trimesh.Trimesh, cap_method: str) -> trimesh.Trimesh:
    closed = close_color_piece(mesh, method=cap_method)
    if closed.is_volume and closed.volume < 0:
        closed.invert()
    return closed


def _pack_parts_into_plates(
    parts: list[AutoPart],
    plate_x: float,
    plate_y: float,
    plate_z: float,
) -> list[tuple[list[AutoPart], list[trimesh.Trimesh], bool, list[float]]]:
    """Bin-packing guloso: tenta colocar cada peça numa mesa existente da mesma cor."""
    ordered = sorted(parts, key=lambda p: float(p.mesh.extents[0] * p.mesh.extents[1]), reverse=True)
    bins: list[list[AutoPart]] = []

    for part in ordered:
        placed = False
        if _fits_plate(part.mesh.extents, plate_x, plate_y, plate_z):
            for group in bins:
                if not all(_fits_plate(p.mesh.extents, plate_x, plate_y, plate_z) for p in group):
                    continue
                _, fits, _ = pack_components_2d(
                    [p.mesh for p in group] + [part.mesh],
                    plate_x,
                    plate_y,
                    plate_z,
                    margin=_PACK_MARGIN_MM,
                    spacing=_PACK_SPACING_MM,
                )
                if fits:
                    group.append(part)
                    placed = True
                    break
        if not placed:
            bins.append([part])

    result = []
    for group in bins:
        packed, fits, extents = pack_components_2d(
            [p.mesh for p in group],
            plate_x,
            plate_y,
            plate_z,
            margin=_PACK_MARGIN_MM,
            spacing=_PACK_SPACING_MM,
        )
        if len(group) == 1:
            fits = _fits_plate(group[0].mesh.extents, plate_x, plate_y, plate_z)
            extents = [float(e) for e in group[0].mesh.extents]
        result.append((group, packed, bool(fits), [round(float(e), 1) for e in extents]))
    return result


def run_auto_color_split(
    split_result: ColorSplitResult,
    plate_x: float,
    plate_y: float,
    plate_z: float,
    generate_connectors: bool,
    tolerance_mm: float,
    pin_shape: str = "hex",
    cap_method: str = "earcut",
    progress: ProgressCallback | None = None,
) -> AutoSplitOutcome:
    report = progress or _noop
    pieces = split_result.pieces
    open_components: list[list[trimesh.Trimesh]] = [
        list(p.sub_meshes) if p.sub_meshes else [p.mesh] for p in pieces
    ]

    # 1. Interfaces entre cores (precisa das cascas ABERTAS — antes do capping)
    interfaces = []
    if generate_connectors and split_result.method == "painted" and len(pieces) > 1:
        report(20, "Analisando as junções entre as cores...")
        try:
            interfaces = find_color_interfaces(open_components)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Detecção de interfaces entre cores falhou: %s", exc)
            interfaces = []

    # 2. Capping de cada componente
    report(28, "Fechando e reparando as malhas de cada cor...")
    closed_components: list[list[trimesh.Trimesh]] = [
        [_close(c, cap_method) for c in comps] for comps in open_components
    ]

    # 3. Pinos nas interfaces entre cores
    interface_pins = 0
    pinned_components: set[tuple[int, int]] = set()
    if interfaces:
        report(35, "Inserindo pinos de encaixe entre as cores...")
        before = [[id(c) for c in comps] for comps in closed_components]
        try:
            pin_report = apply_color_interface_pins(
                closed_components, interfaces, tolerance_mm=tolerance_mm, pin_shape=pin_shape
            )
            interface_pins = pin_report.pins_created
        except Exception as exc:  # noqa: BLE001
            logger.warning("Inserção de pinos entre cores falhou: %s", exc)
        for pi, comps in enumerate(closed_components):
            for ci, c in enumerate(comps):
                if id(c) != before[pi][ci]:
                    pinned_components.add((pi, ci))

    # 4. Divisão automática dos componentes que não cabem + distribuição em mesas
    plates: list[AutoPlate] = []
    subdivided_colors: list[int] = []
    total_parts = 0
    n = max(1, len(pieces))

    for pi, piece in enumerate(pieces):
        ext_num = piece.extruder_index + 1
        color = piece.filament.color_hex
        pct = 40 + int(45 * pi / n)
        parts: list[AutoPart] = []
        color_subdivided = False

        for ci, comp in enumerate(closed_components[pi]):
            if len(comp.faces) == 0:
                continue
            has_itf_pins = (pi, ci) in pinned_components
            oriented = _orient_piece_to_fit_if_needed(comp, plate_x, plate_y, plate_z)
            if _fits_plate(oriented.extents, plate_x, plate_y, plate_z):
                parts.append(AutoPart(oriented, f"Cor {ext_num}", has_itf_pins, False))
                continue

            color_subdivided = True
            report(
                pct,
                f"Dividindo a cor {ext_num} para caber na mesa"
                + (" e inserindo pinos de encaixe..." if generate_connectors else "..."),
            )
            sub_meshes = fit_to_plate(
                comp,
                plate_x,
                plate_y,
                plate_z,
                generate_connectors=generate_connectors,
                connector_tolerance_mm=tolerance_mm,
                connector_pin_shape=pin_shape,
            )
            for k, sm in enumerate(sub_meshes or [comp], start=1):
                if len(sm.faces) == 0:
                    continue
                label = str(sm.metadata.get("label") or f"Parte {k}")
                cut_pins = int(sm.metadata.get("pins_created", 0) or 0) > 0
                parts.append(
                    AutoPart(
                        sm,
                        f"Cor {ext_num} - {label}",
                        has_itf_pins or (generate_connectors and cut_pins),
                        True,
                    )
                )

        if color_subdivided:
            subdivided_colors.append(ext_num)
        if not parts:
            continue

        report(pct, f"Organizando as peças da cor {ext_num} nas mesas...")
        for k, (group, packed, fits, extents) in enumerate(
            _pack_parts_into_plates(parts, plate_x, plate_y, plate_z), start=1
        ):
            plates.append(
                AutoPlate(
                    extruder_number=ext_num,
                    color_hex=color,
                    meshes=packed,
                    part_labels=[p.label for p in group],
                    fits_in_plate=fits,
                    extents_mm=extents,
                    has_connectors=any(p.has_connectors for p in group),
                    is_subdivided=any(p.is_subdivided for p in group),
                    plate_index_in_color=k,
                )
            )
        total_parts += len(parts)

    logger.info(
        "Separação automática: %d mesas, %d peças, %d pinos entre cores, cores divididas=%s",
        len(plates),
        total_parts,
        interface_pins,
        subdivided_colors,
    )
    return AutoSplitOutcome(
        plates=plates,
        total_parts=total_parts,
        interface_pins=interface_pins,
        subdivided_colors=subdivided_colors,
    )


def center_and_ground(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Centraliza em XY na origem e assenta a base em Z=0."""
    mc = mesh.copy()
    lo, hi = mc.bounds
    mc.vertices[:, 0] -= float((lo[0] + hi[0]) / 2.0)
    mc.vertices[:, 1] -= float((lo[1] + hi[1]) / 2.0)
    mc.vertices[:, 2] -= float(lo[2])
    return mc


__all__ = [
    "AutoPlate",
    "AutoSplitOutcome",
    "center_and_ground",
    "run_auto_color_split",
]
