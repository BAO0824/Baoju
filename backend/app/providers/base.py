from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.domain.models import ProviderStatus


@dataclass(frozen=True)
class RawPrediction:
    polygons: list[dict[str, Any]]
    coordinate_width: int
    coordinate_height: int


class RecognitionProvider(ABC):
    @abstractmethod
    def status(self) -> ProviderStatus:
        """Return whether this provider can run a real inference now."""

    @abstractmethod
    def recognize(self, image_path: Path) -> RawPrediction:
        """Run real model inference and return provider-native polygons."""


class ProviderUnavailableError(RuntimeError):
    pass


class ProviderInferenceError(RuntimeError):
    pass
