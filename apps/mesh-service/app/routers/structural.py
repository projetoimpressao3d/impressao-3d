"""
Router para separacao estrutural de pecas (secao 6.4.1 do AGENTS.md).

POST /split-sessions/{id}/separate: inicia job assincrono de extracao de esqueleto.
GET  /split-sessions/{id}/status:   polling do status do job.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.deps import get_supabase_client, verify_internal_token
from app.mesh.natural_cuts import SuggestedCutPlane, suggest_cuts
from app.mesh.repair import load_and_normalize
from app.mesh.skeleton import DEFAULT_SENSITIVITY, StructuralCutPlane, suggest_structural_cuts
from app.storage import create_download_url, download_to_tempfile

logger = logging.getLogger(__name__)
router = APIRouter(tags=["structural"])


# ---------------------------------------------------------------------------
# Contratos de API
# ---------------------------------------------------------------------------


class SeparateRequest(BaseModel):
    """Payload para iniciar a separacao estrutural de pecas."""

    user_id: str
    structural_sensitivity: float = Field(
        default=DEFAULT_SENSITIVITY,
        ge=0.0,
        le=1.0,
        description="Limiar minimo de volume (fracao do total) para apendice ser separavel.",
    )


class CutPlaneOut(BaseModel):
    """Plano de corte serializado (inclui source e structural_group)."""

    normal: list[float]
    origin: list[float]
    label: str
    source: str
    structural_group: str | None = None


class SeparateResponse(BaseModel):
    """Resposta imediata do endpoint de separacao (job disparado)."""

    split_session_id: str
    status: str = "processing"


class StatusResponse(BaseModel):
    """Resposta do polling de status."""

    split_session_id: str
    status: str
    cut_planes: list[CutPlaneOut] = []
    structural_count: int = 0
    natural_count: int = 0
    grid_count: int = 0
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/split-sessions/{session_id}/separate",
    response_model=SeparateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Iniciar separacao estrutural de pecas (job assincrono)",
)
async def start_structural_separation(
    session_id: str,
    payload: SeparateRequest,
    _auth: None = Depends(verify_internal_token),
) -> SeparateResponse:
    """Inicia o job de extracao de esqueleto em background. Retorna imediatamente."""
    supabase = get_supabase_client()

    # Verificar que a sessao existe e pertence ao usuario
    sess = _fetch_session(supabase, session_id, payload.user_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Sessao de corte nao encontrada.")

    # Marcar como processing e salvar sensibilidade
    _update_session_status(
        supabase, session_id,
        status="processing",
        structural_sensitivity=payload.structural_sensitivity,
    )

    # Disparar job em background (nao bloquear a resposta)
    asyncio.create_task(
        _background_separate(session_id, payload.user_id, payload.structural_sensitivity)
    )

    logger.info(
        "Separacao estrutural iniciada: session=%s sensitivity=%.3f",
        session_id, payload.structural_sensitivity,
    )
    return SeparateResponse(split_session_id=session_id, status="processing")


@router.get(
    "/split-sessions/{session_id}/status",
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar status do job de separacao estrutural",
)
async def get_session_status(
    session_id: str,
    user_id: str,
    _auth: None = Depends(verify_internal_token),
) -> StatusResponse:
    """Retorna o status atual da sessao e os planos se ja concluidos."""
    supabase = get_supabase_client()

    sess = _fetch_session_full(supabase, session_id, user_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada.")

    cut_planes_raw: list[dict] = sess.get("cut_planes") or []
    planes_out = [
        CutPlaneOut(
            normal=cp["normal"],
            origin=cp["origin"],
            label=cp.get("label", ""),
            source=cp.get("source", "manual"),
            structural_group=cp.get("structural_group"),
        )
        for cp in cut_planes_raw
    ]

    structural_count = sum(1 for p in planes_out if p.source == "suggested_structural")
    natural_count = sum(1 for p in planes_out if p.source == "suggested_natural")
    grid_count = sum(1 for p in planes_out if p.source == "suggested_grid_fallback")

    return StatusResponse(
        split_session_id=session_id,
        status=sess.get("status", "draft"),
        cut_planes=planes_out,
        structural_count=structural_count,
        natural_count=natural_count,
        grid_count=grid_count,
        error_message=sess.get("error_message"),
    )


# ---------------------------------------------------------------------------
# Job de background
# ---------------------------------------------------------------------------


async def _background_separate(
    session_id: str,
    user_id: str,
    sensitivity: float,
) -> None:
    """Job assincrono: extrai esqueleto, detecta apendices, encadeia suggest_cuts."""
    supabase = get_supabase_client()

    try:
        # 1. Buscar sessao e modelo
        sess = _fetch_session(supabase, session_id, user_id)
        if sess is None:
            logger.error("_background_separate: sessao %s nao encontrada", session_id)
            return

        model = _fetch_model(supabase, sess["model_id"], user_id)
        if model is None:
            _fail_session(supabase, session_id, "Modelo nao encontrado.")
            return

        plate = _fetch_build_plate(supabase, sess["build_plate_id"], user_id)
        if plate is None:
            _fail_session(supabase, session_id, "Mesa de trabalho nao encontrada.")
            return

        plate_dims = {
            "x": float(plate["build_volume_x_mm"]),
            "y": float(plate["build_volume_y_mm"]),
            "z": float(plate["build_volume_z_mm"]),
        }

        # 2. Baixar e preparar malha
        logger.info("_background_separate: baixando malha para sessao %s", session_id)
        download_url = create_download_url(supabase, model["storage_path"], expires_in=600)
        tmp_path = await download_to_tempfile(download_url, model["storage_path"])
        mesh = load_and_normalize(tmp_path)
        bbox_center = mesh.bounds.mean(axis=0)
        mesh.apply_translation(-bbox_center)

        # 3. Extrair esqueleto e detectar candidatos estruturais
        logger.info("_background_separate: extraindo esqueleto...")
        structural_result = await asyncio.to_thread(
            suggest_structural_cuts, mesh, sensitivity
        )

        structural_planes: list[StructuralCutPlane] = structural_result.cut_planes
        logger.info(
            "Esqueleto extraido: %d planos estruturais, %d filtrados",
            len(structural_planes), structural_result.filtered_count,
        )

        # 4. Consolidar os planos estruturais (sem poluir com cortes extras que fatiam peças desnecessariamente)
        all_planes_json: list[dict] = []

        for cp in structural_planes:
            all_planes_json.append({
                "normal": cp.normal,
                "origin": cp.origin,
                "label": cp.label,
                "source": cp.source,
                "structural_group": cp.structural_group,
            })

        # 6. Salvar resultado no banco
        supabase.table("split_sessions").update({
            "status": "completed",
            "cut_planes": all_planes_json,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", session_id).execute()

        logger.info(
            "_background_separate concluido: session=%s total_planes=%d",
            session_id, len(all_planes_json),
        )

    except Exception as exc:  # noqa: BLE001
        logger.error("_background_separate falhou: %s", exc)
        _fail_session(supabase, session_id, str(exc))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch_session(supabase: Any, session_id: str, user_id: str) -> dict[str, Any] | None:
    """Busca sessao por id + user_id."""
    try:
        result = (
            supabase.table("split_sessions")
            .select("id, model_id, build_plate_id, user_id, status")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        return result.data
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_session falhou: %s", exc)
        return None


def _fetch_session_full(supabase: Any, session_id: str, user_id: str) -> dict[str, Any] | None:
    """Busca sessao completa incluindo cut_planes e status."""
    try:
        result = (
            supabase.table("split_sessions")
            .select("id, status, cut_planes, error_message, structural_sensitivity")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        return result.data
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_session_full falhou: %s", exc)
        return None


def _fetch_model(supabase: Any, model_id: str, user_id: str) -> dict[str, Any] | None:
    """Busca modelo no Supabase verificando posse."""
    try:
        result = (
            supabase.table("models")
            .select("id, user_id, storage_path, format, bounding_box_x_mm, bounding_box_y_mm, bounding_box_z_mm")
            .eq("id", model_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        return result.data
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_model falhou: %s", exc)
        return None


def _fetch_build_plate(supabase: Any, plate_id: str, user_id: str) -> dict[str, Any] | None:
    """Busca mesa de trabalho no Supabase verificando posse."""
    try:
        result = (
            supabase.table("build_plates")
            .select("id, build_volume_x_mm, build_volume_y_mm, build_volume_z_mm")
            .eq("id", plate_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        return result.data
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_build_plate falhou: %s", exc)
        return None


def _update_session_status(
    supabase: Any,
    session_id: str,
    status: str,
    structural_sensitivity: float | None = None,
) -> None:
    """Atualiza o status da sessao (e opcionalmente a sensibilidade)."""
    update: dict[str, Any] = {"status": status}
    if structural_sensitivity is not None:
        update["structural_sensitivity"] = structural_sensitivity
    try:
        supabase.table("split_sessions").update(update).eq("id", session_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.error("_update_session_status falhou: %s", exc)


def _fail_session(supabase: Any, session_id: str, message: str) -> None:
    """Marca a sessao como failed com mensagem de erro."""
    try:
        supabase.table("split_sessions").update({
            "status": "failed",
            "error_message": message,
        }).eq("id", session_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.error("_fail_session falhou: %s", exc)
