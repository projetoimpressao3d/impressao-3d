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
import trimesh
from pydantic import BaseModel
from supabase import Client

from app.deps import get_supabase_client, verify_internal_token
from app.mesh.color_splitter import get_color_info, parse_3mf_colors
from app.mesh.capper import close_color_piece
from app.mesh.plate_packer import pack_pieces_to_plates
from app.mesh.threemf_writer import write_plate_3mf_bytes
from app.mesh.skeleton import suggest_structural_cuts
from app.mesh.general_splitter import suggest_general_split
from app.mesh.cutter import cut_mesh_by_planes, CutPlaneInput
from app.storage import create_download_url, download_to_tempfile, upload_bytes, sanitize_storage_key

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
    cap_method: str = "earcut"     # "earcut" (padrao) ou "centroid"
    snap_to_floor: bool = True     # True = encosta Z=0; False = posicao original


class SubdivideColorPieceRequest(BaseModel):
    user_id: str
    build_plate_id: str
    extruder_number: int
    mode: str = "character"         # "character" ou "general"
    character_template: str = "creature"
    general_granularity: str = "auto"
    structural_sensitivity: float = 0.05
    generate_connectors: bool = True
    connector_pin_shape: str = "hex"
    connector_tolerance_mm: float = 0.2
    snap_to_floor: bool = True
    cap_method: str = "earcut"


class PlateOutput(BaseModel):
    plate_number: int
    extruder_number: int
    color_hex: str
    storage_path: str
    download_url: str
    fits_in_plate: bool
    extents_mm: list[float]
    label: str | None = None
    is_subdivided: bool = False


class ColorSplitResponse(BaseModel):
    model_id: str
    plates: list[PlateOutput]
    total_pieces: int
    oversized_count: int
    unified_download_url: str | None = None
    unified_file_name: str | None = None


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
                    label=f"Extruder {ext_num}",
                    is_subdivided=False,
                ))

        # Gerar também o arquivo .3MF unificado com todas as cores
        all_meshes = [p.mesh for p in split_result.pieces]
        all_colors = [p.filament.color_hex for p in split_result.pieces]
        unified_3mf_bytes = write_plate_3mf_bytes(
            meshes=all_meshes,
            colors=all_colors,
            model_name=f"{split_result.model_name}_completo",
            snap_to_floor=payload.snap_to_floor,
        )
        safe_model_name = sanitize_storage_key(split_result.model_name)
        unified_fname = f"{safe_model_name}_completo_todas_cores.3mf"
        unified_path = f"pieces/{payload.user_id}/{model_id}/{unified_fname}"
        upload_bytes(supabase, unified_path, unified_3mf_bytes, content_type="model/3mf")
        unified_url = create_download_url(supabase, unified_path, expires_in=3600)

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
        unified_download_url=unified_url,
        unified_file_name=unified_fname,
    )


# ---------------------------------------------------------------------------
# POST /color-split/{model_id}/subdivide-piece
# ---------------------------------------------------------------------------


@router.post(
    "/{model_id}/subdivide-piece",
    response_model=ColorSplitResponse,
    summary="Subdividir peça oversized preservando todas as cores em 3MF unificado",
)
async def subdivide_color_piece(
    model_id: str,
    payload: SubdivideColorPieceRequest,
    supabase: Client = Depends(get_supabase_client),
    _auth: None = Depends(verify_internal_token),
) -> ColorSplitResponse:
    """
    Subdivide uma cor específica que excedeu a mesa (via Character Split ou General Split),
    gera conectores mecânicos e cria tanto o 3MF unificado com todas as cores
    quanto os arquivos individuais para download de cada peça.
    """
    model = _fetch_model(supabase, model_id, payload.user_id)
    if not model:
        raise HTTPException(status_code=404, detail="Modelo não encontrado.")

    plate = _fetch_build_plate(supabase, payload.build_plate_id, payload.user_id)
    if not plate:
        raise HTTPException(status_code=404, detail="Mesa de trabalho não encontrada.")

    plate_x = float(plate["build_volume_x_mm"])
    plate_y = float(plate["build_volume_y_mm"])
    plate_z = float(plate["build_volume_z_mm"])

    # 1. Download do 3MF original
    url = create_download_url(supabase, model["storage_path"])
    tmp_path = await download_to_tempfile(url, model["storage_path"])

    try:
        # 2. Separar por cor
        split_result = parse_3mf_colors(tmp_path)
        if not split_result.pieces:
            raise HTTPException(status_code=422, detail="Nenhuma cor detectada no modelo.")

        # 3. Fechar buracos de todas as peças
        for p in split_result.pieces:
            p.mesh = close_color_piece(p.mesh, method=payload.cap_method)
            p.is_watertight = p.mesh.is_watertight

        # 4. Localizar a peça alvo do corte (pelo extruder_number)
        target_piece = None
        for p in split_result.pieces:
            if p.extruder_index == payload.extruder_number - 1:
                target_piece = p
                break

        if not target_piece:
            target_piece = max(split_result.pieces, key=lambda p: len(p.mesh.faces))

        # 5. Calcular planos de corte na peça alvo
        cut_inputs: list[CutPlaneInput] = []
        if payload.mode == "character":
            try:
                struct_res = suggest_structural_cuts(
                    target_piece.mesh,
                    sensitivity=payload.structural_sensitivity,
                    build_plate=[plate_x, plate_y, plate_z],
                    template=payload.character_template,
                )
                for cp in struct_res.cut_planes:
                    cut_inputs.append(
                        CutPlaneInput(
                            normal=cp.normal,
                            origin=cp.origin,
                            label=cp.label,
                            bbox_min=cp.bbox_min,
                            bbox_max=cp.bbox_max,
                            branch_pts=cp.branch_pts,
                        )
                    )
            except Exception as e:
                logger.warning("Falha ao sugerir cortes estruturais no modo character: %s", e)

        # Fallback para general split se for o modo general ou se não encontrou cortes anatômicos
        if not cut_inputs:
            gran = payload.general_granularity if payload.general_granularity in ["auto", "low", "medium", "high"] else "auto"
            try:
                gen_res = suggest_general_split(
                    target_piece.mesh,
                    plate_dims={"x": plate_x, "y": plate_y, "z": plate_z},
                    granularity=gran,
                )
                for cp in gen_res.cut_planes:
                    cut_inputs.append(
                        CutPlaneInput(
                            normal=cp.normal,
                            origin=cp.origin,
                            label=cp.label,
                        )
                    )
            except Exception as e:
                logger.warning("Falha ao sugerir cortes gerais: %s", e)

        if not cut_inputs:
            raise HTTPException(
                status_code=400,
                detail="Nenhum plano de corte foi gerado para esta peça nas dimensões da mesa informada.",
            )

        # 6. Executar cortes com conectores mecânicos na peça
        sub_meshes = cut_mesh_by_planes(
            target_piece.mesh,
            cut_inputs,
            generate_connectors=payload.generate_connectors,
            connector_tolerance_mm=payload.connector_tolerance_mm,
            connector_pin_shape=payload.connector_pin_shape,
        )
        if not sub_meshes:
            logger.warning("Corte resultou em 0 peças; mantendo peça original da cor")
            sub_meshes = [target_piece.mesh]

        # 7. Reunir TODAS as peças (sub-peças da cor cortada + outras cores intactas)
        all_pieces_meshes: list[tuple[trimesh.Trimesh, str, int, str, bool]] = []

        # Sub-peças da cor cortada
        for i, sm in enumerate(sub_meshes):
            lbl = cut_inputs[i].label if i < len(cut_inputs) else f"Parte {i+1}"
            all_pieces_meshes.append((
                sm,
                target_piece.filament.color_hex,
                target_piece.extruder_index + 1,
                f"Extruder {target_piece.extruder_index + 1} - {lbl}",
                True,
            ))

        # Outras cores
        for p in split_result.pieces:
            if p is not target_piece:
                all_pieces_meshes.append((
                    p.mesh,
                    p.filament.color_hex,
                    p.extruder_index + 1,
                    f"Extruder {p.extruder_index + 1}",
                    False,
                ))

        # 8. Gerar arquivo .3MF UNIFICADO com TODAS as peças e TODAS as cores
        unified_3mf_bytes = write_plate_3mf_bytes(
            meshes=[m for m, _, _, _, _ in all_pieces_meshes],
            colors=[c for _, c, _, _, _ in all_pieces_meshes],
            model_name=f"{split_result.model_name}_completo",
            snap_to_floor=payload.snap_to_floor,
        )
        safe_model_name = sanitize_storage_key(split_result.model_name)
        unified_fname = f"{safe_model_name}_completo_todas_cores.3mf"
        unified_storage_path = f"pieces/{payload.user_id}/{model_id}/{unified_fname}"
        upload_bytes(supabase, unified_storage_path, unified_3mf_bytes, content_type="model/3mf")
        unified_url = create_download_url(supabase, unified_storage_path, expires_in=3600)

        # 9. Gerar arquivos individuais por peça e verificar se cabem na mesa
        plates_output: list[PlateOutput] = []
        oversized_count = 0

        for idx, (mesh_obj, color_hex, ext_num, label, is_sub) in enumerate(all_pieces_meshes):
            extents = [round(float(e), 1) for e in mesh_obj.extents]
            fits = (
                extents[0] <= plate_x
                and extents[1] <= plate_y
                and extents[2] <= plate_z
            )
            if not fits:
                oversized_count += 1

            # Upload individual .3mf
            indiv_bytes = write_plate_3mf_bytes(
                meshes=[mesh_obj],
                colors=[color_hex],
                model_name=f"{safe_model_name}_p{idx+1}",
                snap_to_floor=payload.snap_to_floor,
            )
            safe_color = color_hex.replace("#", "")
            safe_label = sanitize_storage_key(label)
            fname = f"{model_id}_{safe_label}_{safe_color}.3mf"
            indiv_path = f"pieces/{payload.user_id}/{model_id}/{fname}"
            upload_bytes(supabase, indiv_path, indiv_bytes, content_type="model/3mf")
            indiv_url = create_download_url(supabase, indiv_path, expires_in=3600)

            plates_output.append(PlateOutput(
                plate_number=idx + 1,
                extruder_number=ext_num,
                color_hex=color_hex,
                storage_path=indiv_path,
                download_url=indiv_url,
                fits_in_plate=fits,
                extents_mm=extents,
                label=label,
                is_subdivided=is_sub,
            ))

        logger.info(
            "Subdivisão concluída para modelo %s: %d peças geradas, %d oversized",
            model_id,
            len(plates_output),
            oversized_count,
        )

        return ColorSplitResponse(
            model_id=model_id,
            plates=plates_output,
            total_pieces=len(plates_output),
            oversized_count=oversized_count,
            unified_download_url=unified_url,
            unified_file_name=unified_fname,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Erro ao subdividir peça de cor para o modelo %s: %s", model_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Erro interno ao fatiar peça: {exc}",
        ) from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)

