"""Router de análise de malhas 3D (bounding box + printability check)."""

import logging
import tempfile
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import trimesh
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from supabase import Client, create_client

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analyze"])
security = HTTPBearer()

# ---------------------------------------------------------------------------
# Dependência de autenticação interna
# ---------------------------------------------------------------------------


def verify_internal_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> None:
    """Verifica o token de autenticação interna (Next.js → mesh-service)."""
    if not settings.python_backend_internal_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Token interno não configurado.",
        )
    if credentials.credentials != settings.python_backend_internal_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticação inválido.",
        )


# ---------------------------------------------------------------------------
# Modelos Pydantic (contratos de API)
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    """Payload recebido do Next.js para iniciar a análise."""

    model_id: str
    storage_path: str
    user_id: str


class AnalyzeResponse(BaseModel):
    """Resposta da análise."""

    ok: bool
    model_id: str


class PrintabilityReport(BaseModel):
    """Relatório de printability gerado pelo trimesh."""

    is_watertight: bool
    is_volume: bool
    non_manifold_edge_count: int
    face_count: int
    vertex_count: int
    error: str | None = None


# ---------------------------------------------------------------------------
# Endpoint principal
# ---------------------------------------------------------------------------


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="Analisar malha 3D",
    description=(
        "Recebe o caminho do arquivo no Storage, baixa via URL assinada, "
        "calcula bounding box e roda checagem de printability com trimesh. "
        "Atualiza a tabela `models` com o resultado."
    ),
)
async def analyze_mesh(
    payload: AnalyzeRequest,
    _auth: None = Depends(verify_internal_token),
) -> AnalyzeResponse:
    """Análise completa de uma malha 3D."""
    logger.info("Iniciando análise: model_id=%s", payload.model_id)

    supabase = _get_supabase_client()

    try:
        # 1. Gerar URL assinada de download (válida por 5 minutos)
        signed_url = _create_download_url(supabase, payload.storage_path)

        # 2. Baixar arquivo para um diretório temporário
        file_path = await _download_file(signed_url, payload.storage_path)

        # 3. Analisar a malha com trimesh
        report, bounding_box = _analyze_with_trimesh(file_path)

        # 4. Determinar status de printability
        printability_status = _determine_status(report)

        # 5. Atualizar a tabela models no Supabase
        _update_model(
            supabase,
            payload.model_id,
            bounding_box=bounding_box,
            printability_status=printability_status,
            printability_report=report.model_dump(),
        )

        logger.info(
            "Análise concluída: model_id=%s status=%s",
            payload.model_id,
            printability_status,
        )
        return AnalyzeResponse(ok=True, model_id=payload.model_id)

    except Exception as exc:  # noqa: BLE001
        logger.error("Erro na análise model_id=%s: %s", payload.model_id, exc)

        # Atualizar modelo com status de erro
        error_report = PrintabilityReport(
            is_watertight=False,
            is_volume=False,
            non_manifold_edge_count=0,
            face_count=0,
            vertex_count=0,
            error=str(exc),
        )
        _update_model(
            supabase,
            payload.model_id,
            bounding_box=None,
            printability_status="error",
            printability_report=error_report.model_dump(),
        )
        return AnalyzeResponse(ok=False, model_id=payload.model_id)

    finally:
        # Limpar arquivo temporário
        if "file_path" in locals():
            try:
                Path(file_path).unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------


def _get_supabase_client() -> Client:
    """Cria um cliente Supabase com service_role para operações administrativas."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY são obrigatórios.")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def _create_download_url(supabase: Client, storage_path: str) -> str:
    """Gera uma URL assinada de download válida por 5 minutos."""
    response = supabase.storage.from_("models").create_signed_url(
        storage_path, expires_in=300
    )
    if not response or "signedURL" not in response:
        raise RuntimeError(f"Não foi possível gerar URL de download: {response}")
    return str(response["signedURL"])


async def _download_file(url: str, storage_path: str) -> str:
    """Baixa o arquivo da URL assinada para um arquivo temporário."""
    suffix = Path(storage_path).suffix or ".stl"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with Path(tmp_path).open("wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    f.write(chunk)

    return tmp_path


def _analyze_with_trimesh(
    file_path: str,
) -> tuple[PrintabilityReport, dict[str, float] | None]:
    """
    Carrega a malha com trimesh e calcula bounding box + printability.
    Retorna (PrintabilityReport, bounding_box_dict | None).
    """
    mesh_or_scene = trimesh.load(file_path, force="mesh")

    # Normalizar: cenas (ex: 3MF com múltiplos objetos) → malha única
    if isinstance(mesh_or_scene, trimesh.Scene):
        geometries = list(mesh_or_scene.geometry.values())
        if not geometries:
            raise ValueError("Arquivo 3D vazio ou sem geometria.")
        mesh = trimesh.util.concatenate(geometries)
    elif isinstance(mesh_or_scene, trimesh.Trimesh):
        mesh = mesh_or_scene
    else:
        raise ValueError(f"Tipo de geometria não suportado: {type(mesh_or_scene)}")

    if len(mesh.faces) == 0:
        raise ValueError("A malha não contém faces.")

    # Bounding box em mm (assume-se que as unidades já estão em mm)
    extents: np.ndarray = mesh.extents  # [x, y, z]
    bounding_box = {
        "x": float(round(extents[0], 3)),
        "y": float(round(extents[1], 3)),
        "z": float(round(extents[2], 3)),
    }

    # Checagem de printability
    is_watertight = bool(mesh.is_watertight)
    is_volume = bool(mesh.is_volume)

    # Contar arestas não-manifold (compartilhadas por mais de 2 faces)
    edges_sorted: np.ndarray = mesh.edges_sorted
    _, counts = np.unique(edges_sorted, axis=0, return_counts=True)
    non_manifold_edge_count = int(np.sum(counts > 2))

    report = PrintabilityReport(
        is_watertight=is_watertight,
        is_volume=is_volume,
        non_manifold_edge_count=non_manifold_edge_count,
        face_count=int(len(mesh.faces)),
        vertex_count=int(len(mesh.vertices)),
    )

    return report, bounding_box


def _determine_status(report: PrintabilityReport) -> str:
    """
    Define o status de printability com base no relatório:
    - 'ok': malha fechada, volume válido, sem arestas não-manifold
    - 'warning': malha fechada mas com problemas menores
    - 'error': malha não fechada ou com arestas não-manifold
    """
    if report.is_watertight and report.is_volume and report.non_manifold_edge_count == 0:
        return "ok"
    if not report.is_watertight or report.non_manifold_edge_count > 0:
        return "error"
    return "warning"


def _update_model(
    supabase: Client,
    model_id: str,
    *,
    bounding_box: dict[str, float] | None,
    printability_status: str,
    printability_report: dict[str, Any],
) -> None:
    """Atualiza a tabela models com os resultados da análise."""
    update_data: dict[str, Any] = {
        "printability_status": printability_status,
        "printability_report": printability_report,
    }

    if bounding_box is not None:
        update_data["bounding_box_x_mm"] = bounding_box["x"]
        update_data["bounding_box_y_mm"] = bounding_box["y"]
        update_data["bounding_box_z_mm"] = bounding_box["z"]

    result = supabase.table("models").update(update_data).eq("id", model_id).execute()

    if not result.data:
        logger.warning("UPDATE models retornou vazio para model_id=%s", model_id)
