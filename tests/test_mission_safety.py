from editing.deterministic_update_parser import (
    parse_deterministic_mission_update,
)
from editing.mission_update_service import (
    apply_mission_update,
)
from safety.mission_safety_analysis import (
    evaluate_mission_safety,
)


def test_nominal_qgc_mission_is_feasible(
    qgc_mission,
):
    result = (
        evaluate_mission_safety(
            qgc_mission
        )
    )

    assert (
        result[
            "mission_status"
        ]
        == "FEASIBLE"
    )

    assert (
        result[
            "failure_reasons"
        ]
        == []
    )


def test_qgc_altitude_violation_is_rejected(
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

    updated_mission, _ = (
        apply_mission_update(
            mission=qgc_mission,
            update=update,
        )
    )

    result = (
        evaluate_mission_safety(
            updated_mission
        )
    )

    assert (
        result[
            "mission_status"
        ]
        == "NOT FEASIBLE"
    )

    assert (
        "The planned route exceeds "
        "the maximum allowed altitude."
        in result[
            "failure_reasons"
        ]
    )


def test_low_battery_is_not_feasible(
    qgc_mission,
):
    update = (
        parse_deterministic_mission_update(
            user_input=(
                "Change the battery to 25%."
            ),
            mission=qgc_mission,
        )
    )

    updated_mission, _ = (
        apply_mission_update(
            mission=qgc_mission,
            update=update,
        )
    )

    result = (
        evaluate_mission_safety(
            updated_mission
        )
    )

    assert (
        result[
            "mission_status"
        ]
        == "NOT FEASIBLE"
    )

    assert (
        "The vehicle would finish "
        "the mission below the required "
        "battery reserve."
        in result[
            "failure_reasons"
        ]
    )