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
    Encontra todos os loops de borda aberta na malha.
    Retorna lista de loops, onde cada loop e uma lista ordenada de indices de vertices.
    """
    # Encontrar arestas de borda (aresta referenciada por apenas uma face)
    edges = mesh.edges_sorted
    # Arestas unicas e seus counts
    unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    boundary_edges = unique_edges[counts == 1]

    if len(boundary_edges) == 0:
        return []

    # Construir grafo de adjacencia das arestas de borda
    adjacency: dict[int, list[int]] = {}
    for e in boundary_edges:
        v0, v1 = int(e[0]), int(e[1])
        adjacency.setdefault(v0, []).append(v1)
        adjacency.setdefault(v1, []).append(v0)

    # Tracar loops percorrendo o grafo
    visited_vertices: set[int] = set()
    loops: list[list[int]] = []

    for start_v in adjacency:
        if start_v in visited_vertices:
            continue
        loop = [start_v]
        visited_vertices.add(start_v)
        current = start_v
        prev = -1

        while True:
            neighbors = [n for n in adjacency.get(current, []) if n != prev]
            if not neighbors:
                break
            next_v = neighbors[0]
            if next_v == start_v:
                break  # loop fechado
            if next_v in visited_vertices:
                break
            loop.append(next_v)
            visited_vertices.add(next_v)
            prev = current
            current = next_v

        if len(loop) >= 3:
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
    Qualidade superior ao centroid cap para loops complexos.
    """
    try:
        import mapbox_earcut as earcut
    except ImportError:
        logger.warning("mapbox_earcut nao instalado, usando centroid cap")
        return _cap_loop_centroid(vertices, loop)

    loop_verts = vertices[loop]

    # Calcular normal media do loop (cross product dos edges)
    n = len(loop)
    normal = np.zeros(3)
    centroid = loop_verts.mean(axis=0)
    for i in range(n):
        v0 = loop_verts[i] - centroid
        v1 = loop_verts[(i + 1) % n] - centroid
        normal += np.cross(v0, v1)
    norm_len = np.linalg.norm(normal)
    if norm_len < 1e-10:
        return _cap_loop_centroid(vertices, loop)
    normal /= norm_len

    # Base ortonormal no plano do loop
    u = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(normal, u)) > 0.9:
        u = np.array([0.0, 1.0, 0.0])
    u -= np.dot(u, normal) * normal
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)

    # Projetar vertices no plano 2D
    pts_2d = np.column_stack([
        np.dot(loop_verts - centroid, u),
        np.dot(loop_verts - centroid, v),
    ]).astype(np.float64)

    # Triangular com earcut
    rings = np.array([len(loop)], dtype=np.uint32)
    indices = earcut.triangulate_float64(pts_2d.ravel(), rings)

    if len(indices) == 0:
        return _cap_loop_centroid(vertices, loop)

    # Reconstruir faces com indices originais do loop
    loop_arr = np.array(loop, dtype=np.int32)
    new_faces = loop_arr[indices.reshape(-1, 3)]

    return vertices, new_faces


def cap_open_mesh(
    mesh: trimesh.Trimesh,
    method: str = "centroid",
    min_loop_length: int = 3,
) -> trimesh.Trimesh:
    """
    Fecha todos os buracos de borda aberta na malha.

    Args:
        mesh: Malha possivelmente aberta (open mesh).
        method: "centroid" (rapido) ou "earcut" (melhor qualidade).
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

        if method == "earcut":
            new_verts, new_faces = _cap_loop_earcut(all_new_vertices, loop)
        else:
            new_verts, new_faces = _cap_loop_centroid(all_new_vertices, loop)

        # Offset das faces novas para os novos indices de vertices
        n_prev = len(all_new_vertices)
        if len(new_verts) > n_prev:
            # Novos vertices foram adicionados (centroid cap)
            all_new_vertices = new_verts
            all_new_faces = np.vstack([all_new_faces, new_faces])
        else:
            # Earcut: apenas novas faces (sem novos vertices)
            all_new_faces = np.vstack([all_new_faces, new_faces])

    capped = trimesh.Trimesh(
        vertices=all_new_vertices,
        faces=all_new_faces,
        process=True,  # Reparar orientacao de normais
    )

    logger.info(
        f"Malha fechada: {len(capped.vertices)} verts, {len(capped.faces)} faces, "
        f"watertight={capped.is_watertight}"
    )
    return capped


def close_color_piece(
    mesh: trimesh.Trimesh,
    method: str = "centroid",
) -> trimesh.Trimesh:
    """
    Pipeline completo para preparar uma peca colorida para impressao:
    1. Remove geometria degenerada
    2. Fecha buracos
    3. Fixa normais inconsistentes
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
