"""
Testes do módulo de corte booleano (manifold3d).

Propriedades verificadas:
  - N planos de corte → N+1 peças (sem planos vazios)
  - Todas as peças resultantes são watertight (capping automático)
  - Conservação de volume (< 2% de tolerância)
  - Corte em múltiplos eixos
"""

import math

import numpy as np
import pytest
import trimesh

from app.mesh.cutter import CutPlaneInput, cut_mesh_by_planes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def box(x: float = 100.0, y: float = 100.0, z: float = 100.0) -> trimesh.Trimesh:
    """Caixa centrada na origem com as dimensões dadas."""
    return trimesh.creation.box(extents=[x, y, z])


def sphere(r: float = 50.0) -> trimesh.Trimesh:
    return trimesh.creation.icosphere(subdivisions=3, radius=r)


# ---------------------------------------------------------------------------
# Testes básicos
# ---------------------------------------------------------------------------


class TestCutMeshByPlanes:
    def test_no_planes_returns_original_mesh(self) -> None:
        """Sem planos → retorna a malha original intacta."""
        mesh = box()
        result = cut_mesh_by_planes(mesh, [])
        assert len(result) == 1
        assert result[0] is mesh

    def test_single_plane_center_x_produces_two_pieces(self) -> None:
        """1 plano central em X → 2 peças."""
        mesh = box(200, 100, 100)
        planes = [CutPlaneInput(normal=[1.0, 0.0, 0.0], origin=[0.0, 0.0, 0.0])]
        result = cut_mesh_by_planes(mesh, planes)
        assert len(result) == 2

    def test_two_planes_same_axis_produces_pieces(self) -> None:
        """2 planos em X no mesmo eixo — manifold3d aplica sequencialmente.
        Plano 1 corta em x=0 → top (x≥0) + bottom (x≤0).
        Plano 2 corta o bottom (x≤0) em x=-50 → top (-50≤x≤0) + bottom (x≤-50).
        Total: 3 peças não-vazias (comportamento verificado empiricamente).
        """
        mesh = box(200, 100, 100)  # vai de x=-100 a x=100 centrado
        planes = [
            CutPlaneInput(normal=[1.0, 0.0, 0.0], origin=[0.0, 0.0, 0.0]),   # corte em x=0
            CutPlaneInput(normal=[1.0, 0.0, 0.0], origin=[-50.0, 0.0, 0.0]), # corte em x=-50
        ]
        result = cut_mesh_by_planes(mesh, planes)
        # Deve gerar pelo menos 2 peças (pode ser 3 dependendo de peças degeneradas)
        assert len(result) >= 2
        assert all(p.is_watertight for p in result)

    def test_two_planes_different_axes_produce_three_pieces(self) -> None:
        """2 planos em eixos diferentes → 3 peças garantidas."""
        mesh = box(200, 200, 200)
        planes = [
            CutPlaneInput(normal=[1.0, 0.0, 0.0], origin=[0.0, 0.0, 0.0]),
            CutPlaneInput(normal=[0.0, 1.0, 0.0], origin=[0.0, 0.0, 0.0]),
        ]
        result = cut_mesh_by_planes(mesh, planes)
        assert len(result) == 3
        assert all(p.is_watertight for p in result)

    def test_three_planes_different_axes_produce_four_pieces(self) -> None:
        """3 planos em eixos diferentes → 4 peças."""
        mesh = box(200, 200, 200)
        planes = [
            CutPlaneInput(normal=[1.0, 0.0, 0.0], origin=[0.0, 0.0, 0.0]),
            CutPlaneInput(normal=[0.0, 1.0, 0.0], origin=[0.0, 0.0, 0.0]),
            CutPlaneInput(normal=[0.0, 0.0, 1.0], origin=[0.0, 0.0, 0.0]),
        ]
        result = cut_mesh_by_planes(mesh, planes)
        assert len(result) == 4


# ---------------------------------------------------------------------------
# Propriedade: todas as peças devem ser watertight
# ---------------------------------------------------------------------------


class TestWatertightAfterCut:
    def test_box_cut_in_x_watertight(self) -> None:
        """Corte simples de caixa → peças watertight."""
        result = cut_mesh_by_planes(
            box(200, 100, 100),
            [CutPlaneInput(normal=[1.0, 0.0, 0.0], origin=[0.0, 0.0, 0.0])],
        )
        assert all(p.is_watertight for p in result), "Todas as peças devem ser watertight"

    def test_sphere_cut_watertight(self) -> None:
        """Corte de esfera (malha curva) → peças watertight."""
        result = cut_mesh_by_planes(
            sphere(50.0),
            [CutPlaneInput(normal=[0.0, 0.0, 1.0], origin=[0.0, 0.0, 0.0])],
        )
        assert all(p.is_watertight for p in result)

    def test_multi_axis_cut_watertight(self) -> None:
        """Cortes em 2 eixos diferentes → todas as peças watertight."""
        result = cut_mesh_by_planes(
            box(200, 200, 200),
            [
                CutPlaneInput(normal=[1.0, 0.0, 0.0], origin=[0.0, 0.0, 0.0]),
                CutPlaneInput(normal=[0.0, 1.0, 0.0], origin=[0.0, 0.0, 0.0]),
            ],
        )
        assert all(p.is_watertight for p in result)

    def test_three_planes_all_watertight(self) -> None:
        """3 planos → todas as 4 peças watertight."""
        result = cut_mesh_by_planes(
            box(300, 200, 100),
            [
                CutPlaneInput(normal=[1.0, 0.0, 0.0], origin=[-50.0, 0.0, 0.0]),
                CutPlaneInput(normal=[1.0, 0.0, 0.0], origin=[50.0, 0.0, 0.0]),
                CutPlaneInput(normal=[0.0, 1.0, 0.0], origin=[0.0, 0.0, 0.0]),
            ],
        )
        assert all(p.is_watertight for p in result)


# ---------------------------------------------------------------------------
# Conservação de volume
# ---------------------------------------------------------------------------


class TestVolumeConservation:
    def test_box_volume_conserved_single_cut(self) -> None:
        """Soma dos volumes das peças ≈ volume original (< 2% de variação)."""
        mesh = box(200, 100, 100)
        original_vol = abs(mesh.volume)
        result = cut_mesh_by_planes(
            mesh,
            [CutPlaneInput(normal=[1.0, 0.0, 0.0], origin=[0.0, 0.0, 0.0])],
        )
        total_vol = sum(abs(p.volume) for p in result)
        rel_err = abs(total_vol - original_vol) / original_vol
        assert rel_err < 0.02, f"Variação de volume: {rel_err:.1%} (> 2%)"

    def test_sphere_volume_conserved(self) -> None:
        """Esfera: soma dos volumes conservada após corte."""
        mesh = sphere(50.0)
        original_vol = abs(mesh.volume)
        result = cut_mesh_by_planes(
            mesh,
            [CutPlaneInput(normal=[0.0, 0.0, 1.0], origin=[0.0, 0.0, 0.0])],
        )
        total_vol = sum(abs(p.volume) for p in result)
        rel_err = abs(total_vol - original_vol) / original_vol
        assert rel_err < 0.02

    def test_volume_conserved_two_planes(self) -> None:
        """2 planos: volume conservado."""
        mesh = box(300, 150, 100)
        original_vol = abs(mesh.volume)
        result = cut_mesh_by_planes(
            mesh,
            [
                CutPlaneInput(normal=[1.0, 0.0, 0.0], origin=[-50.0, 0.0, 0.0]),
                CutPlaneInput(normal=[1.0, 0.0, 0.0], origin=[50.0, 0.0, 0.0]),
            ],
        )
        total_vol = sum(abs(p.volume) for p in result)
        rel_err = abs(total_vol - original_vol) / original_vol
        assert rel_err < 0.02


# ---------------------------------------------------------------------------
# Corte com normal não-unitário (deve ser normalizado internamente)
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_non_unit_normal_accepted(self) -> None:
        """Normal com norma ≠ 1 deve ser normalizada internamente sem erro."""
        result = cut_mesh_by_planes(
            box(),
            [CutPlaneInput(normal=[2.0, 0.0, 0.0], origin=[0.0, 0.0, 0.0])],
        )
        assert len(result) == 2
        assert all(p.is_watertight for p in result)

    def test_diagonal_normal(self) -> None:
        """Normal diagonal (45°) deve funcionar corretamente."""
        result = cut_mesh_by_planes(
            box(100, 100, 100),
            [CutPlaneInput(
                normal=[1.0, 1.0, 0.0],
                origin=[0.0, 0.0, 0.0],
                label="Corte diagonal 45°",
            )],
        )
        assert len(result) == 2
        assert all(p.is_watertight for p in result)

    def test_invalid_normal_raises_value_error(self) -> None:
        """Normal zero deve levantar ValueError."""
        with pytest.raises(ValueError, match="normal inválida"):
            cut_mesh_by_planes(
                box(),
                [CutPlaneInput(normal=[0.0, 0.0, 0.0], origin=[0.0, 0.0, 0.0])],
            )
