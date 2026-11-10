"""Multi-agent drone plan -> MissionDefinition through the real project code (swarm rebuild, Hermes validation, QGC
.plan profile, H2 executor compatibility, SITL binding). Input: the sealed M4c-r1 proposal, read without modifying
it (each test mutates a deep copy). Nothing is executed."""
import copy
import json
from pathlib import Path

import pytest

from multiagent import hermes_mission_adapter as ha, integrated_mission as im

M4C_R1 = Path(ha.__file__).parent / "benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9/demo/phase_b_proposal.json"
SEALED = json.loads(M4C_R1.read_text())
CTX = im.load_context(im.CONTEXT)
SITE, FLEET = im._site_fleet(CTX)
SRC = {"kind": "REPLAY_OF_SEALED_RUN", "agents_recorded_as": "REAL_LOCAL_LLM", "new_llm_calls": 0}


def adapt(p=None, *, context=CTX, site=SITE, **kw):
    return ha.adapt_proposal(copy.deepcopy(p or SEALED), context=context, site=site, fleet=FLEET, source=SRC, **kw)


def kinds(r):
    return {f["kind"] for f in r["findings"]}


def aerial(p, vid):
    return next(t for t in p["aerial"]["proposals"] if t["vehicle_id"] == vid)


def test_the_sealed_two_drone_plan_rebuilds_identically_and_passes_every_real_check():
    r = adapt()
    assert r["status"] == "PLANNING_VALID" and r["findings"] == [] and r["commands"] == []
    assert r["approval"]["status"] == "NOT_REQUESTED" and r["movement_authorized"] is False
    by = {d["vehicle_id"]: d for d in r["drones"]}
    for vid, delay, binding in (("drone_01", 45.0, "v1"), ("drone_02", 0.0, "v2")):
        d, t = by[vid], aerial(SEALED, vid)
        assert d["mission_sha256"] == d["recorded_mission_sha256"]           # byte-identical to what was validated
        assert d["qgc_plan"]["sha256"] == t["export"]["plan_sha256"]          # the same .plan the Drone Agent exported
        assert d["hermes_validation"]["mission_status"] == "FEASIBLE"
        assert d["hermes_validation"]["execution_status"] == "APPROVED"
        assert d["sitl_binding"]["simulated_vehicle"] == binding
        assert d["start_delay_s"] == delay and d["georeference"]["verification"] == "SYNTHETIC"
        assert d["sensors"]["required"][d["objective_ids"][0]] in d["sensors"]["drone"]
    assert r["separation"]["status"] == "DECONFLICTED_BY_START_DELAY" and r["separation"]["initial_conflicts"] == 16
    assert {d["task_id"] for d in r["dependencies"]} == {"GROUND_rover_01"}


def test_a_single_drone_mission():
    p = copy.deepcopy(SEALED)
    p["aerial"]["proposals"] = [aerial(p, "drone_02")]
    p["tasks"] = [t for t in p["tasks"] if t["task_id"] != "AIR_drone_01"]
    p["template"]["dependencies"] = [d for d in p["template"]["dependencies"] if d["after"] != "AIR_drone_01"]
    r = adapt(p)
    assert r["status"] == "PLANNING_VALID" and [d["vehicle_id"] for d in r["drones"]] == ["drone_02"]


def test_repeated_objectives_are_rejected():
    p = copy.deepcopy(SEALED)
    t = aerial(p, "drone_01")
    t.update(objective_ids=["A2"], poi_sequence=["POI_3"])
    r = adapt(p)
    assert r["status"] == "REJECTED" and {"DUPLICATE_OBJECTIVE", "DUPLICATE_POINT"} <= kinds(r)


def test_an_altitude_beyond_the_site_limit_is_rejected():
    p = copy.deepcopy(SEALED)
    p["brief"]["altitude_m"] = 500.0
    r = adapt(p)
    assert r["status"] == "REJECTED" and "ROUTE_NOT_FEASIBLE" in kinds(r)


def test_a_point_outside_the_site_is_rejected():
    data = SITE.model_dump()
    data["points"] = data["points"] + [{**data["points"][-1], "point_id": "POI_FAR", "x_m": 400.0, "y_m": 400.0}]
    far = type(SITE).model_validate(data)
    p = copy.deepcopy(SEALED)
    aerial(p, "drone_02")["poi_sequence"] = ["POI_FAR"]
    r = adapt(p, site=far)
    assert r["status"] == "REJECTED" and "ROUTE_NOT_FEASIBLE" in kinds(r)


def test_an_unspecified_speed_falls_to_the_declared_cruise_speed_and_says_so():
    ctx = CTX.model_copy(update={"requested_speed_kmh": None,
                                 "drones": [d.model_copy(update={"survey_speed_kmh": None}) for d in CTX.drones]})
    r = adapt(context=ctx)
    for d in r["drones"]:
        assert d["speed_source"].startswith("VEHICLE_CRUISE_SPEED") and all(w["speed_kmh"] is None for w in d["waypoints"])
    assert "PLAN_MODIFIED_AFTER_VALIDATION" in kinds(r)   # other inputs than the validated plan: never silently reused


def test_a_sensor_the_drone_does_not_carry_is_rejected():
    p = copy.deepcopy(SEALED)
    aerial(p, "drone_01").update(objective_ids=["A2"], poi_sequence=["POI_3"])
    aerial(p, "drone_02").update(objective_ids=["A1"], poi_sequence=["POI_1"])
    r = adapt(p)
    assert r["status"] == "REJECTED" and "SENSOR_NOT_AVAILABLE" in kinds(r)


def test_a_site_without_georeference_leaves_the_mission_pending_parameters():
    r = adapt(site=SITE.model_copy(update={"geo_reference": None}))
    assert r["status"] == "PENDING_PARAMETERS" and "GEOREFERENCE_MISSING" in kinds(r)
    assert all("mission" not in d for d in r["drones"])


def test_unmet_dependencies_are_rejected():
    p = copy.deepcopy(SEALED)
    p["template"]["dependencies"].append({"task_id": "GROUND_rover_01", "after": "AIR_drone_09", "condition": "COMPLETED"})
    p["template"]["dependencies"][0]["point"] = "POI_1"          # drone_02 never visits POI_1
    r = adapt(p)
    assert r["status"] == "REJECTED"
    assert sum(f["kind"] == "UNMET_DEPENDENCY" for f in r["findings"]) == 2


def test_a_plan_modified_after_validation_is_rejected():
    p = copy.deepcopy(SEALED)
    aerial(p, "drone_02")["mission_sha256"] = "0" * 64
    r = adapt(p)
    assert r["status"] == "REJECTED" and "PLAN_MODIFIED_AFTER_VALIDATION" in kinds(r)
    p = copy.deepcopy(SEALED)
    aerial(p, "drone_01")["start_delay_s"] = 0.0                 # the agenda no longer matches the deconfliction
    assert "SCHEDULE_INCONSISTENT" in kinds(adapt(p))


def test_a_cancelled_or_unplanned_mission_prepares_nothing():
    r = adapt(cancelled=True)
    assert r["status"] == "CANCELLED" and r["drones"] == []
    p = copy.deepcopy(SEALED)
    p["status"] = "NEEDS_CLARIFICATION"
    assert adapt(p)["status"] == "REJECTED"


def test_the_mission_files_are_the_exact_validated_bytes():
    from planning.scenario_instance import sha256
    files = ha.mission_files(adapt())
    assert {v: sha256(b) for v, b in files.items()} == {t["vehicle_id"]: t["mission_sha256"]
                                                        for t in SEALED["aerial"]["proposals"]}


def test_the_sealed_evidence_is_not_modified():
    import hashlib
    sums = (M4C_R1.parent / "SHA256SUMS").read_text()
    assert hashlib.sha256(M4C_R1.read_bytes()).hexdigest() in sums


def test_an_objective_no_drone_covers_is_reported_not_dropped():
    p = copy.deepcopy(SEALED)
    p["aerial"]["incompatible"] = [{"objective_id": "A3", "reasons": ["SENSOR_NOT_IN_FLEET: thermal"]}]
    r = adapt(p)
    assert r["status"] == "PLANNING_VALID"                       # informational: the rest of the plan stays valid
    assert [f for f in r["findings"] if f["kind"] == "UNASSIGNED_OBJECTIVE"][0]["action"] == "REPORTED"
