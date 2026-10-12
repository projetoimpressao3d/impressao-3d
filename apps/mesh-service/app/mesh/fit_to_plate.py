import logging
import trimesh
import numpy as np
from .cutter import cut_mesh_by_planes, CutPlaneInput

logger = logging.getLogger(__name__)

def fit_to_plate(
    mesh: trimesh.Trimesh,
    plate_x: float,
    plate_y: float,
    plate_z: float,
    depth: int = 0,
    max_depth: int = 4,
) -> list[trimesh.Trimesh]:
    # Micro-estilhaços ou malhas degeneradas não devem ser cortados recursivamente
    if len(mesh.vertices) < 4 or len(mesh.faces) < 20:
        return [mesh]

    extents = mesh.extents
    
    fits = (
        extents[0] <= plate_x
        and extents[1] <= plate_y
        and extents[2] <= plate_z
    )
    if fits:
        return [mesh]
    
    if depth >= max_depth:
        logger.warning(
            "fit_to_plate atingiu profundidade máxima (%d >= %d) para peça com extents=%s. Interrompendo subdivisão.",
            depth,
            max_depth,
            extents,
        )
        return [mesh]

    logger.info(
        "Peça oversized (profundidade %d/%d): %s. Cortando no maior eixo...",
        depth,
        max_depth,
        extents,
    )
    
    # Encontrar o eixo com maior proporção de excesso
    ratios = [
        extents[0] / plate_x,
        extents[1] / plate_y,
        extents[2] / plate_z,
    ]
    max_axis = int(np.argmax(ratios))
    
    bounds = mesh.bounds
    mid_val = float((bounds[0][max_axis] + bounds[1][max_axis]) / 2.0)
    
    normal = [0.0, 0.0, 0.0]
    normal[max_axis] = 1.0
    
    origin = [0.0, 0.0, 0.0]
    origin[max_axis] = mid_val
    
    cut_plane = CutPlaneInput(
        normal=normal,
        origin=origin,
        label=f"Fit split axis {max_axis} (d={depth})",
    )
    
    sub_meshes = cut_mesh_by_planes(
        mesh,
        [cut_plane],
        generate_connectors=False,
    )
    
    if not sub_meshes or len(sub_meshes) <= 1:
        logger.warning("Split no eixo %d não gerou mais de 1 peça válida; interrompendo recursão.", max_axis)
        return [mesh]
        
    result = []
    for m in sub_meshes:
        if len(m.vertices) < 4 or len(m.faces) < 20:
            # Ignorar micro-estilhaços espúrios gerados pelo corte
            continue

        if m.extents[max_axis] >= extents[max_axis] * 0.98:
            logger.warning("Corte não reduziu significativamente o eixo %d; parando recursão nesta sub-peça.", max_axis)
            result.append(m)
        else:
            result.extend(
                fit_to_plate(
                    m,
                    plate_x,
                    plate_y,
                    plate_z,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            )
        
    return result if result else [mesh]

