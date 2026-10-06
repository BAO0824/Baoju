from __future__ import annotations

import hashlib
import io
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from backend.app.domain.models import (
    CalibrationRequest,
    ProviderStatus,
    RecognitionResponse,
    SourceInfo,
)
from backend.app.providers.base import ProviderInferenceError, ProviderUnavailableError
from backend.app.providers.raster2seq import Raster2SeqProvider
from backend.app.services.geometry import calibrate_model, raster2seq_to_baoju


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}

app = FastAPI(
    title="Baoju Recognition API",
    version="0.1.0",
    description="Real-model floor-plan recognition gateway. No threshold-detector fallback.",
)
provider = Raster2SeqProvider()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "product": "Baoju", "apiVersion": "0.1.0"}


@app.get("/api/providers", response_model=list[ProviderStatus])
def providers() -> list[ProviderStatus]:
    return [provider.status()]


@app.post("/api/recognize", response_model=RecognitionResponse, response_model_by_alias=True)
async def recognize(file: UploadFile = File(...)) -> RecognitionResponse:
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail={
                "code": "unsupported_media_type",
                "message": "目前支援 PNG、JPG、WEBP；PDF 將在 preprocessing 階段加入。",
            },
        )

    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "file_too_large", "message": "圖片不可超過 20 MB。"},
        )
    if not contents:
        raise HTTPException(status_code=400, detail={"code": "empty_file", "message": "圖片內容是空的。"})

    try:
        with Image.open(io.BytesIO(contents)) as image:
            image.verify()
        with Image.open(io.BytesIO(contents)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_image", "message": "檔案不是可讀取的圖片。"},
        ) from exc

    status = provider.status()
    if not status.available:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "recognition_provider_unavailable",
                "message": "Raster2Seq 尚未能在這台主機執行。",
                "reason": status.reason,
                "provider": status.model_dump(by_alias=True),
            },
        )

    suffix = Path(file.filename or "floorplan.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    with tempfile.TemporaryDirectory(prefix="baoju-upload-") as temp_dir:
        image_path = Path(temp_dir) / f"upload{suffix}"
        image_path.write_bytes(contents)
        try:
            raw = provider.recognize(image_path)
        except ProviderUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "recognition_provider_unavailable", "message": str(exc)},
            ) from exc
        except ProviderInferenceError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "recognition_failed", "message": str(exc)},
            ) from exc

    source = SourceInfo(
        filename=file.filename or "floorplan",
        mimeType=file.content_type,
        width=width,
        height=height,
        sha256=hashlib.sha256(contents).hexdigest(),
    )
    model = raster2seq_to_baoju(
        raw.polygons,
        source,
        coordinate_width=raw.coordinate_width,
        coordinate_height=raw.coordinate_height,
    )
    return RecognitionResponse(provider=status, model=model, rawPredictionCount=len(raw.polygons))


@app.post("/api/calibrate", response_model_by_alias=True)
def calibrate(request: CalibrationRequest):
    try:
        return calibrate_model(request)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_calibration", "message": str(exc)},
        ) from exc


@app.get("/api/schema")
def schema() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "shared" / "baoju.schema.json", media_type="application/schema+json")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_ROOT / "index.html")


app.mount("/assets", StaticFiles(directory=FRONTEND_ROOT), name="assets")
