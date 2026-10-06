import copy

import pytest

from backend.app.domain.models import CalibrationRequest, Point, SourceInfo
from backend.app.services.geometry import calibrate_model, raster2seq_to_baoju, wall_length


@pytest.fixture
def source() -> SourceInfo:
    return SourceInfo(
        filename="plan.png",
        mimeType="image/png",
        width=800,
        height=600,
        sha256="a" * 64,
    )


@pytest.fixture
def adjacent_rooms_prediction():
    return [
        {
            "segmentation": [[0, 0], [100, 0], [100, 100], [0, 100]],
            "category_id": 2,
        },
        {
            "segmentation": [[100, 0], [200, 0], [200, 100], [100, 100]],
            "category_id": 3,
        },
        {
            "segmentation": [[98, 40], [102, 40], [102, 60], [98, 60]],
            "category_id": 10,
        },
    ]


def test_builds_shared_topological_wall(source, adjacent_rooms_prediction):
    model = raster2seq_to_baoju(adjacent_rooms_prediction, source)

    assert len(model.rooms) == 2
    assert len(model.nodes) == 6
    assert len(model.walls) == 7
    shared_walls = [wall for wall in model.walls if len(wall.room_ids) == 2]
    assert len(shared_walls) == 1
    assert set(shared_walls[0].room_ids) == {"r1", "r2"}


def test_attaches_opening_to_nearest_wall(source, adjacent_rooms_prediction):
    model = raster2seq_to_baoju(adjacent_rooms_prediction, source)

    assert len(model.openings) == 1
    opening = model.openings[0]
    assert opening.type == "door"
    assert opening.wall_id is not None
    host_wall = next(wall for wall in model.walls if wall.id == opening.wall_id)
    assert len(host_wall.room_ids) == 2
    assert opening.offset == pytest.approx(50)


def test_calibration_converts_all_planar_geometry_to_mm(source, adjacent_rooms_prediction):
    model = raster2seq_to_baoju(adjacent_rooms_prediction, source)
    original = copy.deepcopy(model)
    request = CalibrationRequest(
        model=model,
        pointA=Point(x=0, y=0),
        pointB=Point(x=100, y=0),
        knownDistanceMm=5000,
    )

    calibrated = calibrate_model(request)

    assert calibrated.calibration.status == "calibrated"
    assert calibrated.calibration.coordinate_unit.value == "mm"
    assert calibrated.coordinate_space.width == 12800
    assert wall_length(calibrated, calibrated.walls[0]) == pytest.approx(
        wall_length(original, original.walls[0]) * 50
    )
    assert calibrated.openings[0].width == pytest.approx(original.openings[0].width * 50)
    assert not any(issue.code == "calibration_required" for issue in calibrated.issues)


def test_invalid_polygons_are_reported_not_invented(source):
    model = raster2seq_to_baoju(
        [{"segmentation": [[1, 1], [2, 2]], "category_id": 2}],
        source,
    )

    assert model.rooms == []
    assert any(issue.code == "invalid_room_polygon" for issue in model.issues)
