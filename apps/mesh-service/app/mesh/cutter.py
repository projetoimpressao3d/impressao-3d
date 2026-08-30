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

import numpy as np
import trimesh
from manifold3d import Manifold, Mesh

logger = logging.getLogger(__name__)


@dataclass
class CutPlaneInput:
    """Plano de corte recebido do frontend após confirmação do usuário."""

    normal: list[float]  # vetor normal normalizado, ex: [1.0, 0.0, 0.0]
    origin: list[float]  # ponto no plano em coords. do modelo centrado, ex: [25.0, 0.0, 0.0]
    label: str = field(default="")


def _trimesh_to_manifold(mesh: trimesh.Trimesh) -> Manifold:
    """Converte trimesh.Trimesh → manifold3d.Manifold."""
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.uint32)
    return Manifold(Mesh(vert_properties=verts, tri_verts=faces))


def _manifold_to_trimesh(m: Manifold) -> trimesh.Trimesh:
    """Converte manifold3d.Manifold → trimesh.Trimesh."""
    result = m.to_mesh()
    verts = np.asarray(result.vert_properties)[:, :3]
    faces = np.asarray(result.tri_verts)
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def cut_mesh_by_planes(
    mesh: trimesh.Trimesh,
    planes: list[CutPlaneInput],
) -> list[trimesh.Trimesh]:
    """
    Aplica N planos de corte sequencialmente usando manifold3d.split_by_plane().

    O capping de cada face aberta é feito AUTOMATICAMENTE pelo manifold3d —
    não é necessária nenhuma etapa adicional de fechamento.

    Args:
        mesh:   Malha de entrada. Recomenda-se aplicar repair_mesh() antes.
        planes: Planos de corte na ordem de aplicação. Cada plano divide
                o fragmento "bottom" do plano anterior.

    Returns:
        Lista com N+1 trimesh.Trimesh. Todas as peças são watertight.
        Peças vazias (sem vértices) são descartadas silenciosamente.

    Raises:
        ValueError:   Malha inválida ou normal com norma ≈ 0.
        RuntimeError: Erro interno do manifold3d durante o corte.
    """
    if not planes:
        return [mesh]

    # Converter malha inicial para manifold3d
    try:
        current: Manifold = _trimesh_to_manifold(mesh)
    except Exception as exc:
        raise ValueError(f"Falha ao converter malha para manifold3d: {exc}") from exc

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
            "Corte %d/%d: normal=%s offset=%.3fmm label='%s'",
            i + 1,
            len(planes),
            [round(x, 4) for x in n.tolist()],
            origin_offset,
            plane.label,
        )

        try:
            top, bottom = current.split_by_plane(n.tolist(), origin_offset)
        except Exception as exc:
            raise RuntimeError(
                f"manifold3d falhou no corte {i + 1}/{len(planes)}: {exc}. "
                "Certifique-se de que o plano intersecta a geometria e a malha é válida."
            ) from exc

        accumulated.append(top)
        current = bottom  # continuar particionando o fragmento inferior

    accumulated.append(current)  # último fragmento: bottom do plano final

    # Converter manifolds → trimesh, descartando peças vazias
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

        result.append(piece)
        logger.info(
            "Peça %d: verts=%d faces=%d watertight=%s extents=[%.1f, %.1f, %.1f]mm",
            i,
            len(piece.vertices),
            len(piece.faces),
            piece.is_watertight,
            *piece.extents,
        )

    return result
