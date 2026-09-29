from models.mission_definition import (
    MissionDefinition,
)
from tools.flight_dynamics import (
    calculate_flight_time,
)
from tools.route_geometry import (
    analyze_waypoint_route,
)


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

        flight_result = calculate_flight_time(
            distance_km=leg[
                "distance_km"
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
            "bearing_deg":
                leg["bearing_deg"],
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
                    "flight_time_minutes"
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
        "total_flight_time_minutes": (
            round(
                total_flight_time_minutes,
                2,
            )
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