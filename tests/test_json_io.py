from pathlib import Path

from inputs.json_loader import (
    load_mission_json,
)
from inputs.json_saver import (
    save_mission_json,
)

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


def test_json_loader_returns_valid_mission():
    mission_path = (
        PROJECT_ROOT
        / "missions"
        / "examples"
        / "precision_agriculture_demo.json"
    )

    mission = load_mission_json(
        str(
            mission_path
        )
    )

    assert (
        mission.mission_id
        == "precision_agriculture_001"
    )

    assert (
        mission.name
        == "Field A Crop Inspection"
    )

    assert (
        mission.source
        == "json"
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
        mission.objective.objective_type
        == "precision_agriculture"
    )

    assert (
        mission.route.mode
        == "waypoints"
    )

    assert (
        len(
            mission.route.waypoints
        )
        == 3
    )

    assert (
        mission.route.home
        is not None
    )


def test_json_save_and_reload_preserves_mission(
    tmp_path,
    qgc_mission,
):
    output_path = (
        tmp_path
        / "saved_mission.json"
    )

    saved_path = save_mission_json(
        mission=qgc_mission,
        file_path=str(
            output_path
        ),
    )

    assert (
        saved_path.exists()
    )

    assert (
        saved_path.suffix
        == ".json"
    )

    reloaded_mission = (
        load_mission_json(
            str(
                saved_path
            )
        )
    )

    assert (
        reloaded_mission
        == qgc_mission
    )

    assert (
        reloaded_mission.model_dump(
            mode="json"
        )
        == qgc_mission.model_dump(
            mode="json"
        )
    )