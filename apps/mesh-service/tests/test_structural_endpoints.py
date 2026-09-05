"""
Testes dos endpoints de separacao estrutural:
  POST /split-sessions/{id}/separate
  GET  /split-sessions/{id}/status
"""
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)
VALID_TOKEN = "test-internal-token-structural"


@pytest.fixture(autouse=True)
def _set_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "python_backend_internal_token", VALID_TOKEN)


class TestStructuralEndpoints:
    def test_separate_missing_token_returns_401_or_403(self) -> None:
        resp = client.post("/split-sessions/sess-123/separate", json={"user_id": "u1"})
        assert resp.status_code in (401, 403)

    def test_separate_session_not_found_returns_404(self) -> None:
        with patch("app.routers.structural._fetch_session", return_value=None):
            resp = client.post(
                "/split-sessions/sess-123/separate",
                json={"user_id": "u1", "structural_sensitivity": 0.07},
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )
            assert resp.status_code == 404

    def test_separate_returns_202_accepted_immediately(self) -> None:
        mock_session = {"id": "sess-123", "model_id": "m1", "build_plate_id": "p1", "user_id": "u1", "status": "draft"}
        with patch("app.routers.structural._fetch_session", return_value=mock_session), \
             patch("app.routers.structural._update_session_status") as mock_update, \
             patch("app.routers.structural._background_separate"):
            resp = client.post(
                "/split-sessions/sess-123/separate",
                json={"user_id": "u1", "structural_sensitivity": 0.07},
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )
            assert resp.status_code == 202
            data = resp.json()
            assert data["split_session_id"] == "sess-123"
            assert data["status"] == "processing"
            mock_update.assert_called_once()

    def test_status_endpoint_returns_data(self) -> None:
        mock_session_full = {
            "id": "sess-123",
            "status": "completed",
            "cut_planes": [
                {
                    "normal": [1.0, 0.0, 0.0],
                    "origin": [0.0, 0.0, 0.0],
                    "label": "Ramo 1",
                    "source": "suggested_structural",
                    "structural_group": "branch-0",
                }
            ],
            "error_message": None,
            "structural_sensitivity": 0.07,
        }
        with patch("app.routers.structural._fetch_session_full", return_value=mock_session_full):
            resp = client.get(
                "/split-sessions/sess-123/status?user_id=u1",
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["split_session_id"] == "sess-123"
            assert data["status"] == "completed"
            assert len(data["cut_planes"]) == 1
            assert data["structural_count"] == 1
            assert data["cut_planes"][0]["source"] == "suggested_structural"
            assert data["cut_planes"][0]["structural_group"] == "branch-0"
