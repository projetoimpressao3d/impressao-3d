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
    generate_connectors: bool = True,
    connector_tolerance_mm: float = 0.2,
    connector_pin_shape: str = "hex",
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
    axis_names = ["X", "Y", "Z"]
    
    bounds = mesh.bounds
    b_min = float(bounds[0][max_axis])
    b_max = float(bounds[1][max_axis])
    length = b_max - b_min
    
    # Janela central balanceada: 0.35 a 0.65 do comprimento (proíbe corte de pontas)
    test_positions = np.linspace(b_min + 0.35 * length, b_min + 0.65 * length, 9)
    best_pos = b_min + 0.50 * length
    min_perimeter = float("inf")
    
    normal = [0.0, 0.0, 0.0]
    normal[max_axis] = 1.0
    
    # Varredura de seções transversais para encontrar a menor área/perímetro (cintura)
    for pos in test_positions:
        orig = [0.0, 0.0, 0.0]
        orig[max_axis] = float(pos)
        try:
            lines = trimesh.intersections.mesh_plane(mesh, plane_normal=normal, plane_origin=orig)
            if lines is not None and len(lines) > 0:
                seg_lengths = np.sum(np.linalg.norm(lines[:, 0] - lines[:, 1], axis=1))
                if seg_lengths < min_perimeter:
                    min_perimeter = float(seg_lengths)
                    best_pos = float(pos)
        except Exception:
            pass

    origin = [0.0, 0.0, 0.0]
    origin[max_axis] = best_pos
    
    cut_plane = CutPlaneInput(
        normal=normal,
        origin=origin,
        label=f"Bisseção {axis_names[max_axis]}-{depth+1}",
    )
    
    sub_meshes = cut_mesh_by_planes(
        mesh,
        [cut_plane],
        generate_connectors=generate_connectors,
        connector_tolerance_mm=connector_tolerance_mm,
        connector_pin_shape=connector_pin_shape,
    )
    
    if not sub_meshes or len(sub_meshes) <= 1:
        logger.warning("Split no eixo %s não gerou mais de 1 peça válida; interrompendo recursão.", axis_names[max_axis])
        return [mesh]
        
    result = []
    for idx, m in enumerate(sub_meshes):
        if len(m.vertices) < 4 or len(m.faces) < 20:
            # Ignorar micro-estilhaços espúrios gerados pelo corte
            continue

        m.metadata["label"] = f"Parte {axis_names[max_axis]}_{idx+1}"

        if m.extents[max_axis] >= extents[max_axis] * 0.98:
            logger.warning("Corte não reduziu significativamente o eixo %s; parando recursão nesta sub-peça.", axis_names[max_axis])
            result.append(m)
        else:
            result.extend(
                fit_to_plate(
                    m,
                    plate_x,
                    plate_y,
                    plate_z,
                    generate_connectors=generate_connectors,
                    connector_tolerance_mm=connector_tolerance_mm,
                    connector_pin_shape=connector_pin_shape,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            )
        
    return result if result else [mesh]


