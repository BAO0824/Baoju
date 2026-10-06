from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CoordinateUnit(str, Enum):
    PIXEL = "px"
    MILLIMETER = "mm"


class ConfidenceSource(str, Enum):
    AI = "ai"
    USER = "user"
    SYSTEM = "system"


class Point(StrictModel):
    x: float
    y: float


class SourceInfo(StrictModel):
    filename: str
    mime_type: str = Field(alias="mimeType")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    sha256: str


class CoordinateSpace(StrictModel):
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    image_fit: Literal["contain", "stretch"] = Field(default="contain", alias="imageFit")


class Calibration(StrictModel):
    status: Literal["required", "calibrated"] = "required"
    coordinate_unit: CoordinateUnit = Field(default=CoordinateUnit.PIXEL, alias="coordinateUnit")
    mm_per_unit: float | None = Field(default=None, gt=0, alias="mmPerUnit")

    @model_validator(mode="after")
    def calibrated_scale_is_required(self) -> "Calibration":
        if self.status == "calibrated":
            if self.coordinate_unit != CoordinateUnit.MILLIMETER or self.mm_per_unit != 1:
                raise ValueError("calibrated geometry must use millimetres with mmPerUnit=1")
        return self


class Node(StrictModel):
    id: str
    x: float
    y: float


class Wall(StrictModel):
    id: str
    start_node: str = Field(alias="startNode")
    end_node: str = Field(alias="endNode")
    thickness_mm: float | None = Field(default=None, gt=0, alias="thicknessMm")
    height_mm: float = Field(default=2800, gt=0, alias="heightMm")
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: ConfidenceSource = ConfidenceSource.AI
    room_ids: list[str] = Field(default_factory=list, alias="roomIds")

    @model_validator(mode="after")
    def different_endpoints(self) -> "Wall":
        if self.start_node == self.end_node:
            raise ValueError("wall endpoints must be different nodes")
        return self


class Opening(StrictModel):
    id: str
    type: Literal["door", "window"]
    wall_id: str | None = Field(default=None, alias="wallId")
    offset: float | None = Field(default=None, ge=0)
    width: float = Field(gt=0)
    height_mm: float = Field(gt=0, alias="heightMm")
    sill_height_mm: float | None = Field(default=None, ge=0, alias="sillHeightMm")
    swing: Literal["left", "right", "unknown"] = "unknown"
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_polygon: list[Point] = Field(default_factory=list, alias="sourcePolygon")


class Room(StrictModel):
    id: str
    name: str
    category_id: int | None = Field(default=None, alias="categoryId")
    node_ids: list[str] = Field(min_length=3, alias="nodeIds")
    confidence: float | None = Field(default=None, ge=0, le=1)


class Issue(StrictModel):
    id: str
    severity: Literal["info", "warning", "error"]
    code: str
    message: str
    entity_id: str | None = Field(default=None, alias="entityId")


class BaojuModel(StrictModel):
    version: Literal["1.0"] = "1.0"
    source: SourceInfo
    coordinate_space: CoordinateSpace = Field(alias="coordinateSpace")
    calibration: Calibration = Field(default_factory=Calibration)
    nodes: list[Node] = Field(default_factory=list)
    walls: list[Wall] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)
    rooms: list[Room] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_exist(self) -> "BaojuModel":
        node_ids = {node.id for node in self.nodes}
        wall_ids = {wall.id for wall in self.walls}
        room_ids = {room.id for room in self.rooms}
        for wall in self.walls:
            if wall.start_node not in node_ids or wall.end_node not in node_ids:
                raise ValueError(f"wall {wall.id} references a missing node")
            unknown_rooms = set(wall.room_ids) - room_ids
            if unknown_rooms:
                raise ValueError(f"wall {wall.id} references missing rooms: {sorted(unknown_rooms)}")
        for room in self.rooms:
            unknown_nodes = set(room.node_ids) - node_ids
            if unknown_nodes:
                raise ValueError(f"room {room.id} references missing nodes: {sorted(unknown_nodes)}")
        for opening in self.openings:
            if opening.wall_id is not None and opening.wall_id not in wall_ids:
                raise ValueError(f"opening {opening.id} references a missing wall")
        return self


class ProviderStatus(StrictModel):
    name: str
    available: bool
    reason: str | None = None
    model: str | None = None
    device: str | None = None


class RecognitionResponse(StrictModel):
    provider: ProviderStatus
    model: BaojuModel
    raw_prediction_count: int = Field(alias="rawPredictionCount")


class CalibrationRequest(StrictModel):
    model: BaojuModel
    point_a: Point = Field(alias="pointA")
    point_b: Point = Field(alias="pointB")
    known_distance_mm: float = Field(gt=0, alias="knownDistanceMm")
