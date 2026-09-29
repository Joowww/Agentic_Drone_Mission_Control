def check_altitude_safety(
    waypoint_altitudes_m: list[float],
    maximum_altitude_m: float,
) -> dict:
    print(
        "\n[SAFETY] check_altitude_safety("
        f"maximum_altitude_m={maximum_altitude_m})"
    )

    if maximum_altitude_m <= 0:
        return {
            "status": "error",
            "message": (
                "Maximum altitude must be greater than 0."
            ),
        }

    if not waypoint_altitudes_m:
        return {
            "status": "error",
            "message": (
                "No waypoint altitudes were provided."
            ),
        }

    if any(
        altitude < 0
        for altitude in waypoint_altitudes_m
    ):
        return {
            "status": "error",
            "message": (
                "Waypoint altitude cannot be negative."
            ),
        }

    highest_altitude_m = max(
        waypoint_altitudes_m
    )

    altitude_safe = (
        highest_altitude_m
        <= maximum_altitude_m
    )

    return {
        "status": (
            "safe"
            if altitude_safe
            else "unsafe"
        ),
        "altitude_safe":
            altitude_safe,
        "highest_altitude_m": round(
            highest_altitude_m,
            2,
        ),
        "maximum_altitude_m": round(
            maximum_altitude_m,
            2,
        ),
    }