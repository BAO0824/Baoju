from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from backend.app.domain.models import ProviderStatus
from backend.app.providers.base import (
    ProviderInferenceError,
    ProviderUnavailableError,
    RawPrediction,
    RecognitionProvider,
)


class Raster2SeqProvider(RecognitionProvider):
    """Adapter for Cornell VAILab's official Raster2Seq inference script.

    This provider never falls back to image thresholding. If the official model,
    compiled CUDA extensions, or checkpoint cannot be loaded, `available` is false
    and recognition returns HTTP 503 through the API layer.
    """

    name = "raster2seq"

    def __init__(self) -> None:
        project_root = Path(__file__).resolve().parents[3]
        self.root = Path(os.getenv("BAOJU_RASTER2SEQ_ROOT", project_root / "models" / "Raster2Seq"))
        self.python = os.getenv("BAOJU_RASTER2SEQ_PYTHON", sys.executable)
        self.checkpoint = os.getenv("BAOJU_RASTER2SEQ_CHECKPOINT", "hf:cubicasa5k")
        self.device = os.getenv("BAOJU_RASTER2SEQ_DEVICE", "cuda")
        self.timeout_seconds = int(os.getenv("BAOJU_RASTER2SEQ_TIMEOUT", "300"))
        self._status: ProviderStatus | None = None

    def status(self) -> ProviderStatus:
        if self._status is not None:
            return self._status

        predict_script = self.root / "predict.py"
        if not predict_script.is_file():
            self._status = ProviderStatus(
                name=self.name,
                available=False,
                model="cubicasa5k",
                device=self.device,
                reason=(
                    f"Official Raster2Seq checkout not found at {self.root}. "
                    "Run scripts/setup_raster2seq.sh on a Linux/CUDA machine."
                ),
            )
            return self._status

        check = subprocess.run(
            [
                self.python,
                "-c",
                "import torch, cv2, native_rasterizer; "
                "from models.ops.functions import MSDeformAttnFunction; "
                "assert torch.cuda.is_available(), 'CUDA is not available'",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if check.returncode != 0:
            reason = (check.stderr or check.stdout or "Raster2Seq dependency check failed").strip()
            self._status = ProviderStatus(
                name=self.name,
                available=False,
                model="cubicasa5k",
                device=self.device,
                reason=reason[-1200:],
            )
            return self._status

        self._status = ProviderStatus(
            name=self.name,
            available=True,
            model="cubicasa5k",
            device=self.device,
        )
        return self._status

    def recognize(self, image_path: Path) -> RawPrediction:
        status = self.status()
        if not status.available:
            raise ProviderUnavailableError(status.reason or "Raster2Seq is unavailable")

        with tempfile.TemporaryDirectory(prefix="baoju-r2s-") as work_dir:
            work = Path(work_dir)
            input_dir = work / "input"
            output_dir = work / "output"
            input_dir.mkdir()
            output_dir.mkdir()
            safe_name = f"floorplan{image_path.suffix.lower()}"
            staged_image = input_dir / safe_name
            shutil.copy2(image_path, staged_image)

            command = [
                self.python,
                "predict.py",
                "--dataset_name=cubicasa",
                f"--dataset_root={input_dir}",
                f"--checkpoint={self.checkpoint}",
                f"--output_dir={output_dir}",
                "--semantic_classes=12",
                "--input_channels",
                "3",
                "--poly2seq",
                "--seq_len",
                "512",
                "--num_bins",
                "32",
                "--disable_poly_refine",
                "--dec_attn_concat_src",
                "--per_token_sem_loss",
                "--use_anchor",
                "--ema4eval",
                "--save_pred",
                "--batch_size",
                "1",
                "--device",
                self.device,
            ]
            completed = subprocess.run(
                command,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            if completed.returncode != 0:
                error = (completed.stderr or completed.stdout or "unknown inference error").strip()
                raise ProviderInferenceError(f"Raster2Seq inference failed: {error[-4000:]}")

            prediction_files = list(output_dir.glob("**/jsons/floorplan.json"))
            if len(prediction_files) != 1:
                raise ProviderInferenceError(
                    "Raster2Seq finished but did not produce exactly one floorplan JSON output"
                )
            try:
                polygons = json.loads(prediction_files[0].read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ProviderInferenceError("Raster2Seq produced unreadable JSON") from exc
            if not isinstance(polygons, list):
                raise ProviderInferenceError("Raster2Seq JSON output is not a polygon list")

            return RawPrediction(polygons=polygons, coordinate_width=256, coordinate_height=256)
