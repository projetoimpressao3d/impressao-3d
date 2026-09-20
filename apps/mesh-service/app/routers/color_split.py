"""
Router de separacao de modelos 3MF por cor (paint_color do Bambu Studio).

Endpoints:
  GET  /color-split/{model_id}/info   — Retorna as cores detectadas (rapido, sem processar geometria)
  POST /color-split/{model_id}/split  — Separa as pecas por cor e gera 3MFs por mesa
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from app.deps import get_supabase_client, verify_internal_token
from app.mesh.color_splitter import get_color_info, parse_3mf_colors
from app.mesh.capper import close_color_piece
from app.mesh.plate_packer import pack_pieces_to_plates
from app.mesh.threemf_writer import write_plate_3mf_bytes
from app.storage import create_download_url, download_to_tempfile, upload_bytes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/color-split", tags=["color-split"])


# ---------------------------------------------------------------------------
# Contratos de API (Pydantic)
# ---------------------------------------------------------------------------


class FilamentInfoOut(BaseModel):
    index: int
    extruder_number: int
    color_hex: str
    face_count: int
    face_percentage: float


class ColorInfoResponse(BaseModel):
    model_id: str
    is_painted: bool
    total_faces: int
    filaments: list[FilamentInfoOut]


class ColorSplitRequest(BaseModel):
    user_id: str
    build_plate_id: str
    cap_method: str = "centroid"   # "centroid" ou "earcut"
    snap_to_floor: bool = True     # True = encosta Z=0; False = posicao original


class PlateOutput(BaseModel):
    plate_number: int
    extruder_number: int
    color_hex: str
    storage_path: str
    download_url: str
    fits_in_plate: bool
    extents_mm: list[float]


class ColorSplitResponse(BaseModel):
    model_id: str
    plates: list[PlateOutput]
    total_pieces: int
    oversized_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch_model(supabase: Client, model_id: str, user_id: str) -> dict | None:
    res = supabase.table("models").select("*").eq("id", model_id).eq("user_id", user_id).single().execute()
    return res.data if res.data else None


def _fetch_build_plate(supabase: Client, plate_id: str, user_id: str) -> dict | None:
    res = (
        supabase.table("build_plates")
        .select("*")
        .eq("id", plate_id)
        .or_(f"user_id.eq.{user_id},user_id.is.null")
        .single()
        .execute()
    )
    return res.data if res.data else None


# ---------------------------------------------------------------------------
# GET /color-split/{model_id}/info — Detectar cores (rapido)
# ---------------------------------------------------------------------------


@router.get(
    "/{model_id}/info",
    response_model=ColorInfoResponse,
    summary="Detectar cores de filamento no modelo 3MF pintado",
)
async def get_model_color_info(
    model_id: str,
    user_id: str,
    supabase: Client = Depends(get_supabase_client),
    _auth: None = Depends(verify_internal_token),
) -> ColorInfoResponse:
    """
    Retorna as cores de filamento detectadas no arquivo 3MF.
    Operacao rapida — nao processa geometria completa, apenas conta faces por cor.
    """
    model = _fetch_model(supabase, model_id, user_id)
    if not model:
        raise HTTPException(status_code=404, detail="Modelo nao encontrado.")

    if not model.get("storage_path", "").endswith(".3mf"):
        raise HTTPException(
            status_code=422,
            detail="Apenas arquivos .3mf pintados sao suportados para separacao por cor.",
        )

    # Download temporario so para leitura rapida do XML
    url = create_download_url(supabase, model["storage_path"])
    tmp_path = await download_to_tempfile(url, model["storage_path"])

    try:
        info = get_color_info(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return ColorInfoResponse(
        model_id=model_id,
        is_painted=info["is_painted"],
        total_faces=info["total_faces"],
        filaments=[FilamentInfoOut(**f) for f in info["filaments"]],
    )


# ---------------------------------------------------------------------------
# POST /color-split/{model_id}/split — Separar e gerar 3MFs
# ---------------------------------------------------------------------------


@router.post(
    "/{model_id}/split",
    response_model=ColorSplitResponse,
    summary="Separar modelo por cores e gerar arquivo 3MF por mesa",
)
async def split_model_by_color(
    model_id: str,
    payload: ColorSplitRequest,
    supabase: Client = Depends(get_supabase_client),
    _auth: None = Depends(verify_internal_token),
) -> ColorSplitResponse:
    """
    Pipeline completo:
    1. Baixa o 3MF do Storage
    2. Separa as faces por paint_color
    3. Fecha os buracos de borda de cada peca
    4. Verifica se cada peca cabe na mesa
    5. Gera um arquivo .3mf por peca
    6. Faz upload ao Supabase Storage
    7. Retorna URLs de download
    """
    model = _fetch_model(supabase, model_id, payload.user_id)
    if not model:
        raise HTTPException(status_code=404, detail="Modelo nao encontrado.")

    plate = _fetch_build_plate(supabase, payload.build_plate_id, payload.user_id)
    if not plate:
        raise HTTPException(status_code=404, detail="Mesa de trabalho nao encontrada.")

    plate_x = float(plate["build_volume_x_mm"])
    plate_y = float(plate["build_volume_y_mm"])
    plate_z = float(plate["build_volume_z_mm"])

    # 1. Download do modelo
    logger.info("Baixando modelo %s...", model_id)
    url = create_download_url(supabase, model["storage_path"])
    tmp_path = await download_to_tempfile(url, model["storage_path"])

    try:
        # 2. Separar por cor
        logger.info("Separando por cor...")
        split_result = parse_3mf_colors(tmp_path)

        if not split_result.pieces:
            raise HTTPException(
                status_code=422,
                detail="Nenhuma cor de filamento detectada. Verifique se o modelo foi pintado no Bambu Studio / OrcaSlicer.",
            )

        # 3. Fechar buracos de cada peca
        # 3. Fechar buracos de cada peca e sub-componente
        logger.info("Fechando buracos das pecas...")
        for piece in split_result.pieces:
            piece.mesh = close_color_piece(piece.mesh, method=payload.cap_method)
            piece.is_watertight = piece.mesh.is_watertight
            if piece.sub_meshes:
                piece.sub_meshes = [
                    close_color_piece(sm, method=payload.cap_method)
                    for sm in piece.sub_meshes
                ]

        # 4. Empacotar em mesas (reposicionamento e assentamento Z=0)
        pack_result = pack_pieces_to_plates(
            split_result.pieces,
            plate_x,
            plate_y,
            plate_z,
            snap_to_floor=payload.snap_to_floor,
        )

        # 5. Gerar e fazer upload dos 3MFs
        plates_output: list[PlateOutput] = []

        for plate_obj in pack_result.plates:
            for placement in plate_obj.placements:
                piece = split_result.pieces[placement.piece_index]
                ext_num = piece.extruder_index + 1
                color = piece.filament.color_hex

                plate_num = plate_obj.plate_index + 1
                fits = placement.fits_in_plate
                extents = [round(float(e), 1) for e in placement.extents_mm]

                # Gerar nome de arquivo
                safe_color = color.replace("#", "")
                fname = f"{model_id}_ext{ext_num}_{safe_color}_plate{plate_num}.3mf"
                storage_path = f"pieces/{payload.user_id}/{model_id}/{fname}"

                # Gerar 3MF em memoria com malhas já posicionadas e assentadas
                model_name = f"{split_result.model_name}_ext{ext_num}"
                meshes_to_write = placement.packed_meshes if placement.packed_meshes else [piece.mesh]

                threemf_bytes = write_plate_3mf_bytes(
                    meshes=meshes_to_write,
                    colors=[color] * len(meshes_to_write),
                    model_name=model_name,
                    snap_to_floor=False,  # Já posicionadas e assentadas no pack
                )

                # Upload
                upload_bytes(supabase, storage_path, threemf_bytes, content_type="model/3mf")

                # URL de download
                dl_url = create_download_url(supabase, storage_path, expires_in=3600)

                plates_output.append(PlateOutput(
                    plate_number=plate_num,
                    extruder_number=ext_num,
                    color_hex=color,
                    storage_path=storage_path,
                    download_url=dl_url,
                    fits_in_plate=fits,
                    extents_mm=extents,
                ))

    finally:
        Path(tmp_path).unlink(missing_ok=True)

    logger.info(
        "Separacao por cor concluida: %d pecas, %d oversized",
        len(split_result.pieces),
        len(pack_result.oversized_pieces),
    )

    return ColorSplitResponse(
        model_id=model_id,
        plates=plates_output,
        total_pieces=len(split_result.pieces),
        oversized_count=len(pack_result.oversized_pieces),
    )
