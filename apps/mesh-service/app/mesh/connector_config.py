"""
Configuração centralizada dos conectores mecânicos (pino macho + furo fêmea).

Mantida fora da lógica de corte conforme AGENTS.md (seção 6.4): a folga entre pino e
furo é configurável por material e não deve ficar hardcoded no meio dos algoritmos.
"""
from __future__ import annotations

# Folga radial (por lado) entre pino e furo, em mm, por material de impressão.
CONNECTOR_TOLERANCE_BY_MATERIAL_MM: dict[str, float] = {
    "PLA": 0.20,
    "PETG": 0.25,
    "ABS": 0.25,
    "ASA": 0.25,
    "TPU": 0.30,
    "RESINA": 0.10,
}

DEFAULT_MATERIAL: str = "PLA"
DEFAULT_PIN_SHAPE: str = "hex"


def tolerance_for_material(material: str | None) -> float:
    """Retorna a folga (mm) do material informado, caindo para PLA se desconhecido."""
    key = (material or DEFAULT_MATERIAL).strip().upper()
    return CONNECTOR_TOLERANCE_BY_MATERIAL_MM.get(
        key, CONNECTOR_TOLERANCE_BY_MATERIAL_MM[DEFAULT_MATERIAL]
    )


# ---------------------------------------------------------------------------
# Pinos na interface entre cores diferentes (modelos 3MF pintados)
# ---------------------------------------------------------------------------

# Área mínima (mm²) da interface entre duas cores para receber um pino.
# 25.0 mm² permite juntas funcionais (ex: ponta da cauda / chama de ~33 mm² e asas)
# enquanto ignora dentes, olhos e detalhes decorativos pequenos (< 20 mm²).
COLOR_INTERFACE_MIN_AREA_MM2: float = 25.0
# Raio mínimo (mm) do maior círculo inscrito na interface (polylabel).
COLOR_INTERFACE_MIN_INSCRIBED_RADIUS_MM: float = 2.0
# Fração mínima dos vértices da borda compartilhados com a cor vizinha.
COLOR_INTERFACE_MIN_PARTNER_SHARE: float = 0.6
# Desvio máximo (mm) da borda em relação ao plano médio — bordas muito curvas são ignoradas.
COLOR_INTERFACE_MAX_PLANE_DEVIATION_MM: float = 4.0
# Faixa de raio do pino macho (mm).
COLOR_INTERFACE_PIN_RADIUS_RANGE_MM: tuple[float, float] = (1.5, 4.0)
# Faixa de altura do pino macho (mm) — profundidade de encaixe na peça vizinha.
COLOR_INTERFACE_PIN_HEIGHT_RANGE_MM: tuple[float, float] = (3.5, 9.0)
# Parede mínima (mm) ao redor do furo para não perfurar a superfície externa.
COLOR_INTERFACE_MIN_WALL_MM: float = 1.0
# Quantidade máxima de pinos entre o mesmo par de cores.
COLOR_INTERFACE_MAX_PINS_PER_PAIR: int = 4
