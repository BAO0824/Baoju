from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.domain.models import ProviderStatus
from backend.app.main import app
from backend.app.providers.base import RawPrediction
import backend.app.main as main_module


class UnavailableProvider:
    def status(self):
        return ProviderStatus(
            name="raster2seq",
            available=False,
            model="cubicasa5k",
            device="cuda",
            reason="test model is intentionally unavailable",
        )


class WorkingProvider:
    def status(self):
        return ProviderStatus(
            name="test-raster2seq",
            available=True,
            model="test-cubicasa5k",
            device="cpu-test-double",
        )

    def recognize(self, _image_path):
        return RawPrediction(
            polygons=[
                {
                    "segmentation": [[10, 10], [200, 10], [200, 180], [10, 180]],
                    "category_id": 2,
                }
            ],
            coordinate_width=256,
            coordinate_height=256,
        )


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 24), "white").save(output, format="PNG")
    return output.getvalue()


def test_health():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_recognition_returns_503_instead_of_fake_geometry(monkeypatch):
    monkeypatch.setattr(main_module, "provider", UnavailableProvider())
    client = TestClient(app)

    response = client.post(
        "/api/recognize",
        files={"file": ("plan.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "recognition_provider_unavailable"
    assert "test model" in detail["reason"]


def test_rejects_non_image_before_provider(monkeypatch):
    monkeypatch.setattr(main_module, "provider", UnavailableProvider())
    client = TestClient(app)

    response = client.post(
        "/api/recognize",
        files={"file": ("plan.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 415


def test_real_provider_contract_reaches_canonical_geometry(monkeypatch):
    monkeypatch.setattr(main_module, "provider", WorkingProvider())
    client = TestClient(app)

    response = client.post(
        "/api/recognize",
        files={"file": ("plan.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"]["available"] is True
    assert payload["rawPredictionCount"] == 1
    assert len(payload["model"]["rooms"]) == 1
    assert len(payload["model"]["walls"]) == 4
    assert payload["model"]["calibration"]["coordinateUnit"] == "px"


def test_frontend_is_served():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Baoju" in response.text
    assert "執行 AI 格局辨識" in response.text
