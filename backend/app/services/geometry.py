from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from backend.app.domain.models import (
    BaojuModel,
    Calibration,
    CalibrationRequest,
    ConfidenceSource,
    CoordinateSpace,
    CoordinateUnit,
    Issue,
    Node,
    Opening,
    Point,
    Room,
    SourceInfo,
    Wall,
)


CC5K_LABELS = {
    0: "戶外",
    1: "廚房",
    2: "客廳",
    3: "臥室",
    4: "浴室",
    5: "玄關",
    6: "儲藏室",
    7: "車庫",
    8: "未定義空間",
    9: "窗",
    10: "門",
}
OPENING_TYPES = {9: "window", 10: "door"}


@dataclass
class _NodeIndex:
    tolerance: float

    def __post_init__(self) -> None:
        self.nodes: list[Node] = []

    def get_or_create(self, point: Point) -> str:
        for node in self.nodes:
            if math.hypot(node.x - point.x, node.y - point.y) <= self.tolerance:
                return node.id
        node_id = f"n{len(self.nodes) + 1}"
        self.nodes.append(Node(id=node_id, x=point.x, y=point.y))
        return node_id


def _clean_polygon(segmentation: object) -> list[Point]:
    if not isinstance(segmentation, list):
        return []
    points: list[Point] = []
    for value in segmentation:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            continue
        try:
            point = Point(x=float(value[0]), y=float(value[1]))
        except (TypeError, ValueError):
            continue
        if not points or math.hypot(points[-1].x - point.x, points[-1].y - point.y) > 0.01:
            points.append(point)
    if len(points) > 1 and math.hypot(points[0].x - points[-1].x, points[0].y - points[-1].y) <= 0.01:
        points.pop()
    return points


def _point_segment_projection(point: Point, start: Node, end: Node) -> tuple[float, float]:
    dx = end.x - start.x
    dy = end.y - start.y
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(point.x - start.x, point.y - start.y), 0
    t = max(0.0, min(1.0, ((point.x - start.x) * dx + (point.y - start.y) * dy) / length_sq))
    projected_x = start.x + t * dx
    projected_y = start.y + t * dy
    return math.hypot(point.x - projected_x, point.y - projected_y), t * math.sqrt(length_sq)


def _polygon_extent(points: list[Point]) -> float:
    return max(
        (math.hypot(a.x - b.x, a.y - b.y) for index, a in enumerate(points) for b in points[index + 1 :]),
        default=1.0,
    )


def raster2seq_to_baoju(
    predictions: list[dict[str, object]],
    source: SourceInfo,
    coordinate_width: int = 256,
    coordinate_height: int = 256,
    snap_tolerance: float = 2.0,
) -> BaojuModel:
    index = _NodeIndex(snap_tolerance)
    rooms: list[Room] = []
    walls: list[Wall] = []
    openings_raw: list[tuple[str, list[Point]]] = []
    issues: list[Issue] = []
    wall_by_nodes: dict[tuple[str, str], Wall] = {}

    for prediction_index, prediction in enumerate(predictions):
        try:
            category_id = int(prediction.get("category_id", -1))
        except (TypeError, ValueError):
            category_id = -1
        polygon = _clean_polygon(prediction.get("segmentation"))
        if category_id in OPENING_TYPES:
            if len(polygon) >= 2:
                openings_raw.append((OPENING_TYPES[category_id], polygon))
            else:
                issues.append(
                    Issue(
                        id=f"issue{len(issues) + 1}",
                        severity="warning",
                        code="invalid_opening_polygon",
                        message="AI 回傳的門窗幾何不足，已略過。",
                    )
                )
            continue
        if len(polygon) < 3:
            issues.append(
                Issue(
                    id=f"issue{len(issues) + 1}",
                    severity="warning",
                    code="invalid_room_polygon",
                    message=f"AI polygon {prediction_index} 少於三個有效頂點，已略過。",
                )
            )
            continue

        room_id = f"r{len(rooms) + 1}"
        node_ids = [index.get_or_create(point) for point in polygon]
        deduplicated_node_ids = [
            node_id for idx, node_id in enumerate(node_ids) if idx == 0 or node_id != node_ids[idx - 1]
        ]
        if len(deduplicated_node_ids) > 1 and deduplicated_node_ids[0] == deduplicated_node_ids[-1]:
            deduplicated_node_ids.pop()
        if len(set(deduplicated_node_ids)) < 3:
            issues.append(
                Issue(
                    id=f"issue{len(issues) + 1}",
                    severity="warning",
                    code="collapsed_room_polygon",
                    message=f"房間 {room_id} 在端點吸附後發生塌縮，已略過。",
                )
            )
            continue

        rooms.append(
            Room(
                id=room_id,
                name=CC5K_LABELS.get(category_id, "未分類空間"),
                categoryId=category_id,
                nodeIds=deduplicated_node_ids,
                confidence=None,
            )
        )
        for edge_index, start_node in enumerate(deduplicated_node_ids):
            end_node = deduplicated_node_ids[(edge_index + 1) % len(deduplicated_node_ids)]
            if start_node == end_node:
                continue
            key = tuple(sorted((start_node, end_node)))
            existing = wall_by_nodes.get(key)
            if existing:
                if room_id not in existing.room_ids:
                    existing.room_ids.append(room_id)
                continue
            wall = Wall(
                id=f"w{len(walls) + 1}",
                startNode=start_node,
                endNode=end_node,
                thicknessMm=None,
                heightMm=2800,
                confidence=None,
                source=ConfidenceSource.AI,
                roomIds=[room_id],
            )
            walls.append(wall)
            wall_by_nodes[key] = wall

    nodes_by_id = {node.id: node for node in index.nodes}
    openings: list[Opening] = []
    for opening_type, polygon in openings_raw:
        center = Point(
            x=sum(point.x for point in polygon) / len(polygon),
            y=sum(point.y for point in polygon) / len(polygon),
        )
        nearest: tuple[float, float, Wall] | None = None
        for wall in walls:
            distance, offset = _point_segment_projection(
                center, nodes_by_id[wall.start_node], nodes_by_id[wall.end_node]
            )
            if nearest is None or distance < nearest[0]:
                nearest = (distance, offset, wall)
        wall_id = nearest[2].id if nearest and nearest[0] <= max(8.0, _polygon_extent(polygon)) else None
        offset = nearest[1] if wall_id and nearest else None
        opening_id = f"o{len(openings) + 1}"
        openings.append(
            Opening(
                id=opening_id,
                type=opening_type,
                wallId=wall_id,
                offset=offset,
                width=max(_polygon_extent(polygon), 1.0),
                heightMm=2100 if opening_type == "door" else 1200,
                sillHeightMm=None if opening_type == "door" else 900,
                confidence=None,
                sourcePolygon=polygon,
            )
        )
        if wall_id is None:
            issues.append(
                Issue(
                    id=f"issue{len(issues) + 1}",
                    severity="warning",
                    code="unattached_opening",
                    message=f"{opening_type} 無法可靠地附著到牆，請人工確認。",
                    entityId=opening_id,
                )
            )

    issues.append(
        Issue(
            id=f"issue{len(issues) + 1}",
            severity="info",
            code="confidence_unavailable",
            message="Raster2Seq 官方 prediction JSON 未輸出個別 polygon confidence，介面不會捏造信心分數。",
        )
    )
    issues.append(
        Issue(
            id=f"issue{len(issues) + 1}",
            severity="info",
            code="calibration_required",
            message="目前座標仍為模型像素；請選兩點輸入真實距離後轉換成 mm。",
        )
    )

    return BaojuModel(
        source=source,
        coordinateSpace=CoordinateSpace(width=coordinate_width, height=coordinate_height, imageFit="contain"),
        calibration=Calibration(status="required", coordinateUnit=CoordinateUnit.PIXEL, mmPerUnit=None),
        nodes=index.nodes,
        walls=walls,
        openings=openings,
        rooms=rooms,
        issues=issues,
    )


def calibrate_model(request: CalibrationRequest) -> BaojuModel:
    model = request.model.model_copy(deep=True)
    if model.calibration.status == "calibrated":
        raise ValueError("model is already calibrated")
    pixel_distance = math.hypot(
        request.point_b.x - request.point_a.x,
        request.point_b.y - request.point_a.y,
    )
    if pixel_distance <= 0:
        raise ValueError("calibration points must be different")
    mm_per_pixel = request.known_distance_mm / pixel_distance

    for node in model.nodes:
        node.x *= mm_per_pixel
        node.y *= mm_per_pixel
    for opening in model.openings:
        opening.width *= mm_per_pixel
        if opening.offset is not None:
            opening.offset *= mm_per_pixel
        for point in opening.source_polygon:
            point.x *= mm_per_pixel
            point.y *= mm_per_pixel
    model.coordinate_space.width *= mm_per_pixel
    model.coordinate_space.height *= mm_per_pixel
    model.calibration = Calibration(
        status="calibrated",
        coordinateUnit=CoordinateUnit.MILLIMETER,
        mmPerUnit=1,
    )
    model.issues = [issue for issue in model.issues if issue.code != "calibration_required"]
    return model


def wall_length(model: BaojuModel, wall: Wall) -> float:
    nodes = {node.id: node for node in model.nodes}
    start, end = nodes[wall.start_node], nodes[wall.end_node]
    return math.hypot(end.x - start.x, end.y - start.y)


def iter_room_points(model: BaojuModel, room: Room) -> Iterable[Point]:
    nodes = {node.id: node for node in model.nodes}
    for node_id in room.node_ids:
        node = nodes[node_id]
        yield Point(x=node.x, y=node.y)
