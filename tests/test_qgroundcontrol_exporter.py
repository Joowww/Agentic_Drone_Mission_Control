"""The interactive/Hermes export entry delegates to the strict exporter.

Until 27/10/2026 this entry turned survey/take_photo into plain waypoints, wrote the relative home altitude (0 m)
as plannedHomePosition AMSL and ended with RTL. These tests pin that it now refuses instead, and that with an AMSL
source it produces exactly the strict exporter's bytes.
"""
import json

import pytest

from inputs.json_loader import load_mission_json
from inputs.qgc_plan_export import build_plan, plan_bytes
from inputs.qgroundcontrol_adapter import (
    load_qgroundcontrol_plan,
)
from inputs.qgroundcontrol_exporter import (
    ExportRefused,
    build_qgroundcontrol_plan,
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


def test_session_example_with_photo_actions_is_refused_not_flattened(
    tmp_path,
):
    # The mission the old test exported: PX4, survey/take_photo actions, no AMSL.
    mission = load_mission_json(
        "missions/examples/"
        "precision_agriculture_demo.json"
    )

    output_path = (
        tmp_path
        / "out"
        / "precision_agriculture.plan"
    )

    with pytest.raises(ExportRefused) as refusal:
        export_qgroundcontrol_plan(
            mission=mission,
            file_path=output_path,
        )

    text = " ".join(refusal.value.reasons)

    assert "survey" in text and "take_photo" in text
    assert "PX4" in text
    assert "AMSL" in text
    assert not output_path.parent.exists()


def test_missing_amsl_is_refused_instead_of_writing_zero(
    tmp_path,
):
    mission = load_mission_json(
        "missions/examples/"
        "agri_demo_001_sector_a.json"
    )

    with pytest.raises(ExportRefused, match="AMSL"):
        build_qgroundcontrol_plan(
            mission
        )

    output_path = tmp_path / "a.plan"

    with pytest.raises(ExportRefused):
        export_qgroundcontrol_plan(
            mission=mission,
            file_path=output_path,
        )

    assert not output_path.exists()


def test_with_amsl_the_entry_writes_the_strict_bytes(
    tmp_path,
):
    mission = load_mission_json(
        "missions/examples/"
        "agri_demo_001_sector_a.json"
    )

    output_path = tmp_path / "a.plan"

    export_qgroundcontrol_plan(
        mission=mission,
        file_path=output_path,
        planned_home_amsl_m=584.0,
    )

    strict, _log = build_plan(
        mission,
        planned_home_amsl_m=584.0,
    )

    assert output_path.read_bytes() == plan_bytes(strict)

    commands = [
        item["command"]
        for item in json.loads(
            output_path.read_text()
        )["mission"]["items"]
    ]

    assert commands == [22, 178, 16, 16, 21]


def test_qgroundcontrol_round_trip_keeps_geometry_and_shows_losses(
    tmp_path,
):
    original = load_mission_json(
        "missions/examples/"
        "agri_demo_001_sector_a.json"
    )

    output_path = (
        tmp_path
        / "round_trip.plan"
    )

    export_qgroundcontrol_plan(
        mission=original,
        file_path=output_path,
        planned_home_amsl_m=584.0,
    )

    imported_result = load_qgroundcontrol_plan(
        file_path=str(output_path),
        context=_build_import_context(
            original
        ),
    )

    imported = imported_result.mission.route.waypoints

    # The two mission waypoints come back; the importer adds the LAND as a third
    # "navigation endpoint" and skips TAKEOFF, with warnings.
    assert len(imported) == len(original.route.waypoints) + 1

    for got, want in zip(imported, original.route.waypoints):
        assert got.latitude == pytest.approx(want.latitude, abs=1e-8)
        assert got.longitude == pytest.approx(want.longitude, abs=1e-8)
        assert got.altitude_m == pytest.approx(want.altitude_m)

    assert any("TAKEOFF" in w for w in imported_result.warnings)
    assert any("LAND" in w for w in imported_result.warnings)
    assert imported_result.planned_home_amsl_m == 584.0


def test_extension_is_still_checked(
    tmp_path,
):
    mission = load_mission_json(
        "missions/examples/"
        "agri_demo_001_sector_a.json"
    )

    with pytest.raises(ValueError, match=".plan extension"):
        export_qgroundcontrol_plan(
            mission=mission,
            file_path=tmp_path / "a.json",
            planned_home_amsl_m=584.0,
        )
