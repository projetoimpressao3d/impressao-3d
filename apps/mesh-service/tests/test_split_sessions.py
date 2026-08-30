"""
Testes do endpoint POST /split-sessions e da lógica de planejamento de cortes.

Cobertura:
 - compute_split_plan(): função pura, sem I/O — 5 cenários
 - Endpoint /split-sessions: auth + 3 cenários com Supabase mockado
"""

import math
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.mesh.geometry import Dimensions, compute_split_plan

client = TestClient(app)
VALID_TOKEN = "test-internal-token-split"


@pytest.fixture(autouse=True)
def _set_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Define o token interno para todos os testes deste módulo."""
    monkeypatch.setattr(settings, "python_backend_internal_token", VALID_TOKEN)


# ---------------------------------------------------------------------------
# Testes da lógica pura — sem Supabase, sem arquivos
# ---------------------------------------------------------------------------


class TestComputeSplitPlan:
    """Testa a heurística de cálculo de cortes."""

    def test_model_fits_no_cuts_needed(self) -> None:
        """
        CENÁRIO 1: Modelo 100×80×50mm numa mesa 256×256×256mm.
        Esperado: fits=True, nenhum corte necessário.
        """
        plan = compute_split_plan(
            model_dims=Dimensions(x=100.0, y=80.0, z=50.0),
            plate_dims=Dimensions(x=256.0, y=256.0, z=256.0),
        )

        assert plan.fits is True
        assert plan.cuts_needed == {"x": 0, "y": 0, "z": 0}
        assert plan.cut_planes == []

    def test_one_cut_one_axis(self) -> None:
        """
        CENÁRIO 2: Modelo de 400mm no eixo X numa mesa de 256mm.
        Esperado: fits=False, 1 corte em X, posição = 0mm (centro).
        """
        plan = compute_split_plan(
            model_dims=Dimensions(x=400.0, y=80.0, z=50.0),
            plate_dims=Dimensions(x=256.0, y=256.0, z=256.0),
        )

        assert plan.fits is False
        assert plan.cuts_needed == {"x": 1, "y": 0, "z": 0}
        assert len(plan.cut_planes) == 1

        plane = plan.cut_planes[0]
        assert plane.axis == "x"
        # 2 partes de 200mm cada → corte no centro exato
        assert plane.position_mm == pytest.approx(0.0, abs=0.1)
        assert plane.normal == [1.0, 0.0, 0.0]

        # Verificar que cada parte resultante cabe na mesa
        n_parts = plan.cuts_needed["x"] + 1  # 2
        piece_size = 400.0 / n_parts  # 200mm
        assert piece_size <= 256.0

    def test_multi_axis_multi_cuts(self) -> None:
        """
        CENÁRIO 3: Modelo 700×350×50mm numa mesa 256×256×256mm.
        Esperado: fits=False, 2 cortes em X, 1 em Y → 3 planos no total.
        """
        plan = compute_split_plan(
            model_dims=Dimensions(x=700.0, y=350.0, z=50.0),
            plate_dims=Dimensions(x=256.0, y=256.0, z=256.0),
        )

        assert plan.fits is False
        # X: ceil(700/256) = 3 partes → 2 cortes
        assert plan.cuts_needed["x"] == 2
        # Y: ceil(350/256) = 2 partes → 1 corte
        assert plan.cuts_needed["y"] == 1
        # Z: 50mm < 256mm → sem corte
        assert plan.cuts_needed["z"] == 0

        assert len(plan.cut_planes) == 3  # 2 em X + 1 em Y

        x_planes = sorted(
            [p for p in plan.cut_planes if p.axis == "x"],
            key=lambda p: p.position_mm,
        )
        y_planes = [p for p in plan.cut_planes if p.axis == "y"]

        assert len(x_planes) == 2
        assert len(y_planes) == 1

        # Posições em X: dividindo 700mm em 3 partes iguais de ≈233.3mm
        # Posição 1: -700/2 + 700/3 = -350 + 233.3 = -116.7mm
        # Posição 2: -700/2 + 2*700/3 = -350 + 466.7 = +116.7mm
        expected_x1 = -700 / 2 + 700 / 3
        expected_x2 = -700 / 2 + 2 * 700 / 3
        assert x_planes[0].position_mm == pytest.approx(expected_x1, abs=0.5)
        assert x_planes[1].position_mm == pytest.approx(expected_x2, abs=0.5)

        # Posição em Y: 350mm em 2 partes → corte no centro (0mm)
        assert y_planes[0].position_mm == pytest.approx(0.0, abs=0.1)

        # Verificar que todas as peças cabem na mesa
        part_x = 700.0 / 3
        part_y = 350.0 / 2
        assert part_x <= 256.0, f"Parte X ({part_x:.1f}mm) não cabe na mesa (256mm)"
        assert part_y <= 256.0, f"Parte Y ({part_y:.1f}mm) não cabe na mesa (256mm)"

    def test_exact_fit_boundary(self) -> None:
        """Modelo com dimensões exatamente iguais à mesa — deve caber (sem cortes)."""
        plan = compute_split_plan(
            model_dims=Dimensions(x=256.0, y=256.0, z=256.0),
            plate_dims=Dimensions(x=256.0, y=256.0, z=256.0),
        )

        assert plan.fits is True
        assert plan.cuts_needed == {"x": 0, "y": 0, "z": 0}
        assert plan.cut_planes == []

    def test_all_axes_exceed(self) -> None:
        """Modelo maior que a mesa nos três eixos → 1 corte por eixo."""
        plan = compute_split_plan(
            model_dims=Dimensions(x=512.0, y=512.0, z=512.0),
            plate_dims=Dimensions(x=256.0, y=256.0, z=256.0),
        )

        assert plan.fits is False
        assert plan.cuts_needed == {"x": 1, "y": 1, "z": 1}
        # 1 plano por eixo = 3 planos no total
        assert len(plan.cut_planes) == 3

    def test_piece_sizes_always_fit(self) -> None:
        """
        Propriedade: as peças resultantes de compute_split_plan devem SEMPRE caber.
        Testado com vários tamanhos de modelo.
        """
        plate = Dimensions(x=256.0, y=256.0, z=256.0)
        model_sizes = [
            (300.0, 100.0, 50.0),
            (700.0, 600.0, 300.0),
            (1000.0, 1000.0, 1000.0),
            (257.0, 255.0, 1.0),  # apenas X excede por 1mm
        ]

        for mx, my, mz in model_sizes:
            model = Dimensions(x=mx, y=my, z=mz)
            plan = compute_split_plan(model, plate)

            for axis_name, model_dim, plate_dim in [
                ("x", mx, 256.0),
                ("y", my, 256.0),
                ("z", mz, 256.0),
            ]:
                n_cuts = plan.cuts_needed[axis_name]
                if n_cuts == 0:
                    continue
                piece = model_dim / (n_cuts + 1)
                assert piece <= plate_dim, (
                    f"Modelo ({mx}×{my}×{mz}): peça no eixo {axis_name} "
                    f"tem {piece:.1f}mm mas mesa tem {plate_dim}mm"
                )


# ---------------------------------------------------------------------------
# Testes do endpoint /split-sessions (Supabase mockado)
# ---------------------------------------------------------------------------


def _model_row(
    bbox: tuple[float, float, float],
    user_id: str | None = None,
) -> dict:
    """Cria uma linha fictícia da tabela models."""
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id or str(uuid.uuid4()),
        "bounding_box_x_mm": bbox[0],
        "bounding_box_y_mm": bbox[1],
        "bounding_box_z_mm": bbox[2],
        "printability_status": "ok",
    }


def _plate_row(dims: tuple[float, float, float]) -> dict:
    """Cria uma linha fictícia da tabela build_plates."""
    return {
        "id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "build_volume_x_mm": dims[0],
        "build_volume_y_mm": dims[1],
        "build_volume_z_mm": dims[2],
    }


def _session_row() -> dict:
    """Linha fictícia da tabela split_sessions."""
    return {"id": str(uuid.uuid4()), "status": "draft"}


def _payload(
    model_id: str | None = None,
    build_plate_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    return {
        "model_id": model_id or str(uuid.uuid4()),
        "build_plate_id": build_plate_id or str(uuid.uuid4()),
        "user_id": user_id or str(uuid.uuid4()),
    }


class TestSplitSessionEndpoint:
    """Testes de integração com Supabase e token mockados."""

    def test_missing_token_returns_401_or_403(self) -> None:
        """Sem token deve ser rejeitado."""
        response = client.post("/split-sessions", json=_payload())
        assert response.status_code in (401, 403)

    def test_wrong_token_returns_401(self) -> None:
        """Token errado deve retornar 401."""
        response = client.post(
            "/split-sessions",
            json=_payload(),
            headers={"Authorization": "Bearer token-errado"},
        )
        assert response.status_code == 401

    def test_model_fits(self) -> None:
        """CENÁRIO 1 (endpoint): 100×80×50mm numa mesa 256×256×256mm → fits=True."""
        with (
            patch("app.routers.split_sessions._fetch_model") as mock_model,
            patch("app.routers.split_sessions._fetch_build_plate") as mock_plate,
            patch("app.routers.split_sessions._create_split_session") as mock_session,
        ):
            mock_model.return_value = _model_row(bbox=(100.0, 80.0, 50.0))
            mock_plate.return_value = _plate_row(dims=(256.0, 256.0, 256.0))
            mock_session.return_value = _session_row()

            response = client.post(
                "/split-sessions",
                json=_payload(),
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["fits"] is True
        assert data["cuts_needed"] == {"x": 0, "y": 0, "z": 0}
        assert data["cut_planes"] == []
        assert "split_session_id" in data

    def test_one_cut_one_axis(self) -> None:
        """CENÁRIO 2 (endpoint): 400×80×50mm → 1 corte em X no centro."""
        with (
            patch("app.routers.split_sessions._fetch_model") as mock_model,
            patch("app.routers.split_sessions._fetch_build_plate") as mock_plate,
            patch("app.routers.split_sessions._create_split_session") as mock_session,
        ):
            mock_model.return_value = _model_row(bbox=(400.0, 80.0, 50.0))
            mock_plate.return_value = _plate_row(dims=(256.0, 256.0, 256.0))
            mock_session.return_value = _session_row()

            response = client.post(
                "/split-sessions",
                json=_payload(),
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["fits"] is False
        assert data["cuts_needed"]["x"] == 1
        assert data["cuts_needed"]["y"] == 0
        assert data["cuts_needed"]["z"] == 0
        assert len(data["cut_planes"]) == 1
        assert data["cut_planes"][0]["axis"] == "x"
        assert abs(data["cut_planes"][0]["position_mm"]) < 0.1  # ≈ centro

    def test_multi_axis_multi_cuts(self) -> None:
        """CENÁRIO 3 (endpoint): 700×350×50mm → 2 cortes X + 1 corte Y = 3 planos."""
        with (
            patch("app.routers.split_sessions._fetch_model") as mock_model,
            patch("app.routers.split_sessions._fetch_build_plate") as mock_plate,
            patch("app.routers.split_sessions._create_split_session") as mock_session,
        ):
            mock_model.return_value = _model_row(bbox=(700.0, 350.0, 50.0))
            mock_plate.return_value = _plate_row(dims=(256.0, 256.0, 256.0))
            mock_session.return_value = _session_row()

            response = client.post(
                "/split-sessions",
                json=_payload(),
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["fits"] is False
        assert data["cuts_needed"]["x"] == 2
        assert data["cuts_needed"]["y"] == 1
        assert data["cuts_needed"]["z"] == 0
        assert len(data["cut_planes"]) == 3

        x_planes = [p for p in data["cut_planes"] if p["axis"] == "x"]
        y_planes = [p for p in data["cut_planes"] if p["axis"] == "y"]
        assert len(x_planes) == 2
        assert len(y_planes) == 1
        # Normals corretos
        assert x_planes[0]["normal"] == [1.0, 0.0, 0.0]
        assert y_planes[0]["normal"] == [0.0, 1.0, 0.0]

    def test_model_not_found_returns_404(self) -> None:
        """Modelo inexistente ou de outro usuário → 404."""
        with patch("app.routers.split_sessions._fetch_model") as mock_model:
            mock_model.return_value = None

            response = client.post(
                "/split-sessions",
                json=_payload(),
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )

        assert response.status_code == 404

    def test_model_pending_returns_422(self) -> None:
        """Modelo sem bbox (ainda analisando) → 422."""
        model_no_bbox = _model_row(bbox=(0.0, 0.0, 0.0))
        model_no_bbox["bounding_box_x_mm"] = None  # type: ignore[assignment]

        with (
            patch("app.routers.split_sessions._fetch_model") as mock_model,
        ):
            mock_model.return_value = model_no_bbox

            response = client.post(
                "/split-sessions",
                json=_payload(),
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )

        assert response.status_code == 422

    def test_plate_not_found_returns_404(self) -> None:
        """Mesa inexistente → 404."""
        with (
            patch("app.routers.split_sessions._fetch_model") as mock_model,
            patch("app.routers.split_sessions._fetch_build_plate") as mock_plate,
        ):
            mock_model.return_value = _model_row(bbox=(100.0, 80.0, 50.0))
            mock_plate.return_value = None

            response = client.post(
                "/split-sessions",
                json=_payload(),
                headers={"Authorization": f"Bearer {VALID_TOKEN}"},
            )

        assert response.status_code == 404
