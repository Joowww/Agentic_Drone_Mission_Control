from typing import TypedDict


class MissionState(TypedDict, total=False):
    user_input: str
    intent: str
    response: str
    updated_fields: list[str]

    distance_km: float | None
    drone_speed_kmh: float | None
    wind_speed_kmh: float | None
    flight_bearing_deg: float | None
    wind_direction_from_deg: float | None

    battery_percent: float | None
    consumption_percent_per_minute: float | None
    reserve_percent: float | None

    max_safe_wind_speed_kmh: float | None

    flight_result: dict | None
    wind_result: dict | None
    battery_result: dict | None

    run_flight: bool
    run_wind: bool
    run_battery: bool

    mission_status: str
    missing_fields: list[str]
    failure_reasons: list[str]

    plan_version: int
    mission_plan: str

    replan_status: str
    replan_actions: list[str]
    replan_deferred_actions: list[str]
    replan_requires_reevaluation: bool

    final_report: str
    calculation_trace: str