"""
Router de planejamento e execução de sessões de corte (split sessions).

Fase 4 — planejamento (POST /split-sessions):
  Seção 6.4 passo 2-3: compara bbox do modelo com a mesa, calcula planos sugeridos,
  persiste split_session com status='draft'.

Fase 5 — execução (POST /split-sessions/{id}/execute):
  Seção 6.4 passo 5: verifica assinatura, baixa modelo, repara malha, executa corte
  booleano com manifold3d, valida peças, salva STLs no Storage e linhas em `pieces`.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.deps import get_supabase_client, verify_internal_token
from app.mesh.cutter import CutPlaneInput, cut_mesh_by_planes
from app.mesh.geometry import Dimensions, compute_split_plan
from app.mesh.natural_cuts import SuggestedCutPlane, suggest_cuts
from app.mesh.repair import load_and_normalize, repair_mesh
from app.storage import create_download_url, download_to_tempfile, upload_bytes

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
    """Plano de corte sugerido, serializado para JSON (inclui source)."""

    normal: list[float]
    origin: list[float]   # posicao 3D do plano (coordenadas centradas)
    label: str
    source: str           # "suggested_natural" | "suggested_grid_fallback"


class SplitSessionResponse(BaseModel):
    """Resultado do planejamento — retornado ao Next.js."""

    split_session_id: str
    fits: bool
    model_dimensions: dict[str, float]
    plate_dimensions: dict[str, float]
    cut_planes: list[CutPlaneOut]


# ---------------------------------------------------------------------------
# Endpoint principal
# ---------------------------------------------------------------------------


class SuggestRequest(BaseModel):
    """Payload para acionar analise automatica de gargalos naturais."""
    user_id: str


class SuggestResponse(BaseModel):
    """Resultado da analise automatica."""
    split_session_id: str
    cut_planes: list[CutPlaneOut]
    natural_count: int
    grid_count: int


# ---------------------------------------------------------------------------
# POST /split-sessions — planejamento rapido (grade)
# ---------------------------------------------------------------------------


@router.post(
    "/split-sessions",
    response_model=SplitSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar sessao de corte com planos de grade iniciais",
    description=(
        "Resposta rapida: compara bbox do modelo com a mesa e retorna planos de grade "
        "como sugestao inicial. Para sugestao por gargalos naturais, use "
        "POST /split-sessions/{id}/suggest em seguida."
    ),
)
async def plan_split_session(
    payload: SplitSessionRequest,
    _auth: None = Depends(verify_internal_token),
) -> SplitSessionResponse:
    """Planejamento rapido com divisao em grade — sem download da malha."""
    supabase = _get_supabase_client()

    # 1. Buscar modelo
    model = _fetch_model(supabase, payload.model_id, payload.user_id)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Modelo nao encontrado ou nao pertence a este usuario.",
        )

    if model.get("bounding_box_x_mm") is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "O modelo ainda nao foi analisado. "
                "Aguarde a conclusao da analise de printability antes de planejar os cortes."
            ),
        )

    # 2. Buscar mesa de trabalho
    plate = _fetch_build_plate(supabase, payload.build_plate_id, payload.user_id)
    if plate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mesa de trabalho nao encontrada ou nao pertence a este usuario.",
        )

    model_dims = Dimensions(
        x=float(model["bounding_box_x_mm"]),
        y=float(model["bounding_box_y_mm"]),
        z=float(model["bounding_box_z_mm"]),
    )
    plate_dims_dict = {
        "x": float(plate["build_volume_x_mm"]),
        "y": float(plate["build_volume_y_mm"]),
        "z": float(plate["build_volume_z_mm"]),
    }

    # 3. Planos de grade como sugestao inicial
    plate_dims_obj = Dimensions(**{k: v for k, v in plate_dims_dict.items()})
    grid_plan = compute_split_plan(model_dims, plate_dims_obj)
    fits = grid_plan.fits

    suggested_planes: list[SuggestedCutPlane] = []
    for cp in grid_plan.cut_planes:
        origin = [0.0, 0.0, 0.0]
        if cp.axis == "x":
            origin[0] = cp.position_mm
        elif cp.axis == "y":
            origin[1] = cp.position_mm
        else:
            origin[2] = cp.position_mm
        suggested_planes.append(
            SuggestedCutPlane(
                normal=cp.normal,
                origin=origin,
                label=cp.label,
                source="suggested_grid_fallback",
            )
        )

    # 4. Serializar e persistir
    cut_planes_json: list[dict] = [
        {"normal": cp.normal, "origin": cp.origin, "label": cp.label, "source": cp.source}
        for cp in suggested_planes
    ]

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
            detail="Erro ao criar sessao de corte. Tente novamente.",
        )

    logger.info(
        "Split session criada (grade): id=%s fits=%s planos=%d",
        session["id"], fits, len(suggested_planes),
    )

    return SplitSessionResponse(
        split_session_id=session["id"],
        fits=fits,
        model_dimensions={"x": model_dims.x, "y": model_dims.y, "z": model_dims.z},
        plate_dimensions=plate_dims_dict,
        cut_planes=[
            CutPlaneOut(normal=cp.normal, origin=cp.origin, label=cp.label, source=cp.source)
            for cp in suggested_planes
        ],
    )


# ---------------------------------------------------------------------------
# POST /split-sessions/{id}/suggest — analise automatica de gargalos naturais
# ---------------------------------------------------------------------------


@router.post(
    "/split-sessions/{session_id}/suggest",
    response_model=SuggestResponse,
    status_code=status.HTTP_200_OK,
    summary="Detectar gargalos naturais e atualizar planos de corte",
    description=(
        "Baixa a malha 3D, varre 18 direcoes com trimesh.section para detectar gargalos "
        "anatomicos (pescoco, juncao de asas, cintura, tornozelos, etc.) e retorna o menor "
        "conjunto de cortes que faz cada peca caber na mesa. Atualiza cut_planes no banco. "
        "Pode levar 20-60s dependendo da complexidade do modelo."
    ),
)
async def suggest_split_session(
    session_id: str,
    payload: SuggestRequest,
    _auth: None = Depends(verify_internal_token),
) -> SuggestResponse:
    """Analise inteligente: gargalos naturais com fallback de grade por eixo."""
    supabase = _get_supabase_client()

    # 1. Buscar sessao de corte
    try:
        sess_result = (
            supabase.table("split_sessions")
            .select("id, model_id, build_plate_id, user_id")
            .eq("id", session_id)
            .eq("user_id", payload.user_id)
            .single()
            .execute()
        )
        session_row = sess_result.data
    except Exception as exc:
        logger.warning("Sessao nao encontrada: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sessao de corte nao encontrada.",
        ) from exc

    # 2. Buscar modelo e mesa
    model = _fetch_model(supabase, session_row["model_id"], payload.user_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Modelo nao encontrado.")

    plate = _fetch_build_plate(supabase, session_row["build_plate_id"], payload.user_id)
    if plate is None:
        raise HTTPException(status_code=404, detail="Mesa de trabalho nao encontrada.")

    plate_dims_dict = {
        "x": float(plate["build_volume_x_mm"]),
        "y": float(plate["build_volume_y_mm"]),
        "z": float(plate["build_volume_z_mm"]),
    }

    # 3. Baixar e normalizar malha
    try:
        download_url = create_download_url(supabase, model["storage_path"], expires_in=600)
        tmp_path = await download_to_tempfile(download_url, model["storage_path"])
        mesh = load_and_normalize(tmp_path)
        bbox_center = mesh.bounds.mean(axis=0)
        mesh.apply_translation(-bbox_center)
    except Exception as exc:
        logger.error("Falha ao baixar/carregar malha: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Nao foi possivel baixar o modelo para analise: {exc}",
        ) from exc

    # 4. Detectar gargalos naturais (18 direcoes)
    logger.info("Iniciando suggest_cuts para sessao %s (18 direcoes)", session_id)
    suggestion = suggest_cuts(mesh, plate_dims_dict)
    logger.info(
        "suggest_cuts concluido: fits=%s planos=%d",
        suggestion.fits, len(suggestion.cut_planes),
    )

    # 5. Atualizar cut_planes no banco
    cut_planes_json: list[dict] = [
        {"normal": cp.normal, "origin": cp.origin, "label": cp.label, "source": cp.source}
        for cp in suggestion.cut_planes
    ]
    try:
        supabase.table("split_sessions").update(
            {"cut_planes": cut_planes_json}
        ).eq("id", session_id).execute()
    except Exception as exc:
        logger.warning("Falha ao atualizar cut_planes no banco: %s", exc)
        # Nao falhar — retornar os planos mesmo assim

    natural_count = sum(1 for cp in suggestion.cut_planes if cp.source == "suggested_natural")
    grid_count = sum(1 for cp in suggestion.cut_planes if cp.source == "suggested_grid_fallback")

    return SuggestResponse(
        split_session_id=session_id,
        cut_planes=[
            CutPlaneOut(normal=cp.normal, origin=cp.origin, label=cp.label, source=cp.source)
            for cp in suggestion.cut_planes
        ],
        natural_count=natural_count,
        grid_count=grid_count,
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
                "id, user_id, storage_path, format, "
                "bounding_box_x_mm, bounding_box_y_mm, "
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
            .execute()  # supabase-py v2: .single() não suportado em inserts
        )
        # .execute() após .insert() retorna uma lista — pegamos o primeiro item
        return result.data[0] if result.data else None  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001
        logger.error("_create_split_session falhou: %s", exc)
        return None



# =============================================================================
# FASE 5 — Endpoint de execução do corte booleano
# =============================================================================


# ---------------------------------------------------------------------------
# Contratos de API — execute
# ---------------------------------------------------------------------------


class ExecuteCutPlane(BaseModel):
    """Plano de corte confirmado pelo usuário após ajustes no frontend."""

    normal: list[float]  # vetor normal normalizado, ex: [1.0, 0.0, 0.0]
    origin: list[float]  # ponto no plano em coords. do modelo centrado, ex: [25.0, 0.0, 0.0]
    label: str = ""


class ExecuteRequest(BaseModel):
    """Payload recebido pelo endpoint de execução."""

    user_id: str
    cut_planes: list[ExecuteCutPlane]


class PieceOut(BaseModel):
    """Metadados de uma peça gerada pelo corte."""

    id: str
    piece_index: int
    storage_path: str
    bounding_box_x_mm: float | None
    bounding_box_y_mm: float | None
    bounding_box_z_mm: float | None
    fits_build_plate: bool


class ExecuteResponse(BaseModel):
    """Resultado completo da execução do corte."""

    split_session_id: str
    status: str
    piece_count: int
    pieces: list[PieceOut]


# ---------------------------------------------------------------------------
# Endpoint execute
# ---------------------------------------------------------------------------


@router.post(
    "/split-sessions/{session_id}/execute",
    response_model=ExecuteResponse,
    status_code=status.HTTP_200_OK,
    summary="Executar o corte booleano de um modelo 3D",
    description=(
        "Etapa 5 da seção 6.4 do AGENTS.md. "
        "Verifica assinatura ativa → baixa modelo → repara malha → "
        "executa cortes com manifold3d → valida peças → salva STLs no Storage → "
        "insere linhas em `pieces` → atualiza split_session para 'completed'."
    ),
)
async def execute_split(
    session_id: str,
    payload: ExecuteRequest,
    _auth: None = Depends(verify_internal_token),
) -> ExecuteResponse:
    """Executa o corte booleano real de um modelo 3D."""
    supabase = _get_supabase_client()

    # 1. Verificar assinatura ativa (seção 6.4 — acesso via assinatura)
    if not _check_subscription(supabase, payload.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Assinatura ativa necessária para executar o corte. "
                "Faça upgrade do seu plano para liberar esta funcionalidade."
            ),
        )

    # 2. Buscar sessão e verificar posse
    session = _fetch_session(supabase, session_id, payload.user_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sessão de corte não encontrada ou não pertence a este usuário.",
        )
    if session.get("status") not in ("draft", "failed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A sessão não pode ser executada com status '{session['status']}'. "
                "Apenas sessões 'draft' ou 'failed' podem ser executadas."
            ),
        )

    # 3. Marcar como em processamento
    _update_session_status(supabase, session_id, "processing")

    tmp_path: str | None = None
    try:
        # 4. Buscar metadados do modelo e da mesa de trabalho
        model = _fetch_model_for_execute(supabase, session["model_id"], payload.user_id)
        if model is None:
            raise RuntimeError("Modelo não encontrado.")

        plate = _fetch_build_plate(supabase, session["build_plate_id"], payload.user_id)
        if plate is None:
            raise RuntimeError("Mesa de trabalho não encontrada.")

        # 5. Gerar URL assinada + baixar arquivo 3D
        download_url = create_download_url(supabase, model["storage_path"], expires_in=600)
        tmp_path = await download_to_tempfile(download_url, model["storage_path"])

        # 6. Carregar, normalizar e reparar a malha
        mesh = load_and_normalize(tmp_path)
        mesh = repair_mesh(mesh)

        # CRÍTICO: centrar a malha na origem do bounding box.
        # O Three.js faz geo.center() / group.position.sub(bboxCenter) antes de exibir
        # o modelo, então TODOS os planos de corte enviados pelo frontend são definidos
        # em coordenadas relativas ao modelo JÁ CENTRADO.
        # Sem este passo, os planos passam longe do modelo e o corte não ocorre.
        bbox_center = mesh.bounds.mean(axis=0)  # (min + max) / 2 por eixo
        mesh.apply_translation(-bbox_center)
        logger.info(
            "Malha carregada e centrada: verts=%d faces=%d watertight=%s extents=[%.1f, %.1f, %.1f]mm "
            "(centro original era [%.2f, %.2f, %.2f])",
            len(mesh.vertices),
            len(mesh.faces),
            mesh.is_watertight,
            *mesh.extents,
            *bbox_center,
        )

        # 7. Preparar planos de corte com os valores confirmados pelo usuário
        cut_plane_inputs = [
            CutPlaneInput(
                normal=cp.normal,
                origin=cp.origin,
                label=cp.label,
            )
            for cp in payload.cut_planes
        ]

        # 8. Executar corte booleano com manifold3d (capping automático)
        pieces = cut_mesh_by_planes(mesh, cut_plane_inputs)
        logger.info("Corte concluído: %d peças geradas", len(pieces))

        # 9. Validar, fazer upload e inserir cada peça no banco
        plate_dims = {
            "x": float(plate["build_volume_x_mm"]),
            "y": float(plate["build_volume_y_mm"]),
            "z": float(plate["build_volume_z_mm"]),
        }

        piece_rows: list[dict[str, Any]] = []
        for i, piece in enumerate(pieces):
            extents = piece.extents  # [x, y, z] — dimensões da bounding box

            # Verificar se cabe na mesa (qualquer orientação — usa extents mínimo)
            fits = (
                float(extents[0]) <= plate_dims["x"]
                and float(extents[1]) <= plate_dims["y"]
                and float(extents[2]) <= plate_dims["z"]
            )

            # Exportar como STL binário
            stl_bytes: bytes = piece.export(file_type="stl")

            # Upload ao Storage: path = {user_id}/pieces/{session_id}/piece_{i}.stl
            storage_path = f"{payload.user_id}/pieces/{session_id}/piece_{i}.stl"
            upload_bytes(supabase, storage_path, stl_bytes)

            # Inserir linha na tabela `pieces`
            # supabase-py v2: .single() não é suportado em .insert() — usar data[0]
            insert_result = (
                supabase.table("pieces")
                .insert(
                    {
                        "split_session_id": session_id,
                        "piece_index": i,
                        "storage_path": storage_path,
                        "bounding_box_x_mm": round(float(extents[0]), 3),
                        "bounding_box_y_mm": round(float(extents[1]), 3),
                        "bounding_box_z_mm": round(float(extents[2]), 3),
                        "fits_build_plate": fits,
                    }
                )
                .execute()
            )
            if insert_result.data:
                piece_rows.append(insert_result.data[0])


        # 10. Atualizar split_session: status='completed', cut_planes confirmados
        now_iso = datetime.now(timezone.utc).isoformat()
        supabase.table("split_sessions").update(
            {
                "status": "completed",
                "completed_at": now_iso,
                "cut_planes": [
                    {"normal": cp.normal, "origin": cp.origin, "label": cp.label}
                    for cp in payload.cut_planes
                ],
            }
        ).eq("id", session_id).execute()

        logger.info(
            "Sessão %s concluída com sucesso: %d peças salvas no Storage",
            session_id,
            len(piece_rows),
        )

        return ExecuteResponse(
            split_session_id=session_id,
            status="completed",
            piece_count=len(piece_rows),
            pieces=[
                PieceOut(
                    id=row["id"],
                    piece_index=row["piece_index"],
                    storage_path=row["storage_path"],
                    bounding_box_x_mm=row.get("bounding_box_x_mm"),
                    bounding_box_y_mm=row.get("bounding_box_y_mm"),
                    bounding_box_z_mm=row.get("bounding_box_z_mm"),
                    fits_build_plate=row["fits_build_plate"],
                )
                for row in piece_rows
            ],
        )

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        error_msg = str(exc)
        logger.error("Erro na execução da sessão %s: %s", session_id, error_msg)
        _update_session_status(
            supabase, session_id, "failed", error_message=error_msg[:1000]
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao executar o corte: {error_msg}",
        )
    finally:
        # Limpar arquivo temporário
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Helpers — execute (isolados para testabilidade)
# ---------------------------------------------------------------------------


def _check_subscription(supabase: Any, user_id: str) -> bool:
    """Verifica se o usuário tem assinatura ativa em subscriptions."""
    try:
        result = (
            supabase.table("subscriptions")
            .select("id")
            .eq("user_id", user_id)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception:  # noqa: BLE001
        return False


def _fetch_session(supabase: Any, session_id: str, user_id: str) -> dict[str, Any] | None:
    """Busca split_session verificando que pertence ao user_id."""
    try:
        result = (
            supabase.table("split_sessions")
            .select("id, model_id, build_plate_id, status, user_id")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        return result.data  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_session falhou: %s", exc)
        return None


def _fetch_model_for_execute(
    supabase: Any, model_id: str, user_id: str
) -> dict[str, Any] | None:
    """Busca o modelo com storage_path para o endpoint execute."""
    try:
        result = (
            supabase.table("models")
            .select("id, user_id, storage_path, format")
            .eq("id", model_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        return result.data  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001
        logger.warning("_fetch_model_for_execute falhou: %s", exc)
        return None


def _update_session_status(
    supabase: Any,
    session_id: str,
    new_status: str,
    completed_at: str | None = None,
    error_message: str | None = None,
) -> None:
    """Atualiza o status da split_session no banco."""
    data: dict[str, Any] = {"status": new_status}
    if completed_at:
        data["completed_at"] = completed_at
    if error_message:
        data["error_message"] = error_message
    try:
        supabase.table("split_sessions").update(data).eq("id", session_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.error("_update_session_status falhou para %s: %s", session_id, exc)

