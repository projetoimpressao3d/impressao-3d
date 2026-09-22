"""
Capper: Fechamento de faces abertas em malhas separadas por cor.

Quando separamos faces por cor de um 3MF, cada peca fica com buracos
nas fronteiras com as outras pecas. Este modulo fecha esses buracos
triangulando os contornos de borda (boundary loops).

Algoritmos disponiveis:
1. Centroid Cap (rapido): fan de triangulos a partir do centroide do loop.
2. Earcut (melhor qualidade): triangulacao 2D via projecao no plano normal medio.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import trimesh
import trimesh.graph

logger = logging.getLogger(__name__)


def find_boundary_loops(mesh: trimesh.Trimesh) -> list[list[int]]:
    """
    Encontra todos os loops de borda aberta na malha usando arestas dirigidas.
    Garante loops perfeitamente orientados (winding consistente com o perímetro da malha).
    """
    face_edges = []
    for f in mesh.faces:
        face_edges.append((int(f[0]), int(f[1])))
        face_edges.append((int(f[1]), int(f[2])))
        face_edges.append((int(f[2]), int(f[0])))

    # Contagem de arestas não-orientadas
    edge_counts: dict[tuple[int, int], int] = {}
    for u, v in face_edges:
        key = (min(u, v), max(u, v))
        edge_counts[key] = edge_counts.get(key, 0) + 1

    # Arestas de borda são as que pertencem a apenas 1 face
    boundary_directed = []
    for u, v in face_edges:
        key = (min(u, v), max(u, v))
        if edge_counts[key] == 1:
            boundary_directed.append((u, v))

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
    """
    Fecha um loop criando um vertice no centroide e triangulos em leque.
    Rapido mas pode gerar triangulos alongados para loops grandes.
    """
    loop_verts = vertices[loop]
    centroid = loop_verts.mean(axis=0)

    n_existing = len(vertices)
    # Novo vertice (centroide)
    new_vertices = np.vstack([vertices, centroid[np.newaxis, :]])
    centroid_idx = n_existing

    # Triangulos em leque: (loop[i], loop[i+1], centroid)
    n = len(loop)
    new_faces = []
    for i in range(n):
        v0 = loop[i]
        v1 = loop[(i + 1) % n]
        new_faces.append([v0, v1, centroid_idx])

    return new_vertices, np.array(new_faces, dtype=np.int32)


def _cap_loop_earcut(vertices: np.ndarray, loop: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """
    Fecha um loop projetando no plano da normal media e triangulando com earcut.
    Qualidade superior ao centroid cap para loops complexos e multiplos.
    """
    try:
        import mapbox_earcut as earcut
    except ImportError:
        logger.warning("mapbox_earcut nao instalado, usando centroid cap")
        return _cap_loop_centroid(vertices, loop)

    loop_verts = vertices[loop]
    centroid = loop_verts.mean(axis=0)
    n = len(loop)

    # Calcular normal do loop via método de Newell
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

    # Base ortonormal no plano do loop
    u_axis = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(normal, u_axis)) > 0.9:
        u_axis = np.array([0.0, 1.0, 0.0])
    u_axis -= np.dot(u_axis, normal) * normal
    u_len = np.linalg.norm(u_axis)
    if u_len < 1e-10:
        return _cap_loop_centroid(vertices, loop)
    u_axis /= u_len
    v_axis = np.cross(normal, u_axis)

    # Projetar vertices no plano 2D com shape (N, 2)
    pts_2d = np.column_stack([
        np.dot(loop_verts - centroid, u_axis),
        np.dot(loop_verts - centroid, v_axis),
    ]).astype(np.float64)

    # Triangular com earcut
    rings = np.array([len(loop)], dtype=np.uint32)
    indices = earcut.triangulate_float64(pts_2d, rings)

    if len(indices) == 0:
        return _cap_loop_centroid(vertices, loop)

    # Reconstruir faces com indices originais do loop
    loop_arr = np.array(loop, dtype=np.int32)
    new_faces = loop_arr[indices.reshape(-1, 3)]

    return vertices, new_faces


def cap_open_mesh(
    mesh: trimesh.Trimesh,
    method: str = "earcut",
    min_loop_length: int = 3,
) -> trimesh.Trimesh:
    """
    Fecha todos os buracos de borda aberta na malha.

    Args:
        mesh: Malha possivelmente aberta (open mesh).
        method: "earcut" (padrao, alta qualidade) ou "centroid".
        min_loop_length: Loops com menos vertices sao ignorados.

    Returns:
        Nova malha com buracos fechados (potencialmente watertight).
    """
    loops = find_boundary_loops(mesh)
    if not loops:
        logger.info("Malha ja e watertight — nenhum buraco encontrado")
        return mesh

    logger.info(f"Fechando {len(loops)} loops de borda...")

    all_new_vertices = mesh.vertices.copy()
    all_new_faces = mesh.faces.copy()

    for i, loop in enumerate(loops):
        if len(loop) < min_loop_length:
            continue

        if method == "centroid":
            new_verts, new_faces = _cap_loop_centroid(all_new_vertices, loop)
        else:
            new_verts, new_faces = _cap_loop_earcut(all_new_vertices, loop)

        # Offset das faces novas para os novos indices de vertices
        n_prev = len(all_new_vertices)
        if len(new_verts) > n_prev:
            all_new_vertices = new_verts
            all_new_faces = np.vstack([all_new_faces, new_faces])
        else:
            all_new_faces = np.vstack([all_new_faces, new_faces])

    capped = trimesh.Trimesh(
        vertices=all_new_vertices,
        faces=all_new_faces,
        process=True,  # Reparar orientacao de normais
    )

    try:
        trimesh.repair.fix_winding(capped)
        trimesh.repair.fix_normals(capped)
    except Exception as e:
        logger.warning(f"Erro ao reparar malha capped: {e}")

    logger.info(
        f"Malha fechada: {len(capped.vertices)} verts, {len(capped.faces)} faces, "
        f"watertight={capped.is_watertight}"
    )
    return capped


def close_color_piece(
    mesh: trimesh.Trimesh,
    method: str = "earcut",
) -> trimesh.Trimesh:
    """
    Pipeline completo para preparar uma peca colorida para impressao:
    1. Remove geometria degenerada
    2. Fecha buracos com Earcut
    3. Fixa normais e winding
    """
    # Passo 1: Limpar degenerados
    mesh = trimesh.Trimesh(
        vertices=mesh.vertices,
        faces=mesh.faces,
        process=True,
    )

    if mesh.is_watertight:
        logger.info("Peca ja e watertight")
        return mesh

    # Passo 2: Fechar buracos
    mesh = cap_open_mesh(mesh, method=method)

    # Passo 3: Tentar reparar normais
    try:
        trimesh.repair.fix_normals(mesh)
        trimesh.repair.fix_winding(mesh)
    except Exception as e:
        logger.warning(f"Erro ao reparar normais: {e}")

    return mesh
