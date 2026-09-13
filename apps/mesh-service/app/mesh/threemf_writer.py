"""
threemf_writer.py -- Gera arquivos .3mf a partir de malhas trimesh.

Opcoes de posicionamento:
  snap_to_floor=True  -- encosta a peca em Z=0 (base da mesa)
  snap_to_floor=False -- mantem a posicao original (pode flutuar)
"""
from __future__ import annotations
import io, logging, zipfile
from pathlib import Path
import numpy as np
import trimesh

logger = logging.getLogger(__name__)

CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>"""

RELS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>"""


def _apply_snap_to_floor(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """
    Retorna uma copia da malha com a base encostada em Z=0.
    Translada Z por -min(z) para que o ponto mais baixo fique em Z=0.
    """
    min_z = float(mesh.vertices[:, 2].min())
    if abs(min_z) < 1e-6:
        return mesh
    translated = mesh.copy()
    translated.vertices[:, 2] -= min_z
    return translated


def _mesh_to_model_xml(
    meshes: list,
    colors: list,
    model_name: str = "model",
    snap_to_floor: bool = True,
) -> str:
    """
    Gera o XML 3D/3dmodel.model com um objeto por malha.
    snap_to_floor: Se True, encosta cada peca em Z=0.
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">',
        '<resources>',
    ]

    lines.append('<basematerials id="1">')
    for i, color in enumerate(colors):
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        lines.append(f'  <base name="Filament{i+1}" displaycolor="#{r:02X}{g:02X}{b:02X}FF"/>')
    lines.append('</basematerials>')

    for obj_id, (mesh, color) in enumerate(zip(meshes, colors), start=2):
        color_idx = colors.index(color) if color in colors else 0
        working_mesh = _apply_snap_to_floor(mesh) if snap_to_floor else mesh

        lines.append(f'<object id="{obj_id}" type="model" pid="1" pindex="{color_idx}">')
        lines.append('<mesh>')
        lines.append('<vertices>')
        for v in working_mesh.vertices:
            lines.append(f'  <vertex x="{v[0]:.6f}" y="{v[1]:.6f}" z="{v[2]:.6f}"/>')
        lines.append('</vertices>')
        lines.append('<triangles>')
        for f in working_mesh.faces:
            lines.append(f'  <triangle v1="{f[0]}" v2="{f[1]}" v3="{f[2]}"/>')
        lines.append('</triangles>')
        lines.append('</mesh>')
        lines.append('</object>')

    lines.append('</resources>')
    lines.append('<build>')
    for obj_id in range(2, 2 + len(meshes)):
        lines.append(f'  <item objectid="{obj_id}"/>')
    lines.append('</build>')
    lines.append('</model>')

    return '\n'.join(lines)


def write_plate_3mf(
    meshes: list,
    colors: list,
    output_path,
    model_name: str = "plate",
    snap_to_floor: bool = True,
):
    """Gera um arquivo .3mf com as malhas fornecidas."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    model_xml = _mesh_to_model_xml(meshes, colors, model_name, snap_to_floor=snap_to_floor)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        zf.writestr("_rels/.rels", RELS_XML)
        zf.writestr("3D/3dmodel.model", model_xml)
    logger.info(f"3MF gerado: {output_path} ({output_path.stat().st_size // 1024}KB)")
    return output_path


def write_plate_3mf_bytes(
    meshes: list,
    colors: list,
    model_name: str = "plate",
    snap_to_floor: bool = True,
) -> bytes:
    """
    Gera o .3mf em memoria (bytes) sem gravar em disco.
    snap_to_floor=True  -> encosta a peca na base Z=0
    snap_to_floor=False -> mantem posicao original
    """
    model_xml = _mesh_to_model_xml(meshes, colors, model_name, snap_to_floor=snap_to_floor)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        zf.writestr("_rels/.rels", RELS_XML)
        zf.writestr("3D/3dmodel.model", model_xml)
    return buf.getvalue()
