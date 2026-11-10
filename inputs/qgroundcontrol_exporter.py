"""Interactive-session / Hermes entry to the ``.plan`` export: delegates to the strict exporter.

Until 27/10/2026 this module built its own plan: every waypoint action (survey, take_photo, ...) became a plain
NAV_WAYPOINT, the mission's relative home altitude (0 m) was written as the AMSL ``plannedHomePosition``, requested
waypoint speeds were dropped and the mission ended with RTL. Those files remain readable (and historical ones are
kept), but the same user could otherwise get a strict result from packages and a semantically different one here.

Now both entries share ``inputs.qgc_plan_export.build_plan``. Missions from the session, Hermes or a QGC import carry
no real AMSL for the planned home, so without ``planned_home_amsl_m`` the export is REFUSED with its reasons
(``ExportRefused``); nothing is invented. Geographic export with an AMSL source goes through ``tools.scenario_package``.
"""
from pathlib import Path

from inputs.qgc_plan_export import ExportRefused, build_plan, plan_bytes
from models.mission_definition import MissionDefinition

__all__ = ["ExportRefused", "build_qgroundcontrol_plan", "export_qgroundcontrol_plan"]


def build_qgroundcontrol_plan(
    mission: MissionDefinition,
    *,
    planned_home_amsl_m: float | None = None,
) -> dict:
    plan, _log = build_plan(
        mission,
        planned_home_amsl_m=planned_home_amsl_m,
    )

    return plan


def export_qgroundcontrol_plan(
    mission: MissionDefinition,
    file_path: str | Path,
    *,
    planned_home_amsl_m: float | None = None,
) -> Path:
    path = Path(file_path)

    if path.suffix.lower() != ".plan":
        raise ValueError(
            "QGroundControl export path must "
            "use the .plan extension."
        )

    # Refusals are raised before any directory or file is created.
    data = plan_bytes(
        build_qgroundcontrol_plan(
            mission,
            planned_home_amsl_m=planned_home_amsl_m,
        )
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_bytes(
        data
    )

    return path
