import logging
import trimesh
import numpy as np

logger = logging.getLogger(__name__)

def find_boundary_loops(mesh: trimesh.Trimesh) -> list[list[int]]:
    if mesh.is_watertight:
        return []
    edges = mesh.edges_sorted
    unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    boundary_edges = unique_edges[counts == 1]
    if len(boundary_edges) == 0:
        return []
    boundary_directed = []
    for be in boundary_edges:
        u, v = be
        mask1 = (mesh.faces[:, 0] == u) & (mesh.faces[:, 1] == v)
        mask2 = (mesh.faces[:, 1] == u) & (mesh.faces[:, 2] == v)
        mask3 = (mesh.faces[:, 2] == u) & (mesh.faces[:, 0] == v)
        if np.any(mask1 | mask2 | mask3):
            boundary_directed.append((u, v))
        else:
            boundary_directed.append((v, u))
    if not boundary_directed:
        return []
    from collections import defaultdict
    adj = defaultdict(list)
    for u, v in boundary_directed:
        adj[u].append(v)
    visited_edges = set()
    loops: list[list[int]] = []
    for start_u, start_v in boundary_directed:
        if (start_u, start_v) in visited_edges:
            continue
        loop = [start_u]
        visited_edges.add((start_u, start_v))
        curr = start_v
        while curr != start_u:
            loop.append(curr)
            next_candidates = [n for n in adj[curr] if (curr, n) not in visited_edges]
            if not next_candidates:
                break
            next_v = next_candidates[0]
            visited_edges.add((curr, next_v))
            curr = next_v
        if curr == start_u and len(loop) >= 3:
            loops.append(loop)
    return loops

def _cap_loop_centroid(vertices: np.ndarray, loop: list[int]) -> tuple[np.ndarray, np.ndarray]:
    loop_verts = vertices[loop]
    centroid = loop_verts.mean(axis=0)
    n_existing = len(vertices)
    new_vertices = np.vstack([vertices, centroid[np.newaxis, :]])
    centroid_idx = n_existing
    n = len(loop)
    new_faces = []
    for i in range(n):
        v0 = loop[i]
        v1 = loop[(i + 1) % n]
        new_faces.append([v0, v1, centroid_idx])
    return new_vertices, np.array(new_faces, dtype=np.int32)

def _cap_loop_earcut(vertices: np.ndarray, loop: list[int]) -> tuple[np.ndarray, np.ndarray]:
    try:
        import mapbox_earcut as earcut
    except ImportError:
        return _cap_loop_centroid(vertices, loop)
    loop_verts = vertices[loop]
    centroid = loop_verts.mean(axis=0)
    n = len(loop)
    normal = np.zeros(3)
    for j in range(n):
        v0 = loop_verts[j]
        v1 = loop_verts[(j + 1) % n]
        normal[0] += (v0[1] - v1[1]) * (v0[2] + v1[2])
        normal[1] += (v0[2] - v1[2]) * (v0[0] + v1[0])
        normal[2] += (v0[0] - v1[0]) * (v0[1] + v1[1])
    norm_len = np.linalg.norm(normal)
    if norm_len < 1e-10:
        return _cap_loop_centroid(vertices, loop)
    normal /= norm_len
    u_axis = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(normal, u_axis)) > 0.9:
        u_axis = np.array([0.0, 1.0, 0.0])
    u_axis -= np.dot(u_axis, normal) * normal
    u_len = np.linalg.norm(u_axis)
    if u_len < 1e-10:
        return _cap_loop_centroid(vertices, loop)
    u_axis /= u_len
    v_axis = np.cross(normal, u_axis)
    pts_2d = np.column_stack([
        np.dot(loop_verts - centroid, u_axis),
        np.dot(loop_verts - centroid, v_axis),
    ]).astype(np.float64)
    rings = np.array([len(loop)], dtype=np.uint32)
    indices = earcut.triangulate_float64(pts_2d, rings)
    if len(indices) == 0:
        return _cap_loop_centroid(vertices, loop)
    loop_arr = np.array(loop, dtype=np.int32)
    new_faces = loop_arr[indices.reshape(-1, 3)]
    return vertices, new_faces

def cap_open_mesh(mesh: trimesh.Trimesh, method: str = "earcut", min_loop_length: int = 3) -> trimesh.Trimesh:
    loops = find_boundary_loops(mesh)
    if not loops:
        return mesh
    all_new_vertices = mesh.vertices.copy()
    all_new_faces = mesh.faces.copy()
    for i, loop in enumerate(loops):
        if len(loop) < min_loop_length:
            continue
        if method == "centroid":
            new_verts, new_faces = _cap_loop_centroid(all_new_vertices, loop)
        else:
            new_verts, new_faces = _cap_loop_earcut(all_new_vertices, loop)
        n_prev = len(all_new_vertices)
        if len(new_verts) > n_prev:
            all_new_vertices = new_verts
            all_new_faces = np.vstack([all_new_faces, new_faces])
        else:
            all_new_faces = np.vstack([all_new_faces, new_faces])
    capped = trimesh.Trimesh(vertices=all_new_vertices, faces=all_new_faces, process=True)
    try:
        trimesh.repair.fix_winding(capped)
        trimesh.repair.fix_normals(capped)
    except Exception:
        pass
    return capped

def close_color_piece(mesh: trimesh.Trimesh, method: str = "earcut") -> trimesh.Trimesh:
    mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces, process=True)
    if mesh.is_watertight:
        return mesh
    mesh = cap_open_mesh(mesh, method=method)
    try:
        trimesh.repair.fix_normals(mesh)
        trimesh.repair.fix_winding(mesh)
    except Exception:
        pass
    return mesh
