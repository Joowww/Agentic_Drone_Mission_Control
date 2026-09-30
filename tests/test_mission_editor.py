import pytest

from editing.deterministic_update_parser import (
    parse_deterministic_mission_update,
)
from editing.mission_update_service import (
    apply_mission_update,
)


def test_battery_update_is_deterministic(
    qgc_mission,
):
    update = (
        parse_deterministic_mission_update(
            user_input=(
                "Change the battery to 70%."
            ),
            mission=qgc_mission,
        )
    )

    assert (
        update.battery_percent
        == 70.0
    )

    updated_mission, changes = (
        apply_mission_update(
            mission=qgc_mission,
            update=update,
        )
    )

    assert (
        updated_mission
        .vehicle
        .battery_percent
        == 70.0
    )

    assert any(
        "Battery"
        in change
        for change in changes
    )


def test_west_wind_update_is_deterministic(
    qgc_mission,
):
    update = (
        parse_deterministic_mission_update(
            user_input=(
                "Set the wind to 10 km/h "
                "coming from the west."
            ),
            mission=qgc_mission,
        )
    )

    assert (
        update.wind_speed_kmh
        == 10.0
    )

    assert (
        update.wind_direction_from
        == "west"
    )

    assert (
        update.wind_direction_from_deg
        == 270.0
    )


def test_qgc_waypoint_altitude_update(
    qgc_mission,
):
    update = (
        parse_deterministic_mission_update(
            user_input=(
                "Set QGC_WP2 altitude "
                "to 150 meters."
            ),
            mission=qgc_mission,
        )
    )

    assert (
        len(
            update.waypoint_updates
        )
        == 1
    )

    waypoint_update = (
        update.waypoint_updates[
            0
        ]
    )

    assert (
        waypoint_update.waypoint_id
        == "QGC_WP2"
    )

    assert (
        waypoint_update.altitude_m
        == 150.0
    )

    updated_mission, changes = (
        apply_mission_update(
            mission=qgc_mission,
            update=update,
        )
    )

    assert (
        updated_mission
        .route
        .waypoints[
            1
        ]
        .altitude_m
        == 150.0
    )

    assert any(
        "QGC_WP2 altitude"
        in change
        for change in changes
    )


def test_invalid_battery_is_rejected(
    qgc_mission,
):
    original_battery = (
        qgc_mission
        .vehicle
        .battery_percent
    )

    update = (
        parse_deterministic_mission_update(
            user_input=(
                "Change the battery to 150%."
            ),
            mission=qgc_mission,
        )
    )

    assert (
        update.battery_percent
        == 150.0
    )

    with pytest.raises(
        ValueError,
        match="invalid mission",
    ):
        apply_mission_update(
            mission=qgc_mission,
            update=update,
        )

    assert (
        qgc_mission
        .vehicle
        .battery_percent
        == original_battery
    )