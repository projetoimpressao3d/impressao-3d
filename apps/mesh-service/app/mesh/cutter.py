"""
Módulo de corte booleano de malhas 3D usando manifold3d.

API do manifold3d.split_by_plane(normal, origin_offset):
  - normal:        vetor normal ao plano (lista de 3 floats, não precisa ser unitário)
  - origin_offset: dot(normal_normalizado, ponto_no_plano)
  - Retorna: (top, bottom)
      * top:    parte onde dot(normal, p) >= origin_offset  (lado "positivo")
      * bottom: parte onde dot(normal, p) <= origin_offset  (lado "negativo")
  - Ambas as peças resultantes são SEMPRE watertight (capping automático interno)

Estratégia de corte sequencial (N planos → N+1 peças):
  plane_0 → (top_0, bottom_0)
  plane_1 → split bottom_0 → (top_1, bottom_1)
  ...
  plane_{N-1} → split bottom_{N-2} → (top_{N-1}, bottom_{N-1})
  Peças: [top_0, top_1, ..., top_{N-1}, bottom_{N-1}]
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import trimesh
from manifold3d import Manifold, Mesh

from app.mesh.connectors import add_interlock_connector

logger = logging.getLogger(__name__)


@dataclass
class CutPlaneInput:
    """Plano de corte recebido do frontend após confirmação do usuário."""

    normal: list[float]  # vetor normal normalizado, ex: [1.0, 0.0, 0.0]
    origin: list[float]  # ponto no plano em coords. do modelo centrado, ex: [25.0, 0.0, 0.0]
    label: str = field(default="")
    bbox_min: list[float] | None = field(default=None)
    bbox_max: list[float] | None = field(default=None)
    branch_pts: list[list[float]] | None = field(default=None)


def _trimesh_to_manifold(mesh: trimesh.Trimesh) -> "Manifold":
    """Converte trimesh.Trimesh → manifold3d.Manifold."""
    from manifold3d import Manifold, Mesh  # lazy import
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.uint32)
    return Manifold(Mesh(vert_properties=verts, tri_verts=faces))


def _manifold_to_trimesh(m: "Manifold") -> trimesh.Trimesh:
    """Converte manifold3d.Manifold → trimesh.Trimesh."""
    result = m.to_mesh()
    verts = np.asarray(result.vert_properties)[:, :3]
    faces = np.asarray(result.tri_verts)
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def _clean_piece_shards(piece: trimesh.Trimesh, min_volume: float = 150.0) -> trimesh.Trimesh:
    """
    Remove micro-estilhacos desconectados gerados por cortes de planos infinitos
    em geometrias concavas distantes.
    """
    try:
        comps = piece.split(only_watertight=False)
        if len(comps) <= 1:
            return piece

        # Filtrar componentes significativos (volume >= min_volume ou faces >= 150)
        significant = [
            c for c in comps
            if (c.is_watertight and abs(c.volume) >= min_volume) or len(c.faces) >= 150
        ]
        if not significant:
            return piece
        if len(significant) == 1:
            return significant[0]
        return trimesh.util.concatenate(significant)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha ao filtrar estilhacos da peca: %s", exc)
        return piece


def _cut_mesh_by_planes_trimesh(
    mesh: trimesh.Trimesh,
    planes: list[CutPlaneInput],
    generate_connectors: bool = True,
    connector_tolerance_mm: float = 0.2,
    connector_pin_shape: str = "hex",
) -> list[trimesh.Trimesh]:
    """
    Fatiador planar robusto baseado em trimesh com capping poligonal estanque.
    Utilizado como fallback transparente quando o modelo de entrada contém
    arestas não-manifold que impossibilitam a conversão para manifold3d.
    """
    current = mesh.copy()
    accumulated: list[trimesh.Trimesh] = []

    for i, plane in enumerate(planes):
        n = np.asarray(plane.normal, dtype=np.float64)
        norm_val = float(np.linalg.norm(n))
        if norm_val < 1e-10:
            continue
        n = n / norm_val
        o = np.asarray(plane.origin, dtype=np.float64)

        try:
            top = trimesh.intersections.slice_mesh_plane(current, plane_normal=n, plane_origin=o, cap=True)
            bottom = trimesh.intersections.slice_mesh_plane(current, plane_normal=-n, plane_origin=o, cap=True)

            if len(top.vertices) > 0 and len(bottom.vertices) > 0:
                if generate_connectors:
                    try:
                        m_top = _trimesh_to_manifold(top)
                        m_bottom = _trimesh_to_manifold(bottom)
                        if m_top.num_vert() > 0 and m_bottom.num_vert() > 0 and m_top.status() == 0 and m_bottom.status() == 0:
                            m_top, m_bottom = add_interlock_connector(
                                m_top,
                                m_bottom,
                                reference_mesh=current,
                                plane_origin=plane.origin,
                                plane_normal=n,
                                tolerance_mm=connector_tolerance_mm,
                                pin_shape=connector_pin_shape,
                            )
                            top = _manifold_to_trimesh(m_top)
                            bottom = _manifold_to_trimesh(m_bottom)
                    except Exception as conn_err:
                        logger.warning("Falha ao gerar conector para o plano %d (%s): %s", i + 1, plane.label, conn_err)

                accumulated.append(top)
                current = bottom
            else:
                logger.warning("Plano %d (%s) não seccionou a geometria em 2 partes válidas", i + 1, plane.label)
        except Exception as exc:
            logger.warning("Erro ao fatiar com trimesh no plano %d (%s): %s", i + 1, plane.label, exc)

    accumulated.append(current)
    valid_pieces = [p for p in accumulated if len(p.vertices) > 0 and len(p.faces) > 0]
    return valid_pieces if valid_pieces else [mesh]


def cut_mesh_by_planes(
    mesh: trimesh.Trimesh,
    planes: list[CutPlaneInput],
    generate_connectors: bool = True,
    connector_tolerance_mm: float = 0.2,
    connector_pin_shape: str = "hex",
) -> list[trimesh.Trimesh]:
    """
    Aplica N planos de corte sequencialmente usando manifold3d (com fallback robusto trimesh).
    """
    if not planes:
        return [mesh]

    # Converter malha inicial para manifold3d e verificar validade
    current: Manifold | None = None
    try:
        current = _trimesh_to_manifold(mesh)
        if current.num_vert() == 0 or current.status() != 0:
            current = None
    except Exception:
        current = None

    if current is None:
        logger.info("Malha de entrada possui micro-arestas abertas; utilizando fatiador robusto trimesh")
        return _cut_mesh_by_planes_trimesh(
            mesh, planes, generate_connectors, connector_tolerance_mm, connector_pin_shape
        )

    accumulated: list[Manifold] = []

    for i, plane in enumerate(planes):
        # Normalizar o vetor normal
        n = np.asarray(plane.normal, dtype=np.float64)
        norm_val = float(np.linalg.norm(n))
        if norm_val < 1e-10:
            raise ValueError(
                f"Plano {i} ('{plane.label}'): normal inválida (norma ≈ 0): {plane.normal}"
            )
        n = n / norm_val

        # origin_offset = dot(n, ponto_no_plano)
        o = np.asarray(plane.origin, dtype=np.float64)
        origin_offset = float(np.dot(n, o))

        logger.info(
            "Corte %d/%d: normal=%s offset=%.3fmm label='%s' bounded=%s",
            i + 1,
            len(planes),
            [round(x, 4) for x in n.tolist()],
            origin_offset,
            plane.label,
            plane.bbox_min is not None,
        )

        try:
            if plane.bbox_min is not None and plane.bbox_max is not None:
                # Corte Local Delimitado (Bounded Volume Cut):
                # Tentar construir uma cápsula justa ao redor do esqueleto do apêndice para evitar engolir partes próximas
                capsule_created = False
                branch_pts = getattr(plane, "branch_pts", None)
                if branch_pts and len(branch_pts) >= 2:
                    try:
                        pts = np.array(branch_pts)
                        p_start = pts[-1]
                        p_end = pts[0]
                        vec = p_end - p_start
                        length = np.linalg.norm(vec)
                        if length > 0.1:
                            # Raio 40mm é suficiente para cobrir asas/rabos finos
                            cyl = trimesh.creation.cylinder(radius=40.0, height=length + 80.0)
                            # Alinhar o cilindro com o vetor
                            z_axis = np.array([0, 0, 1])
                            dir_vec = vec / length
                            axis = np.cross(z_axis, dir_vec)
                            angle = np.arccos(np.clip(np.dot(z_axis, dir_vec), -1.0, 1.0))
                            if np.linalg.norm(axis) > 1e-6:
                                axis = axis / np.linalg.norm(axis)
                                rot = trimesh.transformations.rotation_matrix(angle, axis)
                            else:
                                rot = np.eye(4)
                                if dir_vec[2] < 0:
                                    rot[2, 2] = -1
                            
                            rot[:3, 3] = p_start + vec / 2.0
                            cyl.apply_transform(rot)
                            m_box = Manifold(Mesh(
                                vert_properties=np.asarray(cyl.vertices, dtype=np.float64),
                                tri_verts=np.asarray(cyl.faces, dtype=np.uint32),
                            ))
                            capsule_created = True
                    except Exception as e:
                        logger.warning(f"Falha ao criar cápsula delimitadora: {e}")

                if not capsule_created:
                    b_min = np.asarray(plane.bbox_min, dtype=np.float64) - 8.0
                    b_max = np.asarray(plane.bbox_max, dtype=np.float64) + 8.0
                    extents = b_max - b_min
                    # Se for plano de grade, as bounds podem ser invalidas (todas 0)
                    if np.any(extents <= 0):
                        box_mesh = trimesh.creation.box(extents=[1000, 1000, 1000])
                    else:
                        box_mesh = trimesh.creation.box(extents=extents)
                        box_mesh.vertices += (b_min + b_max) / 2.0
                    m_box = Manifold(Mesh(
                        vert_properties=np.asarray(box_mesh.vertices, dtype=np.float64),
                        tri_verts=np.asarray(box_mesh.faces, dtype=np.uint32),
                    ))

                # Separar a malha atual no que está dentro e fora da caixa
                inside_box = current ^ m_box
                outside_box = current - m_box
                
                # Cortar apenas o que está dentro da caixa com o plano
                top_inside, bottom_inside = inside_box.split_by_plane(n.tolist(), origin_offset)
                
                # Isolar apenas o apêndice alvo, devolvendo "bystanders" (ex: Dragonair) para o corpo
                top_pieces = [p for p in top_inside.decompose() if not p.is_empty()]
                if top_pieces:
                    # Encontrar a peça cujo centroid está mais próximo do origin do plano
                    origin_pt = np.asarray(plane.origin)
                    best_piece = top_pieces[0]
                    min_dist = float('inf')
                    for p in top_pieces:
                        tm = _manifold_to_trimesh(p)
                        if len(tm.vertices) < 3 or tm.bounds is None:
                            continue
                        dist = float(np.linalg.norm(tm.bounds.mean(axis=0) - origin_pt))
                        if dist < min_dist:
                            min_dist = dist
                            best_piece = p
                    
                    top = best_piece
                    # As outras peças voltam para o corpo
                    for p in top_pieces:
                        if p != best_piece:
                            bottom_inside = bottom_inside + p
                else:
                    top = top_inside
                
                # O corpo restante é a parte de baixo (dentro da caixa) fundida com tudo que estava fora
                bottom = bottom_inside + outside_box
            else:
                top, bottom = current.split_by_plane(n.tolist(), origin_offset)
        except Exception as exc:
            raise RuntimeError(
                f"manifold3d falhou no corte {i + 1}/{len(planes)}: {exc}. "
                "Certifique-se de que o plano intersecta a geometria e a malha é válida."
            ) from exc

        if generate_connectors:
            try:
                ref_mesh = _manifold_to_trimesh(current)
                top, bottom = add_interlock_connector(
                    top,
                    bottom,
                    reference_mesh=ref_mesh,
                    plane_origin=plane.origin,
                    plane_normal=n,
                    tolerance_mm=connector_tolerance_mm,
                    pin_shape=connector_pin_shape,
                )
            except Exception as conn_err:
                logger.warning("Falha ao gerar conector para o plano %d (%s): %s", i + 1, plane.label, conn_err)

        accumulated.append(top)
        current = bottom  # continuar particionando o fragmento inferior

    accumulated.append(current)  # último fragmento: bottom do plano final

    # Converter manifolds → trimesh, descartando peças vazias e limpando estilhaços
    result: list[trimesh.Trimesh] = []
    for i, m in enumerate(accumulated):
        try:
            piece = _manifold_to_trimesh(m)
        except Exception as exc:
            raise RuntimeError(
                f"Falha ao converter peça {i} de manifold3d de volta para trimesh: {exc}"
            ) from exc

        if len(piece.vertices) == 0 or len(piece.faces) == 0:
            logger.warning("Peça %d ficou vazia após o corte — descartada", i)
            continue

        piece = _clean_piece_shards(piece)

        result.append(piece)
        logger.info(
            "Peça %d: verts=%d faces=%d watertight=%s extents=[%.1f, %.1f, %.1f]mm",
            i,
            len(piece.vertices),
            len(piece.faces),
            piece.is_watertight,
            *piece.extents,
        )

    if not result:
        logger.warning("manifold3d resultou em peças vazias; recorrendo ao fatiador robusto trimesh")
        return _cut_mesh_by_planes_trimesh(
            mesh, planes, generate_connectors, connector_tolerance_mm, connector_pin_shape
        )

    return result
