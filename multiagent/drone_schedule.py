"""Temporal coordination of the planned drone missions: a state machine driven by an injected clock and by
ACCREDITED events, re-checking separation with the same model as the planning deconfliction
(multiagent.deconfliction). It decides when a drone MAY be started; it never starts, arms or commands anything.

Not a reactive swarm controller: with no real telemetry it can only hold, permit or ask for an abort.

Per drone: PLANNED -> READY (fresh accredited readiness) -> START_PERMITTED (decision) -> ARMED -> AIRBORNE ->
LANDED -> COMPLETED, or FAILED / CANCELLED / UNKNOWN (stale telemetry, lost link: never assumed fine).

Start rule (all must hold; a due time alone is never enough):
  - the drone is READY with readiness younger than ``readiness_max_age_s``;
  - nothing is cancelled, no drone FAILED or UNKNOWN, the schedule is the validated one;
  - its aerial dependencies are met (e.g. "after drone_02 COMPLETED" in sequential mode);
  - the time since the ANCHOR (actual take-off of the first drone) is at least its planned start delay;
  - separation still holds against every drone in the air, with each one's timeline shifted by its observed or
    overdue lag (conservative): a risk that reappears blocks the start until it clears.
Modes: OFFSET (the planned delays, for a backend that can run drones concurrently) and SEQUENTIAL_H2 (the historical
H2 executor: the next drone only after the previous one COMPLETED; stricter than any offset).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import json

from multiagent import deconfliction as dc

SCHEMA = "tfg.multiagent.drone-schedule/1"
STATES = ("PLANNED", "READY", "START_PERMITTED", "ARMED", "AIRBORNE", "LANDED", "COMPLETED", "FAILED", "CANCELLED",
          "UNKNOWN")
STARTED = ("START_PERMITTED", "ARMED", "AIRBORNE", "LANDED")
EVENTS = ("READINESS", "ARMED", "AIRBORNE", "WAYPOINT_REACHED", "LANDED", "DISARMED", "TELEMETRY", "FAILED",
          "LINK_LOST", "CANCEL", "CANCEL_ALL", "SCHEDULE_CHANGE")


@dataclass
class DronePlan:
    vehicle_id: str
    task_id: str
    start_delay_s: float
    route_local: list
    labels: list
    leg_minutes: list
    after: list = field(default_factory=list)   # [(vehicle_id, "COMPLETED")] aerial dependencies


def plans_from_adapter(adapted: dict) -> dict:
    return {d["vehicle_id"]: DronePlan(d["vehicle_id"], d["task_id"], float(d["start_delay_s"] or 0.0),
                                       d["timeline_inputs"]["route_local"], d["timeline_inputs"]["labels"],
                                       d["timeline_inputs"]["leg_minutes"])
            for d in adapted["drones"] if d.get("timeline_inputs")}


def plan_digest(plans: dict) -> str:
    body = {v: {"start_delay_s": p.start_delay_s, "route_local": p.route_local, "leg_minutes": p.leg_minutes,
                "after": p.after} for v, p in sorted(plans.items())}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def reproduce_deconfliction(plans: dict, policy) -> dict:
    """Offline reproduction of the planning result (e.g. M4c-r1: 16 conflicts, drone_01 delayed 45 s)."""
    return dc.deconflict({v: {"route_local": p.route_local, "labels": p.labels, "leg_minutes": p.leg_minutes}
                          for v, p in plans.items()}, policy)


class DroneScheduler:
    def __init__(self, plans: dict, policy, *, clock, mode: str = "OFFSET", accredited_sources=("TEST_FIXTURE",),
                 readiness_max_age_s: float = 5.0, telemetry_max_age_s: float = 3.0):
        if mode not in ("OFFSET", "SEQUENTIAL_H2"):
            raise ValueError(f"unknown mode {mode!r}")
        self.plans, self.policy, self.clock, self.mode = dict(plans), policy, clock, mode
        self.accredited = tuple(accredited_sources)
        self.readiness_max_age_s, self.telemetry_max_age_s = readiness_max_age_s, telemetry_max_age_s
        self.validated_digest = plan_digest(self.plans)
        self.state = {v: "PLANNED" for v in plans}
        self.ready_at, self.last_seen, self.started_at, self.reached = {}, {}, {}, {v: {} for v in plans}
        self.anchor = None
        self.global_cancel = False
        self.schedule_problem = None
        self.log = []
        if mode == "SEQUENTIAL_H2":
            order = sorted(plans, key=lambda v: (plans[v].start_delay_s, v))
            for prev, nxt in zip(order, order[1:]):
                if (prev, "COMPLETED") not in [tuple(a) for a in self.plans[nxt].after]:
                    self.plans[nxt].after = list(self.plans[nxt].after) + [(prev, "COMPLETED")]

    # ------------------------------------------------------------------------------------------- events --
    def handle(self, ev: dict) -> dict:
        kind, vid, at = ev.get("type"), ev.get("vehicle_id"), ev.get("at")
        if kind not in EVENTS:
            return self._out(ev, "REFUSED", f"unknown event {kind!r}")
        if ev.get("source") not in self.accredited:
            return self._out(ev, "REFUSED", f"SOURCE_NOT_ACCREDITED: {ev.get('source')!r}")
        if not isinstance(at, datetime) or at.tzinfo is None:
            return self._out(ev, "REFUSED", "event time must be timezone-aware")
        if kind == "CANCEL_ALL":
            self.global_cancel = True
            for v, s in self.state.items():
                if s in ("PLANNED", "READY", "START_PERMITTED"):
                    self.state[v] = "CANCELLED"
            return self._out(ev, "APPLIED", "every drone not yet airborne is cancelled; airborne ones must return")
        if kind == "SCHEDULE_CHANGE":
            new = {**self.plans, **ev.get("plans", {})}
            if plan_digest(new) != self.validated_digest:
                self.schedule_problem = "SCHEDULE_CHANGED_AFTER_VALIDATION: re-validate before any start"
                self.plans = new
                return self._out(ev, "APPLIED", self.schedule_problem)
            return self._out(ev, "APPLIED", "same schedule")
        if vid not in self.state:
            return self._out(ev, "REFUSED", f"UNKNOWN_VEHICLE: {vid!r}")
        self.last_seen[vid] = at
        s = self.state[vid]
        if kind == "TELEMETRY":
            if s == "UNKNOWN" and ev.get("recovered_state") in ("AIRBORNE", "LANDED", "COMPLETED"):
                self.state[vid] = ev["recovered_state"]       # an accredited report re-establishes the state
            return self._out(ev, "APPLIED", None)
        if kind == "READINESS":
            if s in ("PLANNED", "READY"):
                self.state[vid], self.ready_at[vid] = ("READY", at) if ev.get("ready") else ("PLANNED", None)
            return self._out(ev, "APPLIED", None)
        if kind == "CANCEL":
            if s in ("PLANNED", "READY", "START_PERMITTED"):
                self.state[vid] = "CANCELLED"
                return self._out(ev, "APPLIED", f"{vid} cancelled before take-off")
            return self._out(ev, "APPLIED", f"{vid} is {s}: it must return (abort requested, not commanded here)")
        if kind in ("FAILED", "LINK_LOST"):
            self.state[vid] = "FAILED" if kind == "FAILED" else "UNKNOWN"
            return self._out(ev, "APPLIED", f"{vid} {self.state[vid]}: no further start is permitted")
        if kind == "ARMED" and s == "START_PERMITTED":
            self.state[vid] = "ARMED"
        elif kind == "AIRBORNE" and s in ("START_PERMITTED", "ARMED"):
            self.state[vid] = "AIRBORNE"
            self.started_at[vid] = at
            self.anchor = self.anchor or at - timedelta(seconds=self.plans[vid].start_delay_s)
        elif kind == "WAYPOINT_REACHED" and s == "AIRBORNE":
            self.reached[vid][int(ev["index"])] = at
        elif kind == "LANDED" and s == "AIRBORNE":
            self.state[vid] = "LANDED"
        elif kind == "DISARMED" and s == "LANDED":
            self.state[vid] = "COMPLETED"
        else:
            return self._out(ev, "IGNORED", f"{kind} while {s}")
        return self._out(ev, "APPLIED", None)

    # ----------------------------------------------------------------------------------------- decisions --
    def decide(self) -> dict:
        """One evaluation at clock.now(): {vehicle_id: {"decision": START_PERMITTED | WAIT | HOLD | NONE,
        "reasons": [...]}}. START_PERMITTED is a permission to REQUEST a start from the executor, never a command."""
        now = self.clock()
        self._refresh(now)
        out = {}
        for vid, plan in sorted(self.plans.items(), key=lambda kv: (kv[1].start_delay_s, kv[0])):
            s = self.state[vid]
            if s not in ("PLANNED", "READY"):
                out[vid] = {"decision": "NONE", "state": s, "reasons": []}
                continue
            reasons = self._blocking(vid, plan, now)
            if reasons:
                hard = any(r.startswith(("CANCELLED", "SCHEDULE", "VEHICLE_", "PEER_")) for r in reasons)
                out[vid] = {"decision": "HOLD" if hard else "WAIT", "state": s, "reasons": reasons}
            else:
                self.state[vid] = "START_PERMITTED"
                out[vid] = {"decision": "START_PERMITTED", "state": "START_PERMITTED", "reasons": []}
        self.log.append({"at": now.isoformat(), "decisions": out})
        return out

    def _refresh(self, now):
        for vid, s in self.state.items():
            if s in ("ARMED", "AIRBORNE", "LANDED"):
                seen = self.last_seen.get(vid)
                if seen is None or (now - seen).total_seconds() > self.telemetry_max_age_s:
                    self.state[vid] = "UNKNOWN"     # stale telemetry is never assumed fine

    def _blocking(self, vid, plan, now) -> list[str]:
        r = []
        if self.global_cancel:
            r.append("CANCELLED: global cancellation")
        if self.schedule_problem:
            r.append(self.schedule_problem)
        bad = {v: s for v, s in self.state.items() if v != vid and s in ("FAILED", "UNKNOWN")}
        if bad:
            r.append(f"PEER_NOT_NOMINAL: {bad}")
        if self.state[vid] != "READY":
            r.append("VEHICLE_NOT_READY: no accredited readiness")
        elif (now - self.ready_at[vid]).total_seconds() > self.readiness_max_age_s:
            r.append("VEHICLE_READINESS_STALE")
        for other, cond in plan.after:
            if self.state.get(other) != cond:
                r.append(f"DEPENDENCY_PENDING: {other} {cond} (is {self.state.get(other)})")
        if self.anchor is None:
            if plan.start_delay_s > 0:
                r.append("WAITING_FOR_ANCHOR: the first drone has not taken off")
        else:
            elapsed = (now - self.anchor).total_seconds()
            if elapsed < plan.start_delay_s:
                r.append(f"START_TIME_NOT_REACHED: {elapsed:.1f} s of {plan.start_delay_s} s")
        cancelled = [v for v, s in self.state.items() if v != vid and s == "CANCELLED"]
        if cancelled and self.anchor is None:
            r.append(f"PEER_CANCELLED: {cancelled} cancelled before take-off; the validated plan no longer holds")
        if not r:
            r += self._separation(vid, plan, now)
        return r

    def _lag(self, vid, now) -> float:
        """Observed or overdue lag of a drone in the air against its nominal timeline (conservative, >= 0). Its
        landing counts too: still not LANDED after the nominal landing end is an overdue lag."""
        p, start = self.plans[vid], (self.started_at[vid] - self.anchor).total_seconds()  # take-off = climb start
        segs = dc.timeline(vid, p.route_local, p.labels, p.leg_minutes, self.policy, start)
        legs = [s for s in segs if s.kind == "leg"]
        lag = 0.0
        for i, s in enumerate(legs):
            t_nom = s.t1
            got = self.reached[vid].get(i + 1)
            t_now = (now - self.anchor).total_seconds()
            if got is not None:
                lag = max(lag, (got - self.anchor).total_seconds() - t_nom)
            elif t_now > t_nom:
                lag = max(lag, t_now - t_nom)   # overdue: where it is now is unknown, so assume it is late
                break
            else:
                break
        t_now = (now - self.anchor).total_seconds()
        if self.state.get(vid) in ("ARMED", "AIRBORNE") and t_now > segs[-1].t1:
            lag = max(lag, t_now - segs[-1].t1)   # still not landed after its nominal landing end
        return max(0.0, lag)

    def _separation(self, vid, plan, now) -> list[str]:
        anchor = self.anchor or now        # before the first take-off, candidates are checked as if starting now
        t = (now - anchor).total_seconds()
        cand = dc.timeline(vid, plan.route_local, plan.labels, plan.leg_minutes, self.policy, t)
        found = []
        for other, s in self.state.items():
            if other == vid or s not in ("START_PERMITTED", "ARMED", "AIRBORNE", "LANDED"):
                continue
            p = self.plans[other]
            if other in self.started_at:
                start = (self.started_at[other] - anchor).total_seconds()
            else:
                start = t
            segs = dc.timeline(other, p.route_local, p.labels, p.leg_minutes, self.policy,
                               start + (self._lag(other, now) if other in self.started_at and self.anchor else 0.0))
            found += dc.conflicts_between(cand, segs, self.policy)
        return [f"SEPARATION_RISK: {len(found)} conflict(s) with the drones in the air, e.g. {found[0]['segments']}"] \
            if found else []

    # ------------------------------------------------------------------------------------- persistence --
    def snapshot(self) -> dict:
        enc = lambda d: {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in d.items()}  # noqa: E731
        return {"schema": SCHEMA, "mode": self.mode, "validated_digest": self.validated_digest,
                "plans_digest": plan_digest(self.plans), "state": dict(self.state), "ready_at": enc(self.ready_at),
                "last_seen": enc(self.last_seen), "started_at": enc(self.started_at),
                "reached": {v: {str(i): t.isoformat() for i, t in r.items()} for v, r in self.reached.items()},
                "anchor": self.anchor.isoformat() if self.anchor else None, "global_cancel": self.global_cancel,
                "schedule_problem": self.schedule_problem}

    def restore(self, snap: dict) -> None:
        if snap["validated_digest"] != self.validated_digest or snap["plans_digest"] != plan_digest(self.plans):
            raise ValueError("SNAPSHOT_OF_ANOTHER_SCHEDULE")
        dec = lambda d: {k: datetime.fromisoformat(v) for k, v in d.items()}  # noqa: E731
        self.state = dict(snap["state"])
        self.ready_at, self.last_seen, self.started_at = dec(snap["ready_at"]), dec(snap["last_seen"]), \
            dec(snap["started_at"])
        self.reached = {v: {int(i): datetime.fromisoformat(t) for i, t in r.items()} for v, r in snap["reached"].items()}
        self.anchor = datetime.fromisoformat(snap["anchor"]) if snap["anchor"] else None
        self.global_cancel, self.schedule_problem = snap["global_cancel"], snap["schedule_problem"]
        for v, s in self.state.items():   # after a restart nothing is trusted until it is reported again
            if s == "READY":
                self.state[v], self.ready_at[v] = "PLANNED", None

    def _out(self, ev, outcome, reason):
        rec = {"type": ev.get("type"), "vehicle_id": ev.get("vehicle_id"), "outcome": outcome, "reason": reason}
        self.log.append(rec)
        return rec


def sitl_effective_deconfliction(plans: dict, spawn_xy: dict, policy) -> dict:
    """The H2 executor flies each mission relative to the drone's own launch position. In SITL the relative geometry
    is spawn + (route - takeoff), not the site's: re-run the same deconfliction on that geometry."""
    shifted = {}
    for v, p in plans.items():
        if v not in spawn_xy:
            return {"status": "PENDING_MISSING_DATA", "reason": f"no spawn position for {v}"}
        ox, oy = p.route_local[0]
        sx, sy = spawn_xy[v]
        shifted[v] = {"route_local": [[x - ox + sx, y - oy + sy] for x, y in p.route_local], "labels": p.labels,
                      "leg_minutes": p.leg_minutes}
    out = dc.deconflict(shifted, policy)
    out["geometry"] = "SITL_EFFECTIVE (spawn + mission offsets; Gazebo x east, y north assumed, to be verified)"
    out["spawn_xy"] = spawn_xy
    return out


def launch_spawn_positions(launch_file, names=(("drone1", "drone_01"), ("drone2", "drone_02"))) -> dict:
    """Spawn x, y of the drones as DECLARED in a committed launch file (read as text; nothing is launched)."""
    import re
    text = open(launch_file).read()
    out = {}
    for model, vid in names:
        m = re.search(r'"name":\s*"' + model + r'".*?"position":\s*\[\s*"([-0-9.]+)",\s*"([-0-9.]+)"', text, re.S)
        if m:
            out[vid] = (float(m.group(1)), float(m.group(2)))
    return out
