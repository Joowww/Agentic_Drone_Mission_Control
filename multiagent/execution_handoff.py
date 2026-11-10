"""Controlled hand-off from a PENDING_AUTHORIZATION proposal to future vehicle adapters (CubePilot/ArduPilot drone,
JetRacer rover). DRY RUN ONLY: every adapter here describes what it would receive and refuses to execute.

Shapes follow what the executors will need, without importing any executor:
- aerial task -> the validated mission and its QGC .plan (MAVLink mission protocol), identified by sha256, for an
  ArduPilot vehicle (SITL or CubePilot) through the existing authorized upload entry;
- ground task -> a navigation target in the SITE local frame (frame, target_x_m, target_y_m) like the vehicle
  contract prepared for the rover (NavigationPlan: frame, target, max_speed_mps, timeout_s); speed and timeout come
  from a human authorization, never from a model.
Blocking reasons are explicit (no authorization; for the JetRacer, no accredited localization and no driver).
"""
from __future__ import annotations

REFUSED = "REFUSED_DRY_RUN_ONLY"


class DryRunAdapter:
    kind = "abstract"

    def execute(self, handoff: dict, authorization: dict | None = None) -> dict:
        return {"status": REFUSED, "physical_effect": False, "commands_sent": 0,
                "reason": "no execution path exists in the multi-agent prototype; use the authorized entries"}


class ArduPilotPlanHandoff(DryRunAdapter):
    kind = "ARDUPILOT_MAVLINK_MISSION"

    def describe(self, task: dict, mission_sha256: str | None) -> dict:
        return {"adapter": self.kind, "vehicle_id": task["vehicle_id"], "task_id": task["task_id"],
                "artifact": {"format": "QGC .plan (MAVLink mission)", "mission_sha256": mission_sha256},
                "targets": ["ArduPilot SITL (existing entry)", "CubePilot/ArduPilot on the lab drone (not connected)"],
                "blocked_by": ["AUTHORIZATION_NOT_GRANTED", "SITE_GEO_REFERENCE_PENDING_MEASUREMENT (real flight)"],
                "executable_now": False}


class RoverTargetHandoff(DryRunAdapter):
    kind = "ROVER_NAVIGATION_TARGET"

    def describe(self, task: dict, site, platform: str = "JetRacer") -> dict:
        point = site.point(task["target_point"])
        return {"adapter": self.kind, "platform": platform, "vehicle_id": task["vehicle_id"], "task_id": task["task_id"],
                "navigation_plan": {"frame": site.local_frame.frame_id,
                                    "target_x_m": point.x_m if point else None, "target_y_m": point.y_m if point else None,
                                    "max_speed_mps": None, "timeout_s": None,
                                    "speed_and_timeout_from": "human authorization, never the model"},
                "blocked_by": ["AUTHORIZATION_NOT_GRANTED", "LOCALIZATION_NOT_ACCREDITED",
                               "SITE_FRAME_TO_ROVER_ODOMETRY_NOT_ACCREDITED"]
                + (["NO_DRIVER (JetRacer adapter not implemented)"] if platform == "JetRacer" else []),
                "executable_now": False}


def handoffs(proposal: dict, site) -> list[dict]:
    """One dry-run hand-off per task of a proposal. Never executes; refuses unless the proposal is pending."""
    if proposal.get("authorization", {}).get("granted"):
        raise ValueError("a proposal never arrives here authorized: the prototype cannot grant authority")
    air = {p["task_id"]: p for p in (proposal.get("aerial") or {}).get("proposals", [])}
    ground = {p["task_id"]: p for p in (proposal.get("ground") or {}).get("proposals", [])}
    out = []
    for task in proposal.get("tasks", []):
        if task["task_id"] in air:
            out.append(ArduPilotPlanHandoff().describe(air[task["task_id"]], air[task["task_id"]].get("mission_sha256")))
        elif task["task_id"] in ground:
            out.append(RoverTargetHandoff().describe(ground[task["task_id"]], site))
    return out
