import math


def calculate_flight_time(
    distance_km: float,
    drone_speed_kmh: float,
    wind_speed_kmh: float,
    flight_bearing_deg: float,
    wind_direction_from_deg: float,
) -> dict:
    print(
        "\n[FLIGHT DYNAMICS] calculate_flight_time("
        f"distance_km={distance_km}, "
        f"drone_speed_kmh={drone_speed_kmh}, "
        f"wind_speed_kmh={wind_speed_kmh}, "
        f"flight_bearing_deg={flight_bearing_deg}, "
        f"wind_direction_from_deg={wind_direction_from_deg})"
    )

    if distance_km <= 0:
        return {
            "status": "error",
            "message": "Distance must be greater than 0 km.",
        }

    if drone_speed_kmh <= 0:
        return {
            "status": "error",
            "message": "Drone speed must be greater than 0 km/h.",
        }

    if wind_speed_kmh < 0:
        return {
            "status": "error",
            "message": "Wind speed cannot be negative.",
        }

    flight_bearing_deg %= 360
    wind_direction_from_deg %= 360

    relative_angle_rad = math.radians(
        wind_direction_from_deg - flight_bearing_deg
    )

    headwind_component_kmh = (
        wind_speed_kmh * math.cos(relative_angle_rad)
    )

    crosswind_component_kmh = (
        wind_speed_kmh * math.sin(relative_angle_rad)
    )

    if abs(crosswind_component_kmh) >= drone_speed_kmh:
        return {
            "status": "unsafe",
            "message": "The drone cannot compensate for the crosswind.",
            "headwind_component_kmh": round(
                headwind_component_kmh,
                2,
            ),
            "crosswind_component_kmh": round(
                crosswind_component_kmh,
                2,
            ),
        }

    ground_speed_kmh = (
        -headwind_component_kmh
        + math.sqrt(
            drone_speed_kmh**2
            - crosswind_component_kmh**2
        )
    )

    if ground_speed_kmh <= 0:
        return {
            "status": "unsafe",
            "message": (
                "The headwind prevents the drone from moving "
                "forward along the route."
            ),
            "ground_speed_kmh": round(
                ground_speed_kmh,
                2,
            ),
            "headwind_component_kmh": round(
                headwind_component_kmh,
                2,
            ),
            "crosswind_component_kmh": round(
                crosswind_component_kmh,
                2,
            ),
        }

    flight_time_minutes = (
        distance_km / ground_speed_kmh
    ) * 60

    return {
        "status": "success",
        "flight_time_minutes": round(
            flight_time_minutes,
            2,
        ),
        "ground_speed_kmh": round(
            ground_speed_kmh,
            2,
        ),
        "headwind_component_kmh": round(
            headwind_component_kmh,
            2,
        ),
        "crosswind_component_kmh": round(
            crosswind_component_kmh,
            2,
        ),
    }