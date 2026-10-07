import asyncio
import os
from unittest.mock import MagicMock
from app.routers.color_split import subdivide_color_piece, _TASKS
from app.routers.color_split import SubdivideColorPieceRequest

async def main():
    payload = SubdivideColorPieceRequest(
        build_plate_id="mock",
        extruder_number=1, # Orange is 0-indexed, so it's extruder_number 1
        user_id="test",
        mode="character",
        character_template="creature",
        general_granularity="auto",
        structural_sensitivity=0.05,
        generate_connectors=True,
        connector_pin_shape="hex",
        connector_tolerance_mm=0.2,
        snap_to_floor=True
    )
    
    # Mocking FastAPI dependencies and Supabase
    class MockBackgroundTasks:
        def add_task(self, func, **kwargs):
            self.func = func
            self.kwargs = kwargs
            
    background = MockBackgroundTasks()
    
    # Mock supabase to provide the mock build plate and model
    supabase = MagicMock()
    
    supabase.table().select().eq().eq().single().execute.side_effect = [
        # Model fetch
        MagicMock(data={"id": "charizard", "storage_path": "test.3mf", "name": "Charizard", "user_id": "test"}),
        # Plate fetch
        MagicMock(data={"id": "mock", "build_volume_x_mm": 100, "build_volume_y_mm": 100, "build_volume_z_mm": 100})
    ]
    
    supabase.storage.from_().create_signed_url.return_value = {"signedURL": "file://C:/Users/Fabricio/Downloads/Modelos 3D/charizard_cores.3mf"}
    
    # Run the route
    res = await subdivide_color_piece(
        model_id="charizard",
        payload=payload,
        background_tasks=background,
        supabase=supabase,
        _auth=None
    )
    
    task_id = res.task_id
    print(f"Task started: {task_id}")
    
    # Run background task synchronously
    from app.routers.color_split import _run_subdivide_task
    import app.routers.color_split as cs
    
    # Monkeypatch download to just use the local file
    async def mock_download(url, path):
        import shutil
        import tempfile
        tmp = tempfile.mktemp(suffix=".3mf")
        shutil.copy("C:/Users/Fabricio/Downloads/Modelos 3D/charizard_cores.3mf", tmp)
        return tmp
    
    cs.download_to_tempfile = mock_download
    
    await background.func(**background.kwargs)
    
    status = _TASKS[task_id]
    if status["status"] == "failed":
        print("Task failed:", status["error"])
        assert False, status["error"]
        
    result = status["result"]
    print("Task completed successfully!")
    
    plates = result["plates"]
    
    # Verify orange pieces (extruder_number 1)
    orange_pieces = [p for p in plates if p["extruder_number"] == 1]
    print(f"Number of orange pieces: {len(orange_pieces)}")
    assert len(orange_pieces) >= 5, f"Expected >= 5 orange pieces, got {len(orange_pieces)}"
    
    for p in plates:
        extents = p["extents_mm"]
        assert extents[0] <= 100 and extents[1] <= 100 and extents[2] <= 100, f"Piece {p['label']} oversized: {extents}"
        # Watertight isn't in output, but we could check
    
    print("All assertions passed!")

if __name__ == "__main__":
    asyncio.run(main())
