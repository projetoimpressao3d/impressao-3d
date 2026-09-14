"""Router de analise de malhas 3D (bounding box + printability check)."""
import logging
import tempfile
import zipfile
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


def verify_internal_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> None:
    """Verifica o token de autenticacao interna (Next.js -> mesh-service)."""
    if not settings.python_backend_internal_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Token interno nao configurado.",
        )
    if credentials.credentials != settings.python_backend_internal_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticacao invalido.",
        )


class AnalyzeRequest(BaseModel):
    model_id: str
    storage_path: str
    user_id: str


class AnalyzeResponse(BaseModel):
    ok: bool
    model_id: str


class PrintabilityReport(BaseModel):
    is_watertight: bool
    is_volume: bool
    non_manifold_edge_count: int
    face_count: int
    vertex_count: int
    error: str | None = None


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="Analisar malha 3D",
)
async def analyze_mesh(
    payload: AnalyzeRequest,
    _auth: None = Depends(verify_internal_token),
) -> AnalyzeResponse:
    """Analise completa de uma malha 3D."""
    logger.info("Iniciando analise: model_id=%s", payload.model_id)

    supabase = _get_supabase_client()

    try:
        signed_url = _create_download_url(supabase, payload.storage_path)
        file_path = await _download_file(signed_url, payload.storage_path)

        # Detectar se e multi_object (pecas fisicamente separadas — valido por design)
        is_multi_object = _is_multi_object_3mf(file_path)

        report, bounding_box = _analyze_with_trimesh(file_path, is_multi_object=is_multi_object)
        printability_status = _determine_status(report, is_multi_object=is_multi_object)

        _update_model(
            supabase,
            payload.model_id,
            bounding_box=bounding_box,
            printability_status=printability_status,
            printability_report=report.model_dump(),
        )

        logger.info(
            "Analise concluida: model_id=%s status=%s is_multi_object=%s",
            payload.model_id, printability_status, is_multi_object,
        )
        return AnalyzeResponse(ok=True, model_id=payload.model_id)

    except Exception as exc:
        logger.error("Erro na analise model_id=%s: %s", payload.model_id, exc)
        error_report = PrintabilityReport(
            is_watertight=False, is_volume=False, non_manifold_edge_count=0,
            face_count=0, vertex_count=0, error=str(exc),
        )
        _update_model(
            supabase, payload.model_id,
            bounding_box=None, printability_status="error",
            printability_report=error_report.model_dump(),
        )
        return AnalyzeResponse(ok=False, model_id=payload.model_id)

    finally:
        if "file_path" in locals():
            try:
                Path(file_path).unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Funcoes auxiliares
# ---------------------------------------------------------------------------


def _get_supabase_client() -> Client:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY sao obrigatorios.")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def _is_multi_object_3mf(file_path: str) -> bool:
    """
    Detecta se o 3MF usa formato multi-objeto (pecas fisicamente separadas por extruder).
    Formato multi-objeto: model_settings.config tem <part id="N"> com key="extruder".
    """
    try:
        with zipfile.ZipFile(file_path, "r") as z:
            if "Metadata/model_settings.config" not in z.namelist():
                return False
            cfg = z.read("Metadata/model_settings.config").decode("utf-8", errors="replace")
            return '<part id=' in cfg and 'key="extruder"' in cfg
    except Exception:
        return False


def _create_download_url(supabase: Client, storage_path: str) -> str:
    response = supabase.storage.from_("models").create_signed_url(
        storage_path, expires_in=300
    )
    # supabase-py 2.x retorna um objeto SignedURLResponse com atributo .signed_url
    # Versoes antigas retornavam um dict com chave "signedURL"
    url: str | None = None
    if hasattr(response, "signed_url"):
        url = str(response.signed_url)
    elif isinstance(response, dict):
        url = response.get("signedURL") or response.get("signedUrl")
    if not url:
        raise RuntimeError(f"Nao foi possivel gerar URL de download: {response}")
    return url


async def _download_file(url: str, storage_path: str) -> str:
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
    is_multi_object: bool = False,
) -> tuple[PrintabilityReport, dict[str, float] | None]:
    """
    Carrega a malha com trimesh e calcula bounding box + printability.
    Usa Scene.bounds para evitar concatenação de geometrias (economiza memória).
    Para modelos multi-objeto, pecas separadas sao validas por design.
    """
    # process=False evita reconstrução automática da malha (economiza RAM)
    mesh_or_scene = trimesh.load(file_path, process=False)

    bounding_box: dict[str, float] | None = None
    mesh: trimesh.Trimesh | None = None

    if isinstance(mesh_or_scene, trimesh.Scene):
        # Bounding box via Scene.bounds — sem concatenar geometrias
        bounds = mesh_or_scene.bounds
        if bounds is None:
            raise ValueError("Arquivo 3D sem geometria mensurável.")
        extents = bounds[1] - bounds[0]
        bounding_box = {
            "x": float(round(float(extents[0]), 3)),
            "y": float(round(float(extents[1]), 3)),
            "z": float(round(float(extents[2]), 3)),
        }
        # Para verificar watertightness, usa a maior geometria individualmente
        geometries = [g for g in mesh_or_scene.geometry.values()
                      if isinstance(g, trimesh.Trimesh) and len(g.faces) > 0]
        if not geometries:
            raise ValueError("Arquivo 3D vazio ou sem geometria.")
        mesh = max(geometries, key=lambda g: len(g.faces))

    elif isinstance(mesh_or_scene, trimesh.Trimesh):
        mesh = mesh_or_scene
        extents: np.ndarray = mesh.extents
        bounding_box = {
            "x": float(round(float(extents[0]), 3)),
            "y": float(round(float(extents[1]), 3)),
            "z": float(round(float(extents[2]), 3)),
        }
    else:
        raise ValueError(f"Tipo de geometria nao suportado: {type(mesh_or_scene)}")

    if mesh is None or len(mesh.faces) == 0:
        raise ValueError("A malha nao contem faces.")

    if is_multi_object:
        report = PrintabilityReport(
            is_watertight=True, is_volume=True, non_manifold_edge_count=0,
            face_count=int(len(mesh.faces)), vertex_count=int(len(mesh.vertices)),
        )
    else:
        is_watertight = bool(mesh.is_watertight)
        is_volume = bool(mesh.is_volume)
        edges_sorted: np.ndarray = mesh.edges_sorted
        _, counts = np.unique(edges_sorted, axis=0, return_counts=True)
        non_manifold_edge_count = int(np.sum(counts > 2))
        report = PrintabilityReport(
            is_watertight=is_watertight, is_volume=is_volume,
            non_manifold_edge_count=non_manifold_edge_count,
            face_count=int(len(mesh.faces)), vertex_count=int(len(mesh.vertices)),
        )

    return report, bounding_box


def _determine_status(report: PrintabilityReport, is_multi_object: bool = False) -> str:
    """
    Define o status de printability:
    - 'ok'      : malha valida ou multi-objeto (valido por design)
    - 'warning' : problemas menores mas printavel
    - 'error'   : malha invalida (sem faces, erro interno)
    """
    if report.face_count == 0:
        return "error"
    if is_multi_object:
        return "ok"
    if report.is_watertight and report.is_volume and report.non_manifold_edge_count == 0:
        return "ok"
    return "warning"


def _update_model(
    supabase: Client,
    model_id: str,
    *,
    bounding_box: dict[str, float] | None,
    printability_status: str,
    printability_report: dict[str, Any],
) -> None:
    """Atualiza a tabela models com os resultados da analise."""
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
