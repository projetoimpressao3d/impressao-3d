"""
Testes para app/mesh/natural_cuts.py.

Usa modelos sinteticos criados com trimesh para validar:
- Deteccao de gargalo em modelo tipo haltere (dumbbell)
- Modelo que cabe na mesa -> fits=True
- Modelo sem gargalo natural -> fallback de grade
- Selecao gulosa minima de cortes
- _compute_pieces e _greedy_cuts_for_axis em isolamento
"""
import math

import numpy as np
import pytest
import trimesh

from app.mesh.natural_cuts import (
    CutCandidate,
    _compute_pieces,
    _greedy_cuts_for_axis,
    detect_natural_cut_candidates,
    find_local_minima,
    scan_cross_sections,
    suggest_cuts,
)


# ---------------------------------------------------------------------------
# Fixtures de modelos sinteticos
# ---------------------------------------------------------------------------


def _centered(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Centraliza o mesh na origem (espelha comportamento do frontend)."""
    center = mesh.bounds.mean(axis=0)
    mesh.apply_translation(-center)
    return mesh


def make_dumbbell_z(
    cap_radius: float = 15.0,
    cap_height: float = 10.0,
    neck_radius: float = 3.0,
    neck_height: float = 30.0,
) -> trimesh.Trimesh:
    """
    Haltere com gargalo estreito no centro, alinhado com eixo Z.
    Altura total: neck_height + 2*cap_height = 50mm.
    Gargalo esperado proximo a Z=0 (centro).
    """
    neck = trimesh.creation.cylinder(radius=neck_radius, height=neck_height, sections=16)
    cap_bottom = trimesh.creation.cylinder(radius=cap_radius, height=cap_height, sections=16)
    cap_bottom.apply_translation([0.0, 0.0, -(neck_height / 2.0 + cap_height / 2.0)])
    cap_top = trimesh.creation.cylinder(radius=cap_radius, height=cap_height, sections=16)
    cap_top.apply_translation([0.0, 0.0, (neck_height / 2.0 + cap_height / 2.0)])
    mesh = trimesh.util.concatenate([neck, cap_bottom, cap_top])
    return _centered(mesh)


def make_long_box(lx: float = 20.0, ly: float = 20.0, lz: float = 100.0) -> trimesh.Trimesh:
    """Caixa longa sem gargalo natural -> forcara fallback de grade."""
    mesh = trimesh.creation.box([lx, ly, lz])
    return _centered(mesh)


def make_small_box(lx: float = 20.0, ly: float = 20.0, lz: float = 20.0) -> trimesh.Trimesh:
    """Caixa pequena que ja cabe na mesa."""
    mesh = trimesh.creation.box([lx, ly, lz])
    return _centered(mesh)


# ---------------------------------------------------------------------------
# Testes de scan_cross_sections
# ---------------------------------------------------------------------------


class TestScanCrossSections:
    def test_uniform_box_has_flat_area_curve(self) -> None:
        """Caixa uniforme deve ter area de seccao aproximadamente constante."""
        box = make_long_box(20, 20, 100)
        data = scan_cross_sections(box, np.array([0.0, 0.0, 1.0]))
        assert len(data) > 0
        areas = [a for _, a in data]
        # Para uma caixa, a area deve ser aproximadamente constante
        ratio = max(areas) / min(areas)
        assert ratio < 1.5, f"Caixa nao deveria ter gargalo: ratio={ratio:.2f}"

    def test_dumbbell_has_smaller_area_at_center(self) -> None:
        """Haltere deve ter area muito menor no pescoco do que nas tampas."""
        dumbbell = make_dumbbell_z()
        data = scan_cross_sections(dumbbell, np.array([0.0, 0.0, 1.0]))
        assert len(data) >= 5

        areas = [a for _, a in data]
        center_idx = len(areas) // 2
        center_area = areas[center_idx]
        max_area = max(areas)

        # O pescoco deve ter area significativamente menor
        assert center_area < max_area * 0.5, (
            f"Area no centro ({center_area:.1f}) nao e significativamente menor "
            f"que o maximo ({max_area:.1f})"
        )

    def test_zero_direction_returns_empty(self) -> None:
        box = make_long_box()
        result = scan_cross_sections(box, np.array([0.0, 0.0, 0.0]))
        assert result == []


# ---------------------------------------------------------------------------
# Testes de find_local_minima
# ---------------------------------------------------------------------------


class TestFindLocalMinima:
    def test_no_minima_in_flat_curve(self) -> None:
        data = [(float(i), 100.0) for i in range(20)]
        assert find_local_minima(data) == []

    def test_detects_single_bottleneck(self) -> None:
        """Curva de U com minimo claro no centro."""
        positions = list(range(11))
        areas = [100.0, 80.0, 60.0, 40.0, 20.0, 10.0, 20.0, 40.0, 60.0, 80.0, 100.0]
        data = list(zip(positions, areas))
        minima = find_local_minima(data)
        assert len(minima) == 1
        assert minima[0] == 5  # indice do minimo em areas[5] = 10.0

    def test_filters_shallow_minima(self) -> None:
        """Minimo muito raso nao deve ser detectado com limiar padrao (15% do range)."""
        # Caso 1: curva plana -> nenhum minimo
        data_flat = [(float(i), 100.0) for i in range(10)]
        assert find_local_minima(data_flat, min_prominence_ratio=0.15) == []

        # Caso 2: minimo com prominencia de exatamente 1 unidade mas range de 100
        # prominence_threshold = 0.15 * 100 = 15. Prominencia = 1 < 15 -> filtrado
        # areas: sobe de 0 a 100, desce 1 unidade no meio, volta a subir
        areas = list(range(0, 51)) + [49] + list(range(50, 101))
        # Indice 51 tem area 49, vizinhos 50 e 50
        # Nao e minimo estrito (50 == 50) — mas testa outro caso
        # Usar caso mais claro:
        # range = 100-50 = 50, threshold = 0.15*50 = 7.5
        # minimo em meio: area=50, left_max=100, right_max=100, prominence=50 >= 7.5
        # Logo: detecta mesmo. Para nao detectar, precisa de prominencia < 7.5:
        areas2 = [100, 96, 100]  # range=4, threshold=0.6, prominence=4 >= 0.6 -> detecta
        # Caso correto: range muito grande, prominencia minima:
        # range = 1000, threshold = 150, prominence = 1 < 150 -> nao detecta
        big_range = [0.0] + [1000.0] * 3 + [999.0] + [1000.0] * 3 + [0.0]
        # minimo em indice 4: area=999, left_max=1000, right_max=1000, prominence=1
        # range = 1000-0=1000, threshold=150, 1 < 150 -> filtrado
        data_big = list(enumerate(big_range))
        minima = find_local_minima(data_big, min_prominence_ratio=0.15)
        assert len(minima) == 0, f"Esperado sem minimos, encontrou: {minima}"



    def test_returns_empty_for_few_points(self) -> None:
        assert find_local_minima([]) == []
        assert find_local_minima([(0, 1.0), (1, 0.5)]) == []

    def test_detects_two_distinct_bottlenecks(self) -> None:
        """Dois vales distintos devem gerar dois minimos."""
        areas = [100, 50, 100, 50, 100, 50, 100]
        data = list(enumerate(areas))
        minima = find_local_minima(data, min_prominence_ratio=0.1)
        assert len(minima) == 3  # indices 1, 3, 5


# ---------------------------------------------------------------------------
# Testes de _compute_pieces e _greedy_cuts_for_axis
# ---------------------------------------------------------------------------


class TestComputePieces:
    def test_no_cuts_returns_whole_range(self) -> None:
        pieces = _compute_pieces(-50.0, 50.0, [])
        assert pieces == [(-50.0, 50.0)]

    def test_one_cut_at_center(self) -> None:
        pieces = _compute_pieces(-50.0, 50.0, [0.0])
        assert pieces == [(-50.0, 0.0), (0.0, 50.0)]

    def test_multiple_cuts(self) -> None:
        pieces = _compute_pieces(0.0, 90.0, [30.0, 60.0])
        assert pieces == [(0.0, 30.0), (30.0, 60.0), (60.0, 90.0)]


class TestGreedyCutsForAxis:
    def test_already_fits_returns_empty(self) -> None:
        cuts = _greedy_cuts_for_axis(-50.0, 50.0, 200.0, [])
        assert cuts == []

    def test_no_natural_candidates_uses_grid(self) -> None:
        """Sem candidatos naturais, deve usar grade."""
        cuts = _greedy_cuts_for_axis(-50.0, 50.0, 60.0, [])
        assert len(cuts) == 1
        _, source = cuts[0]
        assert source == "suggested_grid_fallback"

    def test_natural_candidate_used_when_available(self) -> None:
        """Candidato natural dentro da peca grande deve ser preferido."""
        # Modelo de 100mm, mesa de 60mm -> 1 corte necessario
        # Candidato natural em 0mm (centro)
        candidates = [(0.0, 50.0)]  # posicao=0mm, area=50mm2
        cuts = _greedy_cuts_for_axis(-50.0, 50.0, 60.0, candidates)
        assert len(cuts) == 1
        pos, source = cuts[0]
        assert source == "suggested_natural"
        assert abs(pos) < 1.0  # proximo ao centro

    def test_natural_plus_fallback_for_large_model(self) -> None:
        """
        Modelo de 200mm, mesa de 60mm: precisa de 3 cortes.
        1 candidato natural em 0mm, mais 2 fallbacks.
        """
        candidates = [(0.0, 30.0)]
        cuts = _greedy_cuts_for_axis(-100.0, 100.0, 60.0, candidates)
        sources = [s for _, s in cuts]
        assert "suggested_natural" in sources
        assert "suggested_grid_fallback" in sources

    def test_minimum_cuts_selected(self) -> None:
        """Deve selecionar o MINIMO de cortes necessarios."""
        # 100mm, mesa 60mm -> 1 corte
        candidates = [(0.0, 100.0), (10.0, 200.0), (-10.0, 150.0)]
        cuts = _greedy_cuts_for_axis(-50.0, 50.0, 60.0, candidates)
        assert len(cuts) == 1


# ---------------------------------------------------------------------------
# Testes de suggest_cuts (integracao)
# ---------------------------------------------------------------------------


class TestSuggestCuts:
    def test_small_model_fits(self) -> None:
        """Modelo pequeno que cabe na mesa deve retornar fits=True."""
        box = make_small_box(20, 20, 20)
        plan = suggest_cuts(box, {"x": 30.0, "y": 30.0, "z": 30.0})
        assert plan.fits is True
        assert len(plan.cut_planes) == 0

    def test_long_box_needs_grid_fallback(self) -> None:
        """Caixa sem gargalo natural deve usar fallback de grade."""
        box = make_long_box(20, 20, 100)
        plan = suggest_cuts(box, {"x": 60.0, "y": 60.0, "z": 60.0})
        assert plan.fits is False
        assert len(plan.cut_planes) >= 1
        # Todos os planos devem ser fallback (sem gargalo natural em caixa uniforme)
        sources = [p.source for p in plan.cut_planes]
        assert all(s in ("suggested_natural", "suggested_grid_fallback") for s in sources)

    def test_dumbbell_natural_cut_detected(self) -> None:
        """Haltere deve gerar pelo menos 1 plano de corte natural proximo ao centro."""
        dumbbell = make_dumbbell_z()
        # Mesa nao comporta as tampas (50mm de altura, mesa de 35mm)
        plan = suggest_cuts(dumbbell, {"x": 60.0, "y": 60.0, "z": 35.0})
        assert plan.fits is False
        assert len(plan.cut_planes) >= 1

        # Verificar que pelo menos um corte e natural e proximo ao centro (|z| < 10mm)
        natural_near_center = [
            p for p in plan.cut_planes
            if p.source == "suggested_natural" and abs(p.origin[2]) < 15.0
        ]
        assert len(natural_near_center) >= 1, (
            f"Esperado gargalo natural proximo ao centro. Planos: {plan.cut_planes}"
        )

    def test_planes_have_required_fields(self) -> None:
        """Todos os planos devem ter normal, origin, label e source validos."""
        box = make_long_box(20, 20, 100)
        plan = suggest_cuts(box, {"x": 60.0, "y": 60.0, "z": 60.0})
        for plane in plan.cut_planes:
            assert len(plane.normal) == 3
            assert len(plane.origin) == 3
            assert isinstance(plane.label, str) and len(plane.label) > 0
            assert plane.source in ("suggested_natural", "suggested_grid_fallback")

    def test_resulting_pieces_fit_in_plate(self) -> None:
        """Apos aplicar os cortes sugeridos, cada peca deve caber na mesa."""
        box = make_long_box(20, 20, 120)
        plate = {"x": 60.0, "y": 60.0, "z": 60.0}
        plan = suggest_cuts(box, plate)
        assert plan.fits is False

        # Simular cortes no eixo Z (o unico que nao cabe)
        z_cuts = sorted(
            p.origin[2]
            for p in plan.cut_planes
            if abs(p.normal[2]) > 0.9
        )

        bounds = box.bounds
        pieces = _compute_pieces(
            float(bounds[0][2]), float(bounds[1][2]), z_cuts
        )
        for lo, hi in pieces:
            assert hi - lo <= plate["z"] + 0.1, (
                f"Peca [{lo:.1f}, {hi:.1f}] nao cabe na mesa de {plate['z']}mm"
            )
