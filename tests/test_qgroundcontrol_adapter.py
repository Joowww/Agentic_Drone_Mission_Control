import json

import pytest

from inputs.qgroundcontrol_adapter import (
    load_qgroundcontrol_plan,
)


def test_qgc_imports_expected_structure(
    qgc_import_result,
):
    result = qgc_import_result

    assert (
        result.source_item_count
        == 5
    )

    assert (
        result.imported_waypoint_count
        == 3
    )

    assert (
        result.planned_home_amsl_m
        == 250.0
    )

    mission = result.mission

    assert (
        mission.source
        == "qgroundcontrol"
    )

    assert (
        mission.vehicle.autopilot
        == "PX4"
    )

    assert (
        mission.vehicle.vehicle_type
        == "multirotor"
    )

    assert (
        mission.vehicle.cruise_speed_kmh
        == 18.0
    )

    assert (
        mission.route.return_to_home
        is True
    )

    waypoint_ids = [
        waypoint.waypoint_id
        for waypoint
        in mission.route.waypoints
    ]

    assert waypoint_ids == [
        "QGC_WP1",
        "QGC_WP2",
        "QGC_WP3",
    ]


def test_qgc_takeoff_warning_is_reported(
    qgc_import_result,
):
    assert any(
        "MAV_CMD_NAV_TAKEOFF"
        in warning
        for warning
        in qgc_import_result.warnings
    )


def test_qgc_home_is_normalized_to_zero(
    qgc_import_result,
):
    home = (
        qgc_import_result
        .mission
        .route
        .home
    )

    assert home is not None

    assert (
        home.latitude
        == pytest.approx(
            41.2750
        )
    )

    assert (
        home.longitude
        == pytest.approx(
            1.9870
        )
    )

    assert (
        home.altitude_m
        == 0.0
    )


def test_qgc_complex_item_is_rejected(
    tmp_path,
    qgc_plan_path,
    qgc_context,
):
    with qgc_plan_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(
            file
        )

    data[
        "mission"
    ][
        "items"
    ] = [
        {
            "type": "ComplexItem",
            "complexItemType": "survey",
        }
    ]

    complex_plan = (
        tmp_path
        / "complex_mission.plan"
    )

    with complex_plan.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
        )

    with pytest.raises(
        ValueError,
        match="SimpleItem missions only",
    ):
        load_qgroundcontrol_plan(
            file_path=str(
                complex_plan
            ),
            context=qgc_context,
        )