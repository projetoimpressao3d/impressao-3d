"""Testes do endpoint /analyze."""

import struct
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings

client = TestClient(app)

VALID_TOKEN = "test-token-for-pytest"


@pytest.fixture(autouse=True)
def _set_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configura o token interno para os testes."""
    monkeypatch.setattr(settings, "python_backend_internal_token", VALID_TOKEN)


def _make_stl_bytes(mesh: trimesh.Trimesh) -> bytes:
    """Serializa um Trimesh para bytes STL binário."""
    header = b"\x00" * 80
    num_triangles = len(mesh.faces)
    data = bytearray(header + struct.pack("<I", num_triangles))
    for face, normal in zip(mesh.faces, mesh.face_normals):
        data += struct.pack("<fff", *normal)
        for vertex_idx in face:
            data += struct.pack("<fff", *mesh.vertices[vertex_idx])
        data += b"\x00\x00"  # attribute byte count
    return bytes(data)


@pytest.fixture()
def watertight_stl_path() -> str:
    """Cria um arquivo STL temporário com uma esfera (malha fechada)."""
    mesh = trimesh.creation.icosphere(subdivisions=2, radius=10.0)
    stl_bytes = _make_stl_bytes(mesh)
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        f.write(stl_bytes)
        return f.name


def _build_payload(storage_path: str = "user-id/test.stl") -> dict:
    return {
        "model_id": str(uuid.uuid4()),
        "storage_path": storage_path,
        "user_id": str(uuid.uuid4()),
    }


class TestAnalyzeAuth:
    """Testes de autenticação do endpoint /analyze."""

    def test_missing_token_returns_401_or_403(self) -> None:
        """Sem token deve retornar 401 ou 403 (HTTPBearer usa 403 em alguns casos)."""
        response = client.post("/analyze", json=_build_payload())
        assert response.status_code in (401, 403)

    def test_wrong_token_returns_401(self) -> None:
        """Token incorreto deve retornar 401."""
        response = client.post(
            "/analyze",
            json=_build_payload(),
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401

    def test_valid_token_accepted(self, watertight_stl_path: str) -> None:
        """Token correto deve ser aceito (analisando um arquivo real)."""
        with (
            patch("app.routers.analyze._get_supabase_client") as mock_supabase,
            patch("app.routers.analyze._create_download_url") as mock_url,
            patch("app.routers.analyze._download_file") as mock_download,
        ):
            mock_url.return_value = "https://fake-signed-url"
            mock_download.return_value = watertight_stl_path
            mock_supabase.return_value = MagicMock()
            mock_supabase.return_value.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])

            response = client.post(
                "/analyze",
                json=_build_payload(),
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )

        assert response.status_code == 200
        assert response.json()["ok"] is True


class TestAnalyzeMesh:
    """Testes da lógica de análise de malha."""

    def test_watertight_sphere_returns_ok(self, watertight_stl_path: str) -> None:
        """Uma esfera fechada deve retornar status ok."""
        with (
            patch("app.routers.analyze._get_supabase_client") as mock_supabase,
            patch("app.routers.analyze._create_download_url") as mock_url,
            patch("app.routers.analyze._download_file") as mock_download,
        ):
            mock_url.return_value = "https://fake-signed-url"
            mock_download.return_value = watertight_stl_path
            db_mock = MagicMock()
            db_mock.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
            mock_supabase.return_value = db_mock

            response = client.post(
                "/analyze",
                json=_build_payload(),
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )

        assert response.status_code == 200
        assert response.json()["ok"] is True

        # Verificar que o UPDATE foi chamado com status correto
        call_args = db_mock.table.return_value.update.call_args
        update_data: dict = call_args[0][0]
        assert update_data["printability_status"] == "ok"
        assert update_data["printability_report"]["is_watertight"] is True
        assert update_data["bounding_box_x_mm"] > 0

    def test_error_on_invalid_file(self) -> None:
        """Arquivo inválido deve retornar ok=False e atualizar status para error."""
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            f.write(b"not a valid stl file content")
            bad_path = f.name

        with (
            patch("app.routers.analyze._get_supabase_client") as mock_supabase,
            patch("app.routers.analyze._create_download_url") as mock_url,
            patch("app.routers.analyze._download_file") as mock_download,
        ):
            mock_url.return_value = "https://fake-signed-url"
            mock_download.return_value = bad_path
            db_mock = MagicMock()
            db_mock.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])
            mock_supabase.return_value = db_mock

            response = client.post(
                "/analyze",
                json=_build_payload(),
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )

        Path(bad_path).unlink(missing_ok=True)
        assert response.status_code == 200
        assert response.json()["ok"] is False
