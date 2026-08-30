"""
Utilitários de reparo de malhas 3D com trimesh.

Este módulo é reutilizável por:
- POST /split-sessions/{id}/execute (Fase 6) — reparo antes do corte booleano
- POST /analyze (Fase 2)            — pode ser aplicado antes da checagem de printability
                                       passando repair=True (opcional, não altera o resultado padrão)
"""

import logging

import trimesh

logger = logging.getLogger(__name__)


def repair_mesh(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """
    Aplica reparo básico em uma malha 3D para aumentar a robustez do corte booleano.

    Operações aplicadas (em ordem):
    1. ``fix_inversion``  — corrige faces com normais invertidas em relação ao volume
    2. ``fix_winding``    — garante orientação consistente de todas as faces (CCW)
    3. ``fill_holes``     — fecha buracos na malha (somente se não for watertight)
    4. ``fix_normals``    — recalcula normais após as modificações acima

    Args:
        mesh: Trimesh a ser reparado. **Não é modificado** — retorna uma cópia.

    Returns:
        Nova instância de ``trimesh.Trimesh`` com os reparos aplicados.
    """
    repaired = mesh.copy()

    original_watertight = bool(repaired.is_watertight)
    original_face_count = len(repaired.faces)

    # 1. Corrigir normais invertidas
    trimesh.repair.fix_inversion(repaired, multibody=True)

    # 2. Garantir winding consistente (orientação antihorária vista de fora)
    trimesh.repair.fix_winding(repaired)

    # 3. Fechar buracos — só se necessário (pode ser lento para malhas grandes)
    if not repaired.is_watertight:
        trimesh.repair.fill_holes(repaired)

    # 4. Recalcular normais após todas as modificações
    trimesh.repair.fix_normals(repaired, multibody=True)

    repaired_watertight = bool(repaired.is_watertight)

    logger.info(
        "Reparo concluído: watertight %s→%s | faces %d→%d",
        original_watertight,
        repaired_watertight,
        original_face_count,
        len(repaired.faces),
    )

    return repaired


def load_and_normalize(file_path: str) -> trimesh.Trimesh:
    """
    Carrega um arquivo STL ou 3MF e retorna um Trimesh unificado.

    - Cenas com múltiplos objetos (ex: 3MF) são concatenadas em uma malha única.
    - Não aplica reparo — use repair_mesh() separadamente se necessário.

    Args:
        file_path: Caminho absoluto do arquivo no sistema de arquivos.

    Returns:
        Instância de ``trimesh.Trimesh`` com todos os objetos concatenados.

    Raises:
        ValueError: Se o arquivo não contiver geometria válida.
    """
    mesh_or_scene = trimesh.load(file_path, force="mesh")

    if isinstance(mesh_or_scene, trimesh.Scene):
        geometries = list(mesh_or_scene.geometry.values())
        if not geometries:
            raise ValueError("Arquivo 3D vazio ou sem geometria.")
        mesh = trimesh.util.concatenate(geometries)
    elif isinstance(mesh_or_scene, trimesh.Trimesh):
        mesh = mesh_or_scene
    else:
        raise ValueError(f"Tipo de geometria não suportado: {type(mesh_or_scene)}")

    if len(mesh.faces) == 0:
        raise ValueError("A malha não contém faces.")

    return mesh
