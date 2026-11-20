"""Testes unitários do gerenciador de ociosidade e auto-suspensão do Render."""

from __future__ import annotations

import time
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import idle_manager
from app.main import app
from app.routers import color_split


@pytest.fixture(autouse=True)
def _reset_idle_state() -> Iterator[None]:
    """Garante estado limpo antes e depois de cada teste."""
    saved_tasks = dict(color_split._TASKS)
    color_split._TASKS.clear()
    idle_manager._active_requests = 0
    idle_manager._active_jobs = 0
    idle_manager.touch_activity()
    yield
    color_split._TASKS.clear()
    color_split._TASKS.update(saved_tasks)
    idle_manager._active_requests = 0
    idle_manager._active_jobs = 0
    idle_manager.touch_activity()


def test_health_get_and_head_do_not_reset_activity() -> None:
    """Chamadas GET e HEAD em /health não devem resetar o timer de ociosidade."""
    client = TestClient(app)
    stale_ts = time.monotonic() - 120.0
    idle_manager._last_activity_ts = stale_ts

    res_get = client.get("/health")
    assert res_get.status_code == 200
    assert idle_manager._last_activity_ts == stale_ts

    res_head = client.head("/health")
    assert res_head.status_code == 200
    assert idle_manager._last_activity_ts == stale_ts


def test_work_request_resets_activity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Requisições em rotas de trabalho devem renovar o timestamp de última atividade."""
    monkeypatch.setattr("app.deps.settings.python_backend_internal_token", "test-secret")
    client = TestClient(app)
    stale_ts = time.monotonic() - 500.0
    idle_manager._last_activity_ts = stale_ts

    res = client.get(
        "/color-split/tasks/inexistente",
        headers={"Authorization": "Bearer test-secret"},
    )
    assert res.status_code == 404
    assert idle_manager._last_activity_ts > stale_ts


@pytest.mark.asyncio
async def test_active_color_split_task_and_job_block_suspend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tarefas em processamento ou begin_job() devem impedir auto-suspensão."""
    monkeypatch.setenv("RENDER_API_KEY", "rnd_test")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv_test")
    monkeypatch.setenv("RENDER_AUTO_SUSPEND_ENABLED", "true")
    monkeypatch.setenv("RENDER_IDLE_TIMEOUT_SECONDS", "300")

    idle_manager._last_activity_ts = time.monotonic() - 600.0
    color_split._TASKS["task-1"] = {"status": "processing", "progress": 25}

    assert idle_manager.is_busy() is True
    with patch("app.idle_manager.suspend_render_service", new_callable=AsyncMock) as mock_suspend:
        suspended = await idle_manager.check_and_suspend_if_idle()
        assert suspended is False
        mock_suspend.assert_not_awaited()

    color_split._TASKS["task-1"]["status"] = "completed"
    idle_manager.begin_job()
    idle_manager._last_activity_ts = time.monotonic() - 600.0
    assert idle_manager.is_busy() is True
    with patch("app.idle_manager.suspend_render_service", new_callable=AsyncMock) as mock_suspend:
        suspended = await idle_manager.check_and_suspend_if_idle()
        assert suspended is False
        mock_suspend.assert_not_awaited()

    idle_manager.end_job()
    assert idle_manager.is_busy() is False


@pytest.mark.asyncio
async def test_check_and_suspend_calls_render_api_when_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Após atingir RENDER_IDLE_TIMEOUT_SECONDS sem atividade, deve chamar /suspend no Render."""
    monkeypatch.setenv("RENDER_API_KEY", "rnd_secret_123")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-abc123")
    monkeypatch.setenv("RENDER_AUTO_SUSPEND_ENABLED", "true")
    monkeypatch.setenv("RENDER_IDLE_TIMEOUT_SECONDS", "300")

    idle_manager._last_activity_ts = time.monotonic() - 310.0

    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.text = ""

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_client
    mock_cm.__aexit__.return_value = False

    with patch("app.idle_manager.httpx.AsyncClient", return_value=mock_cm):
        suspended = await idle_manager.check_and_suspend_if_idle()

    assert suspended is True
    mock_client.post.assert_awaited_once_with(
        "https://api.render.com/v1/services/srv-abc123/suspend",
        headers={
            "Authorization": "Bearer rnd_secret_123",
            "Accept": "application/json",
        },
    )
    assert idle_manager.get_idle_seconds() < 5.0


@pytest.mark.asyncio
async def test_disabled_flag_never_calls_render_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Com RENDER_AUTO_SUSPEND_ENABLED=false, nenhuma chamada ao Render deve ocorrer."""
    monkeypatch.setenv("RENDER_API_KEY", "rnd_secret_123")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-abc123")
    monkeypatch.setenv("RENDER_AUTO_SUSPEND_ENABLED", "false")
    monkeypatch.setenv("RENDER_IDLE_TIMEOUT_SECONDS", "10")

    idle_manager._last_activity_ts = time.monotonic() - 600.0

    with patch("app.idle_manager.httpx.AsyncClient") as mock_client_cls:
        suspended = await idle_manager.check_and_suspend_if_idle()

    assert suspended is False
    mock_client_cls.assert_not_called()
