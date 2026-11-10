"""The ground goal as it is handed to the protected executor: ONE conversion site -> rover frame, by ONE owner.

Decision (07/11/2026): the final site -> odom/map conversion belongs to the rover's executor input adapter
(``ROVER_ADAPTER``). The Rover Agent's goal stays in the SITE frame; this side delivers everything the adapter needs
to verify and apply the transform, and applies nothing. ``MULTIAGENT_FRAMES2D`` (frames2d converts here) is kept as an
OFFLINE TEST mode only, while the rover's adapter is not in a committed, versioned snapshot; it is refused in OPERATIONAL
mode. No owner is ever picked by default: an undeclared owner is a refusal.

Record ``tfg.multiagent.rover-goal-handoff/1``:
  conversion_owner, goal_site (frame, x, y, sigma, point_id), frame_identity (site frame, expected rover frame),
  observation (id, sha256, data kind, source, timestamp, original pose / camera chain, uncertainty), dependencies,
  transform_required (reference to the transform the converter must use; status REQUIRED_NOT_APPLIED or
  APPLIED_ONCE), localization (state, frame, timestamp, uncertainty, source), vehicle (id, boot), constraints
  (human and operator limits, authorized area), applied_conversions (who converted, at most once), delegated_checks.

conversion_problems() is the double-conversion guard; record_conversion() refuses a second conversion.
"""
from __future__ import annotations

import copy

SCHEMA = "tfg.multiagent.rover-goal-handoff/1"
FINAL_OWNER = "ROVER_ADAPTER"
OFFLINE_TEST_OWNER = "MULTIAGENT_FRAMES2D"
OWNERS = (FINAL_OWNER, OFFLINE_TEST_OWNER)
IDENTITY = "IDENTITY_SAME_ACCREDITED_FRAME"


class DoubleConversion(ValueError):
    pass


def owner_problems(owner: str | None, mode: str) -> list[str]:
    if owner is None:
        return ["CONVERSION_OWNER_NOT_DECLARED: ROVER_ADAPTER (final) or MULTIAGENT_FRAMES2D (offline test) must be stated"]
    if owner not in OWNERS:
        return [f"CONVERSION_OWNER_UNKNOWN: {owner!r}"]
    if owner == OFFLINE_TEST_OWNER and mode != "OFFLINE_TEST":
        return ["MULTIAGENT_FRAMES2D_IS_OFFLINE_TEST_ONLY: the final conversion owner is ROVER_ADAPTER"]
    return []


def localization_state(loc: dict | None) -> str:
    if loc is None:
        return "NO_POSITION"
    return "ACCREDITED" if loc.get("validated") is True else "NOT_ACCREDITED"


def build(*, owner: str, site_goal: dict | None, point_id: str | None, rover_frame: str, observation: dict,
          dependencies, localization: dict | None, rover_identity: dict | None, constraints: dict,
          frames_result: dict) -> dict:
    loc = localization or {}
    conv = frames_result.get("conversion") if frames_result.get("applied") else None
    ref = frames_result.get("transform_reference")
    return {
        "schema": SCHEMA, "conversion_owner": owner,
        "goal_site": None if site_goal is None else {**site_goal, "point_id": point_id},
        "frame_identity": {"site_frame": (site_goal or {}).get("frame"), "rover_frame_expected": rover_frame},
        "observation": observation,
        "dependencies": copy.deepcopy(dependencies),
        "transform_required": {"from": (site_goal or {}).get("frame"), "to": rover_frame, "reference": ref,
                               "status": "APPLIED_ONCE" if conv else "REQUIRED_NOT_APPLIED"},
        "localization": {"state": localization_state(localization), "frame": loc.get("frame"),
                         "observed_at": loc.get("observed_at").isoformat() if hasattr(loc.get("observed_at"), "isoformat")
                         else loc.get("observed_at"), "sigma_m": loc.get("sigma_m"), "source": loc.get("source"),
                         "source_sha256": loc.get("source_sha256"), "vehicle_id": loc.get("vehicle_id"),
                         "boot_id": loc.get("boot_id")},
        "vehicle": dict(rover_identity) if rover_identity else None,
        "constraints": constraints,
        "goal_rover": frames_result.get("goal_rover") if conv else None,
        "applied_conversions": [conv] if conv else [],
        "delegated_checks": list(frames_result.get("delegated_checks") or []),
    }


def conversion_problems(rec: dict) -> list[str]:
    """Exactly one conversion, by the declared owner; a goal never reaches a converter already converted."""
    out = []
    applied = rec.get("applied_conversions") or []
    goal = rec.get("goal_site") or {}
    rover_frame = (rec.get("frame_identity") or {}).get("rover_frame_expected")
    if len(applied) > 1:
        out.append(f"DOUBLE_CONVERSION: {len(applied)} conversions recorded")
    if goal.get("frame") is not None and goal.get("frame") == rover_frame:
        out.append(f"GOAL_ALREADY_IN_ROVER_FRAME: the site goal is in {rover_frame!r}; converting it would apply the "
                   "transform a second time")
    if rec.get("conversion_owner") == FINAL_OWNER:
        if applied or rec.get("goal_rover") is not None:
            out.append("DOUBLE_CONVERSION_RISK: ROVER_ADAPTER owns the conversion but this side already converted")
        if (rec.get("transform_required") or {}).get("status") != "REQUIRED_NOT_APPLIED":
            out.append("TRANSFORM_STATUS_INCONSISTENT: ROVER_ADAPTER requires REQUIRED_NOT_APPLIED")
    elif rec.get("conversion_owner") == OFFLINE_TEST_OWNER and applied:
        if applied[0].get("converted_by") != "multiagent.frames2d" or (applied[0].get("to") or {}).get(
                "frame") != rover_frame:
            out.append("CONVERSION_RECORD_INCONSISTENT")
    return out


def record_conversion(rec: dict, conversion: dict) -> dict:
    """The only way to add a conversion to a record: refused if one exists or if another component owns it."""
    if rec.get("applied_conversions"):
        raise DoubleConversion(f"DOUBLE_CONVERSION: already converted by {rec['applied_conversions'][0].get('converted_by')}")
    if rec.get("conversion_owner") != OFFLINE_TEST_OWNER:
        raise DoubleConversion(f"CONVERSION_NOT_OWNED_HERE: owner is {rec.get('conversion_owner')}")
    out = copy.deepcopy(rec)
    out["applied_conversions"] = [conversion]
    out["goal_rover"] = conversion.get("to")
    out["transform_required"]["status"] = "APPLIED_ONCE"
    return out


def executor_goal_problems(rec: dict, nav: dict | None) -> list[str]:
    """The executor request must carry the ALREADY converted goal and declare that it must not convert again."""
    if nav is None:
        return []
    goal = nav.get("goal") or {}
    if goal.get("transform") != IDENTITY:
        return [f"EXECUTOR_WOULD_CONVERT_AGAIN: transform {goal.get('transform')!r}"]
    to = (rec.get("applied_conversions") or [{}])[0].get("to") or {}
    if (goal.get("frame"), round(goal.get("x_m", float("nan")), 9), round(goal.get("y_m", float("nan")), 9)) != (
            to.get("frame"), round(to.get("x_m", float("nan")), 9), round(to.get("y_m", float("nan")), 9)):
        return ["EXECUTOR_GOAL_DIFFERS_FROM_THE_RECORDED_CONVERSION"]
    return []
