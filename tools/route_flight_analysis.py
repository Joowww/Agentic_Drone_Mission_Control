from models.mission_definition import (
    MissionDefinition,
)
from tools.flight_dynamics import (
    calculate_flight_time,
)
from tools.route_geometry import (
    analyze_waypoint_route,
)

VERTICAL_LEG_NOT_MODELLED = "VERTICAL_LEG_NOT_MODELLED"
NO_DISPLACEMENT = "NO_DISPLACEMENT"


def _zero_horizontal_leg_result(
    leg: dict,
) -> dict:
    """Diagnose a leg without horizontal displacement.

    The flight-time model only covers horizontal motion, so such a leg
    is not evaluated (and the mission is not approved). This is not a
    wind or performance verdict.
    """
    if leg["altitude_change_m"] != 0:
        return {
            "status": "not_modelled",
            "reason": VERTICAL_LEG_NOT_MODELLED,
            "message": (
                "Vertical-only leg: the current flight-time model "
                "evaluates horizontal motion only and does not "
                "assess this leg."
            ),
        }

    return {
        "status": "no_displacement",
        "reason": NO_DISPLACEMENT,
        "message": (
            "Leg without displacement: same horizontal position "
            "and altitude as the previous point."
        ),
    }


def analyze_mission_flight(
    mission: MissionDefinition,
) -> dict:
    route_analysis = analyze_waypoint_route(
        mission.route
    )

    leg_results = []

    total_flight_time_minutes = 0.0

    mission_safe = True

    for leg in route_analysis[
        "legs"
    ]:
        airspeed_kmh = (
            leg["speed_kmh"]
            if leg["speed_kmh"] is not None
            else mission.vehicle.cruise_speed_kmh
        )

        if leg["distance_km_exact"] == 0:
            flight_result = _zero_horizontal_leg_result(
                leg
            )

        else:
            flight_result = calculate_flight_time(
                distance_km=leg[
                    "distance_km_exact"
                ],
                drone_speed_kmh=airspeed_kmh,
                wind_speed_kmh=mission.environment.wind_speed_kmh,
                flight_bearing_deg=leg[
                    "bearing_deg"
                ],
                wind_direction_from_deg=mission.environment.wind_direction_from_deg,
            )

        leg_result = {
            "leg_number":
                leg["leg_number"],
            "from":
                leg["from"],
            "to":
                leg["to"],
            "distance_km":
                leg["distance_km"],
            "distance_km_exact":
                leg["distance_km_exact"],
            "bearing_deg":
                leg["bearing_deg"],
            "altitude_change_m":
                leg["altitude_change_m"],
            "airspeed_kmh":
                airspeed_kmh,
            "destination_action":
                leg["destination_action"],
            "flight_result":
                flight_result,
        }

        leg_results.append(
            leg_result
        )

        if (
            flight_result.get("status")
            == "success"
        ):
            total_flight_time_minutes += (
                flight_result[
                    "flight_time_minutes_exact"
                ]
            )

        else:
            mission_safe = False

    return {
        "status": (
            "success"
            if mission_safe
            else "unsafe"
        ),
        "total_horizontal_distance_km":
            route_analysis[
                "total_horizontal_distance_km"
            ],
        # Rounded for presentation; battery and later decisions use the exact sum.
        "total_flight_time_minutes": (
            round(
                total_flight_time_minutes,
                2,
            )
            if mission_safe
            else None
        ),
        "total_flight_time_minutes_exact": (
            total_flight_time_minutes
            if mission_safe
            else None
        ),
        "total_climb_m":
            route_analysis[
                "total_climb_m"
            ],
        "total_descent_m":
            route_analysis[
                "total_descent_m"
            ],
        "leg_results":
            leg_results,
    }
