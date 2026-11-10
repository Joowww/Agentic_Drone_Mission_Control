"""Temporal coordination of the two planned drone missions (injected clock, accredited events, separation re-checked
with the planning model). Plans: the sealed M4c-r1 proposal through the Hermes adapter (read-only). No vehicle."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from multiagent import drone_schedule as ds, hermes_mission_adapter as ha, integrated_mission as im

CTX = im.load_context(im.CONTEXT)
SITE, FLEET = im._site_fleet(CTX)
POLICY = CTX.separation_policy
SEALED = json.loads((Path(ha.__file__).parent / "benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9/demo/"
                     "phase_b_proposal.json").read_text())
ADAPTED = ha.adapt_proposal(SEALED, context=CTX, site=SITE, fleet=FLEET, source={"kind": "REPLAY_OF_SEALED_RUN"})
T0 = datetime(2026, 11, 8, 10, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t

    def at(self, s):
        self.t = T0 + timedelta(seconds=s)
        return self.t


def make(mode="OFFSET", plans=None):
    clock = Clock()
    return ds.DroneScheduler(plans or ds.plans_from_adapter(ADAPTED), POLICY, clock=clock, mode=mode), clock


def ev(s, clock, kind, vid=None, at=None, **kw):
    return s.handle({"type": kind, "vehicle_id": vid, "source": kw.pop("source", "TEST_FIXTURE"),
                     "at": clock.at(at) if at is not None else clock.t, **kw})


def ready_both(s, c, at=0.0):
    for v in ("drone_01", "drone_02"):
        ev(s, c, "READINESS", v, at, ready=True)


def fly_drone_02_nominally(s, c, until):
    """drone_02 takes off at 0 and reports on its nominal timeline (telemetry every second) up to ``until``."""
    ev(s, c, "AIRBORNE", "drone_02", 0.0)
    p = s.plans["drone_02"]
    segs = ds.dc.timeline("drone_02", p.route_local, p.labels, p.leg_minutes, POLICY, 0.0)
    legs = [x for x in segs if x.kind == "leg"]
    marks = {round(x.t1, 2): ("WAYPOINT_REACHED", i + 1) for i, x in enumerate(legs)}
    marks[round(segs[-1].t1, 2)] = ("LANDED", None)
    t = 0.0
    while t <= until:
        for m, (kind, idx) in sorted(marks.items()):
            if t - 1.0 < m <= t:
                if kind == "LANDED":
                    ev(s, c, "LANDED", "drone_02", t)
                    ev(s, c, "DISARMED", "drone_02", t)
                else:
                    ev(s, c, kind, "drone_02", t, index=idx)
        ev(s, c, "TELEMETRY", "drone_02", t)
        t += 1.0


# 1-3 ------------------------------------------------------------------------------------------------------------
def test_the_m4c_r1_deconfliction_is_reproduced_offline_and_holds_on_the_sitl_geometry():
    plans = ds.plans_from_adapter(ADAPTED)
    d = ds.reproduce_deconfliction(plans, POLICY)
    assert d["status"] == "DECONFLICTED_BY_START_DELAY" and len(d["initial_conflicts"]) == 16
    assert d["schedule"]["drone_01"]["start_delay_s"] == 45.0 and d["schedule"]["drone_02"]["start_delay_s"] == 0.0
    launch = Path(ha.__file__).parents[1] / "simulation/ros2_gazebo/launch/tfg_demo_2drones.launch.py"
    spawn = ds.launch_spawn_positions(launch)
    assert spawn == {"drone_01": (-2.0, 0.0), "drone_02": (2.0, 0.0)}
    e = ds.sitl_effective_deconfliction(plans, spawn, POLICY)
    assert e["status"] == "DECONFLICTED_BY_START_DELAY" and e["schedule"]["drone_01"]["start_delay_s"] == 45.0


def test_two_drones_without_conflict_are_both_permitted():
    far = {v: ds.DronePlan(v, f"AIR_{v}", 0.0, [[x, -6.0], [x, 5.0], [x, -6.0]], ["T", "P", "T"], [0.05, 0.05])
           for v, x in (("drone_01", -40.0), ("drone_02", 40.0))}
    assert ds.reproduce_deconfliction(far, POLICY)["status"] == "CLEAR"
    s, c = make(plans=far)
    ready_both(s, c)
    assert {v: d["decision"] for v, d in s.decide().items()} == {"drone_01": "START_PERMITTED",
                                                                  "drone_02": "START_PERMITTED"}


def test_the_conflicting_pair_starts_drone_02_first_and_drone_01_exactly_45_s_later():
    s, c = make()
    ready_both(s, c)
    d = s.decide()
    assert d["drone_02"]["decision"] == "START_PERMITTED" and d["drone_01"]["decision"] == "WAIT"
    assert d["drone_01"]["reasons"] == ["WAITING_FOR_ANCHOR: the first drone has not taken off"]
    fly_drone_02_nominally(s, c, 44.0)
    ev(s, c, "READINESS", "drone_01", 44.0, ready=True)
    c.at(44.9)
    assert s.decide()["drone_01"]["reasons"][0].startswith("START_TIME_NOT_REACHED")
    c.at(45.0)
    assert s.decide()["drone_01"]["decision"] == "START_PERMITTED"


# 4-6 ------------------------------------------------------------------------------------------------------------
def test_a_drone_that_is_not_ready_is_held_whatever_the_time():
    s, c = make()
    ev(s, c, "READINESS", "drone_02", 0.0, ready=True)
    fly = s.decide()
    assert fly["drone_02"]["decision"] == "START_PERMITTED"
    fly_drone_02_nominally(s, c, 46.0)
    d = s.decide()["drone_01"]
    assert d["decision"] == "HOLD" and "VEHICLE_NOT_READY: no accredited readiness" in d["reasons"]


def test_without_the_first_drone_ready_nothing_starts():
    s, c = make()
    ev(s, c, "READINESS", "drone_01", 0.0, ready=True)
    c.at(100.0)
    d = s.decide()
    assert d["drone_02"]["decision"] == "HOLD" and d["drone_01"]["decision"] != "START_PERMITTED"


def test_an_aerial_dependency_keeps_the_second_drone_waiting_after_its_time_in_sequential_mode():
    s, c = make(mode="SEQUENTIAL_H2")
    ready_both(s, c)
    s.decide()
    ev(s, c, "AIRBORNE", "drone_02", 0.0)
    for t in range(1, 50):
        ev(s, c, "TELEMETRY", "drone_02", float(t))
    ev(s, c, "READINESS", "drone_01", 49.0, ready=True)
    d = s.decide()["drone_01"]
    assert d["decision"] == "WAIT" and any(r.startswith("DEPENDENCY_PENDING: drone_02 COMPLETED") for r in d["reasons"])
    ev(s, c, "LANDED", "drone_02", 50.0)
    ev(s, c, "DISARMED", "drone_02", 50.0)
    ev(s, c, "READINESS", "drone_01", 50.0, ready=True)
    assert s.decide()["drone_01"]["decision"] == "START_PERMITTED"


# 7-9 ------------------------------------------------------------------------------------------------------------
def test_stale_telemetry_makes_the_drone_unknown_and_holds_the_other():
    s, c = make()
    ready_both(s, c)
    s.decide()
    ev(s, c, "AIRBORNE", "drone_02", 0.0)
    ev(s, c, "READINESS", "drone_01", 45.0, ready=True)
    d = s.decide()
    assert s.state["drone_02"] == "UNKNOWN" and d["drone_01"]["decision"] == "HOLD"
    assert any(r.startswith("PEER_NOT_NOMINAL") for r in d["drone_01"]["reasons"])


def test_a_failure_during_a_mission_holds_every_further_start():
    s, c = make()
    ready_both(s, c)
    s.decide()
    ev(s, c, "AIRBORNE", "drone_02", 0.0)
    ev(s, c, "FAILED", "drone_02", 5.0, reason="EKF failsafe (fixture)")
    ev(s, c, "READINESS", "drone_01", 45.0, ready=True)
    assert s.decide()["drone_01"]["decision"] == "HOLD"


def test_one_drone_landing_before_the_other_starts_clears_it():
    s, c = make()
    ready_both(s, c)
    s.decide()
    fly_drone_02_nominally(s, c, 44.0)
    assert s.state["drone_02"] == "COMPLETED"
    ev(s, c, "READINESS", "drone_01", 44.5, ready=True)
    c.at(45.0)
    assert s.decide()["drone_01"]["decision"] == "START_PERMITTED"


# 10-12 ----------------------------------------------------------------------------------------------------------
def test_a_global_cancellation_stops_every_pending_start():
    s, c = make()
    ready_both(s, c)
    ev(s, c, "CANCEL_ALL", None, 0.0)
    d = s.decide()
    assert all(x["decision"] == "NONE" and x["state"] == "CANCELLED" for x in d.values())


def test_an_individual_cancellation_invalidates_the_plan_for_the_other_drone():
    s, c = make()
    ready_both(s, c)
    ev(s, c, "CANCEL", "drone_02", 0.0)
    c.at(50.0)
    ev(s, c, "READINESS", "drone_01", 50.0, ready=True)
    d = s.decide()["drone_01"]
    assert s.state["drone_02"] == "CANCELLED" and d["decision"] == "HOLD"
    assert any(r.startswith("PEER_CANCELLED") for r in d["reasons"])


def test_an_unexpected_schedule_change_holds_until_revalidated():
    s, c = make()
    ready_both(s, c)
    changed = ds.plans_from_adapter(ADAPTED)["drone_01"]
    changed.start_delay_s = 10.0
    out = ev(s, c, "SCHEDULE_CHANGE", None, 0.0, plans={"drone_01": changed})
    assert out["reason"].startswith("SCHEDULE_CHANGED_AFTER_VALIDATION")
    assert all(d["decision"] == "HOLD" for d in s.decide().values())


# 13-15 ----------------------------------------------------------------------------------------------------------
def test_a_restarted_coordinator_keeps_the_flight_state_but_trusts_no_old_readiness():
    s, c = make()
    ready_both(s, c)
    s.decide()
    fly_drone_02_nominally(s, c, 10.0)
    snap = json.loads(json.dumps(s.snapshot()))
    r, rc = make()
    rc.at(10.5)
    r.restore(snap)
    assert r.state["drone_02"] == "AIRBORNE" and r.state["drone_01"] == "PLANNED" and r.anchor == T0
    other, _ = make(plans={**ds.plans_from_adapter(ADAPTED), "drone_01": ds.DronePlan("drone_01", "x", 0.0,
                                                                                      [[0, 0], [1, 1]], ["a", "b"], [1])})
    with pytest.raises(ValueError, match="SNAPSHOT_OF_ANOTHER_SCHEDULE"):
        other.restore(snap)


def test_a_lost_link_is_unknown_never_assumed_fine():
    s, c = make()
    ready_both(s, c)
    s.decide()
    ev(s, c, "AIRBORNE", "drone_02", 0.0)
    ev(s, c, "LINK_LOST", "drone_02", 1.0)
    ev(s, c, "READINESS", "drone_01", 45.0, ready=True)
    assert s.state["drone_02"] == "UNKNOWN" and s.decide()["drone_01"]["decision"] == "HOLD"


def test_a_late_first_drone_brings_the_separation_risk_back_and_blocks_the_second():
    s, c = make()
    ready_both(s, c)
    s.decide()
    ev(s, c, "AIRBORNE", "drone_02", 0.0)
    for t in range(1, 46):                      # alive, but never reports its waypoint nor its landing
        ev(s, c, "TELEMETRY", "drone_02", float(t))
    ev(s, c, "READINESS", "drone_01", 45.0, ready=True)
    d = s.decide()["drone_01"]
    assert d["decision"] == "WAIT" and d["reasons"][0].startswith("SEPARATION_RISK")
    ev(s, c, "LANDED", "drone_02", 46.0)
    ev(s, c, "DISARMED", "drone_02", 46.0)
    ev(s, c, "READINESS", "drone_01", 46.0, ready=True)
    assert s.decide()["drone_01"]["decision"] == "START_PERMITTED"


def test_an_unaccredited_source_changes_nothing():
    s, c = make()
    out = ev(s, c, "READINESS", "drone_02", 0.0, ready=True, source="SITL_UNACCREDITED")
    assert out["outcome"] == "REFUSED" and s.state["drone_02"] == "PLANNED"
