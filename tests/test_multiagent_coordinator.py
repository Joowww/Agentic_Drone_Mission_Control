"""The event-driven mission coordinator, offline with TEST_FIXTURE events: transitions, dependencies, duplicates,
out-of-order and late events, timeouts, cancellation, unassigned objectives, lost information, identity changes,
invalid authorizations, error propagation, UNKNOWN, recovery and a persisted restart. Nothing moves anything."""
from datetime import timedelta
import json

import pytest

from multiagent import integrated_mission as im, perception as pc
from multiagent.mission_coordinator import MISSION_TRANSITIONS, Coordinator

SITE, FLEET = im._site_fleet(im.load_context(im.CONTEXT))
CTX = im.load_context(im.CONTEXT)
NOW = pc.utc_now()
A = im.run(now=NOW)["phase_a"]


def coord(**kw):
    return Coordinator(proposal=A["proposal"], conditional_tasks=A["conditional_ground_tasks"], site=SITE, context=CTX,
                       fleet=FLEET, cameras=im.CAMERAS, created_at=NOW, **kw)


def ev(kind, dt=0.0, **kw):
    return {"type": kind, "source": "TEST_FIXTURE", "at": NOW + timedelta(seconds=dt), **kw}


def obs(oid="obs-1", dt=0.0, **kw):
    o = pc.fixture_observation(site=SITE, drone="drone_02", poi="POI_3", now=NOW + timedelta(seconds=dt), age_s=0.0, **kw)
    o["observation_id"] = oid
    return o


def signed(dt=0.0, *, vehicle="rover_01"):
    """AUTHORIZATION event fields: a human-authorization RECORD for exactly this request (TEST_FIXTURE)."""
    from multiagent import human_authorization as ha, rover_executor_bridge as rb
    task = {"task_id": "GROUND_rover_01", "vehicle_id": vehicle, "target_point": "POI_3", "start_point": "ROVER_START"}
    req = rb.execution_request(task, SITE, proposal={"proposal_sha256": "b" * 64}, dependencies=[],
                               human_limits={"max_speed_mps": 0.2, "timeout_s": 60.0})
    rec = ha.record(req, operator_id="op-fixture", at=NOW + timedelta(seconds=dt - 1), valid_for_s=300, statement="fixture")
    return {"authorization_record": rec, "request": req}


def through_validated(c):
    for phase in ("INTERPRETED", "AERIAL_PLANNED", "VALIDATED"):
        assert c.handle(ev("MISSION_PHASE", phase=phase))["outcome"] == "APPLIED"
    assert c.mission_state == "AWAITING_DETECTION"
    return c


def g(c):
    return c.states()["G1"]["state"]


def test_the_full_mission_ladder_stops_at_execution_pending_or_blocked():
    c = through_validated(coord())
    c.handle(ev("HEARTBEAT", task_id="AIR_drone_02"))
    c.handle(ev("OBSERVATION", 1, observation=obs(dt=1)))
    assert c.mission_state == "TARGET_VALIDATED" and g(c) == "TARGET_VALIDATED"
    c.handle(ev("AERIAL_POINT_REACHED", 2, task_id="AIR_drone_02", point="POI_3"))
    assert g(c) == "READY_FOR_AUTHORIZATION"
    for phase in ("GROUND_PLANNED", "GROUND_VALIDATED", "AUTHORIZATION_REQUESTED"):
        assert c.handle(ev("MISSION_PHASE", 3, phase=phase))["outcome"] == "APPLIED"
    assert c.handle(ev("AUTHORIZATION", 4, human_authorized=True, scope_sha256="s", expected_scope="s"))["outcome"] \
        == "REFUSED"  # a boolean is not an authorization
    out = c.handle(ev("AUTHORIZATION", 4.5, **signed(4.5), preconditions=["DRY_RUN_ADAPTER: no physical adapter"]))
    assert out["outcome"] == "APPLIED" and c.mission_state == "EXECUTION_BLOCKED"
    assert c.summary()["executing"] == [] and c.summary()["commands_sent"] == 0


def test_illegal_transitions_are_refused():
    c = coord()
    assert c.handle(ev("MISSION_PHASE", phase="GROUND_PLANNED"))["outcome"] == "REFUSED"
    assert c.mission_state == "MISSION_CREATED"
    assert all(set(v) <= set(MISSION_TRANSITIONS) for v in MISSION_TRANSITIONS.values())  # closed table


def test_duplicates_are_idempotent_and_old_events_are_ignored():
    c = through_validated(coord())
    first = c.handle(ev("OBSERVATION", 1, observation=obs(dt=1), event_id="e1"))
    assert c.handle(ev("OBSERVATION", 1, observation=obs(dt=1), event_id="e1"))["outcome"] == "DUPLICATE"
    assert c.handle(ev("OBSERVATION", 2, observation=obs(dt=1), event_id="e2"))["outcome"] == "DUPLICATE"  # same obs id
    c.handle(ev("HEARTBEAT", 5, task_id="AIR_drone_02"))
    assert c.handle(ev("HEARTBEAT", 3, task_id="AIR_drone_02"))["outcome"] == "OUT_OF_ORDER"
    assert first["outcome"] == "APPLIED"


def test_a_cancelled_mission_never_reactivates():
    c = through_validated(coord())
    c.handle(ev("CANCEL", 1, reason="operator"))
    assert c.mission_state == "CANCELLED" and g(c) == "CANCELLED"
    late = c.handle(ev("OBSERVATION", 2, observation=obs("late", dt=2)))
    assert late["outcome"] == "REFUSED" and g(c) == "CANCELLED" and c.mission_state == "CANCELLED"
    assert c.handle(ev("RECOVER", 3))["outcome"] == "REFUSED"


def test_unassigned_objectives_and_separation_are_kept_visible():
    p = json.loads(json.dumps(A["proposal"]))
    p["aerial"]["incompatible"] = [{"objective_id": "A9", "reasons": ["COORDINATION_CONFLICT: ..."]}]
    c = Coordinator(proposal=p, conditional_tasks=A["conditional_ground_tasks"], site=SITE, context=CTX, fleet=FLEET,
                    cameras=im.CAMERAS)
    for _ in range(3):
        c.handle(ev("CLOCK"))
    assert c.summary()["unassigned_objectives"] == [{"objective_id": "A9", "reasons": ["COORDINATION_CONFLICT: ..."]}]
    assert c.summary()["separation"] == A["proposal"]["swarm_coordination"]["status"]


def test_detection_timeout_lost_dependency_identity_change_and_localization():
    c = through_validated(coord(detection_deadline_s=30))
    c.handle(ev("CLOCK", 31))
    assert g(c) == "BLOCKED_DETECTION_TIMEOUT"
    c = through_validated(coord())
    c.handle(ev("OBSERVATION", 1, observation=obs(dt=1)))
    c.handle(ev("VEHICLE_IDENTITY", 2, vehicle_id="rover_07"))
    assert g(c) == "BLOCKED_VEHICLE_IDENTITY_CHANGED"
    c = through_validated(coord())
    c.handle(ev("OBSERVATION", 1, observation=obs(dt=1)))
    c.handle(ev("EXECUTOR_PRECONDITIONS", 2, reasons=["NO_POSITION_SOURCE: none declared"]))
    assert g(c) == "WAITING_FOR_ROVER_LOCALIZATION"


def test_a_target_without_a_position_waits_for_georeference_and_mission_changes_force_a_replan():
    c = through_validated(coord())
    no_pose = obs("no-pose")
    no_pose["camera_pose"] = None
    c.handle(ev("OBSERVATION", 1, observation=no_pose))
    assert g(c) == "AWAITING_GEOREFERENCED_TARGET" and c.mission_state == "AWAITING_DETECTION"
    c.handle(ev("OBSERVATION", 2, observation=obs("ok", dt=2)))
    assert g(c) == "TARGET_VALIDATED"
    c.handle(ev("MISSION_CHANGED", 3, detail="operator moved the inspection area"))
    assert g(c) == "REPLAN_REQUESTED" and c.mission_state == "REPLAN_REQUIRED" and c.states()["G1"]["target"] is None


def test_errors_propagate_unknown_feedback_is_never_success_and_recovery_is_explicit():
    c = through_validated(coord())
    c.handle(ev("TOOL_ERROR", 1, tool="validate_ground_target", error="TOOL_TIMEOUT"))
    assert c.mission_state == "ERROR" and g(c) == "BLOCKED_ERROR"
    assert c.handle(ev("OBSERVATION", 2, observation=obs(dt=2)))["outcome"] in ("APPLIED", "APPLIED_REFUSED_OBSERVATION")
    assert g(c) == "BLOCKED_ERROR"  # an observation does not clear an error
    c.handle(ev("RECOVER", 3))
    assert c.mission_state == "AWAITING_DETECTION" and g(c) == "CONDITIONAL_AWAITING_OBSERVATION"
    c2 = through_validated(coord())
    c2.handle(ev("EXECUTOR_FEEDBACK", 1, feedback_type="SOMETHING_NEW"))
    assert c2.mission_state == "UNKNOWN"
    c3 = through_validated(coord())
    c3.handle(ev("EXECUTOR_FEEDBACK", 1, feedback_type="GROUND_TASK_FAILED", error="odometry lost"))
    assert c3.mission_state == "ERROR" and g(c3) == "BLOCKED_ERROR"


def test_invalid_authorizations_are_refused():
    c = through_validated(coord())
    assert c.handle(ev("AUTHORIZATION", 1, human_authorized=True, scope_sha256="s", expected_scope="s"))["outcome"] == \
        "REFUSED"  # nothing was requested yet
    c.handle(ev("OBSERVATION", 1, observation=obs(dt=1)))
    for phase in ("GROUND_PLANNED", "GROUND_VALIDATED", "AUTHORIZATION_REQUESTED"):
        c.handle(ev("MISSION_PHASE", 2, phase=phase))
    assert c.handle(ev("AUTHORIZATION", 3, human_authorized=False, scope_sha256="s", expected_scope="s"))["outcome"] == "REFUSED"
    assert c.handle(ev("AUTHORIZATION", 3, human_authorized=True, scope_sha256="x", expected_scope="s"))["outcome"] == "REFUSED"
    assert c.mission_state == "AUTHORIZATION_REQUESTED"


def test_rover_decisions_and_events_from_other_sources():
    c = through_validated(coord())
    assert c.handle(ev("ROVER_DECISION", 1, objective_id="G1", decision="PLAN_TO_DECLARED_POI"))["outcome"] == "REFUSED"
    c.handle(ev("ROVER_DECISION", 1, objective_id="G1", decision="CANNOT_PLAN", reason="ROVER_UNAVAILABLE"))
    assert g(c) == "REJECTED_IMPOSSIBLE"
    real = {**ev("OBSERVATION", 1, observation=obs("x")), "source": "OAK_D_PRO_W"}
    assert c.handle(real)["outcome"] == "REFUSED"
    assert c.handle({"type": "ARM", "source": "TEST_FIXTURE", "at": NOW})["outcome"] == "REFUSED"


def test_a_persisted_coordinator_restarts_in_the_same_state():
    c = through_validated(coord())
    c.handle(ev("OBSERVATION", 1, observation=obs(dt=1), event_id="e1"))
    snap = json.loads(json.dumps(c.snapshot()))  # through JSON: what would be written to disk
    d = coord()
    d.restore(snap)
    assert d.mission_state == c.mission_state and d.states() == c.states()
    assert d.handle(ev("OBSERVATION", 1, observation=obs(dt=1), event_id="e1"))["outcome"] == "DUPLICATE"
    d.handle(ev("CLOCK", 120))
    assert g(d) == "BLOCKED_OBSERVATION_EXPIRED"  # the restored target keeps its expiry


def test_two_cards_bind_to_two_tasks_and_a_reobservation_never_takes_another_task():
    tasks = A["conditional_ground_tasks"] + [{**A["conditional_ground_tasks"][0], "objective_id": "G2"}]
    c = Coordinator(proposal=A["proposal"], conditional_tasks=tasks, site=SITE, context=CTX, fleet=FLEET, cameras=im.CAMERAS)
    red = obs("red-1")
    c.handle(ev("OBSERVATION", observation=red))
    assert [c.states()[k]["state"] for k in ("G1", "G2")] == ["TARGET_VALIDATED", "CONDITIONAL_AWAITING_OBSERVATION"]
    again = {**obs("red-2", dt=1)}  # the same physical card (same target_id) seen again
    c.handle(ev("OBSERVATION", 1, observation=again))
    assert c.states()["G2"]["state"] == "CONDITIONAL_AWAITING_OBSERVATION"
    yellow = pc.fixture_observation(site=SITE, drone="drone_02", poi="POI_1", now=NOW + timedelta(seconds=2), age_s=0.0)
    yellow["observation_id"] = "yellow-1"
    yellow["detection"] = {**yellow["detection"], "object_class": "yellow_card", "target_id": "card_yellow_1"}
    c.handle(ev("OBSERVATION", 2, observation=yellow))
    s = c.states()
    assert s["G1"]["target"] == "POI_3" and s["G2"]["target"] == "POI_1"


def test_a_mission_the_supervisor_refused_is_terminal():
    c = coord()
    c.handle(ev("MISSION_PHASE", phase="INTERPRETED"))
    assert c.handle(ev("MISSION_PHASE", phase="REFUSED_BY_SUPERVISOR"))["outcome"] == "APPLIED"
    for e in (ev("MISSION_PHASE", 1, phase="AERIAL_PLANNED"), ev("OBSERVATION", 1, observation=obs("late")),
              ev("AUTHORIZATION", 1, human_authorized=True, scope_sha256="s", expected_scope="s")):
        assert c.handle(e)["outcome"] == "REFUSED"
    assert c.mission_state == "REFUSED_BY_SUPERVISOR"
