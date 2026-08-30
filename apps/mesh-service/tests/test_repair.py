"""
Testes do módulo app/mesh/repair.py.

Usa primitivas do trimesh (esferas, caixas) para evitar dependência de arquivos externos.
"""

import trimesh
import pytest

from app.mesh.repair import repair_mesh, load_and_normalize


class TestRepairMesh:
    """Testes da função repair_mesh()."""

    def test_repair_preserves_watertight_mesh(self) -> None:
        """Uma malha já fechada deve permanecer fechada após o reparo."""
        mesh = trimesh.creation.icosphere(subdivisions=2, radius=10.0)
        assert mesh.is_watertight, "Pré-condição: esfera deve ser watertight"

        repaired = repair_mesh(mesh)

        assert repaired.is_watertight

    def test_repair_returns_copy_not_inplace(self) -> None:
        """repair_mesh NÃO deve modificar a malha original."""
        mesh = trimesh.creation.icosphere(subdivisions=2, radius=10.0)
        original_faces = len(mesh.faces)
        original_verts = len(mesh.vertices)

        repaired = repair_mesh(mesh)

        # Retorno é um objeto diferente
        assert repaired is not mesh
        # Original não foi alterado
        assert len(mesh.faces) == original_faces
        assert len(mesh.vertices) == original_verts

    def test_repair_preserves_volume(self) -> None:
        """O reparo não deve distorcer a geometria significativamente (< 5% de variação)."""
        mesh = trimesh.creation.icosphere(subdivisions=3, radius=25.0)
        original_volume = mesh.volume

        repaired = repair_mesh(mesh)

        # Volume deve ser preservado com tolerância de 5%
        relative_change = abs(repaired.volume - original_volume) / original_volume
        assert relative_change < 0.05, (
            f"Volume variou {relative_change:.1%} após reparo "
            f"(original={original_volume:.2f}, reparado={repaired.volume:.2f})"
        )

    def test_repair_box_mesh(self) -> None:
        """Reparo de uma caixa (malha simples e fechada) deve funcionar sem erros."""
        mesh = trimesh.creation.box(extents=[10.0, 20.0, 30.0])
        assert mesh.is_watertight

        repaired = repair_mesh(mesh)

        assert repaired.is_watertight
        assert len(repaired.faces) > 0


class TestLoadAndNormalize:
    """Testes da função load_and_normalize() usando arquivos STL temporários."""

    def test_load_stl_returns_trimesh(self, tmp_path) -> None:
        """load_and_normalize deve retornar um Trimesh a partir de um STL."""
        # Exportar uma esfera como STL temporário
        sphere = trimesh.creation.icosphere(subdivisions=1, radius=5.0)
        stl_path = str(tmp_path / "test.stl")
        sphere.export(stl_path)

        loaded = load_and_normalize(stl_path)

        assert isinstance(loaded, trimesh.Trimesh)
        assert len(loaded.faces) > 0

    def test_load_preserves_dimensions(self, tmp_path) -> None:
        """As dimensões da bounding box devem ser preservadas no carregamento."""
        box = trimesh.creation.box(extents=[100.0, 200.0, 50.0])
        stl_path = str(tmp_path / "box.stl")
        box.export(stl_path)

        loaded = load_and_normalize(stl_path)

        extents = loaded.bounding_box.extents
        assert extents[0] == pytest.approx(100.0, rel=0.01)
        assert extents[1] == pytest.approx(200.0, rel=0.01)
        assert extents[2] == pytest.approx(50.0, rel=0.01)
