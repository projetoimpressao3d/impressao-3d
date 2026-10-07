import logging
import trimesh
from .cutter import cut_mesh_by_planes, CutPlaneInput

logger = logging.getLogger(__name__)

def fit_to_plate(
    mesh: trimesh.Trimesh,
    plate_x: float,
    plate_y: float,
    plate_z: float,
) -> list[trimesh.Trimesh]:
    """
    Splits the mesh horizontally (perpendicular to Z) into equal halves 
    until all resulting pieces fit within the plate dimensions.
    Returns a list of meshes.
    """
    extents = mesh.extents
    fits = (
        extents[0] <= plate_x
        and extents[1] <= plate_y
        and extents[2] <= plate_z
    )
    if fits:
        return [mesh]
    
    logger.info(f"Piece is oversized: {extents}. Splitting horizontally...")
    
    # Split exactly in the middle of Z
    bounds = mesh.bounds
    mid_z = (bounds[0][2] + bounds[1][2]) / 2.0
    
    cut_plane = CutPlaneInput(
        normal=[0.0, 0.0, 1.0],
        origin=[0.0, 0.0, mid_z],
        label="Horizontal Split"
    )
    
    # We do a simple cut without connectors
    sub_meshes = cut_mesh_by_planes(
        mesh,
        [cut_plane],
        generate_connectors=False
    )
    
    if not sub_meshes or len(sub_meshes) <= 1:
        logger.warning("Horizontal split failed or returned 1 piece, stopping recursion.")
        return [mesh]
        
    result = []
    for m in sub_meshes:
        # Recursively fit each half
        result.extend(fit_to_plate(m, plate_x, plate_y, plate_z))
        
    return result
