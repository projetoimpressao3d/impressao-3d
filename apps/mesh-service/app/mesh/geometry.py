"""
Utilitários geométricos para cálculo de planos de corte mínimos.

Heurística implementada (seção 6.4 do AGENTS.md):
- Para cada eixo onde dim_modelo > dim_mesa:
    n_partes = ceil(dim_modelo / dim_mesa)
    n_cortes = n_partes − 1
    posições  = divisão em partes iguais, relativas ao centro do modelo

As posições de corte são **relativas ao centro da bounding box do modelo**,
que é onde o visualizador Three.js também posiciona a origem após centrar a geometria.
"""

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Dimensions:
    """Dimensões em mm nos três eixos."""

    x: float
    y: float
    z: float


@dataclass(frozen=True)
class CutPlane:
    """
    Plano de corte sugerido pela heurística.

    Attributes:
        axis:        Eixo de corte — ``"x"``, ``"y"`` ou ``"z"``.
        position_mm: Posição do plano em mm, relativa ao centro do modelo.
                     Negativo = lado esquerdo/traseiro/baixo; positivo = oposto.
        normal:      Vetor normal do plano (perpendicular ao eixo de corte).
        label:       Descrição legível para o usuário.
    """

    axis: str
    position_mm: float
    normal: list[float]
    label: str


@dataclass
class SplitPlan:
    """Resultado completo do planejamento de cortes."""

    fits: bool
    """True se o modelo já cabe na mesa sem nenhum corte."""

    model_dimensions: Dimensions
    plate_dimensions: Dimensions

    cuts_needed: dict[str, int]
    """Número de cortes por eixo. Ex: {"x": 1, "y": 0, "z": 0}"""

    cut_planes: list[CutPlane]
    """Lista ordenada de planos de corte sugeridos (todos os eixos combinados)."""


def compute_split_plan(
    model_dims: Dimensions,
    plate_dims: Dimensions,
) -> SplitPlan:
    """
    Calcula o plano mínimo de cortes para que todas as partes caibam na mesa.

    Complexidade: O(1) por eixo — puramente aritmético, sem I/O.

    Args:
        model_dims: Dimensões da bounding box do modelo em mm.
        plate_dims: Dimensões do volume de impressão da mesa em mm.

    Returns:
        :class:`SplitPlan` com ``fits=True`` se nenhum corte for necessário,
        ou com os planos sugeridos caso contrário.

    Examples:
        >>> plan = compute_split_plan(
        ...     Dimensions(100, 80, 50),   # modelo
        ...     Dimensions(256, 256, 256), # mesa
        ... )
        >>> plan.fits
        True

        >>> plan = compute_split_plan(
        ...     Dimensions(400, 80, 50),
        ...     Dimensions(256, 256, 256),
        ... )
        >>> plan.cuts_needed
        {'x': 1, 'y': 0, 'z': 0}
        >>> plan.cut_planes[0].position_mm
        0.0
    """
    _AXES = [
        ("x", model_dims.x, plate_dims.x, [1.0, 0.0, 0.0]),
        ("y", model_dims.y, plate_dims.y, [0.0, 1.0, 0.0]),
        ("z", model_dims.z, plate_dims.z, [0.0, 0.0, 1.0]),
    ]

    cuts_needed: dict[str, int] = {}
    cut_planes: list[CutPlane] = []

    for axis_name, model_dim, plate_dim, normal in _AXES:
        if model_dim <= plate_dim:
            # Modelo cabe neste eixo — nenhum corte necessário
            cuts_needed[axis_name] = 0
            continue

        # Número mínimo de partes para que cada uma caiba na mesa
        n_parts = math.ceil(model_dim / plate_dim)
        n_cuts = n_parts - 1
        cuts_needed[axis_name] = n_cuts

        # Tamanho de cada parte após a divisão igualitária
        part_size = model_dim / n_parts

        # Posições de corte relativas ao centro do modelo
        # O modelo vai de -model_dim/2 a +model_dim/2 (centrado na origem)
        # Corte i separa a parte i da parte i+1
        for i in range(1, n_parts):
            position = -model_dim / 2.0 + i * part_size
            cut_planes.append(
                CutPlane(
                    axis=axis_name,
                    position_mm=round(position, 3),
                    normal=normal,
                    label=f"Corte {axis_name.upper()}-{i} (de {n_parts} partes)",
                )
            )

    fits = all(v == 0 for v in cuts_needed.values())

    return SplitPlan(
        fits=fits,
        model_dimensions=model_dims,
        plate_dimensions=plate_dims,
        cuts_needed=cuts_needed,
        cut_planes=cut_planes,
    )


def validate_plan_piece_sizes(plan: SplitPlan) -> bool:
    """
    Verifica que todas as peças resultantes dos cortes sugeridos
    caberiam na mesa de trabalho.

    Útil como sanity-check antes de persistir a sessão.
    Retorna True se todas as peças couberem.
    """
    if plan.fits:
        return True

    plate = plan.plate_dimensions
    model = plan.model_dimensions

    for axis_name, model_dim, plate_dim in [
        ("x", model.x, plate.x),
        ("y", model.y, plate.y),
        ("z", model.z, plate.z),
    ]:
        n_cuts = plan.cuts_needed[axis_name]
        if n_cuts == 0:
            continue
        n_parts = n_cuts + 1
        piece_size = model_dim / n_parts
        if piece_size > plate_dim:
            return False  # pragma: no cover — heurística garante que isso não aconteça

    return True
