"""
Gerenciador de ociosidade para auto-suspensão do serviço no Render.

Mantém o registro da última atividade real (ignorando chamadas de health check
e documentação), impede a suspensão enquanto houver requisições HTTP ativas ou
jobs assíncronos em andamento, e chama a API oficial do Render para suspender o
serviço após `RENDER_IDLE_TIMEOUT_SECONDS` (padrão: 300s / 5 minutos).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable

import httpx
from fastapi import Request, Response

logger = logging.getLogger(__name__)

_last_activity_ts: float = time.monotonic()
_active_requests: int = 0
_active_jobs: int = 0

_IGNORED_PATHS: set[str] = {"/health", "/", "/docs", "/redoc", "/openapi.json"}
_FALSE_VALUES: set[str] = {"false", "0", "no", "off"}
_RENDER_API_BASE = "https://api.render.com/v1/services"


def touch_activity() -> None:
    """Atualiza o timestamp da última atividade para o instante atual."""
    global _last_activity_ts
    _last_activity_ts = time.monotonic()


def begin_job() -> None:
    """Registra o início de um job em background e renova o timer de atividade."""
    global _active_jobs
    _active_jobs += 1
    touch_activity()


def end_job() -> None:
    """Registra o término de um job em background e renova o timer de atividade."""
    global _active_jobs
    _active_jobs = max(0, _active_jobs - 1)
    touch_activity()


def has_active_color_split_tasks() -> bool:
    """Verifica se há tarefas de separação por cor ainda em processamento."""
    from app.routers import color_split

    return any(t.get("status") == "processing" for t in color_split._TASKS.values())


def is_busy() -> bool:
    """Indica se há requisições HTTP ou jobs em andamento que bloqueiam suspensão."""
    return _active_requests > 0 or _active_jobs > 0 or has_active_color_split_tasks()


def is_auto_suspend_enabled() -> bool:
    """Retorna True se a auto-suspensão está habilitada e configurada com credenciais."""
    flag = os.getenv("RENDER_AUTO_SUSPEND_ENABLED", "true").strip().lower()
    if flag in _FALSE_VALUES:
        return False
    api_key = os.getenv("RENDER_API_KEY", "").strip()
    service_id = os.getenv("RENDER_SERVICE_ID", "").strip()
    return bool(api_key and service_id)


def get_idle_timeout_seconds() -> float:
    """Retorna o tempo limite de ociosidade em segundos (padrão 300s)."""
    raw = os.getenv("RENDER_IDLE_TIMEOUT_SECONDS", "300").strip()
    try:
        value = float(raw)
        return max(1.0, value)
    except ValueError:
        logger.warning(
            "Valor inválido para RENDER_IDLE_TIMEOUT_SECONDS=%r; usando 300s.",
            raw,
        )
        return 300.0


def get_idle_seconds() -> float:
    """Retorna quantos segundos o serviço está ocioso (0.0 se estiver ocupado)."""
    if is_busy():
        touch_activity()
        return 0.0
    return max(0.0, time.monotonic() - _last_activity_ts)


async def suspend_render_service() -> bool:
    """Chama a API do Render para suspender o serviço e interromper a cobrança."""
    api_key = os.getenv("RENDER_API_KEY", "").strip()
    service_id = os.getenv("RENDER_SERVICE_ID", "").strip()
    if not api_key or not service_id:
        return False

    url = f"{_RENDER_API_BASE}/{service_id}/suspend"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=headers)
        if response.status_code < 300:
            logger.info(
                "Serviço Render %s suspenso por ociosidade (HTTP %d).",
                service_id,
                response.status_code,
            )
            return True
        logger.warning(
            "Falha ao suspender serviço Render %s (HTTP %d): %s",
            service_id,
            response.status_code,
            response.text,
        )
        return False
    except Exception:
        logger.exception("Erro ao chamar API do Render para suspender %s.", service_id)
        return False


async def check_and_suspend_if_idle() -> bool:
    """Verifica se o serviço atingiu o limite de ociosidade e o suspende no Render."""
    if not is_auto_suspend_enabled():
        return False
    if is_busy():
        touch_activity()
        return False
    if get_idle_seconds() >= get_idle_timeout_seconds():
        suspended = await suspend_render_service()
        if suspended:
            # Evita múltiplas chamadas /suspend enquanto o container recebe SIGTERM.
            touch_activity()
        return suspended
    return False


async def idle_monitor_loop(poll_interval_seconds: float = 20.0) -> None:
    """Loop contínuo em background que monitora a ociosidade do servidor."""
    while True:
        try:
            await asyncio.sleep(poll_interval_seconds)
            await check_and_suspend_if_idle()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Erro inesperado no monitor de ociosidade do Render.")


async def track_activity_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Middleware HTTP que contabiliza requisições ativas e renova última atividade."""
    if request.url.path in _IGNORED_PATHS:
        return await call_next(request)

    global _active_requests
    _active_requests += 1
    touch_activity()
    try:
        return await call_next(request)
    finally:
        _active_requests = max(0, _active_requests - 1)
        touch_activity()
