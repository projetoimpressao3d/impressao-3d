import re

with open("C:/Users/Fabricio/Downloads/projeto-impressao-3d/apps/mesh-service/app/routers/color_split.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add BackgroundTasks
content = content.replace(
    "from fastapi import APIRouter, Depends, HTTPException, status",
    "from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks"
)

# 2. Add TASKS and endpoints
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

# 3. Rename subdivide_color_piece to _run_subdivide_task
old_signature = """@router.post(
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

new_signature = """@router.post(
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

content = content.replace(old_signature, new_signature)

# Now, we need to replace the return statement ONLY inside _run_subdivide_task.
# Let's split by "_run_subdivide_task"
parts = content.split("async def _run_subdivide_task(")
if len(parts) == 2:
    func_body = parts[1]
    
    # Replace return
    func_body = re.sub(
        r"return ColorSplitResponse\((.*?)\)",
        r"""res = ColorSplitResponse(\1)\n        _TASKS[task_id] = {"status": "completed", "result": res.model_dump()}\n        return""",
        func_body,
        flags=re.DOTALL
    )
    
    # Replace exception
    func_body = re.sub(
        r"except HTTPException:\s+raise\s+except Exception as exc:[\s\S]+?from exc\s+finally:\s+Path\(tmp_path\)\.unlink\(missing_ok=True\)",
        r"""except Exception as exc:
        logger.exception("Erro ao subdividir peça de cor para o modelo %s: %s", model_id, exc)
        _TASKS[task_id] = {"status": "failed", "error": str(exc)}
    finally:
        Path(tmp_path).unlink(missing_ok=True)""",
        func_body
    )
    
    content = parts[0] + "async def _run_subdivide_task(" + func_body

with open("C:/Users/Fabricio/Downloads/projeto-impressao-3d/apps/mesh-service/app/routers/color_split.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Done")
