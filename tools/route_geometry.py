import math

from models.mission_definition import (
    RouteDefinition,
)

EARTH_RADIUS_KM = 6371.0088


def haversine_distance_km(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    latitude_1_rad = math.radians(
        latitude_1
    )

    latitude_2_rad = math.radians(
        latitude_2
    )

    delta_latitude_rad = math.radians(
        latitude_2 - latitude_1
    )

    delta_longitude_rad = math.radians(
        longitude_2 - longitude_1
    )

    a = (
        math.sin(
            delta_latitude_rad / 2
        ) ** 2
        + math.cos(
            latitude_1_rad
        )
        * math.cos(
            latitude_2_rad
        )
        * math.sin(
            delta_longitude_rad / 2
        ) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )

    return (
        EARTH_RADIUS_KM
        * c
    )


def calculate_initial_bearing_deg(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    latitude_1_rad = math.radians(
        latitude_1
    )

    latitude_2_rad = math.radians(
        latitude_2
    )

    delta_longitude_rad = math.radians(
        longitude_2 - longitude_1
    )

    x = (
        math.sin(
            delta_longitude_rad
        )
        * math.cos(
            latitude_2_rad
        )
    )

    y = (
        math.cos(
            latitude_1_rad
        )
        * math.sin(
            latitude_2_rad
        )
        - math.sin(
            latitude_1_rad
        )
        * math.cos(
            latitude_2_rad
        )
        * math.cos(
            delta_longitude_rad
        )
    )

    bearing = math.degrees(
        math.atan2(
            x,
            y,
        )
    )

    return (
        bearing + 360
    ) % 360


def analyze_waypoint_route(
    route: RouteDefinition,
) -> dict:
    if route.mode != "waypoints":
        raise ValueError(
            "Route analysis requires waypoint mode."
        )

    if route.home is None:
        raise ValueError(
            "Waypoint route analysis requires a home position."
        )

    route_points = [
        {
            "point_id": "HOME",
            "latitude": route.home.latitude,
            "longitude": route.home.longitude,
            "altitude_m": route.home.altitude_m,
            "action": "home",
        }
    ]

    for waypoint in route.waypoints:
        route_points.append(
            {
                "point_id": waypoint.waypoint_id,
                "latitude": waypoint.latitude,
                "longitude": waypoint.longitude,
                "altitude_m": waypoint.altitude_m,
                "action": waypoint.action,
            }
        )

    if route.return_to_home:
        route_points.append(
            {
                "point_id": "HOME",
                "latitude": route.home.latitude,
                "longitude": route.home.longitude,
                "altitude_m": route.home.altitude_m,
                "action": "return_to_home",
            }
        )

    legs = []

    total_horizontal_distance_km = 0.0
    total_climb_m = 0.0
    total_descent_m = 0.0

    for index in range(
        len(route_points) - 1
    ):
        start = route_points[index]
        end = route_points[index + 1]

        distance_km = haversine_distance_km(
            start["latitude"],
            start["longitude"],
            end["latitude"],
            end["longitude"],
        )

        bearing_deg = calculate_initial_bearing_deg(
            start["latitude"],
            start["longitude"],
            end["latitude"],
            end["longitude"],
        )

        altitude_change_m = (
            end["altitude_m"]
            - start["altitude_m"]
        )

        if altitude_change_m > 0:
            total_climb_m += (
                altitude_change_m
            )

        elif altitude_change_m < 0:
            total_descent_m += abs(
                altitude_change_m
            )

        leg = {
            "leg_number": index + 1,
            "from": start["point_id"],
            "to": end["point_id"],
            "distance_km": round(
                distance_km,
                3,
            ),
            "bearing_deg": round(
                bearing_deg,
                2,
            ),
            "start_altitude_m":
                start["altitude_m"],
            "end_altitude_m":
                end["altitude_m"],
            "altitude_change_m":
                altitude_change_m,
            "destination_action":
                end["action"],
        }

        legs.append(
            leg
        )

        total_horizontal_distance_km += (
            distance_km
        )

    return {
        "route_mode": "waypoints",
        "leg_count": len(
            legs
        ),
        "total_horizontal_distance_km": round(
            total_horizontal_distance_km,
            3,
        ),
        "total_climb_m": round(
            total_climb_m,
            2,
        ),
        "total_descent_m": round(
            total_descent_m,
            2,
        ),
        "return_to_home":
            route.return_to_home,
        "legs": legs,
    }