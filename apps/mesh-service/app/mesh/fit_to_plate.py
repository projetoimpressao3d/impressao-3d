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
) -> list[trimesh.Trimesh]:
    extents = mesh.extents
    
    fits = (
        extents[0] <= plate_x
        and extents[1] <= plate_y
        and extents[2] <= plate_z
    )
    if fits:
        return [mesh]
    
    logger.info(f"Piece is oversized: {extents}. Splitting along largest oversized axis...")
    
    # Find the axis that is most oversized relative to the plate
    ratios = [
        extents[0] / plate_x,
        extents[1] / plate_y,
        extents[2] / plate_z,
    ]
    max_axis = np.argmax(ratios)
    
    bounds = mesh.bounds
    mid_val = (bounds[0][max_axis] + bounds[1][max_axis]) / 2.0
    
    normal = [0.0, 0.0, 0.0]
    normal[max_axis] = 1.0
    
    origin = [0.0, 0.0, 0.0]
    origin[max_axis] = mid_val
    
    cut_plane = CutPlaneInput(
        normal=normal,
        origin=origin,
        label=f"Fit split axis {max_axis}"
    )
    
    # We do a simple cut without connectors
    sub_meshes = cut_mesh_by_planes(
        mesh,
        [cut_plane],
        generate_connectors=False
    )
    
    if not sub_meshes or len(sub_meshes) <= 1:
        logger.warning(f"Split along axis {max_axis} failed or returned 1 piece, stopping recursion.")
        return [mesh]
        
    result = []
    for m in sub_meshes:
        # Prevent infinite recursion if the extent along the cut axis didn't actually decrease
        # This shouldn't happen for a mid-cut, but floating point math/thin meshes might cause it
        if m.extents[max_axis] >= extents[max_axis] * 0.99:
            logger.warning("Cut did not significantly reduce size, stopping recursion.")
            result.append(m)
        else:
            result.extend(fit_to_plate(m, plate_x, plate_y, plate_z))
        
    return result
