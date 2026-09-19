"""
Motor de separacao de malhas 3MF por cor -- suporta dois formatos:

A) "painted" -- paint_color por triangulo (Charizard / AMS painting)
B) "multi_object" -- objetos separados por extruder (Majin Buu / NO AMS)
"""
from __future__ import annotations
import logging, re, zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import numpy as np
import trimesh

logger = logging.getLogger(__name__)

RE_VERTEX       = re.compile(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"')
RE_TRIANGLE     = re.compile(r'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"(?:[^>]*paint_color="([0-9A-Fa-f]+)")?')
RE_FILAMENT_CLR = re.compile(r'"filament_colour"\s*:\s*\[([^\]]+)\]')
RE_HEX_COLOR    = re.compile(r'"(#[0-9A-Fa-f]{6})"')
RE_PART         = re.compile(r'<part id="(\d+)"[^>]*>([\s\S]*?)</part>')
RE_PART_EXT     = re.compile(r'key="extruder" value="(\d+)"')
RE_PART_NAME    = re.compile(r'key="name" value="([^"]+)"')
RE_COMPONENT    = re.compile(r'objectid="(\d+)"[^>]*transform="([^"]+)"')
RE_OBJECT_BLOCK = re.compile(r'<object id="(\d+)"[^>]*>([\s\S]*?)</object>')


@dataclass
class FilamentInfo:
    extruder_index: int      # 0-based
    color_hex: str
    face_count: int = 0
    part_names: list = field(default_factory=list)


@dataclass
class ColorPiece:
    extruder_index: int
    filament: FilamentInfo
    mesh: trimesh.Trimesh
    is_watertight: bool = False


@dataclass
class ColorSplitResult:
    pieces: list
    filaments: list
    total_faces: int
    model_name: str = "model"
    method: str = "painted"


def _paint_color_to_extruder(pc_str: str | None, use_new_format: bool = False) -> int:
    """
    Decodifica paint_color -> índice de extrusor 0-based.

    Dois formatos suportados:
      - Formato antigo (decimal): valores como "4", "16", "64"
        Fórmula: max(0, bit_position_do_menor_bit - 1)
      - Formato novo Bambu hex: valores como "4", "8", "3C", "1C"
        Fórmula: bit_position_do_menor_bit + 1
        Detectado quando o arquivo contém paint_color com chars A-F.
    """
    if not pc_str:
        return 0
    val = int(pc_str, 16)   # sempre parsear como hex (valores decimais puros são iguais)
    if val == 0:
        return 0
    trailing = (val & -val).bit_length() - 1   # posição do bit mais baixo (0-indexed)
    if use_new_format:
        return trailing + 1   # Bambu hex: bit_position + 1
    return max(0, trailing - 1)   # formato antigo


def _read_filament_colors(zip_file: zipfile.ZipFile) -> list:
    try:
        if "Metadata/project_settings.config" not in zip_file.namelist():
            return []
        content = zip_file.read("Metadata/project_settings.config").decode("utf-8", errors="replace")
        match = RE_FILAMENT_CLR.search(content)
        if not match:
            return []
        return RE_HEX_COLOR.findall(match.group(1))
    except Exception as e:
        logger.warning(f"Nao foi possivel ler filament_colour: {e}")
        return []


def _find_object_model_path(zip_file: zipfile.ZipFile):
    for name in zip_file.namelist():
        if name.startswith("3D/Objects/") and name.endswith(".model"):
            return name
    if "3D/3dmodel.model" in zip_file.namelist():
        return "3D/3dmodel.model"
    return None


def _detect_method(obj_content: str, model_settings) -> str:
    if model_settings:
        has_parts    = '<part id=' in model_settings
        has_extruder = 'key="extruder"' in model_settings
        if has_parts and has_extruder:
            # Verificar paint_color no conteúdo inteiro — não apenas nos primeiros 50KB,
            # pois o XML tem megabytes de vértices antes da seção de triângulos.
            if 'paint_color="' not in obj_content:
                return "multi_object"
    return "painted"


def _apply_transform(x, y, z, t):
    return (
        t[0]*x + t[1]*y + t[2]*z + t[9],
        t[3]*x + t[4]*y + t[5]*z + t[10],
        t[6]*x + t[7]*y + t[8]*z + t[11],
    )


def _parse_painted(content: str, filament_colors: list) -> ColorSplitResult:
    logger.info("Formato: painted (paint_color por triangulo)")

    # Detectar formato Bambu hex (tem chars A-F nos valores de paint_color)
    use_new_format = bool(re.search(r'paint_color="[0-9]*[A-Fa-f][0-9A-Fa-f]*"', content))
    if use_new_format:
        logger.info("  Detectado formato Bambu hex (paint_color com chars A-F)")

    vertex_matches = RE_VERTEX.findall(content)
    vertices = np.array([[float(x), float(y), float(z)] for x, y, z in vertex_matches], dtype=np.float64)

    triangle_matches = RE_TRIANGLE.findall(content)
    groups = {}
    face_indices_by_ext = []

    for v1, v2, v3, pc_str in triangle_matches:
        ext = _paint_color_to_extruder(pc_str if pc_str else None, use_new_format)
        groups.setdefault(ext, []).append((int(v1), int(v2), int(v3)))
        face_indices_by_ext.append(ext)

    total_faces = len(triangle_matches)
    logger.info(f"  {total_faces} triangulos em {len(groups)} grupos")

    filaments = []
    for ext_idx in sorted(groups.keys()):
        color = filament_colors[ext_idx] if ext_idx < len(filament_colors) else "#808080"
        filaments.append(FilamentInfo(extruder_index=ext_idx, color_hex=color, face_count=len(groups[ext_idx])))

    pieces = []
    face_arr = np.array(face_indices_by_ext, dtype=np.int32)

    for fi in filaments:
        ext_idx = fi.extruder_index
        faces_orig = np.array(groups[ext_idx], dtype=np.int32)
        unique_verts, inverse = np.unique(faces_orig.ravel(), return_inverse=True)
        sub_verts = vertices[unique_verts]
        sub_faces = inverse.reshape(-1, 3)
        mesh = trimesh.Trimesh(vertices=sub_verts, faces=sub_faces, process=False)
        pieces.append(ColorPiece(extruder_index=ext_idx, filament=fi, mesh=mesh, is_watertight=mesh.is_watertight))

    return ColorSplitResult(pieces=pieces, filaments=filaments, total_faces=total_faces, method="painted")


def _parse_multi_object(obj_content, root_content, model_settings, filament_colors) -> ColorSplitResult:
    logger.info("Formato: multi_object (objetos separados por extruder)")

    part_extruder = {}
    part_name = {}
    for pm in RE_PART.finditer(model_settings):
        pid, body = pm.group(1), pm.group(2)
        em = RE_PART_EXT.search(body)
        nm = RE_PART_NAME.search(body)
        if em:
            part_extruder[pid] = int(em.group(1)) - 1
        if nm:
            part_name[pid] = nm.group(1)

    transforms = {}
    for cm in RE_COMPONENT.finditer(root_content):
        oid, tstr = cm.group(1), cm.group(2)
        vals = [float(v) for v in tstr.strip().split()]
        if len(vals) == 12:
            transforms[oid] = vals

    positions_by_ext = {}
    names_by_ext = {}
    total_faces = 0

    for om in RE_OBJECT_BLOCK.finditer(obj_content):
        obj_id, block = om.group(1), om.group(2)
        ext_idx = part_extruder.get(obj_id, 0)
        transform = transforms.get(obj_id)
        name = part_name.get(obj_id)

        verts = [(float(m[0]), float(m[1]), float(m[2])) for m in RE_VERTEX.findall(block)]
        if transform:
            verts = [_apply_transform(x, y, z, transform) for x, y, z in verts]

        tris = [(int(m[0]), int(m[1]), int(m[2])) for m in RE_TRIANGLE.findall(block)]
        if not tris:
            continue

        total_faces += len(tris)
        positions_by_ext.setdefault(ext_idx, [])
        names_by_ext.setdefault(ext_idx, [])

        # ── Snap Z por objeto individual ─────────────────────────────────────
        # Cada part id separado recebe seu proprio snap Z=0.
        # Aneis, maos, pes, cinto — cada um senta independentemente no chao.
        # Isso replica o comportamento do Split3mf.
        if verts:
            min_z = min(v[2] for v in verts)
            if abs(min_z) > 1e-6:
                verts = [(x, y, z - min_z) for x, y, z in verts]
        # ─────────────────────────────────────────────────────────────────────

        for v1, v2, v3 in tris:
            for vi in (v1, v2, v3):
                if vi < len(verts):
                    positions_by_ext[ext_idx].extend(verts[vi])

        if name:
            names_by_ext[ext_idx].append(name)


    logger.info(f"  {total_faces} triangulos em {len(positions_by_ext)} grupos")

    filaments = []
    pieces = []
    for ext_idx in sorted(positions_by_ext.keys()):
        raw = positions_by_ext[ext_idx]
        color = filament_colors[ext_idx] if ext_idx < len(filament_colors) else "#808080"
        n_verts = len(raw) // 3
        n_faces = n_verts // 3

        fi = FilamentInfo(
            extruder_index=ext_idx,
            color_hex=color,
            face_count=n_faces,
            part_names=names_by_ext.get(ext_idx, []),
        )
        filaments.append(fi)

        verts_arr = np.array(raw, dtype=np.float64).reshape(-1, 3)
        faces_arr = np.arange(n_verts, dtype=np.int32).reshape(-1, 3)
        mesh = trimesh.Trimesh(vertices=verts_arr, faces=faces_arr, process=False)
        pieces.append(ColorPiece(extruder_index=ext_idx, filament=fi, mesh=mesh, is_watertight=mesh.is_watertight))
        logger.info(f"  Ext {ext_idx+1} ({color}): {n_faces} faces")

    return ColorSplitResult(pieces=pieces, filaments=filaments, total_faces=total_faces, method="multi_object")


def parse_3mf_colors(threemf_path) -> ColorSplitResult:
    threemf_path = Path(threemf_path)
    logger.info(f"Lendo arquivo 3MF: {threemf_path.name}")

    with zipfile.ZipFile(threemf_path, "r") as z:
        filament_colors = _read_filament_colors(z)
        model_path = _find_object_model_path(z)
        if not model_path:
            raise ValueError("Arquivo .3mf nao contem geometria 3D valida")

        obj_content    = z.read(model_path).decode("utf-8", errors="replace")
        root_content   = z.read("3D/3dmodel.model").decode("utf-8", errors="replace") if "3D/3dmodel.model" in z.namelist() else ""
        model_settings = z.read("Metadata/model_settings.config").decode("utf-8", errors="replace") if "Metadata/model_settings.config" in z.namelist() else None

    method = _detect_method(obj_content, model_settings)
    logger.info(f"Metodo detectado: {method}")

    if method == "multi_object" and model_settings and root_content:
        result = _parse_multi_object(obj_content, root_content, model_settings, filament_colors)
    else:
        result = _parse_painted(obj_content, filament_colors)

    result.model_name = threemf_path.stem
    return result


def get_color_info(threemf_path) -> dict:
    """
    Versao leve: retorna metadados de cor sem parsear toda a geometria.
    Suporta ambos os formatos (painted e multi_object).
    """
    threemf_path = Path(threemf_path)

    with zipfile.ZipFile(threemf_path, "r") as z:
        filament_colors = _read_filament_colors(z)
        model_path = _find_object_model_path(z)
        if not model_path:
            return {"filaments": [], "total_faces": 0, "is_painted": False, "method": "unknown"}

        obj_content    = z.read(model_path).decode("utf-8", errors="replace")
        model_settings = z.read("Metadata/model_settings.config").decode("utf-8", errors="replace") if "Metadata/model_settings.config" in z.namelist() else None

    method = _detect_method(obj_content, model_settings)

    if method == "multi_object" and model_settings:
        part_extruder = {}
        for pm in RE_PART.finditer(model_settings):
            pid, body = pm.group(1), pm.group(2)
            em = RE_PART_EXT.search(body)
            if em:
                part_extruder[pid] = int(em.group(1)) - 1

        counter = {}
        for om in RE_OBJECT_BLOCK.finditer(obj_content):
            oid, block = om.group(1), om.group(2)
            ext = part_extruder.get(oid, 0)
            n = block.count("<triangle ")
            counter[ext] = counter.get(ext, 0) + n

        total = sum(counter.values())
        filaments_out = []
        for ext_idx, count in sorted(counter.items()):
            color = filament_colors[ext_idx] if ext_idx < len(filament_colors) else "#808080"
            filaments_out.append({
                "index": ext_idx,
                "extruder_number": ext_idx + 1,
                "color_hex": color,
                "face_count": count,
                "face_percentage": round(count / total * 100, 1) if total > 0 else 0,
            })
        return {
            "filaments": filaments_out,
            "total_faces": total,
            "is_painted": True,
            "method": "multi_object",
        }

    # painted
    use_new_format = bool(re.search(r'paint_color="[0-9]*[A-Fa-f][0-9A-Fa-f]*"', obj_content))
    triangle_matches = RE_TRIANGLE.findall(obj_content)
    total = len(triangle_matches)
    counter_a = {}
    for _, _, _, pc_str in triangle_matches:
        idx = _paint_color_to_extruder(pc_str if pc_str else None, use_new_format)
        counter_a[idx] = counter_a.get(idx, 0) + 1

    filaments_out = []
    for ext_idx, count in sorted(counter_a.items()):
        color = filament_colors[ext_idx] if ext_idx < len(filament_colors) else "#808080"
        filaments_out.append({
            "index": ext_idx,
            "extruder_number": ext_idx + 1,
            "color_hex": color,
            "face_count": count,
            "face_percentage": round(count / total * 100, 1) if total > 0 else 0,
        })

    return {
        "filaments": filaments_out,
        "total_faces": total,
        "is_painted": len(counter_a) > 1,
        "method": "painted",
    }
