"""Dependências compartilhadas entre os routers do mesh-service."""

import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client

from app.config import settings

logger = logging.getLogger(__name__)
_security = HTTPBearer()


def verify_internal_token(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> None:
    """
    Dependência FastAPI que verifica o Bearer token interno.
    Protege todos os endpoints que o Next.js chama no mesh-service.
    """
    if not settings.python_backend_internal_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Token interno não configurado no servidor.",
        )
    if credentials.credentials != settings.python_backend_internal_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticação inválido.",
        )


def get_supabase_client() -> Client:
    """
    Cria e retorna um cliente Supabase com ``service_role`` (bypassa RLS).
    Usar apenas em operações administrativas confiáveis (servidor ↔ servidor).
    """
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError(
            "SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY são obrigatórios."
        )
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
