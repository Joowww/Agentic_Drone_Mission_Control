import pytest

from editing.mission_update_guard import (
    validate_update_grounding,
)
from models.mission_update import (
    MissionUpdate,
    WaypointUpdate,
)


def test_guard_rejects_ungrounded_waypoint_removal(
    qgc_mission,
):
    update = MissionUpdate(
        wind_speed_kmh=35.0,
        waypoint_removals=[
            "QGC_WP3"
        ],
    )

    with pytest.raises(
        ValueError,
        match=(
            "not grounded"
        ),
    ):
        validate_update_grounding(
            user_input=(
                "Set the wind to "
                "35 km/h from the north."
            ),
            update=update,
            mission=qgc_mission,
        )


def test_guard_accepts_grounded_waypoint_update(
    qgc_mission,
):
    update = MissionUpdate(
        waypoint_updates=[
            WaypointUpdate(
                waypoint_id=(
                    "QGC_WP2"
                ),
                altitude_m=150.0,
            )
        ]
    )

    validate_update_grounding(
        user_input=(
            "Set QGC_WP2 altitude "
            "to 150 meters."
        ),
        update=update,
        mission=qgc_mission,
    )