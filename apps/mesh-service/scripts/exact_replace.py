import sys

with open("C:/Users/Fabricio/Downloads/projeto-impressao-3d/apps/mesh-service/app/routers/color_split.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. BackgroundTasks
content = content.replace(
    "from fastapi import APIRouter, Depends, HTTPException, status",
    "from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks"
)

# 2. _TASKS and TaskResponse
tasks_code = """
import uuid
import asyncio

_TASKS: dict[str, dict] = {}

class TaskResponse(BaseModel):
    task_id: str

@router.get("/tasks/{task_id}", summary="Check task status")
async def get_task_status(
    task_id: str,
    _auth: None = Depends(verify_internal_token),
):
    if task_id not in _TASKS:
        raise HTTPException(status_code=404, detail="Task not found")
    return _TASKS[task_id]
"""

content = content.replace("class ColorSplitResponse(BaseModel):", tasks_code + "\nclass ColorSplitResponse(BaseModel):")

# 3. Rename subdivide_color_piece and insert new one
old_sig = """@router.post(
    "/{model_id}/subdivide-piece",
    response_model=ColorSplitResponse,
    summary="Subdividir peça oversized preservando todas as cores em 3MF unificado",
)
async def subdivide_color_piece(
    model_id: str,
    payload: SubdivideColorPieceRequest,
    supabase: Client = Depends(get_supabase_client),
    _auth: None = Depends(verify_internal_token),
) -> ColorSplitResponse:"""

new_sig = """@router.post(
    "/{model_id}/subdivide-piece",
    response_model=TaskResponse,
    summary="Subdividir peça oversized (assíncrono)",
)
async def subdivide_color_piece(
    model_id: str,
    payload: SubdivideColorPieceRequest,
    background_tasks: BackgroundTasks,
    supabase: Client = Depends(get_supabase_client),
    _auth: None = Depends(verify_internal_token),
) -> TaskResponse:
    task_id = str(uuid.uuid4())
    _TASKS[task_id] = {"status": "processing", "progress": 0}
    
    background_tasks.add_task(
        _run_subdivide_task,
        task_id=task_id,
        model_id=model_id,
        payload=payload,
        supabase=supabase,
    )
    return TaskResponse(task_id=task_id)

async def _run_subdivide_task(
    task_id: str,
    model_id: str,
    payload: SubdivideColorPieceRequest,
    supabase: Client,
):"""

content = content.replace(old_sig, new_sig)

# 4. Replace return block (we can just replace the whole text block)
old_ret = """        return ColorSplitResponse(
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
        ) from exc"""

new_ret = """        res = ColorSplitResponse(
            model_id=model_id,
            plates=plates_output,
            total_pieces=len(plates_output),
            oversized_count=oversized_count,
            unified_download_url=unified_url,
            unified_file_name=unified_fname,
        )
        _TASKS[task_id] = {"status": "completed", "result": res.model_dump()}
        return

    except Exception as exc:
        logger.exception("Erro ao subdividir peça de cor para o modelo %s: %s", model_id, exc)
        _TASKS[task_id] = {"status": "failed", "error": str(exc)}"""

content = content.replace(old_ret, new_ret)

# 5. Add fit_to_plate logic
old_fallback = """        if not sub_meshes:
            logger.warning("Corte resultou em 0 peças; mantendo peça original da cor")
            sub_meshes = [target_piece.mesh]"""

new_fallback = """        if not sub_meshes:
            raise RuntimeError("O corte não gerou peças.")
            
        from app.mesh.fit_to_plate import fit_to_plate
        final_sub_meshes = []
        for sm in sub_meshes:
            final_sub_meshes.extend(fit_to_plate(sm, plate_x, plate_y, plate_z))
        sub_meshes = final_sub_meshes"""

content = content.replace(old_fallback, new_fallback)

with open("C:/Users/Fabricio/Downloads/projeto-impressao-3d/apps/mesh-service/app/routers/color_split.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Done exact replace")
