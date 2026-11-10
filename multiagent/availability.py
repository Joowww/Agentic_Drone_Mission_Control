"""Vehicle availability across three levels (declared text -> inventory -> operational), deterministic.

resolve(brief, context, fleet, stated) -> report and the drones the planner may use:
- identity: every vehicle named must exist in the fleet AND the operating context, otherwise IDENTITY_CONFLICT;
- inventory (level 2) = the operating context's DECLARED availability (DroneProfile.available);
- text (level 1) = the brief's statements, cross-checked with the deterministic reading of the raw text
  (risk_signals.stated_availability): when they disagree the request needs clarification;
- planning availability:
  * text UNAVAILABLE                     -> excluded (also when the inventory says available: conflict recorded);
  * text AVAILABLE, inventory unavailable -> excluded + INVENTORY_CONFLICT -> clarification (text cannot override);
  * text UNKNOWN                         -> clarification (AVAILABILITY_UNKNOWN);
  * no statement                         -> inventory value;
- operational (level 3): always NOT_ESTABLISHED. Nothing here can raise it.
"""
from __future__ import annotations

OPERATIONAL = "NOT_ESTABLISHED: only the executor's own gates establish operational availability"


def resolve(brief: dict, context, fleet, stated: dict) -> dict:
    statements = {s["vehicle_id"]: s for s in (brief.get("vehicle_availability") or [])}
    profiles = {d.vehicle_id: d for d in context.drones}
    profiles.update({r.vehicle_id: r for r in context.rovers})
    vehicles, clarifications, excluded = [], [], []
    for vehicle_id in sorted(set(statements) | set(stated) | set(profiles)):
        statement, text = statements.get(vehicle_id), stated.get(vehicle_id)
        profile, in_fleet = profiles.get(vehicle_id), fleet.vehicle(vehicle_id) is not None
        entry = {"vehicle_id": vehicle_id, "identity": "DECLARED_IN_FLEET_AND_CONTEXT" if profile and in_fleet else
                 ("NOT_IN_CONTEXT" if in_fleet else "NOT_IN_FLEET"),
                 "declared_by_text": statement["declared"] if statement else None,
                 "quote": statement.get("quote") if statement else None,
                 "deterministic_text_reading": text,
                 "inventory": None if profile is None else ("AVAILABLE" if profile.available else "UNAVAILABLE"),
                 "inventory_source": None if profile is None else f"operating context ({profile.provenance})",
                 "operational": OPERATIONAL, "conflicts": []}
        declared = entry["declared_by_text"]
        if (statement or text) and entry["identity"] != "DECLARED_IN_FLEET_AND_CONTEXT":
            entry["conflicts"].append(f"IDENTITY_CONFLICT: {vehicle_id} is {entry['identity']}")
        if text is not None and declared != text:
            entry["conflicts"].append(f"TEXT_READING_DIFFERS: brief says {declared}, text reads {text}")
        effective = declared or text
        if effective == "UNAVAILABLE":
            planning = "UNAVAILABLE"
            if entry["inventory"] == "AVAILABLE":
                entry["notes"] = "operator says unavailable: excluded although the inventory lists it available"
        elif effective == "AVAILABLE":
            planning = entry["inventory"] or "UNAVAILABLE"
            if entry["inventory"] != "AVAILABLE":
                entry["conflicts"].append(f"INVENTORY_CONFLICT: text says AVAILABLE, inventory says {entry['inventory']}")
        elif effective == "UNKNOWN":
            planning = "UNKNOWN"
            entry["conflicts"].append(f"AVAILABILITY_UNKNOWN: {vehicle_id}")
        else:
            planning = entry["inventory"] or "UNKNOWN"
        entry["planning"] = planning
        if planning != "AVAILABLE" and profile is not None:
            excluded.append(vehicle_id)
        clarifications.extend(f"{c}" for c in entry["conflicts"])
        vehicles.append(entry)
    return {"schema": "tfg.multiagent.availability/1", "vehicles": vehicles, "excluded_from_planning": sorted(excluded),
            "clarifications": clarifications, "operational_availability": OPERATIONAL,
            "levels": ["DECLARED_TEXT", "INVENTORY", "OPERATIONAL (not established here)"]}


def apply(context, report: dict):
    """Copy of the context where every excluded vehicle is unavailable (the inventory itself is not changed)."""
    excluded = set(report["excluded_from_planning"])
    return context.model_copy(update={
        "drones": [d.model_copy(update={"available": False}) if d.vehicle_id in excluded else d for d in context.drones],
        "rovers": [r.model_copy(update={"available": False}) if r.vehicle_id in excluded else r for r in context.rovers]})
