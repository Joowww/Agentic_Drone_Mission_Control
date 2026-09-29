from safety.battery_guard import check_battery_safety
from safety.wind_guard import check_wind_safety
from tools.flight_dynamics import calculate_flight_time


def main() -> None:
    flight_result = calculate_flight_time(
        distance_km=15.0,
        drone_speed_kmh=40.0,
        wind_speed_kmh=12.0,
        flight_bearing_deg=90.0,
        wind_direction_from_deg=0.0,
    )

    print("\nFLIGHT RESULT")
    print(flight_result)

    wind_result = check_wind_safety(
        wind_speed_kmh=12.0,
        max_safe_wind_speed_kmh=30.0,
    )

    print("\nWIND SAFETY RESULT")
    print(wind_result)

    if flight_result["status"] == "success":
        battery_result = check_battery_safety(
            flight_time_minutes=flight_result[
                "flight_time_minutes"
            ],
            battery_percent=10.0,
            consumption_percent_per_minute=1.0,
            reserve_percent=10.0,
        )

        print("\nBATTERY SAFETY RESULT")
        print(battery_result)


if __name__ == "__main__":
    main()