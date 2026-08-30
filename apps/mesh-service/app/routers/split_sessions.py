"""
Router de planejamento de sessões de corte (split sessions).

Implementa o passo 2-3 do fluxo da seção 6.4 do AGENTS.md:
- Compara a bounding box do modelo com as dimensões da mesa de trabalho.
- Se não couber, calcula o número mínimo de cortes por eixo e as posições sugeridas.
- Persiste uma split_session com status='draft' no banco.

O corte real (passo 5) será implementado na Fase 6 em POST /split-sessions/{id}/execute.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.deps import get_supabase_client, verify_internal_token
from app.mesh.geometry import CutPlane, Dimensions, SplitPlan, compute_split_plan

logger = logging.getLogger(__name__)
router = APIRouter(tags=["split-sessions"])


# ---------------------------------------------------------------------------
# Contratos de API (Pydantic)
# ---------------------------------------------------------------------------


class SplitSessionRequest(BaseModel):
    """Payload recebido do Next.js para iniciar o planejamento de cortes."""

    model_id: str
    build_plate_id: str
    user_id: str


class CutPlaneOut(BaseModel):
    """Plano de corte sugerido, serializado para JSON."""

    axis: str
    position_mm: float
    normal: list[float]
    label: str


class SplitSessionResponse(BaseModel):
    """Resultado do planejamento — retornado ao Next.js."""

    split_session_id: str
    fits: bool
    model_dimensions: dict[str, float]
    plate_dimensions: dict[str, float]
    cuts_needed: dict[str, int]
    cut_planes: list[CutPlaneOut]


# ---------------------------------------------------------------------------
# Endpoint principal
# ---------------------------------------------------------------------------


@router.post(
    "/split-sessions",
    response_model=SplitSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Planejar cortes de um modelo 3D",
    description=(
        "Compara a bounding box do modelo com as dimensões da mesa de trabalho. "
        "Se cabe: retorna fits=true sem planos de corte. "
        "Se não cabe: calcula o número mínimo de cortes por eixo "
        "(ceil(dim_modelo / dim_mesa) − 1) e retorna as posições sugeridas "
        "(divisão em partes iguais, relativas ao centro do modelo). "
        "Persiste uma split_session com status='draft'. "
        "Seção 6.4 do AGENTS.md — heurística simples, não é IA."
    ),
)
async def plan_split_session(
    payload: SplitSessionRequest,
    _auth: None = Depends(verify_internal_token),
) -> SplitSessionResponse:
    """Planeja os cortes necessários para um modelo 3D numa mesa de trabalho."""
    supabase = _get_supabase_client()

    # 1. Buscar modelo — verifica posse via user_id do payload
    model = _fetch_model(supabase, payload.model_id, payload.user_id)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Modelo não encontrado ou não pertence a este usuário.",
        )

    # 2. Verificar se a bounding box já foi calculada pela análise de printability
    if model.get("bounding_box_x_mm") is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "O modelo ainda não foi analisado. "
                "Aguarde a conclusão da análise de printability antes de planejar os cortes."
            ),
        )

    # 3. Buscar mesa de trabalho — verifica posse
    plate = _fetch_build_plate(supabase, payload.build_plate_id, payload.user_id)
    if plate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mesa de trabalho não encontrada ou não pertence a este usuário.",
        )

    # 4. Calcular plano de cortes (puro — sem I/O)
    model_dims = Dimensions(
        x=float(model["bounding_box_x_mm"]),
        y=float(model["bounding_box_y_mm"]),
        z=float(model["bounding_box_z_mm"]),
    )
    plate_dims = Dimensions(
        x=float(plate["build_volume_x_mm"]),
        y=float(plate["build_volume_y_mm"]),
        z=float(plate["build_volume_z_mm"]),
    )
    plan = compute_split_plan(model_dims, plate_dims)

    # 5. Serializar planos de corte para JSONB
    cut_planes_json: list[dict[str, Any]] = [
        {
            "axis": cp.axis,
            "position_mm": cp.position_mm,
            "normal": cp.normal,
            "label": cp.label,
        }
        for cp in plan.cut_planes
    ]

    # 6. Persistir split_session com status='draft'
    session = _create_split_session(
        supabase=supabase,
        model_id=payload.model_id,
        build_plate_id=payload.build_plate_id,
        user_id=payload.user_id,
        cut_planes_json=cut_planes_json,
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao criar sessão de corte. Tente novamente.",
        )

    logger.info(
        "Split session criada: id=%s fits=%s cortes_por_eixo=%s",
        session["id"],
        plan.fits,
        plan.cuts_needed,
    )

    return SplitSessionResponse(
        split_session_id=session["id"],
        fits=plan.fits,
        model_dimensions={
            "x": model_dims.x,
            "y": model_dims.y,
            "z": model_dims.z,
        },
        plate_dimensions={
            "x": plate_dims.x,
            "y": plate_dims.y,
            "z": plate_dims.z,
        },
        cuts_needed=plan.cuts_needed,
        cut_planes=[
            CutPlaneOut(
                axis=cp.axis,
                position_mm=cp.position_mm,
                normal=cp.normal,
                label=cp.label,
            )
            for cp in plan.cut_planes
        ],
    )


# ---------------------------------------------------------------------------
# Helpers (separados para facilitar mock nos testes)
# ---------------------------------------------------------------------------


def _get_supabase_client():  # type: ignore[return]
    """Wrapper isolado para facilitar mock em testes."""
    return get_supabase_client()


def _fetch_model(
    supabase: Any,
    model_id: str,
    user_id: str,
) -> dict[str, Any] | None:
    """Busca o modelo no Supabase verificando que pertence ao user_id."""
    try:
        result = (
            supabase.table("models")
            .select(
                "id, user_id, bounding_box_x_mm, bounding_box_y_mm, "
                "bounding_box_z_mm, printability_status"
            )
            .eq("id", model_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        return result.data  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_model falhou: %s", exc)
        return None


def _fetch_build_plate(
    supabase: Any,
    plate_id: str,
    user_id: str,
) -> dict[str, Any] | None:
    """Busca a mesa de trabalho no Supabase verificando que pertence ao user_id."""
    try:
        result = (
            supabase.table("build_plates")
            .select(
                "id, user_id, build_volume_x_mm, build_volume_y_mm, build_volume_z_mm"
            )
            .eq("id", plate_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        return result.data  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_build_plate falhou: %s", exc)
        return None


def _create_split_session(
    *,
    supabase: Any,
    model_id: str,
    build_plate_id: str,
    user_id: str,
    cut_planes_json: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Persiste a split_session no Supabase com status='draft'."""
    try:
        result = (
            supabase.table("split_sessions")
            .insert(
                {
                    "model_id": model_id,
                    "build_plate_id": build_plate_id,
                    "user_id": user_id,
                    "status": "draft",
                    "cut_planes": cut_planes_json,
                    "has_connectors": False,
                }
            )
            .select()
            .single()
            .execute()
        )
        return result.data  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001
        logger.error("_create_split_session falhou: %s", exc)
        return None
