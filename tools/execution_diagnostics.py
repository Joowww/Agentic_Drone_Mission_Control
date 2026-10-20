"""Bounded execution evidence. UTC/monotonic durations are host wall time, not SITL time."""
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import time

from tools.simulated_vehicle import logical_vehicle_for_interface

current_trace = ContextVar("execution_trace", default=None)
last_ros_call = ContextVar("last_ros_call", default=None)


def error_evidence(exc):
    chain, seen = [], set()
    while exc is not None and id(exc) not in seen and len(chain) < 8:
        seen.add(id(exc))
        chain.append({"type": type(exc).__name__, "message": str(exc),
                      "diagnostic": getattr(exc, "diagnostic", None)})
        exc = exc.__cause__ or exc.__context__
    return chain


SPECS = {
    "read_origin": ("topic", "gps_global_origin/filtered", 15, 10, False),
    "read_position": ("topic", "geopose/filtered", 15, 10, False),
    "read_status": ("topic", "status", 15, 10, False),
    "guided": ("service", "mode_switch", 30, None, True),
    "arm": ("service", "arm_motors", 30, None, True),
    "takeoff": ("service", "experimental/takeoff", 30, None, True),
    "navigate": ("topic", "cmd_gps_pose", 20, None, True),
    "return_home": ("topic", "cmd_gps_pose", 20, None, True),
    "land": ("service", "mode_switch", 30, None, True),
    "recovery_land": ("service", "mode_switch", 30, None, True),
}


class OperationTrace:
    def __init__(self, vehicle):
        self.vehicle = vehicle
        self.initial = []
        self.recent = deque(maxlen=96)
        self.total = 0
        self.controls = []
        self.context = {}

    def append(self, record):
        self.total += 1
        (self.initial if len(self.initial) < 16 else self.recent).append(record)

    def evidence(self):
        return {"clock": "HOST_UTC_AND_MONOTONIC", "simulated_time_inferred": False,
                "total_operations": self.total, "omitted_operations": self.total-len(self.initial)-len(self.recent),
                "initial": self.initial, "recent": list(self.recent)}


def operation(name, fn, *args, **kwargs):
    trace = current_trace.get()
    if trace is None:
        return fn(*args, **kwargs)
    kind, endpoint, outer, inner, control = SPECS[name]
    record = {"operation": name, "stage": name.upper(), "vehicle": trace.vehicle,
              "vehicle_id": logical_vehicle_for_interface(trace.vehicle),
              "endpoint_kind": kind, "endpoint": f"/ap/{trace.vehicle}/{endpoint}",
              "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "timeout_seconds": outer, "inner_timeout_seconds": inner,
              "attempted": True, "confirmed": False, "return_code": None,
              "parameters": {"args": list(args), "kwargs": dict(kwargs)},
              "effects": "UNCONFIRMED" if control else "READ_ONLY"}
    trace.append(record)
    if control:
        trace.context["stage"] = name.upper()
    record["stage"] = trace.context.get("stage", record["stage"])
    if control:
        trace.controls.append(record)
    started = time.monotonic()
    token = last_ros_call.set(None)
    try:
        value = fn(*args, **kwargs)
        confirmed = (isinstance(value, dict) and value.get("success") is True) if control else True
        record.update(confirmed=confirmed, effects=("ACKNOWLEDGED" if confirmed else "UNCONFIRMED") if control else "READ_ONLY")
        # This records the actual observation returned, not an invented sample/header.
        if not control:
            record["observation"] = value
        return value
    except Exception as exc:
        record["error"] = error_evidence(exc)
        raise
    finally:
        record.update(finished_at_utc=datetime.now(timezone.utc).isoformat(),
                      elapsed_wall_seconds=time.monotonic()-started)
        if last_ros_call.get() is not None:
            record["transport"] = last_ros_call.get()
            record["return_code"] = last_ros_call.get().get("return_code")
        last_ros_call.reset(token)


def trace_execution(fn):
    @wraps(fn)
    def wrapped(*args, vehicle="v1", **kwargs):
        trace = OperationTrace(vehicle)
        token = current_trace.set(trace)
        try:
            try:
                result = fn(*args, vehicle=vehicle, **kwargs)
            except Exception as exc:
                # Includes gate/load failures preceding the main flight try block.
                # Never invent recovery or attempt new controls in this fallback.
                result = {"success":False, "status":"FAILED", "stage":"MISSION_EXECUTION",
                          "vehicle":vehicle, "vehicle_id":logical_vehicle_for_interface(vehicle),
                          "mission_id":trace.context.get('mission_id'),
                          "error":str(exc), "error_evidence":error_evidence(exc),
                          "events":[], "recovery":{"landing_attempted":False,"landing_completed":False},
                          "control_outcome":"UNCONFIRMED" if trace.controls else "NOT_ATTEMPTED"}
            return {**result, "operation_diagnostics": trace.evidence(),
                    "control_attempts": trace.controls,
                    "controls_not_attempted": sorted({k for k,v in SPECS.items() if v[-1]}-
                                                     {r["operation"] for r in trace.controls}),
                    "partial_context": trace.context}
        finally:
            current_trace.reset(token)
    return wrapped
