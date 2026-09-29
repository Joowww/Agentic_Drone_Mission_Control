REQUIRED_MISSION_FIELDS = {
    "distance_km": "flight distance",
    "drone_speed_kmh": "drone speed",
    "wind_speed_kmh": "wind speed",
    "flight_bearing_deg": "flight direction or bearing",
    "wind_direction_from_deg": "wind direction",
    "max_safe_wind_speed_kmh": "maximum safe wind speed",
    "battery_percent": "current battery percentage",
    "consumption_percent_per_minute":
        "battery consumption percentage per minute",
    "reserve_percent": "required battery reserve",
}


def validate_mission(
    state: dict,
) -> dict:
    missing_fields = [
        label
        for field, label in REQUIRED_MISSION_FIELDS.items()
        if state.get(field) is None
    ]

    flight_result = state.get(
        "flight_result"
    )

    wind_result = state.get(
        "wind_result"
    )

    battery_result = state.get(
        "battery_result"
    )

    invalid = False
    unsafe = False
    failure_reasons = []

    for name, result in [
        ("Flight dynamics", flight_result),
        ("Wind safety", wind_result),
        ("Battery safety", battery_result),
    ]:
        if (
            result is not None
            and result.get("status") == "error"
        ):
            invalid = True

            failure_reasons.append(
                f"{name}: "
                f"{result.get('message', 'validation error')}"
            )

    if (
        flight_result is not None
        and flight_result.get("status") == "unsafe"
    ):
        unsafe = True

        failure_reasons.append(
            "Flight dynamics: "
            + flight_result.get(
                "message",
                "unsafe flight dynamics",
            )
        )

    if (
        wind_result is not None
        and wind_result.get("status") == "unsafe"
    ):
        unsafe = True

        failure_reasons.append(
            "Wind safety: current wind exceeds "
            "the allowed safety limit."
        )

    if (
        battery_result is not None
        and battery_result.get("status") == "unsafe"
    ):
        unsafe = True

        failure_reasons.append(
            "Battery safety: the drone would finish "
            "below the required reserve."
        )

    if invalid:
        mission_status = "INVALID"

    elif unsafe:
        mission_status = "NOT FEASIBLE"

    elif (
        missing_fields
        or flight_result is None
        or wind_result is None
        or battery_result is None
    ):
        mission_status = "UNDETERMINED"

    else:
        mission_status = "FEASIBLE"

    return {
        "mission_status": mission_status,
        "missing_fields": missing_fields,
        "failure_reasons": failure_reasons,
    }