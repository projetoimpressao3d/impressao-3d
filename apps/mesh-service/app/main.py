"""Mesh Service — FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import health, analyze, split_sessions

app = FastAPI(
    title="Mesh Service",
    description="Backend Python para corte, reparo e análise de malhas 3D.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# CORS — ajustar origens em produção via variável de ambiente
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(health.router)
app.include_router(analyze.router)
app.include_router(split_sessions.router)

