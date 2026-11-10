"""Offline event-driven coordinator of an integrated proposal: the mission's global state and the ground task that
waits for an observation, with explicit transitions, blocking on lost/stale information, and no execution.

It is NOT an executor and never commands anything. The furthest the mission gets is EXECUTION_PENDING (a valid,
scoped authorization exists but an executor would still have to pass its own preconditions) or EXECUTION_BLOCKED.
Offline only TEST_FIXTURE events are accepted; any other source is refused until a real, verified source exists.

Mission states (MISSION_TRANSITIONS lists every allowed move):
  MISSION_CREATED -> INTERPRETED -> AERIAL_PLANNED -> VALIDATED -> AWAITING_DETECTION -> DETECTION_RECEIVED
  -> TARGET_VALIDATED -> GROUND_PLANNED -> GROUND_VALIDATED -> AUTHORIZATION_REQUESTED -> EXECUTION_PENDING
  | EXECUTION_BLOCKED; any state -> CANCELLED (terminal) | ERROR (until an explicit RECOVER) | UNKNOWN (an
  unrecognised executor status: never assumed success); MISSION_CHANGED -> REPLAN_REQUIRED.
Ground task states:
  CONDITIONAL_AWAITING_OBSERVATION -> (observation refused for lack of position: AWAITING_GEOREFERENCED_TARGET)
  -> TARGET_VALIDATED -> (dependency reached) READY_FOR_AUTHORIZATION; blocked states: BLOCKED_OBSERVATION_EXPIRED,
  BLOCKED_DRONE_REPORTS_STALE, BLOCKED_DEPENDENCY_LOST, BLOCKED_NO_DRONE_TASK_AT_TARGET, BLOCKED_DETECTION_TIMEOUT,
  BLOCKED_VEHICLE_IDENTITY_CHANGED, BLOCKED_ERROR, WAITING_FOR_ROVER_LOCALIZATION, REJECTED_IMPOSSIBLE;
  REPLAN_REQUESTED after a mission change; CANCELLED.
Invariants: an unassigned objective is listed until the end; a cancelled mission never reactivates; a refused
later observation never erases a validated target; an observation is never an order.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from multiagent import perception

ACCEPTED_SOURCES = ("TEST_FIXTURE",)
# the observation sources each event source may carry: a fixture event cannot carry "sensor" data (that would let a
# SYNTHETIC_TEST image be relabelled as REAL_SENSOR or SITL_SENSOR); sensor kinds need their own accredited source
OBSERVATION_KINDS_BY_EVENT_SOURCE = {"TEST_FIXTURE": ("TEST_FIXTURE",)}
EVENT_TYPES = ("MISSION_PHASE", "OBSERVATION", "AERIAL_POINT_REACHED", "AERIAL_TASK_ABORTED", "HEARTBEAT", "CLOCK",
               "CANCEL", "MISSION_CHANGED", "VEHICLE_IDENTITY", "TOOL_ERROR", "EXECUTOR_PRECONDITIONS",
               "EXECUTOR_FEEDBACK", "AUTHORIZATION", "ROVER_DECISION", "RECOVER", "ROVER_AVAILABILITY",
               "AUTHORIZATION_REVOKED", "TARGET_WITHDRAWN")
MISSION_TRANSITIONS = {
    "MISSION_CREATED": {"INTERPRETED"},
    "INTERPRETED": {"AERIAL_PLANNED", "REFUSED_BY_SUPERVISOR", "CLARIFICATION_REQUESTED"},
    "REFUSED_BY_SUPERVISOR": set(), "CLARIFICATION_REQUESTED": set(),
    "AERIAL_PLANNED": {"VALIDATED"},
    "VALIDATED": {"AWAITING_DETECTION", "AUTHORIZATION_REQUESTED"},
    "AWAITING_DETECTION": {"DETECTION_RECEIVED"},
    "DETECTION_RECEIVED": {"TARGET_VALIDATED", "AWAITING_DETECTION"},
    "TARGET_VALIDATED": {"GROUND_PLANNED", "AWAITING_DETECTION"},
    "GROUND_PLANNED": {"GROUND_VALIDATED"},
    "GROUND_VALIDATED": {"AUTHORIZATION_REQUESTED"},
    "AUTHORIZATION_REQUESTED": {"EXECUTION_PENDING", "EXECUTION_BLOCKED"},
    "EXECUTION_BLOCKED": {"AUTHORIZATION_REQUESTED"},
    "EXECUTION_PENDING": {"EXECUTION_BLOCKED"},  # a revoked or expired authorization blocks it
    "REPLAN_REQUIRED": {"INTERPRETED"},
    "ERROR": set(), "UNKNOWN": set(), "CANCELLED": set(),
}
ALWAYS = {"CANCELLED", "ERROR", "UNKNOWN", "REPLAN_REQUIRED"}
# blocks an observation cannot clear: they need RECOVER, a new plan or a different vehicle state
STICKY = ("BLOCKED_ERROR", "BLOCKED_VEHICLE_IDENTITY_CHANGED", "WAITING_FOR_ROVER_LOCALIZATION", "REJECTED_IMPOSSIBLE",
          "BLOCKED_CONTRADICTORY_OBSERVATION", "WAITING_FOR_ROVER_AVAILABILITY", "BLOCKED_TARGET_WITHDRAWN",
          "READY_FOR_AUTHORIZATION", "CANCELLED", "REPLAN_REQUESTED")
GEOMETRY_REASONS = ("METRIC 3D POINT", "CAMERA POSE", "POSE IN THE SITE FRAME", "POSE CLOSE IN TIME", "UNIT QUATERNION",
                    "POSITION UNCERTAINTY")


class Coordinator:
    def __init__(self, *, proposal: dict, conditional_tasks: list[dict], site, context, fleet, cameras: dict,
                 policy: perception.Policy | None = None, stale_after_s: float = 10.0,
                 detection_deadline_s: float | None = None, created_at: datetime | None = None,
                 expected_rover: str | None = None, ready_hold_s: float = 300.0):
        self.site, self.context, self.fleet, self.cameras = site, context, fleet, cameras
        self.policy = policy or perception.Policy(allow_fixtures=True)
        self.stale_after = timedelta(seconds=stale_after_s)
        # how long after its observation stops being fresh a READY target may still be authorized (declared, not
        # learned); after that the target is no longer valid and needs a new observation
        self.ready_hold = timedelta(seconds=ready_hold_s)
        self.deadline = (created_at + timedelta(seconds=detection_deadline_s)) \
            if created_at and detection_deadline_s else None
        self.mission_state, self.mission_reason = "MISSION_CREATED", None
        self.aerial = {p["task_id"]: {"vehicle_id": p["vehicle_id"], "points": p["poi_sequence"],
                                      "state": "PENDING_AUTHORIZATION", "last_report": None, "reached": set()}
                       for p in (proposal.get("aerial") or {}).get("proposals", [])}
        self.unassigned = [{"objective_id": i["objective_id"], "reasons": i["reasons"]}
                           for i in (proposal.get("aerial") or {}).get("incompatible", [])]
        self.separation = (proposal.get("swarm_coordination") or {}).get("status")
        self.expected_rover = expected_rover or next((t.get("vehicle_id") for t in conditional_tasks), None)
        self.ground = {t["objective_id"]: {**t, "state": "CONDITIONAL_AWAITING_OBSERVATION", "target": None,
                                           "observation_id": None, "waits_for_task": None, "observation_valid_until": None}
                       for t in conditional_tasks}
        self.seen_events, self.seen_observations, self.last_at = set(), set(), {}
        self.unassigned_targets = []   # accepted cards no ground task was waiting for (for the operator)
        self.authorization_expires = None
        self.log: list[dict] = []

    # ------------------------------------------------------------------ mission state --
    def _mission(self, new: str, reason: str | None = None) -> bool:
        if self.mission_state == "CANCELLED":
            return False
        if new in ALWAYS or new in MISSION_TRANSITIONS.get(self.mission_state, set()):
            self.mission_state, self.mission_reason = new, reason
            return True
        return False

    def _ground_all(self, state, reason=None, only_open=True):
        for g in self.ground.values():
            if only_open and g["state"] in ("CANCELLED",):
                continue
            g["state"] = state
            if reason:
                g["reason"] = reason

    # ------------------------------------------------------------------ events --
    def handle(self, event: dict) -> dict:
        kind, source, at = event.get("type"), event.get("source"), event.get("at")
        if kind not in EVENT_TYPES:
            return self._record(event, "REFUSED", f"unknown event type {kind!r}")
        if source not in ACCEPTED_SOURCES:
            return self._record(event, "REFUSED", f"source {source!r} not accepted offline (only {ACCEPTED_SOURCES})")
        if not isinstance(at, datetime) or at.tzinfo is None:
            return self._record(event, "REFUSED", "event time must be timezone-aware")
        eid = event.get("event_id")
        if eid is not None:
            if eid in self.seen_events:
                return self._record(event, "DUPLICATE", f"event {eid} already applied (idempotent)")
            self.seen_events.add(eid)
        stream = event.get("task_id") or event.get("stream") or kind
        if kind not in ("CLOCK", "CANCEL") and stream in self.last_at and at < self.last_at[stream]:
            return self._record(event, "OUT_OF_ORDER", f"older than the last {stream} event; ignored")
        if self.mission_state == "CANCELLED" and kind != "CLOCK":
            return self._record(event, "REFUSED", "MISSION_CANCELLED: nothing reactivates a cancelled mission")
        if self.mission_state in ("REFUSED_BY_SUPERVISOR", "CLARIFICATION_REQUESTED") and kind not in ("CLOCK", "CANCEL"):
            return self._record(event, "REFUSED", f"{self.mission_state}: no plan exists, nothing continues")
        self.last_at[stream] = at
        handler = getattr(self, "_on_" + kind.lower())
        outcome = handler(event, at)
        self._advance(at)
        if outcome:
            return self._record(event, *outcome)
        return self._record(event, "APPLIED", None)

    def _on_mission_phase(self, e, at):
        if self.mission_state in ("REFUSED_BY_SUPERVISOR", "CLARIFICATION_REQUESTED"):
            return "REFUSED", f"the supervisor ended the mission ({self.mission_state}); nothing continues"
        if not self._mission(e.get("phase"), e.get("detail")):
            return "REFUSED", f"illegal transition {self.mission_state} -> {e.get('phase')}"
        if e.get("phase") == "VALIDATED" and self.ground and self.mission_state == "VALIDATED":
            self._mission("AWAITING_DETECTION")

    def _on_observation(self, e, at):
        raw = e["observation"]
        oid = (raw or {}).get("observation_id")
        if oid in self.seen_observations:
            return "DUPLICATE", f"observation {oid} already processed"
        self.seen_observations.add(oid)
        kind = (((raw or {}).get("source") or {}).get("kind"))
        if kind not in OBSERVATION_KINDS_BY_EVENT_SOURCE.get(e.get("source"), ()):
            return "REFUSED", (f"OBSERVATION_PROVENANCE_INCONSISTENT: a {e.get('source')} event cannot carry a "
                               f"{kind} observation (no accredited source for it)")
        if self.mission_state == "AWAITING_DETECTION":
            self._mission("DETECTION_RECEIVED")
        gate = perception.ground_target_from_observation(raw, site=self.site, context=self.context, fleet=self.fleet,
                                                         now=at, policy=self.policy, camera_ids=self.cameras)
        target_id = ((raw or {}).get("detection") or {}).get("target_id")
        bound = next((g for g in self.ground.values() if g.get("target_id") == target_id and target_id), None)
        if gate["status"] == "ACCEPTED":
            # one observation binds to ONE waiting task; a target already bound to a task is never given to another
            open_ = [g for g in self.ground.values() if g["state"] not in STICKY and g["state"] != "TARGET_VALIDATED"]
            candidates = [bound] if bound is not None else open_[:1]
            if not candidates and self.ground and self.mission_state not in ("ERROR", "UNKNOWN") and all(
                    x.get("target_id") not in (None, target_id) and x["state"] not in STICKY for x in self.ground.values()):
                # another card while every ground task already has ANOTHER target: recorded for the operator, never
                # attached to a task that was planned for a different target
                self.unassigned_targets.append({"target_id": target_id, "observation_id": oid,
                                                "poi": gate["target"]["matched_poi"]})
                return "UNASSIGNED_TARGET", (f"{target_id} at {gate['target']['matched_poi']}: no ground task is "
                                             "waiting for it; recorded for the operator")
        else:
            candidates = list(self.ground.values())
        for g in candidates:
            if g is None or g["state"] in STICKY or self.mission_state in ("ERROR", "UNKNOWN"):
                continue  # never silently replaces a handed-on target nor clears an error or a vehicle problem
            if gate["status"] != "ACCEPTED":
                if g["state"] == "TARGET_VALIDATED":
                    continue  # a refused second observation does not erase a valid first one (it is logged)
                geometric = any(r.startswith(GEOMETRY_REASONS) for r in gate["reasons"])
                g.update(state="AWAITING_GEOREFERENCED_TARGET" if geometric else "CONDITIONAL_AWAITING_OBSERVATION",
                         last_refusal=gate["reasons"][:3])
                continue
            target = gate["target"]["matched_poi"]
            stamp = perception.Observation.model_validate(raw).stamp_utc
            if g is bound and g.get("observation_stamp") is not None and stamp <= g["observation_stamp"]:
                # an OLDER report of the same target arriving late never replaces the newer one (logged)
                return "OUT_OF_ORDER_OBSERVATION", (f"{oid} observed at {stamp.isoformat()} is not newer than "
                                                    f"{g['observation_id']} ({g['observation_stamp'].isoformat()})")
            if g is bound and g.get("target") not in (None, target):
                # the same physical target reported at another point: never silently replaced
                g.update(state="BLOCKED_CONTRADICTORY_OBSERVATION",
                         reason=f"{target_id} validated at {g['target']}, now reported at {target}")
                continue
            waits = next((tid for tid, a in self.aerial.items() if target in a["points"]), None)
            obs = perception.Observation.model_validate(raw)
            g.update(state="TARGET_VALIDATED", target=target, observation_id=gate["observation_id"], target_id=target_id,
                     observation_stamp=obs.stamp_utc,
                     waits_for_task=waits, data_kind=gate["data_kind"], target_xy=(gate["target"]["x_m"], gate["target"]["y_m"]),
                     observation_valid_until=obs.stamp_utc + timedelta(seconds=min(obs.valid_for_s, self.policy.max_age_s)))
            if waits is None:
                g.update(state="BLOCKED_NO_DRONE_TASK_AT_TARGET")
        if self.mission_state == "DETECTION_RECEIVED":
            self._mission("TARGET_VALIDATED" if any(g["state"] == "TARGET_VALIDATED" for g in self.ground.values())
                          else "AWAITING_DETECTION")
        if gate["status"] != "ACCEPTED":
            return "APPLIED_REFUSED_OBSERVATION", "; ".join(gate["reasons"][:2])

    def _on_aerial_point_reached(self, e, at):
        task = self.aerial.get(e.get("task_id"))
        if task is None or e.get("point") not in task["points"]:
            return "REFUSED", "unknown aerial task or a point outside its plan"
        task["reached"].add(e["point"])
        task["last_report"] = at

    def _on_aerial_task_aborted(self, e, at):
        task = self.aerial.get(e.get("task_id"))
        if task is not None:
            task["state"], task["last_report"] = "ABORTED_REPORTED", at

    def _on_heartbeat(self, e, at):
        task = self.aerial.get(e.get("task_id"))
        if task is not None:
            task["last_report"] = at

    def _on_clock(self, e, at):
        return None

    def _on_cancel(self, e, at):
        self._mission("CANCELLED", e.get("reason"))
        self._ground_all("CANCELLED", e.get("reason"), only_open=False)

    def _on_mission_changed(self, e, at):
        self._mission("REPLAN_REQUIRED", e.get("detail"))
        for g in self.ground.values():
            g.update(state="REPLAN_REQUESTED", target=None, waits_for_task=None,
                     reason="mission changed: the target and dependencies must be planned again")

    def _on_vehicle_identity(self, e, at):
        if e.get("vehicle_id") != self.expected_rover:
            self._ground_all("BLOCKED_VEHICLE_IDENTITY_CHANGED",
                             f"planned {self.expected_rover}, reported {e.get('vehicle_id')}")

    def _on_tool_error(self, e, at):
        self._mission("ERROR", f"{e.get('tool')}: {e.get('error')}")
        self._ground_all("BLOCKED_ERROR", f"{e.get('tool')}: {e.get('error')}")

    def _on_executor_preconditions(self, e, at):
        reasons = e.get("reasons") or []
        if any(r.startswith(("NO_POSITION_SOURCE", "NO_POSITION")) for r in reasons):
            for g in self.ground.values():
                if g["state"] in ("TARGET_VALIDATED", "READY_FOR_AUTHORIZATION"):
                    g.update(state="WAITING_FOR_ROVER_LOCALIZATION", reason=reasons[0])

    def _on_executor_feedback(self, e, at):
        kind = e.get("feedback_type")
        if kind == "GROUND_TASK_FAILED":
            self._mission("ERROR", e.get("error"))
            self._ground_all("BLOCKED_ERROR", e.get("error"))
        elif kind == "GROUND_TASK_REFUSED_BY_EXECUTOR":
            self._mission("EXECUTION_BLOCKED", e.get("error")) or None
        elif kind == "GROUND_TASK_PHYSICAL_EFFECT_REPORTED":
            self._mission("UNKNOWN", "a physical effect was reported offline: stop and review")
        elif kind != "GROUND_TASK_STATUS":
            self._mission("UNKNOWN", f"unrecognised executor feedback {kind!r}: never assumed to be success")

    def _on_authorization(self, e, at):
        if self.mission_state != "AUTHORIZATION_REQUESTED":
            return "REFUSED", f"no authorization was requested (mission is {self.mission_state})"
        rec, req = e.get("authorization_record"), e.get("request")
        if rec is None or req is None:
            return "REFUSED", ("AUTHORIZATION_INVALID: a human authorization record bound to the exact plan is required "
                               "(a boolean or a bare scope is not one)")
        from multiagent import human_authorization
        problems = human_authorization.check(rec, req, now=at)
        if req.get("vehicle_id") != self.expected_rover:
            problems.append(f"ROVER_NOT_IN_THIS_MISSION: {req.get('vehicle_id')}")
        if problems:
            return "REFUSED", "AUTHORIZATION_INVALID: " + "; ".join(problems[:4])
        self._advance(at)  # the ground tasks as they are at the moment of the authorization, not when it was requested
        blocked = {oid: g["state"] for oid, g in self.ground.items() if g["state"].startswith("BLOCKED_")}
        ready = [oid for oid, g in self.ground.items() if g["state"] == "READY_FOR_AUTHORIZATION"]
        if blocked or not ready:
            return "REFUSED", (f"GROUND_TASK_NOT_READY_AT_AUTHORIZATION: "
                               f"{blocked or {oid: g['state'] for oid, g in self.ground.items()}}")
        reasons = e.get("preconditions") or []
        self.authorization_expires = datetime.fromisoformat(rec["expires_at_utc"])
        self._mission("EXECUTION_BLOCKED" if reasons else "EXECUTION_PENDING",
                      "; ".join(reasons[:3]) if reasons else "authorized; an executor must still pass its checks")

    def _on_rover_decision(self, e, at):
        """The Rover Agent's validated decision for an objective (from rover_gate): PLAN / CANNOT_PLAN / WAIT."""
        g = self.ground.get(e.get("objective_id"))
        if g is None:
            return "REFUSED", f"unknown ground objective {e.get('objective_id')}"
        if e.get("decision") == "CANNOT_PLAN":
            g.update(state="REJECTED_IMPOSSIBLE", reason=e.get("reason"))
        elif e.get("decision") == "PLAN_TO_DECLARED_POI" and g["state"] not in ("TARGET_VALIDATED", "READY_FOR_AUTHORIZATION"):
            return "REFUSED", "the rover cannot plan to a target that is not validated"

    def _on_rover_availability(self, e, at):
        """Temporary rover unavailability: tasks wait (reversibly) and nothing can be authorized meanwhile."""
        if e.get("vehicle_id") != self.expected_rover:
            return "REFUSED", f"not this mission's rover: {e.get('vehicle_id')}"
        for g in self.ground.values():
            if e.get("available") is False and g["state"] in ("TARGET_VALIDATED", "READY_FOR_AUTHORIZATION",
                                                              "CONDITIONAL_AWAITING_OBSERVATION"):
                g.update(state="WAITING_FOR_ROVER_AVAILABILITY", resume_state=g["state"], reason=e.get("reason"))
            elif e.get("available") is True and g["state"] == "WAITING_FOR_ROVER_AVAILABILITY":
                g.update(state=g.pop("resume_state", "CONDITIONAL_AWAITING_OBSERVATION"), reason=None)
        if e.get("available") is False and self.mission_state == "EXECUTION_PENDING":
            self._mission("EXECUTION_BLOCKED", f"rover unavailable: {e.get('reason')}")

    def _on_target_withdrawn(self, e, at):
        """The target is no longer available (e.g. the card was removed): the task bound to it can never execute."""
        hit = [g for g in self.ground.values() if g.get("target_id") == e.get("target_id")]
        if not hit:
            return "REFUSED", f"no ground task is bound to target {e.get('target_id')}"
        for g in hit:
            g.update(state="BLOCKED_TARGET_WITHDRAWN", reason=e.get("reason"))
        if self.mission_state == "EXECUTION_PENDING":
            self._mission("EXECUTION_BLOCKED", f"TARGET_WITHDRAWN: {e.get('reason')}")

    def _on_authorization_revoked(self, e, at):
        self.authorization_expires = None
        if self.mission_state in ("EXECUTION_PENDING",):
            self._mission("EXECUTION_BLOCKED", f"AUTHORIZATION_REVOKED: {e.get('reason')}")
        elif self.mission_state != "EXECUTION_BLOCKED":
            return "REFUSED", f"no applied authorization to revoke (mission is {self.mission_state})"

    def _on_recover(self, e, at):
        if self.mission_state != "ERROR":
            return "REFUSED", "nothing to recover"
        self.mission_state, self.mission_reason = "AWAITING_DETECTION", "recovered: waiting for a new valid observation"
        for g in self.ground.values():
            if g["state"] == "BLOCKED_ERROR":
                g.update(state="CONDITIONAL_AWAITING_OBSERVATION", target=None, waits_for_task=None)

    # ------------------------------------------------------------------ derived states --
    def _advance(self, at):
        if self.mission_state == "EXECUTION_PENDING" and getattr(self, "authorization_expires", None) and \
                at > self.authorization_expires:
            self._mission("EXECUTION_BLOCKED", "AUTHORIZATION_EXPIRED")
        for g in self.ground.values():
            if g["state"] == "CONDITIONAL_AWAITING_OBSERVATION" and self.deadline and at > self.deadline:
                g["state"] = "BLOCKED_DETECTION_TIMEOUT"
                continue
            if g["state"] in ("TARGET_VALIDATED", "READY_FOR_AUTHORIZATION"):
                if g["observation_valid_until"] and at > g["observation_valid_until"] and g["state"] == "TARGET_VALIDATED":
                    g["state"] = "BLOCKED_OBSERVATION_EXPIRED"
                    continue
                if g["observation_valid_until"] and at > g["observation_valid_until"] + self.ready_hold:
                    g["state"] = "BLOCKED_OBSERVATION_EXPIRED"  # a READY target is no longer valid either
                    continue
                task = self.aerial.get(g["waits_for_task"])
                if task is None or task["state"] == "ABORTED_REPORTED":
                    g["state"] = "BLOCKED_DEPENDENCY_LOST"
                    continue
                if task["last_report"] is not None and at - task["last_report"] > self.stale_after:
                    g["state"] = "BLOCKED_DRONE_REPORTS_STALE"
                    continue
                if g["state"] == "TARGET_VALIDATED" and g["target"] in task["reached"]:
                    g["state"] = "READY_FOR_AUTHORIZATION"

    def _record(self, event, outcome, reason):
        entry = {"event": {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in event.items()
                           if k not in ("observation",)}
                 | ({"observation_id": (event.get("observation") or {}).get("observation_id")}
                    if event.get("type") == "OBSERVATION" else {}),
                 "outcome": outcome, "reason": reason, "mission": self.mission_state, "ground": self.states()}
        self.log.append(entry)
        return entry

    def states(self) -> dict:
        return {oid: {k: g.get(k) for k in ("state", "target", "observation_id", "waits_for_task")}
                for oid, g in self.ground.items()}

    def summary(self) -> dict:
        return {"mission": self.mission_state, "mission_reason": self.mission_reason, "ground": self.states(),
                "aerial": {t: a["state"] for t, a in self.aerial.items()}, "unassigned_objectives": self.unassigned,
                "unassigned_targets": list(self.unassigned_targets),
                "separation": self.separation, "executing": [], "commands_sent": 0, "events": len(self.log),
                "note": "offline coordination states only; nothing here moves a vehicle"}

    # ------------------------------------------------------------------ persistence (recovery) --
    def snapshot(self) -> dict:
        """A JSON-able snapshot of the coordinator state (for a safe restart). Observations are not re-validated
        from it: a restored validated target keeps its expiry time."""
        def enc(v):
            if isinstance(v, datetime):
                return {"__dt__": v.isoformat()}
            if isinstance(v, set):
                return {"__set__": sorted(v)}
            if isinstance(v, tuple):
                return list(v)
            if isinstance(v, dict):
                return {k: enc(x) for k, x in v.items()}
            if isinstance(v, list):
                return [enc(x) for x in v]
            return v
        return enc({"mission_state": self.mission_state, "mission_reason": self.mission_reason, "aerial": self.aerial,
                    "ground": self.ground, "unassigned": self.unassigned, "separation": self.separation,
                    "seen_events": self.seen_events, "seen_observations": self.seen_observations,
                    "last_at": self.last_at, "deadline": self.deadline, "expected_rover": self.expected_rover,
                    "authorization_expires": self.authorization_expires,
                    "unassigned_targets": self.unassigned_targets})

    def restore(self, snap: dict) -> None:
        def dec(v):
            if isinstance(v, dict) and "__dt__" in v:
                return datetime.fromisoformat(v["__dt__"])
            if isinstance(v, dict) and "__set__" in v:
                return set(v["__set__"])
            if isinstance(v, dict):
                return {k: dec(x) for k, x in v.items()}
            if isinstance(v, list):
                return [dec(x) for x in v]
            return v
        s = dec(snap)
        for key in ("mission_state", "mission_reason", "aerial", "ground", "unassigned", "separation", "seen_events",
                    "seen_observations", "last_at", "deadline", "expected_rover"):
            setattr(self, key, s[key])
        self.authorization_expires = s.get("authorization_expires")
        self.unassigned_targets = s.get("unassigned_targets", [])
