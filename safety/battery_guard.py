def check_battery_safety(
    flight_time_minutes: float,
    battery_percent: float,
    consumption_percent_per_minute: float,
    reserve_percent: float,
) -> dict:
    print(
        "\n[SAFETY] check_battery_safety("
        f"flight_time_minutes={flight_time_minutes}, "
        f"battery_percent={battery_percent}, "
        f"consumption_percent_per_minute="
        f"{consumption_percent_per_minute}, "
        f"reserve_percent={reserve_percent})"
    )

    if flight_time_minutes <= 0:
        return {
            "status": "error",
            "message": "Flight time must be greater than 0.",
        }

    if not 0 <= battery_percent <= 100:
        return {
            "status": "error",
            "message": (
                "Battery percentage must be between 0 and 100."
            ),
        }

    if consumption_percent_per_minute <= 0:
        return {
            "status": "error",
            "message": (
                "Battery consumption per minute must be greater than 0."
            ),
        }

    if not 0 <= reserve_percent <= 100:
        return {
            "status": "error",
            "message": (
                "Reserve percentage must be between 0 and 100."
            ),
        }

    required_battery_percent = (
        flight_time_minutes
        * consumption_percent_per_minute
    )

    battery_after_flight_percent = (
        battery_percent
        - required_battery_percent
    )

    battery_sufficient = (
        battery_after_flight_percent
        >= reserve_percent
    )

    return {
        "status": (
            "safe"
            if battery_sufficient
            else "unsafe"
        ),
        "battery_sufficient": battery_sufficient,
        "required_battery_percent": round(
            required_battery_percent,
            2,
        ),
        "battery_after_flight_percent": round(
            battery_after_flight_percent,
            2,
        ),
        "required_reserve_percent": round(
            reserve_percent,
            2,
        ),
    }