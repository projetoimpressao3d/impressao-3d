"""Mesh Service — FastAPI application entry point."""

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.idle_manager import idle_monitor_loop, touch_activity, track_activity_middleware
from app.routers import analyze, color_split, health, split_sessions, structural


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Gerencia ciclo de vida da aplicação e monitor de ociosidade do Render."""
    touch_activity()
    monitor_task = asyncio.create_task(idle_monitor_loop())
    try:
        yield
    finally:
        monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor_task


app = FastAPI(
    title="Mesh Service",
    description="Backend Python para corte, reparo e análise de malhas 3D.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — origens permitidas via variável de ambiente em produção
# ---------------------------------------------------------------------------
_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(track_activity_middleware)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(health.router)
app.include_router(analyze.router)
app.include_router(split_sessions.router)
app.include_router(structural.router)
app.include_router(color_split.router)

