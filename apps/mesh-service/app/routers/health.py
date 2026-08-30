"""Health check router."""

import time

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])

# Momento em que o serviço iniciou (para calcular uptime)
_START_TIME: float = time.time()


class HealthResponse(BaseModel):
    """Resposta do endpoint de health check."""

    status: str
    version: str
    uptime_seconds: float


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Verifica se o serviço está operacional.",
)
async def health_check() -> HealthResponse:
    """Retorna o status operacional do serviço."""
    return HealthResponse(
        status="ok",
        version="0.1.0",
        uptime_seconds=round(time.time() - _START_TIME, 2),
    )
