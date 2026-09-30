from models.mission_plan_draft import (
    MissionPlanDraft,
    PlannedWaypointDraft,
)
from planning.deterministic_plan_parser import (
    parse_deterministic_plan_fields,
)
from planning.mission_plan_service import (
    build_mission_from_draft,
    get_missing_planning_fields,
    merge_mission_plan_drafts,
)


def test_precision_agriculture_is_detected():
    draft = (
        parse_deterministic_plan_fields(
            "Create a precision agriculture "
            "mission for Field C."
        )
    )

    assert (
        draft.objective_type
        == "precision_agriculture"
    )

    assert (
        draft.objective_target
        is not None
    )

    assert (
        draft.objective_target.lower()
        == "field_c"
    )


def test_vehicle_and_autopilot_are_detected():
    draft = (
        parse_deterministic_plan_fields(
            "Use a PX4 multirotor and "
            "return to home after the mission."
        )
    )

    assert (
        draft.vehicle_type
        == "multirotor"
    )

    assert (
        draft.autopilot
        == "PX4"
    )

    assert (
        draft.return_to_home
        is True
    )


def test_planner_does_not_invent_missing_data():
    draft = (
        parse_deterministic_plan_fields(
            "Create a precision agriculture "
            "mission for Field C."
        )
    )

    missing = (
        get_missing_planning_fields(
            draft
        )
    )

    assert (
        "objective type"
        not in missing
    )

    assert (
        "objective target"
        not in missing
    )

    assert (
        "current battery percentage"
        in missing
    )

    assert (
        "home latitude"
        in missing
    )

    assert (
        "home longitude"
        in missing
    )

    assert (
        "wind speed"
        in missing
    )

    assert (
        "at least one waypoint"
        in missing
    )


def test_complete_draft_builds_mission_definition():
    draft = MissionPlanDraft(
        name=(
            "Field B Precision "
            "Agriculture Inspection"
        ),

        vehicle_id="drone_01",

        vehicle_type="multirotor",

        autopilot="PX4",

        cruise_speed_kmh=35.0,

        battery_percent=82.0,

        battery_consumption_percent_per_minute=0.8,

        objective_type=(
            "precision_agriculture"
        ),

        objective_target="field_B",

        home_latitude=41.2750,

        home_longitude=1.9870,

        home_altitude_m=0.0,

        waypoints=[
            PlannedWaypointDraft(
                waypoint_id="WP1",
                latitude=41.2760,
                longitude=1.9890,
                altitude_m=30.0,
                speed_kmh=30.0,
                action="navigate",
            ),

            PlannedWaypointDraft(
                waypoint_id="WP2",
                latitude=41.2780,
                longitude=1.9920,
                altitude_m=30.0,
                speed_kmh=25.0,
                action="survey",
            ),

            PlannedWaypointDraft(
                waypoint_id="WP3",
                latitude=41.2765,
                longitude=1.9950,
                altitude_m=30.0,
                speed_kmh=25.0,
                action="take_photo",
            ),
        ],

        return_to_home=True,

        wind_speed_kmh=12.0,

        wind_direction_from="north",

        minimum_battery_reserve_percent=20.0,

        maximum_wind_speed_kmh=30.0,

        maximum_altitude_m=120.0,
    )

    mission = (
        build_mission_from_draft(
            draft
        )
    )

    assert (
        mission.source
        == "natural_language"
    )

    assert (
        mission.vehicle.autopilot
        == "PX4"
    )

    assert (
        mission.objective.objective_type
        == "precision_agriculture"
    )

    assert (
        mission.environment
        .wind_direction_from_deg
        == 0.0
    )

    assert (
        len(
            mission.route.waypoints
        )
        == 3
    )

    assert (
        mission.route.return_to_home
        is True
    )


def test_progressive_mission_draft_merge():
    current = MissionPlanDraft(
        name=(
            "Field C Mission"
        ),

        objective_type=(
            "precision_agriculture"
        ),

        objective_target=(
            "field_c"
        ),

        vehicle_type=(
            "multirotor"
        ),

        autopilot="PX4",

        waypoints=[
            PlannedWaypointDraft(
                waypoint_id="WP1",
                latitude=41.2760,
                longitude=1.9890,
                altitude_m=None,
            )
        ],
    )

    new = MissionPlanDraft(
        battery_percent=82.0,

        cruise_speed_kmh=35.0,

        wind_speed_kmh=12.0,

        waypoints=[
            PlannedWaypointDraft(
                waypoint_id="WP1",
                altitude_m=30.0,
                speed_kmh=25.0,
            ),

            PlannedWaypointDraft(
                waypoint_id="WP2",
                latitude=41.2780,
                longitude=1.9920,
                altitude_m=30.0,
                action="survey",
            ),
        ],
    )

    merged = (
        merge_mission_plan_drafts(
            current=current,
            new=new,
        )
    )

    assert (
        merged.name
        == "Field C Mission"
    )

    assert (
        merged.objective_type
        == "precision_agriculture"
    )

    assert (
        merged.objective_target
        == "field_c"
    )

    assert (
        merged.vehicle_type
        == "multirotor"
    )

    assert (
        merged.autopilot
        == "PX4"
    )

    assert (
        merged.battery_percent
        == 82.0
    )

    assert (
        merged.cruise_speed_kmh
        == 35.0
    )

    assert (
        merged.wind_speed_kmh
        == 12.0
    )

    assert (
        len(
            merged.waypoints
        )
        == 2
    )

    wp1 = (
        merged.waypoints[
            0
        ]
    )

    assert (
        wp1.waypoint_id
        == "WP1"
    )

    assert (
        wp1.latitude
        == 41.2760
    )

    assert (
        wp1.longitude
        == 1.9890
    )

    assert (
        wp1.altitude_m
        == 30.0
    )

    assert (
        wp1.speed_kmh
        == 25.0
    )

    wp2 = (
        merged.waypoints[
            1
        ]
    )

    assert (
        wp2.waypoint_id
        == "WP2"
    )

    assert (
        wp2.action
        == "survey"
    )