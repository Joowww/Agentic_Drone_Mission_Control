"""Attribution records are agent statements, never authentication of a dialogue."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from planning.artifact_store import fingerprint
from planning.mission_plan_service import _generate_mission_id

DISCLAIMER = (
    "MCP input comes from the agent. Operator attribution is an unverified agent declaration, "
    "not proof of dialogue fidelity; no authenticated conversation source is stored."
)
SHARED_MISSION_FIELDS = ("home_latitude", "home_longitude", "home_altitude_m", "return_to_home")


class InputAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["OPERATOR_DECLARED_VIA_AGENT", "UNKNOWN"]
    statement: str | None = None

    @model_validator(mode="after")
    def require_statement(self):
        if self.source == "OPERATOR_DECLARED_VIA_AGENT" and not (self.statement or "").strip():
            raise ValueError("An operator attribution needs the agent's supporting statement")
        return self


def _token(value):
    return value.replace("~", "~0").replace("/", "~1")


def facts(draft):
    """Stable JSON-pointer paths; waypoint IDs address merged waypoint facts."""
    result = {}
    for field, value in draft.model_dump(mode="json", exclude_none=True).items():
        if field == "waypoints":
            for waypoint in value:
                prefix = "/waypoints/" + _token(waypoint["waypoint_id"].upper())
                for key, fact in waypoint.items():
                    result[prefix + "/" + key] = fact.upper() if key == "waypoint_id" else fact
        elif field == "geometry_intent":
            for key, fact in value.items():
                result["/geometry_intent/" + key] = fact
        else:
            result["/" + field] = value
    return result


def record_sources(current, merged, previous, updates, attributions, generated, replace_route=False):
    supplied = facts(updates)
    if set(attributions) - supplied.keys():
        raise ValueError("Attributions must address explicitly supplied non-null facts using JSON-pointer paths")
    before, after = facts(current), facts(merged)
    prior_sources = previous.get("field_provenance", {}) if previous.get("schema_version") == 2 else {}
    records = {key: value for key, value in prior_sources.items()
               if key in after and value.get("value_sha256") == fingerprint(after[key])}
    for path, value in after.items():
        changed = path not in before or before[path] != value
        if path in supplied and (changed or path in attributions or replace_route and path.startswith("/waypoints/")):
            entry = (attributions[path].model_dump(exclude_none=True) if path in attributions
                     else {"source": "UNKNOWN", "note": "Agent supplied value without operator attribution"})
        elif changed or generated and path.startswith("/waypoints/"):
            if generated and path.startswith("/waypoints/"):
                entry = {"source": "DETERMINISTIC_GENERATION", "method": "relative_route_generator",
                         "parameters_sha256": fingerprint(merged.geometry_intent.model_dump(mode="json"))}
            else:
                field = path.rsplit("/", 1)[-1]
                counterpart = ("/" + field if path.startswith("/geometry_intent/")
                               else "/geometry_intent/" + field)
                entry = ({"source": "DETERMINISTIC_DERIVATION", "from": counterpart,
                          "method": "copy_shared_geometry_field"}
                         if field in SHARED_MISSION_FIELDS and counterpart in after and after[counterpart] == value
                         else {"source": "UNKNOWN", "note": "No field attribution recorded"})
        else:
            continue
        records[path] = {**entry, "authenticated": False, "value_sha256": fingerprint(value)}
    return records


def compatibility_defaults(draft):
    """Expose existing builder defaults; do not fill the draft or add safety values."""
    defaults = []
    def add(path, value, applied=True):
        defaults.append({"path": path, "value": value, "source": "COMPATIBILITY_DEFAULT",
                         "applies_on_finalization": applied})
    if not draft.mission_id and draft.name:
        add("/mission_id", _generate_mission_id(draft.name))
    if not draft.vehicle_id:
        add("/vehicle/vehicle_id", "drone_01")
    if draft.return_to_home is None:
        add("/route/return_to_home", True, applied=draft.geometry_intent is None)
    for field in ("low_battery_action", "unsafe_wind_action", "communication_loss_action"):
        if getattr(draft, field) is None:
            add("/failsafe/" + field, "RETURN_TO_HOME")
    for i, waypoint in enumerate(draft.waypoints):
        if waypoint.action is None:
            add(f"/route/waypoints/{i}/action", "navigate")
    return defaults


def provenance_view(draft, state):
    recorded = state.get("field_provenance", {}) if state.get("schema_version") == 2 else {}
    fields = {}
    for key, value in facts(draft).items():
        entry = recorded.get(key)
        fields[key] = (entry if entry and entry.get("value_sha256") == fingerprint(value)
                       else {"source": "UNKNOWN", "authenticated": False,
                             "note": "No trustworthy field attribution recorded; no retrospective inference"})
    return {"provenance_status": ("UNVERIFIED_AGENT_INPUT" if state.get("schema_version") == 2
                                  else "UNKNOWN_LEGACY_INPUT"),
            "stored_provenance_status": state.get("provenance_status"),
            "field_provenance": fields, "provenance_notice": DISCLAIMER,
            "compatibility_defaults": compatibility_defaults(draft)}
