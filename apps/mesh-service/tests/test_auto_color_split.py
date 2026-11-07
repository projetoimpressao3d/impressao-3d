"""
Testes do pipeline automático de separação por cores e dos pinos entre cores.

Fixture principal: uma caixa "pintada" em duas cores (metade superior / inferior),
reproduzindo o formato de um 3MF pintado — duas cascas abertas que compartilham
exatamente os vértices da borda em z=0.
"""
from __future__ import annotations

import numpy as np
import pytest
import trimesh

from app.mesh import connector_config as cfg
from app.mesh.auto_color_split import run_auto_color_split
from app.mesh.capper import close_color_piece
from app.mesh.color_interface_pins import apply_color_interface_pins, find_color_interfaces
from app.mesh.color_splitter import ColorPiece, ColorSplitResult, FilamentInfo


def _painted_box(extents: tuple[float, float, float]) -> tuple[trimesh.Trimesh, trimesh.Trimesh]:
    """Retorna (casca superior, casca inferior) de uma caixa pintada em z=0."""
    box = trimesh.creation.box(extents=extents).subdivide()
    centers = box.triangles_center
    top_idx = np.where(centers[:, 2] > 0)[0]
    bot_idx = np.where(centers[:, 2] <= 0)[0]
    top = box.submesh([top_idx], append=True)
    bot = box.submesh([bot_idx], append=True)
    return top, bot


def _split_result(meshes: list[trimesh.Trimesh], method: str = "painted") -> ColorSplitResult:
    colors = ["#FF8800", "#FFFFFF", "#000000", "#2255FF"]
    pieces = []
    filaments = []
    for i, m in enumerate(meshes):
        fi = FilamentInfo(extruder_index=i, color_hex=colors[i % len(colors)], face_count=len(m.faces))
        filaments.append(fi)
        pieces.append(ColorPiece(extruder_index=i, filament=fi, mesh=m, sub_meshes=[m]))
    return ColorSplitResult(
        pieces=pieces,
        filaments=filaments,
        total_faces=sum(len(m.faces) for m in meshes),
        method=method,
    )


class TestColorInterfaceDetection:
    def test_detects_single_interface_between_two_colors(self) -> None:
        top, bot = _painted_box((40.0, 40.0, 60.0))
        interfaces = find_color_interfaces([[top], [bot]])

        assert len(interfaces) == 1
        itf = interfaces[0]
        assert {itf.owner_piece, itf.partner_piece} == {0, 1}
        assert abs(itf.center[2]) < 1e-6
        assert abs(abs(itf.normal[2]) - 1.0) < 1e-6
        assert itf.inscribed_radius == pytest.approx(20.0, abs=0.5)

    def test_ignores_interface_too_small(self) -> None:
        top, bot = _painted_box((4.0, 4.0, 20.0))  # área 16 mm² < mínimo configurado de 25 mm²
        assert find_color_interfaces([[top], [bot]]) == []

    def test_single_color_has_no_interfaces(self) -> None:
        top, _ = _painted_box((40.0, 40.0, 60.0))
        assert find_color_interfaces([[top]]) == []


class TestApplyColorInterfacePins:
    def test_pin_and_socket_keep_pieces_watertight(self) -> None:
        top, bot = _painted_box((40.0, 40.0, 60.0))
        interfaces = find_color_interfaces([[top], [bot]])
        closed = [[close_color_piece(top)], [close_color_piece(bot)]]
        vol_before = [closed[0][0].volume, closed[1][0].volume]

        report = apply_color_interface_pins(closed, interfaces, tolerance_mm=cfg.tolerance_for_material("PLA"))

        assert report.pins_created == 1
        assert report.pins_by_piece == {0: 1, 1: 1}
        for comps in closed:
            assert comps[0].is_watertight
        deltas = sorted([closed[0][0].volume - vol_before[0], closed[1][0].volume - vol_before[1]])
        # Uma peça ganha o pino (volume +), a outra perde o furo (volume −) e o furo é maior (folga).
        assert deltas[0] < 0 < deltas[1]
        assert abs(deltas[0]) > deltas[1]

    def test_skips_when_host_too_thin_for_socket(self) -> None:
        # Metades com 3 mm de espessura: nenhuma comporta furo + parede mínima.
        top, bot = _painted_box((40.0, 40.0, 6.0))
        interfaces = find_color_interfaces([[top], [bot]])
        closed = [[close_color_piece(top)], [close_color_piece(bot)]]
        report = apply_color_interface_pins(closed, interfaces, tolerance_mm=0.2)
        assert report.pins_created == 0


class TestRunAutoColorSplit:
    def test_everything_fits_without_subdivision(self) -> None:
        top, bot = _painted_box((40.0, 40.0, 60.0))
        outcome = run_auto_color_split(
            _split_result([top, bot]), 100.0, 100.0, 100.0, generate_connectors=False, tolerance_mm=0.2
        )
        assert len(outcome.plates) == 2
        assert outcome.interface_pins == 0
        assert outcome.subdivided_colors == []
        assert all(p.fits_in_plate for p in outcome.plates)
        assert not any(p.has_connectors for p in outcome.plates)

    def test_oversized_color_is_subdivided_automatically(self) -> None:
        top, bot = _painted_box((40.0, 40.0, 300.0))  # cada metade tem 150 mm de altura
        outcome = run_auto_color_split(
            _split_result([top, bot]), 100.0, 100.0, 100.0, generate_connectors=False, tolerance_mm=0.2
        )
        assert sorted(outcome.subdivided_colors) == [1, 2]
        assert outcome.total_parts >= 4
        assert all(p.fits_in_plate for p in outcome.plates)
        for plate in outcome.plates:
            for m in plate.meshes:
                assert float(m.bounds[0][2]) == pytest.approx(0.0, abs=1e-6)  # assentada na mesa

    def test_connectors_mode_adds_interface_and_cut_pins(self) -> None:
        top, bot = _painted_box((40.0, 40.0, 300.0))
        outcome = run_auto_color_split(
            _split_result([top, bot]), 100.0, 100.0, 100.0, generate_connectors=True, tolerance_mm=0.2
        )
        assert outcome.interface_pins == 1
        assert all(p.fits_in_plate for p in outcome.plates)
        assert any(p.has_connectors for p in outcome.plates)

    def test_multi_object_models_skip_interface_pins(self) -> None:
        top, bot = _painted_box((40.0, 40.0, 60.0))
        outcome = run_auto_color_split(
            _split_result([top, bot], method="multi_object"),
            100.0,
            100.0,
            100.0,
            generate_connectors=True,
            tolerance_mm=0.2,
        )
        assert outcome.interface_pins == 0

    def test_small_parts_of_same_color_share_a_plate(self) -> None:
        a = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
        b = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
        b.apply_translation([200.0, 0.0, 0.0])
        result = _split_result([a])
        result.pieces[0].sub_meshes = [a, b]
        outcome = run_auto_color_split(result, 100.0, 100.0, 100.0, generate_connectors=False, tolerance_mm=0.2)
        assert len(outcome.plates) == 1
        assert len(outcome.plates[0].meshes) == 2
        assert outcome.plates[0].fits_in_plate


def test_tolerance_table_falls_back_to_pla() -> None:
    assert cfg.tolerance_for_material("petg") == pytest.approx(0.25)
    assert cfg.tolerance_for_material("desconhecido") == pytest.approx(0.20)
    assert cfg.tolerance_for_material(None) == pytest.approx(0.20)
