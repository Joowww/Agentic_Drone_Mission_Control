"""Drone Agent contract /3: exhaustive offline integration (scripted replies through the real gate, separation check,
revision feedback and supervisor; no model call). D13 is not run against Qwen here (no budget outside M4b)."""
import json

import pytest

from multiagent.benchmark import agents_pilot as ap, run as bench
from multiagent.llm_agents import MultiAgentConfig


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("OPIK_API_KEY", raising=False)


def run_case(case_id, replies, *, max_revisions=1):
    """replies: list of proposals, one per call (the last one repeats). Returns (row, role_row, prompts seen)."""
    seen = []

    def responder(p):
        seen.append(p)
        prop = replies[min(len(seen), len(replies)) - 1]
        return json.dumps({"proposal": prop, "verify": [], "explanation": "scripted"})
    config = MultiAgentConfig.model_validate({
        "schema": "tfg.multiagent.agents-config/1", "config_id": "t", "data_kind": "SIMULATED_MODELS",
        "mission_orchestrator": {"mode": "oracle"},
        "drone_swarm_agent": {"mode": "llm", "candidate": "scripted:d", "step_contract": "single_shot",
                              "prompt_id": "agent_drone_single/3", "max_llm_calls": 1 + max_revisions,
                              "max_revisions": max_revisions, "revision_feedback": "findings_and_verifications"}})
    r = bench.run("rules", dataset_name="dev_v3", agents_config=config, only={case_id}, keep_internals=True,
                  simulated={"d": responder})
    return r["rows"][0], ap.role_row("drone_swarm_agent", r["rows"][0], r["_internals"][0]), seen


def findings(rr, phase="first"):
    return (rr["phases"].get(phase) or {}).get("findings") or []


def feedback_of(prompt):
    line = next(l for l in prompt.splitlines() if l.startswith("FEEDBACK (data): "))
    return json.loads(json.loads(line.split(": ", 1)[1])[0])["revision"]


def test_an_omitted_objective_is_a_contract_finding():
    row, rr, _ = run_case("D10", [{"assignments": {"drone_03": ["A1", "A3"]}, "unassigned": []}], max_revisions=0)
    assert any(f.startswith("INCONSISTENT_UNASSIGNED: A2 appears 0 times") for f in findings(rr))
    assert rr["agent_success"] is False and rr["final_allocation_from"] != "MODEL"


@pytest.mark.parametrize("proposal", [
    {"assignments": {"drone_03": ["A1", "A3"], "drone_01": ["A2", "A2"]}, "unassigned": []},          # twice to one drone
    {"assignments": {"drone_03": ["A1", "A3"], "drone_01": ["A2"]},
     "unassigned": [{"objective_id": "A2", "reason": "ROUTE_INFEASIBLE"}]},                            # assigned and left out
    {"assignments": {"drone_03": ["A3", "A2"], "drone_01": ["A1", "A2"]}, "unassigned": []},          # to two drones
])
def test_a_duplicated_objective_is_a_contract_finding(proposal):
    row, rr, _ = run_case("D10", [proposal], max_revisions=0)
    assert any(f.startswith("INCONSISTENT_UNASSIGNED: A2 appears 2 times") for f in findings(rr))
    assert rr["agent_success"] is False


def test_an_assignment_without_the_sensor_is_rejected_and_a_viable_alternative_is_accepted_after_revision():
    bad = {"assignments": {"drone_01": ["A1", "A3"], "drone_03": ["A2"]}, "unassigned": []}  # drone_01 cannot do A3
    good = {"assignments": {"drone_01": ["A1", "A2"], "drone_03": ["A3"]}, "unassigned": []}
    row, rr, seen = run_case("D10", [bad, good])
    assert rr["phases"]["first"]["accepted"] is False
    revision = feedback_of(seen[1])
    assert revision["violated_constraint"] == "ELIGIBILITY_OR_ROUTE" and "ASSIGN_ONLY_ELIGIBLE_DRONES" in revision["allowed_actions"]
    assert any("A3" in v or "drone_01" in v for v in revision["violations"])
    assert rr["phases"]["success"] == "AFTER_REVISION" and rr["final_allocation_from"] == "MODEL"
    assert row["status"] == "PROPOSED_PENDING_AUTHORIZATION" and row["case_pass"]


def test_an_identical_revision_is_refused_without_checks_and_the_fallback_is_labelled():
    bad = {"assignments": {"drone_01": ["A1", "A3"], "drone_03": ["A2"]}, "unassigned": []}
    row, rr, _ = run_case("D10", [bad])
    assert any(f.startswith("REPEATED_REJECTED_ASSIGNMENT") for f in findings(rr, "second"))
    assert rr["agent_success"] is False and rr["final_allocation_from"] in ("DETERMINISTIC_REFERENCE", "DETERMINISTIC_ALTERNATIVE")


def test_an_unresolved_separation_conflict_is_never_accepted():
    both = {"assignments": {"drone_02": ["A2"], "drone_03": ["A1"]}, "unassigned": []}
    row, rr, _ = run_case("D13", [both], max_revisions=0)
    assert rr["phases"]["first"]["accepted"] is False
    assert any(f.startswith("SEPARATION UNRESOLVED") for f in findings(rr))
    assert row["status"] == "PARTIAL_PENDING_AUTHORIZATION"  # the deterministic side leaves one out, never flies both
    assert row["case_pass"] and rr["agent_success"] is False


def test_a_valid_declaration_of_impossibility_is_accepted():
    # D05: no drone carries the sensor; the agent says so with the closed reason
    row, rr, _ = run_case("D05", [{"assignments": {}, "unassigned": [{"objective_id": "A1", "reason": "NO_ELIGIBLE_DRONE"}]}],
                          max_revisions=0)
    assert not any(f.startswith("UNASSIGNED_REASON_CONTRADICTS_CONTEXT") for f in findings(rr))
    assert row["status"] == "INFEASIBLE" and row["case_pass"]
    # D13: leaving one conflicting objective out with SEPARATION_CONFLICT is the resolution
    row, rr, _ = run_case("D13", [{"assignments": {"drone_03": ["A1"]},
                                   "unassigned": [{"objective_id": "A2", "reason": "SEPARATION_CONFLICT"}]}], max_revisions=0)
    assert rr["phases"]["success"] == "FIRST_ROUND" and rr["final_allocation_from"] == "MODEL"
    assert row["status"] == "PARTIAL_PENDING_AUTHORIZATION" and row["criteria"]["max_residual_conflicts"]
    # fixed (D13 expectation unchanged): the declared SEPARATION_CONFLICT is verified and reaches the plan's reasons
    assert row["criteria"]["reason_contains"] is True and row["case_pass"] is True


@pytest.mark.parametrize("case_id, proposal, needle", [
    ("D10", {"assignments": {"drone_01": ["A1", "A2"]}, "unassigned": [{"objective_id": "A3", "reason": "NO_ELIGIBLE_DRONE"}]},
     "A3: NO_ELIGIBLE_DRONE but eligible ['drone_03']"),
    ("D01", {"assignments": {}, "unassigned": [{"objective_id": "A1", "reason": "SEPARATION_CONFLICT"}]},
     "A1: SEPARATION_CONFLICT with no assigned drone"),
])
def test_an_impossibility_that_contradicts_the_context_is_refused(case_id, proposal, needle):
    row, rr, _ = run_case(case_id, [proposal], max_revisions=0)
    assert any(needle in f for f in findings(rr)), findings(rr)
    assert rr["agent_success"] is False and rr["final_allocation_from"] != "MODEL"


def test_leaving_out_the_objective_the_rover_depends_on_is_not_accepted():
    """D11: the rover waits at POI_3 after A1. An agent dropping A1 with a false reason is refused; the final plan
    keeps the dependency (A1 planned, ground task after it) through the deterministic side."""
    row, rr, _ = run_case("D11", [{"assignments": {}, "unassigned": [{"objective_id": "A1", "reason": "NO_ELIGIBLE_DRONE"}]}],
                          max_revisions=0)
    assert any("UNASSIGNED_REASON_CONTRADICTS_CONTEXT: A1" in f for f in findings(rr))
    assert row["status"] == "PROPOSED_PENDING_AUTHORIZATION" and row["case_pass"]
    assert rr["final_allocation_from"] != "MODEL"


def test_leaving_out_the_rover_dependency_with_a_closed_but_false_route_reason_still_keeps_the_dependency():
    """ROUTE_INFEASIBLE is not re-derived by the contract check; the gate's reference plan still covers A1, and the
    case's expectation is unchanged: the ground task is never left waiting on a point no drone visits."""
    row, rr, _ = run_case("D11", [{"assignments": {}, "unassigned": [{"objective_id": "A1", "reason": "ROUTE_INFEASIBLE"}]}],
                          max_revisions=0)
    assert row["status"] in ("PROPOSED_PENDING_AUTHORIZATION", "INFEASIBLE", "PARTIAL_PENDING_AUTHORIZATION")
    if row["status"] == "PROPOSED_PENDING_AUTHORIZATION":
        assert rr["final_allocation_from"] != "MODEL"


# ----------------------------------------------------------------------- D13: declared reasons reach the plan --
LEAVE_A2 = {"assignments": {"drone_03": ["A1"]}, "unassigned": [{"objective_id": "A2", "reason": "SEPARATION_CONFLICT"}]}


def test_d13_declared_unassignable_objective_with_a_structured_reason_reaches_the_final_plan():
    row, rr, _ = run_case("D13", [LEAVE_A2], max_revisions=0)
    first = rr["decision_record"]["llm_proposals"][0]
    assert first["accepted"] and first["unassigned_verification"]["A2"] == {
        "declared": "SEPARATION_CONFLICT", "verified": True, "detail": first["unassigned_verification"]["A2"]["detail"]}
    assert "drone_02" in first["unassigned_verification"]["A2"]["detail"]  # the only eligible drone was tried
    assert any(r.startswith("INCOMPATIBLE A2: COORDINATION_CONFLICT: left out by the drone agent (SEPARATION_CONFLICT)")
               for r in row["reasons"])
    assert rr["phases"]["success"] == "FIRST_ROUND" and rr["final_allocation_from"] == "MODEL"
    assert row["case_pass"] and row["criteria"]["reason_contains"]   # the evaluator agrees; expectation unchanged
    assert row["status"] == "PARTIAL_PENDING_AUTHORIZATION" and row["criteria"]["max_residual_conflicts"]


def test_a_verified_no_eligible_drone_reaches_the_plan():
    row, rr, _ = run_case("D05", [{"assignments": {}, "unassigned": [{"objective_id": "A1", "reason": "NO_ELIGIBLE_DRONE"}]}],
                          max_revisions=0)
    assert row["status"] == "INFEASIBLE" and row["case_pass"]


def test_a_declared_separation_conflict_with_a_viable_alternative_is_refused():
    """D10: A2 can be flown by drone_01 or drone_03; leaving it out 'for separation' is not confirmed."""
    claim = {"assignments": {"drone_01": ["A1"], "drone_03": ["A3"]},
             "unassigned": [{"objective_id": "A2", "reason": "SEPARATION_CONFLICT"}]}
    good = {"assignments": {"drone_01": ["A1", "A2"], "drone_03": ["A3"]}, "unassigned": []}
    row, rr, seen = run_case("D10", [claim, good])
    first = rr["phases"]["first"]
    assert first["accepted"] is False and any(f.startswith("UNASSIGNED_REASON_NOT_CONFIRMED: A2") for f in first["findings"])
    assert "can take it without conflict" in " ".join(first["findings"])
    assert rr["phases"]["success"] == "AFTER_REVISION" and row["status"] == "PROPOSED_PENDING_AUTHORIZATION"
    row, rr, _ = run_case("D10", [claim], max_revisions=0)  # no revision left: the unconfirmed claim is not the plan
    assert rr["final_allocation_from"] != "MODEL" and row["status"] == "PROPOSED_PENDING_AUTHORIZATION"


def test_a_real_unresolved_conflict_still_never_flies_both():
    both = {"assignments": {"drone_02": ["A2"], "drone_03": ["A1"]}, "unassigned": []}
    row, rr, _ = run_case("D13", [both, both])
    assert rr["agent_success"] is False and row["status"] == "PARTIAL_PENDING_AUTHORIZATION"
    assert row["criteria"]["max_residual_conflicts"] and row["case_pass"]
