"""Explicit logical-to-SITL binding. No file writes, ROS calls or flight consent."""
from dataclasses import dataclass


class VehicleSelectionError(ValueError):
    pass


@dataclass(frozen=True)
class SimulatedVehicle:
    vehicle_id: str
    simulated_vehicle: str

    def as_dict(self):
        return {"vehicle_id": self.vehicle_id, "simulated_vehicle": self.simulated_vehicle}


_BINDINGS = (SimulatedVehicle("drone_01", "v1"), SimulatedVehicle("drone_02", "v2"))


def validate_interface(vehicle):
    if vehicle not in ("v1", "v2"):
        raise VehicleSelectionError(f"Unsupported simulated interface: {vehicle!r}; expected v1 or v2")
    return vehicle


def resolve_vehicle(vehicle_id, requested_vehicle=None):
    selection = next((item for item in _BINDINGS if item.vehicle_id == vehicle_id), None)
    if selection is None:
        raise VehicleSelectionError(f"Unknown logical vehicle_id: {vehicle_id!r}; expected drone_01 or drone_02")
    if requested_vehicle is not None and validate_interface(requested_vehicle) != selection.simulated_vehicle:
        raise VehicleSelectionError(
            f"Vehicle mismatch: {vehicle_id} maps to {selection.simulated_vehicle}, requested {requested_vehicle}"
        )
    return selection


def resolve_mission_vehicle(mission, requested_vehicle=None):
    return resolve_vehicle(mission.vehicle.vehicle_id, requested_vehicle)


def logical_vehicle_for_interface(vehicle):
    validate_interface(vehicle)
    return next(item.vehicle_id for item in _BINDINGS if item.simulated_vehicle == vehicle)


def checked_selection(value):
    if not isinstance(value, dict) or set(value) != {"vehicle_id", "simulated_vehicle"}:
        raise VehicleSelectionError("Missing or malformed vehicle_selection")
    result = resolve_vehicle(value["vehicle_id"], value["simulated_vehicle"])
    return result


def recorded_report_selection(report):
    """Check new identity fields; expose old recorded v1 without rewriting history.

    Legacy identity can have an unknown logical ID. Never infer drone_01 from
    a missing field or reinterpret a legacy run as having executed on v2.
    """
    identity = report.get("mission_identity") or {}
    if not isinstance(identity, dict):
        raise VehicleSelectionError("Malformed report mission identity")
    raw = report.get("executor_result")
    if report.get("schema_version") != "1.1" and report.get("vehicle_selection") is not None:
        raise VehicleSelectionError("Vehicle selection requires the new report contract; no legacy downgrade")
    if report.get("schema_version") == "1.1":
        value = report.get("vehicle_selection")
        if value is None:
            if identity or report.get("execution_attempted"):
                raise VehicleSelectionError("New report lacks resolved vehicle identity")
            return None  # invalid input or progress before parsing snapshot
        selected = checked_selection(value).as_dict()
        if any(identity.get(k) != v for k, v in selected.items()):
            raise VehicleSelectionError("Report mission identity contradicts vehicle_selection")
        if isinstance(raw, dict) and (
            raw.get("vehicle") != selected["simulated_vehicle"]
            or raw.get("vehicle_id") != selected["vehicle_id"]
            or raw.get("mission_id", identity.get("mission_id")) != identity.get("mission_id")
            or (isinstance(raw.get("waypoint_diagnostic"), dict)
                and raw["waypoint_diagnostic"].get("vehicle", selected["simulated_vehicle"]) != selected["simulated_vehicle"])
        ):
            raise VehicleSelectionError("Executor identity contradicts report vehicle_selection")
        return selected
    if identity.get("simulated_vehicle", "v1") != "v1" or (
        isinstance(raw, dict) and raw.get("vehicle", "v1") != "v1"
    ):
        raise VehicleSelectionError("Legacy report contradicts its recorded v1-only scope")
    return {"vehicle_id": identity.get("vehicle_id"), "simulated_vehicle": "v1"}
