import asyncio
import io
import json
import os
import shutil
import tempfile
from unittest.mock import MagicMock
import trimesh

from app.routers.color_split import subdivide_color_piece, _TASKS, SubdivideColorPieceRequest
import app.routers.color_split as cs

async def test_cumulative():
    print("=== INICIANDO TESTE DE SESSÃO CUMULATIVA MULTICOR ===")
    
    # Armazenamento em memória simulando Supabase Storage
    storage_store: dict[str, bytes] = {}

    def mock_upload_bytes(supabase, path, data, content_type="application/octet-stream"):
        storage_store[path] = data
        return path

    def mock_download_bytes_or_none(supabase, path):
        return storage_store.get(path, None)

    def mock_create_download_url(supabase, path, expires_in=3600):
        return f"https://mock-storage.local/{path}"

    async def mock_download(url, path):
        tmp = tempfile.mktemp(suffix=".3mf")
        shutil.copy("C:/Users/Fabricio/Downloads/Modelos 3D/charizard_cores.3mf", tmp)
        return tmp

    # Setup mocks
    cs.upload_bytes = mock_upload_bytes
    cs.download_bytes_or_none = mock_download_bytes_or_none
    cs.create_download_url = mock_create_download_url
    cs.download_to_tempfile = mock_download
    cs._fetch_model = lambda s, m, u: {"id": "charizard", "storage_path": "charizard_cores.3mf", "name": "Charizard", "user_id": "test_user"}
    cs._fetch_build_plate = lambda s, p, u: {"id": "mock_plate", "build_volume_x_mm": 100.0, "build_volume_y_mm": 100.0, "build_volume_z_mm": 100.0}

    # Inicializar manifesto vazio como split_model_by_color faria
    manifest_path = "pieces/test_user/charizard/session_manifest.json"
    storage_store[manifest_path] = json.dumps({"extruders": {}}).encode("utf-8")

    class MockBackgroundTasks:
        def add_task(self, func, **kwargs):
            self.func = func
            self.kwargs = kwargs

    supabase = MagicMock()

    # -------------------------------------------------------------
    # PASSO 1: Subdividir Extruder 2 (Barriga / Branco)
    # -------------------------------------------------------------
    print("\n--- PASSO 1: Fatiando Extruder 2 (Barriga) ---")
    payload_ext2 = SubdivideColorPieceRequest(
        build_plate_id="mock_plate",
        extruder_number=2,
        user_id="test_user",
        generate_connectors=True,
        connector_pin_shape="cylinder",
        connector_tolerance_mm=0.2,
        snap_to_floor=True
    )
    bg1 = MockBackgroundTasks()
    res1 = await subdivide_color_piece("charizard", payload_ext2, bg1, supabase, None)
    await bg1.func(**bg1.kwargs)

    t1_status = _TASKS[res1.task_id]
    assert t1_status["status"] == "completed", f"Passo 1 falhou: {t1_status.get('error')}"
    plates1 = t1_status["result"]["plates"]
    
    ext2_plates = [p for p in plates1 if p["extruder_number"] == 2]
    ext1_plates = [p for p in plates1 if p["extruder_number"] == 1]
    print(f"Extruder 2 gerou {len(ext2_plates)} subpeça(s):")
    for p in ext2_plates:
        print(f"  {p['label']} - {p['extents_mm']} mm - Cabe: {p['fits_in_plate']}")
    print(f"Extruder 1 permaneceu com {len(ext1_plates)} peça(s) intacta(s).")
    assert len(ext2_plates) >= 1, "Extruder 2 deveria ter gerado peças."

    # Verificar se o manifesto gravou Extruder 2
    assert manifest_path in storage_store, "Manifesto não foi salvo!"
    manifest_data = json.loads(storage_store[manifest_path].decode("utf-8"))
    print("Estado do manifesto após Passo 1:", list(manifest_data["extruders"].keys()))
    assert "2" in manifest_data["extruders"], "Extruder 2 deve estar registrado no manifesto!"

    # -------------------------------------------------------------
    # PASSO 2: Subdividir Extruder 1 (Corpo Laranja - peça grande)
    # -------------------------------------------------------------
    print("\n--- PASSO 2: Fatiando Extruder 1 (Corpo Laranja) ---")
    payload_ext1 = SubdivideColorPieceRequest(
        build_plate_id="mock_plate",
        extruder_number=1,
        user_id="test_user",
        generate_connectors=True,
        connector_pin_shape="hex",
        connector_tolerance_mm=0.2,
        snap_to_floor=True
    )
    bg2 = MockBackgroundTasks()
    res2 = await subdivide_color_piece("charizard", payload_ext1, bg2, supabase, None)
    await bg2.func(**bg2.kwargs)

    t2_status = _TASKS[res2.task_id]
    assert t2_status["status"] == "completed", f"Passo 2 falhou: {t2_status.get('error')}"
    plates2 = t2_status["result"]["plates"]

    ext1_step2 = [p for p in plates2 if p["extruder_number"] == 1]
    ext2_step2 = [p for p in plates2 if p["extruder_number"] == 2]

    print(f"Extruder 1 gerou {len(ext1_step2)} subpeças:")
    for p in ext1_step2:
        print(f"  {p['label']} - {p['extents_mm']} mm - Cabe: {p['fits_in_plate']}")
    
    print(f"\nExtruder 2 PRESERVADO na sessão cumulativa com {len(ext2_step2)} subpeças:")
    for p in ext2_step2:
        print(f"  {p['label']} - {p['extents_mm']} mm - Cabe: {p['fits_in_plate']}")

    # Asserções críticas da Sessão Cumulativa:
    assert len(ext1_step2) >= 5, f"Esperado >= 5 peças para Extruder 1, obteve {len(ext1_step2)}"
    assert len(ext2_step2) == len(ext2_plates), f"Extruder 2 perdeu subpeças! Tinha {len(ext2_plates)}, agora tem {len(ext2_step2)}"

    # Verificar manifesto final
    manifest_final = json.loads(storage_store[manifest_path].decode("utf-8"))
    print("\nEstado final do manifesto:", list(manifest_final["extruders"].keys()))
    assert "1" in manifest_final["extruders"] and "2" in manifest_final["extruders"], "Ambos extruders devem estar persistidos!"

    # Verificar o 3MF unificado final
    unified_keys = [k for k in storage_store.keys() if k.endswith("_completo_todas_cores.3mf")]
    assert len(unified_keys) > 0, f"3MF unificado não encontrado no storage! Chaves: {list(storage_store.keys())}"
    unified_path = unified_keys[-1]
    print(f"Caminho do 3MF unificado mais recente: {unified_path}")
    unified_bytes = storage_store[unified_path]
    print(f"\n3MF Unificado gerado com sucesso: {len(unified_bytes)} bytes")

    loaded_unified = trimesh.load(io.BytesIO(unified_bytes), file_type="3mf")
    if isinstance(loaded_unified, trimesh.Scene):
        total_geoms = len(loaded_unified.geometry)
    else:
        total_geoms = 1
    print(f"Total de geometrias no 3MF unificado: {total_geoms} (total de peças no modelo = {len(plates2)})")
    assert total_geoms == len(plates2), f"Geometrias no 3MF ({total_geoms}) != total de peças ({len(plates2)})"

    print("\n=== TODOS OS TESTES CUMULATIVOS PASSARAM COM SUCESSO! ===")

if __name__ == "__main__":
    asyncio.run(test_cumulative())
