"""
Módulo de geração automática de conectores mecânicos (Interlock Connectors).
Inspirado nas plataformas Hi3D e Split3MF.

Funcionalidades:
- Gera conectores macho/fêmea (pinos de encaixe com furo conjugado) nas interfaces de corte.
- Formatos de pino:
    * "hex" (Prisma Hexagonal - Anti-rotação e auto-alinhamento, padrão recomendado)
    * "triangle" (Prisma Triangular estilo Split3MF)
    * "cylinder" (Cilindro clássico)
- Aplica folga paramétrica de tolerância mecânica (padrão 0.2mm para compensar dilatação de PLA/PETG).
- Aplica chanfro suave na ponta do pino macho para facilitar a inserção e alinhamento.
- Profundidade extra de 0.5mm no furo fêmea (reservatório para cola cianoacrilato / encaixe perfeito).
- Ambos os corpos resultantes são 100% estanques (watertight/manifold).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

import numpy as np
import trimesh

if TYPE_CHECKING:
    from manifold3d import Manifold

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE_MM: float = 0.2
MIN_INTERFACE_AREA_MM2: float = 30.0  # Mínimo para caber um pino sem enfraquecer paredes


def _rotation_matrix_from_z_to_dir(target_dir: np.ndarray) -> np.ndarray:
    """Calcula matriz 4x4 de rotação que alinha o vetor [0, 0, 1] com target_dir."""
    z = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    target = np.asarray(target_dir, dtype=np.float64)
    norm = float(np.linalg.norm(target))
    if norm < 1e-9:
        return np.eye(4)
    target = target / norm

    dot = float(np.dot(z, target))
    if dot > 0.999999:
        return np.eye(4)
    if dot < -0.999999:
        R = np.eye(4)
        R[1, 1] = -1.0
        R[2, 2] = -1.0
        return R

    axis = np.cross(z, target)
    axis_norm = float(np.linalg.norm(axis))
    if axis_norm < 1e-9:
        return np.eye(4)
    axis = axis / axis_norm
    angle = np.arccos(np.clip(dot, -1.0, 1.0))
    return trimesh.transformations.rotation_matrix(angle, axis)


def add_interlock_connector(
    top_manifold: "Manifold",
    bottom_manifold: "Manifold",
    reference_mesh: trimesh.Trimesh,
    plane_origin: list[float] | np.ndarray,
    plane_normal: list[float] | np.ndarray,
    tolerance_mm: float = DEFAULT_TOLERANCE_MM,
    pin_shape: Literal["hex", "triangle", "cylinder"] = "hex",
) -> tuple["Manifold", "Manifold"]:
    """
    Adiciona um conector macho à peça superior (top) e subtrai o socket fêmea
    da peça inferior (bottom) na interface do plano de corte.

    Args:
        top_manifold: Peça no lado positivo do plano (recebe o pino macho).
        bottom_manifold: Peça no lado negativo do plano (recebe o furo fêmea).
        reference_mesh: Malha de referência para extração da secção transversal.
        plane_origin: Ponto no plano de corte.
        plane_normal: Vetor normal apontando para o lado do top_manifold.
        tolerance_mm: Folga de encaixe em mm (0.2mm padrão).
        pin_shape: "hex", "triangle" ou "cylinder".

    Returns:
        (top_with_pin, bottom_with_socket) ambos como manifold3d.Manifold.
    """
    from manifold3d import Manifold  # lazy import

    origin_arr = np.asarray(plane_origin, dtype=np.float64)
    normal_arr = np.asarray(plane_normal, dtype=np.float64)
    n_len = float(np.linalg.norm(normal_arr))
    if n_len < 1e-9:
        return top_manifold, bottom_manifold
    normal_arr = normal_arr / n_len

    try:
        # 1. Extrair secção transversal na interface
        sec = reference_mesh.section(plane_origin=origin_arr, plane_normal=normal_arr)
        if sec is None:
            logger.debug("Nenhuma secção transversal encontrada no plano de corte.")
            return top_manifold, bottom_manifold

        p2d, to_3D = sec.to_2D()
        area = abs(float(p2d.area))
        if area < MIN_INTERFACE_AREA_MM2:
            logger.info("Área de corte (%.1f mm²) muito pequena para pino mecânico.", area)
            return top_manifold, bottom_manifold

        r_eff = np.sqrt(area / np.pi)
        c_2d = p2d.centroid
        c_3d = trimesh.transformations.transform_points([[c_2d[0], c_2d[1], 0.0]], to_3D)[0]

        # 2. Dimensionamento paramétrico do pino
        # Raio entre 2.0mm e 6.5mm (diâmetro 4mm a 13mm)
        r_pin = float(np.clip(r_eff * 0.28, 2.0, 6.5))
        # Comprimento entre 5mm e 12mm
        h_pin = float(np.clip(r_pin * 2.0, 5.0, 12.0))

        # 3. Escolha do formato (circular_segments no Manifold.cylinder)
        if pin_shape == "triangle":
            circ_segs = 3
        elif pin_shape == "hex":
            circ_segs = 6
        else:
            circ_segs = 0  # cilindro liso

        # 4. Construção do pino macho (com chanfro/taper de 15% na ponta para facilitar inserção)
        # O pino estende-se a partir de c_3d na direção -normal_arr (penetrando na peça bottom)
        m_male_pin = Manifold.cylinder(
            height=h_pin,
            radius_low=r_pin,
            radius_high=r_pin * 0.85,
            circular_segments=circ_segs,
            center=False,
        )

        # Matriz de alinhamento com -normal_arr
        rot = _rotation_matrix_from_z_to_dir(-normal_arr)
        rot[:3, 3] = c_3d
        m_male_pin = m_male_pin.transform(rot[:3, :].tolist())

        # 5. Construção do furo fêmea (com folga de tolerância e profundidade extra para cola)
        r_socket = r_pin + float(tolerance_mm)
        h_socket = h_pin + 0.5  # 0.5mm extra para não travar no fundo
        m_female_socket = Manifold.cylinder(
            height=h_socket,
            radius_low=r_socket,
            radius_high=r_socket,
            circular_segments=circ_segs,
            center=False,
        )
        m_female_socket = m_female_socket.transform(rot[:3, :].tolist())

        # 6. Operações booleanas
        new_top = top_manifold + m_male_pin
        new_bottom = bottom_manifold - m_female_socket

        # Validar volumes resultantes
        if new_top.volume() > 0 and new_bottom.volume() > 0:
            logger.info(
                "Conector interlock adicionado com sucesso: formato=%s r=%.1fmm h=%.1fmm tol=%.2fmm",
                pin_shape,
                r_pin,
                h_pin,
                tolerance_mm,
            )
            return new_top, new_bottom
        else:
            logger.warning("Falha de volume após adição de conector, mantendo peças originais.")
            return top_manifold, bottom_manifold

    except Exception as exc:
        logger.warning("Erro ao gerar conector mecânico: %s", exc)
        return top_manifold, bottom_manifold
