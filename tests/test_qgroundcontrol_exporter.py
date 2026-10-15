import json

import pytest

from inputs.json_loader import load_mission_json
from inputs.qgroundcontrol_adapter import (
    load_qgroundcontrol_plan,
)
from inputs.qgroundcontrol_exporter import (
    export_qgroundcontrol_plan,
)
from models.qgc_import import (
    QGroundControlImportContext,
)


def _build_import_context(
    mission,
) -> QGroundControlImportContext:
    return QGroundControlImportContext(
        battery_percent=(
            mission.vehicle.battery_percent
        ),
        battery_consumption_percent_per_minute=(
            mission.vehicle
            .battery_consumption_percent_per_minute
        ),
        wind_speed_kmh=(
            mission.environment.wind_speed_kmh
        ),
        wind_direction_from_deg=(
            mission.environment
            .wind_direction_from_deg
        ),
        minimum_battery_reserve_percent=(
            mission.constraints
            .minimum_battery_reserve_percent
        ),
        maximum_wind_speed_kmh=(
            mission.constraints
            .maximum_wind_speed_kmh
        ),
        maximum_altitude_m=(
            mission.constraints
            .maximum_altitude_m
        ),
    )


def test_export_qgroundcontrol_plan(
    tmp_path,
):
    mission = load_mission_json(
        "missions/examples/"
        "precision_agriculture_demo.json"
    )

    output_path = (
        tmp_path
        / "precision_agriculture.plan"
    )

    saved_path = export_qgroundcontrol_plan(
        mission=mission,
        file_path=output_path,
    )

    assert saved_path == output_path
    assert output_path.exists()

    data = json.loads(
        output_path.read_text(
            encoding="utf-8"
        )
    )

    assert data["fileType"] == "Plan"
    assert (
        data["groundStation"]
        == "QGroundControl"
    )

    qgc_mission = data["mission"]

    assert qgc_mission["firmwareType"] == 12
    assert qgc_mission["vehicleType"] == 2

    assert (
        qgc_mission[
            "plannedHomePosition"
        ][0]
        == pytest.approx(
            mission.route.home.latitude
        )
    )

    commands = [
        item["command"]
        for item in qgc_mission["items"]
    ]

    assert commands[0] == 22
    assert commands[-1] == 20

    waypoint_commands = [
        command
        for command in commands
        if command == 16
    ]

    assert len(
        waypoint_commands
    ) == len(
        mission.route.waypoints
    )


def test_qgroundcontrol_round_trip(
    tmp_path,
):
    original = load_mission_json(
        "missions/examples/"
        "precision_agriculture_demo.json"
    )

    output_path = (
        tmp_path
        / "round_trip.plan"
    )

    export_qgroundcontrol_plan(
        mission=original,
        file_path=output_path,
    )

    imported_result = load_qgroundcontrol_plan(
        file_path=str(output_path),
        context=_build_import_context(
            original
        ),
    )

    imported = imported_result.mission

    assert (
        imported.vehicle.vehicle_type
        == original.vehicle.vehicle_type
    )

    assert (
        imported.vehicle.autopilot
        == original.vehicle.autopilot
    )

    assert (
        imported.vehicle.cruise_speed_kmh
        == pytest.approx(
            original.vehicle.cruise_speed_kmh,
            abs=0.02,
        )
    )

    assert (
        imported.route.return_to_home
        == original.route.return_to_home
    )

    assert (
        len(imported.route.waypoints)
        == len(original.route.waypoints)
    )

    for original_wp, imported_wp in zip(
        original.route.waypoints,
        imported.route.waypoints,
        strict=True,
    ):
        assert (
            imported_wp.latitude
            == pytest.approx(
                original_wp.latitude
            )
        )

        assert (
            imported_wp.longitude
            == pytest.approx(
                original_wp.longitude
            )
        )

        assert (
            imported_wp.altitude_m
            == pytest.approx(
                original_wp.altitude_m
            )
        )