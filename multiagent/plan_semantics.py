"""What a QGroundControl .plan can and cannot carry for this project's missions, and a semantics manifest for the rest.

Investigation (07/11/2026), against MAVLink common.xml as shipped with pymavlink 2.4.50 (read-only) and the project's
own exporter profile (inputs/qgc_plan_export.py: NAV_TAKEOFF 22, NAV_WAYPOINT 16, DO_CHANGE_SPEED 178, NAV_LAND 21):

  action / field      MAVLink candidates that EXIST                          why it is still not representable here
  navigate            NAV_WAYPOINT (16)                                       represented
  take_photo          IMAGE_START_CAPTURE (2000), DO_DIGICAM_CONTROL (203)    they address a camera INSTANCE (target
                                                                              camera id 1-6 / 7-255), not a sensor TYPE;
                                                                              no camera inventory is declared, so an id
                                                                              would be invented; not in the exporter
                                                                              profile; Hermes' importer skips them
  loiter              NAV_LOITER_TIME (19)                                    needs a loiter time; the mission model has
                                                                              no hold duration (it would be invented)
  survey / inspect    none for a single point (a QGC survey is a ComplexItem  no polygon or camera geometry in the
                      with polygon and camera calculations)                   mission model
  required sensor     none (sensor TYPE is not a MAVLink mission field)       -
  waypoint_id         none (QGC items carry doJumpId only)                    the importer renames them QGC_WP<n>

Nothing is invented and nothing is lost silently:
  export_with_manifest()  refuses (REFUSED_SEMANTIC_LOSS, listing exactly what cannot be represented) unless the
                          caller accepts a navigation-only .plan; then it writes the .plan through Hermes' exporter
                          AND a manifest (<plan>.semantics.json) bound to the .plan's sha256 that keeps every
                          original action, sensor and waypoint id.
  import_with_manifest()  imports the .plan through Hermes (mission_inputs.from_qgc_plan) and re-attaches the
                          manifest's semantics only if the .plan is byte-identical and every waypoint matches by
                          order and coordinates; otherwise the manifest is refused and the loss is reported.
  semantic_loss()         compares what was intended with what arrived: one row per lost field.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA = "tfg.multiagent.plan-semantics/1"
COORD_TOL_DEG = 1e-7  # the exporter writes 8 decimals; degE7 transport quantization is ~1.1e-7
MAVLINK_SOURCE = "MAVLink common.xml in pymavlink 2.4.50 (read-only); exporter profile inputs/qgc_plan_export.py"
WHY = {
    "take_photo": ("IMAGE_START_CAPTURE (2000) / DO_DIGICAM_CONTROL (203) exist but address a camera instance id, not a "
                   "sensor type; no camera inventory is declared, they are outside the exporter profile and the "
                   "importer skips them"),
    "loiter": "NAV_LOITER_TIME (19) needs a loiter time that the mission model does not have",
    "survey": "no point command; a QGC survey is a ComplexItem needing a polygon and camera geometry",
    "inspect": "no MAVLink mission command expresses an inspection",
}


def representability(md, sensors: dict | None = None) -> list[dict]:
    """One row per element of the mission that the .plan cannot carry (empty = nothing is lost)."""
    rows = []
    for i, w in enumerate(md.route.waypoints):
        if w.action != "navigate":
            rows.append({"waypoint_index": i, "waypoint_id": w.waypoint_id, "field": "action", "value": w.action,
                         "status": "NOT_REPRESENTABLE", "why": WHY[w.action]})
        if (sensors or {}).get(w.waypoint_id):
            rows.append({"waypoint_index": i, "waypoint_id": w.waypoint_id, "field": "sensor",
                         "value": sensors[w.waypoint_id], "status": "NOT_REPRESENTABLE",
                         "why": "a sensor type is not a MAVLink mission field"})
        rows.append({"waypoint_index": i, "waypoint_id": w.waypoint_id, "field": "waypoint_id", "value": w.waypoint_id,
                     "status": "NOT_REPRESENTABLE", "why": "QGC items carry doJumpId only; the importer renames them"})
    return rows


def export_with_manifest(md, plan_path: Path, *, planned_home_amsl_m: float, sensors: dict | None = None,
                         accept_navigation_only: bool = False) -> dict:
    from inputs.qgroundcontrol_exporter import export_qgroundcontrol_plan
    plan_path = Path(plan_path)
    lost = representability(md, sensors)
    semantic = [r for r in lost if r["field"] != "waypoint_id"]
    if semantic and not accept_navigation_only:
        return {"schema": SCHEMA, "status": "REFUSED_SEMANTIC_LOSS", "not_representable": semantic,
                "detail": "the .plan would carry navigation only; pass accept_navigation_only=True to export it WITH "
                          "a semantics manifest", "source": MAVLINK_SOURCE}
    nav_only = md.model_copy(deep=True)
    for w in nav_only.route.waypoints:
        w.action = "navigate"
    export_qgroundcontrol_plan(nav_only, plan_path, planned_home_amsl_m=planned_home_amsl_m)
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    manifest = {"schema": SCHEMA, "plan_file": plan_path.name, "plan_sha256": plan_sha, "source": MAVLINK_SOURCE,
                "waypoints": [{"index": i, "waypoint_id": w.waypoint_id, "action": w.action,
                               "sensor": (sensors or {}).get(w.waypoint_id), "latitude": w.latitude,
                               "longitude": w.longitude, "altitude_m": w.altitude_m}
                              for i, w in enumerate(md.route.waypoints)],
                "not_representable_in_plan": lost}
    manifest_path = plan_path.with_name(plan_path.name + ".semantics.json")
    with manifest_path.open("x") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    return {"schema": SCHEMA, "status": "EXPORTED_WITH_MANIFEST" if lost else "EXPORTED", "plan": str(plan_path),
            "plan_sha256": plan_sha, "manifest": str(manifest_path), "not_representable_in_plan": lost}


def import_with_manifest(plan_path: Path, manifest_path: Path | None, *, site, context, import_context) -> dict:
    from multiagent import mission_inputs as mi
    from inputs.qgroundcontrol_adapter import load_qgroundcontrol_plan
    plan_path = Path(plan_path)
    if manifest_path is None:
        r = mi.from_qgc_plan(plan_path, site=site, context=context, import_context=import_context)
        r["semantics"] = {"status": "NO_MANIFEST", "detail": "actions other than navigation, sensors and waypoint "
                          "ids cannot travel in a .plan; none were supplied"}
        return r
    manifest = json.loads(Path(manifest_path).read_text())
    problems = []
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    if manifest.get("schema") != SCHEMA:
        problems.append(f"MANIFEST_SCHEMA: {manifest.get('schema')!r}")
    if manifest.get("plan_sha256") != plan_sha:
        problems.append("MANIFEST_PLAN_MISMATCH: the .plan is not the file this manifest describes")
    semantics_by_wp = {}
    if not problems:
        try:
            imported = load_qgroundcontrol_plan(str(plan_path), import_context).mission.route.waypoints
        except (OSError, ValueError) as exc:
            imported, problems = [], [f"QGC_PLAN_INVALID: {type(exc).__name__}"]
        for m in manifest["waypoints"]:
            w = imported[m["index"]] if m["index"] < len(imported) else None
            if w is None or abs(w.latitude - m["latitude"]) > COORD_TOL_DEG or \
                    abs(w.longitude - m["longitude"]) > COORD_TOL_DEG:
                problems.append(f"MANIFEST_WAYPOINT_MISMATCH: {m['waypoint_id']} at index {m['index']}")
            else:
                semantics_by_wp[w.waypoint_id] = {"action": m["action"], "sensor": m["sensor"],
                                                  "original_waypoint_id": m["waypoint_id"]}
    if problems:
        r = mi.from_qgc_plan(plan_path, site=site, context=context, import_context=import_context)
        r["semantics"] = {"status": "MANIFEST_REFUSED", "problems": problems}
        r["findings"] = r.get("findings", []) + [{"kind": "SEMANTICS_MANIFEST_REFUSED", "detail": p,
                                                  "action": "ASK_OPERATOR"} for p in problems]
        if r["status"] == "OK":
            r["status"] = "NEEDS_CLARIFICATION"
        return r
    r = mi.from_qgc_plan(plan_path, site=site, context=context, import_context=import_context,
                         waypoint_semantics=semantics_by_wp)
    r["semantics"] = {"status": "MANIFEST_APPLIED", "manifest_sha256": hashlib.sha256(
        Path(manifest_path).read_bytes()).hexdigest(), "plan_sha256": plan_sha}
    return r


def semantic_loss(md, sensors: dict | None, mission_input: dict) -> list[dict]:
    """Intended (mission + declared sensors) vs. arrived (mission-input/1): one row per field that did not survive."""
    ordered = [p for k, p in (mission_input.get("provenance") or {}).items() if k.startswith("aerial_objectives.")]
    by_name = {p.get("original_waypoint_id") or p.get("waypoint_id"): p for p in ordered}
    objectives = {o["objective_id"]: o for o in (mission_input.get("brief") or {}).get("aerial_objectives", [])}
    out = []
    for i, w in enumerate(md.route.waypoints):
        p = by_name.get(w.waypoint_id) or (ordered[i] if i < len(ordered) else None)   # by name, else by order
        if p is None:
            out.append({"waypoint_id": w.waypoint_id, "field": "objective", "intended": w.waypoint_id, "arrived": None})
            continue
        name = p.get("original_waypoint_id") or p.get("waypoint_id")
        if name != w.waypoint_id:
            out.append({"waypoint_id": w.waypoint_id, "field": "waypoint_id", "intended": w.waypoint_id, "arrived": name})
        if p.get("action") != w.action:
            out.append({"waypoint_id": w.waypoint_id, "field": "action", "intended": w.action, "arrived": p.get("action")})
        want = (sensors or {}).get(w.waypoint_id)
        got = objectives.get(p["objective_id"], {}).get("required_sensor")
        if want != got:
            out.append({"waypoint_id": w.waypoint_id, "field": "sensor", "intended": want, "arrived": got})
    return out
