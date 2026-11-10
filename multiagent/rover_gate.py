"""Deterministic check of a Rover Agent proposal (before the comparison with the deterministic rover agent).

Each finding has a kind that keeps apart what pilot v1 mixed up:
- PLANNING errors of the proposal: TARGET_NOT_DECLARED_POI, TARGET_DIFFERS_FROM_OBJECTIVE, WAIT_POINT_MISSING,
  WAIT_POINT_WRONG, TASK_FOR_UNKNOWN_OBJECTIVE, OBJECTIVE_NOT_COVERED, CONTRADICTION (a task proposed for an
  objective it also reports as impossible);
- RESOURCE: ROVER_UNAVAILABLE_TASK_PROPOSED (the declared rover is unavailable: no task may be proposed);
- DEPENDENCY: DEPENDENCY_UNSATISFIED_TASK_PROPOSED (no proposed drone task reaches the wait point);
- PENDING DATA: AWAITING_OBSERVATION_TARGET_INVENTED (an objective whose point comes from a future observation got
  a target) and AWAITING_OBSERVATION_NOT_CONDITIONAL (it was neither a conditional task nor reported);
- EXECUTION vs PLANNING: EXECUTION_PRECONDITION_REPORTED_AS_MISSING (live localization / authorization are the
  executor's checks; they are not missing information for a plan to a declared POI). Informational: it does not
  reject a proposal on its own, it is fed back so a revision can drop it.
The deterministic rover agent keeps the last word whatever this gate says.
"""
from __future__ import annotations

import re

EXECUTION_WORDS = re.compile(r"locali[sz]ation|pose source|position source|verified pose|accredited|authori[sz]",
                             re.IGNORECASE)
REJECTING = {"TARGET_NOT_DECLARED_POI", "TARGET_DIFFERS_FROM_OBJECTIVE", "WAIT_POINT_MISSING", "WAIT_POINT_WRONG",
             "TASK_FOR_UNKNOWN_OBJECTIVE", "OBJECTIVE_NOT_COVERED", "CONTRADICTION",
             "ROVER_UNAVAILABLE_TASK_PROPOSED", "DEPENDENCY_UNSATISFIED_TASK_PROPOSED",
             "AWAITING_OBSERVATION_TARGET_INVENTED", "AWAITING_OBSERVATION_NOT_CONDITIONAL", "PROPOSAL_SHAPE"}


def check(proposal, *, objectives: list[dict], awaiting: list[dict], rover_available: bool, declared_pois: set,
          aerial_points: set) -> dict:
    """``objectives``: ground objectives with a point; ``awaiting``: ground objectives whose point a validated
    observation must provide (planned only as conditional tasks)."""
    findings = []

    def add(kind, detail):
        findings.append({"kind": kind, "detail": detail, "rejecting": kind in REJECTING})

    if not isinstance(proposal, dict) or not isinstance(proposal.get("tasks", []), list):
        add("PROPOSAL_SHAPE", "proposal must hold a list of tasks")
        return {"accepted": False, "findings": findings}
    tasks = [t for t in proposal.get("tasks") or [] if isinstance(t, dict)]
    conditional = [t for t in proposal.get("conditional_tasks") or [] if isinstance(t, dict)]
    missing = [str(m) for m in proposal.get("insufficient_information") or []]
    by_id = {o["objective_id"]: o for o in objectives}
    waiting = {o["objective_id"]: o for o in awaiting}
    for m in missing:
        if EXECUTION_WORDS.search(m):
            add("EXECUTION_PRECONDITION_REPORTED_AS_MISSING", m[:200])
    for t in tasks:
        oid = t.get("objective_id")
        if oid in waiting:
            add("AWAITING_OBSERVATION_TARGET_INVENTED", f"{oid}: its target comes from a future observation")
            continue
        o = by_id.get(oid)
        if o is None:
            add("TASK_FOR_UNKNOWN_OBJECTIVE", str(oid))
            continue
        if not rover_available:
            add("ROVER_UNAVAILABLE_TASK_PROPOSED", f"{oid}: the declared rover is unavailable")
        target, wait = t.get("target_point"), t.get("after_aerial_point")
        if target not in declared_pois:
            add("TARGET_NOT_DECLARED_POI", f"{oid}: {target}")
        elif target != o.get("point_id"):
            add("TARGET_DIFFERS_FROM_OBJECTIVE", f"{oid}: {target} vs {o.get('point_id')}")
        if o.get("after_aerial"):
            if wait is None:
                add("WAIT_POINT_MISSING", f"{oid}: after_aerial is true, the wait point is {o.get('point_id')}")
            elif wait != o.get("point_id"):
                add("WAIT_POINT_WRONG", f"{oid}: {wait} vs {o.get('point_id')}")
            elif wait not in aerial_points:
                add("DEPENDENCY_UNSATISFIED_TASK_PROPOSED", f"{oid}: no proposed drone task reaches {wait}")
        if any(oid in m for m in missing):
            add("CONTRADICTION", f"{oid}: proposed as a task and reported as missing information")
    covered = {t.get("objective_id") for t in tasks} | {t.get("objective_id") for t in conditional}
    for oid in by_id:
        if oid not in covered and not any(oid in m for m in missing) and not (missing and len(by_id) == 1):
            add("OBJECTIVE_NOT_COVERED", oid)
    for oid in waiting:
        if oid not in {t.get("objective_id") for t in conditional} and not any(oid in m for m in missing):
            add("AWAITING_OBSERVATION_NOT_CONDITIONAL", oid)
    return {"accepted": not any(f["rejecting"] for f in findings), "findings": findings,
            "tasks": len(tasks), "conditional_tasks": len(conditional), "insufficient_information": len(missing)}


# ------------------------------------------------------------------------- contract v3 (rover /3) --
# One typed decision per ground objective. The wait point is NOT asked from the model (v1/v2 asked it to restate a
# value derivable from the objective, and the example said "or null"); execution matters (localization,
# authorization) cannot be chosen as a reason.
DECISIONS = ("PLAN_TO_DECLARED_POI", "WAIT_FOR_OBSERVATION", "CANNOT_PLAN")
REASONS = ("ROVER_UNAVAILABLE", "NO_DRONE_TASK_REACHES_WAIT_POINT", "TARGET_NOT_DECLARED")


AUTHORITY_KEYS = ("authorized", "authorization", "human_authorized", "approved", "approval", "execute",
                  "execution_authorized", "movement_authorized", "command", "commands")


def check_v3(proposal, *, objectives: list[dict], awaiting: list[dict], rover_available: bool, declared_pois: set,
             aerial_points: set) -> dict:
    """Accepted only if there is exactly one valid decision per objective and every decision agrees with the facts.
    Each finding names the field (decisions[i].field) so a revision can be told exactly what to change.
    ``normalized``: the same proposal in the shape the orchestrator compares (tasks / conditional / infeasible),
    with the wait point DERIVED by the runtime from the objective (recorded as such)."""
    findings = []

    def add(kind, field, detail):
        findings.append({"kind": kind, "field": field, "detail": detail, "rejecting": True})

    decisions = proposal.get("decisions") if isinstance(proposal, dict) else None
    if not isinstance(decisions, list):
        add("PROPOSAL_SHAPE", "proposal.decisions", "must be a list with one decision per ground objective")
        return {"accepted": False, "findings": findings, "normalized": None}
    # an agent never carries authority: a claim of authorization, approval, execution or commands rejects the proposal
    claims = sorted(k for k in AUTHORITY_KEYS if k in proposal) + sorted(
        f"decisions[{i}].{k}" for i, d in enumerate(decisions) if isinstance(d, dict) for k in AUTHORITY_KEYS if k in d)
    for c in claims:
        add("AGENT_CLAIMS_AUTHORITY", c, "the rover agent proposes; only a human authorizes and only the executor acts")
    known = {o["objective_id"]: o for o in objectives}
    pending = {o["objective_id"]: o for o in awaiting}
    seen, tasks, conditional, infeasible = set(), [], [], []
    for i, d in enumerate(decisions):
        f = f"decisions[{i}]"
        if not isinstance(d, dict):
            add("PROPOSAL_SHAPE", f, "each decision must be an object")
            continue
        oid, decision, reason, target = d.get("objective_id"), d.get("decision"), d.get("reason"), d.get("target_point")
        if oid in seen:
            add("DUPLICATE_DECISION", f"{f}.objective_id", f"{oid} decided twice")
            continue
        seen.add(oid)
        if oid not in known and oid not in pending:
            add("TASK_FOR_UNKNOWN_OBJECTIVE", f"{f}.objective_id", str(oid))
            continue
        if decision not in DECISIONS:
            add("INVALID_DECISION", f"{f}.decision", f"{decision!r} is not one of {list(DECISIONS)}")
            continue
        if oid in pending:
            if decision == "WAIT_FOR_OBSERVATION" and target is None:
                conditional.append({"objective_id": oid, "waits_for": "VALIDATED_OBSERVATION"})
            elif decision == "CANNOT_PLAN" and reason == "ROVER_UNAVAILABLE" and not rover_available:
                infeasible.append({"objective_id": oid, "reason": reason})
            elif target is not None:
                add("AWAITING_OBSERVATION_TARGET_INVENTED", f"{f}.target_point",
                    f"{oid}: its target comes from a future observation; target_point must be null")
            else:
                add("AWAITING_OBSERVATION_NOT_CONDITIONAL", f"{f}.decision", f"{oid} must be WAIT_FOR_OBSERVATION")
            continue
        o = known[oid]
        wait = o.get("point_id") if o.get("after_aerial") else None
        if decision == "WAIT_FOR_OBSERVATION":
            add("WAIT_WITHOUT_PENDING_OBSERVATION", f"{f}.decision", f"{oid} has a declared target {o.get('point_id')}")
        elif decision == "PLAN_TO_DECLARED_POI":
            ok = True
            if not rover_available:
                add("ROVER_UNAVAILABLE_TASK_PROPOSED", f"{f}.decision", "the declared rover is unavailable"); ok = False
            if target not in declared_pois:
                add("TARGET_NOT_DECLARED_POI", f"{f}.target_point", f"{target!r}"); ok = False
            elif target != o.get("point_id"):
                add("TARGET_DIFFERS_FROM_OBJECTIVE", f"{f}.target_point", f"{target} vs {o.get('point_id')}"); ok = False
            if wait and wait not in aerial_points:
                add("DEPENDENCY_UNSATISFIED_TASK_PROPOSED", f"{f}.decision", f"no proposed drone task reaches {wait}")
                ok = False
            if ok:
                tasks.append({"objective_id": oid, "target_point": target, "after_aerial_point": wait,
                              "after_aerial_point_source": "DERIVED_BY_RUNTIME_FROM_OBJECTIVE"})
        else:  # CANNOT_PLAN
            facts = {"ROVER_UNAVAILABLE": not rover_available,
                     "NO_DRONE_TASK_REACHES_WAIT_POINT": bool(wait) and wait not in aerial_points,
                     "TARGET_NOT_DECLARED": o.get("point_id") not in declared_pois}
            if reason not in REASONS:
                add("INVALID_REASON", f"{f}.reason", f"{reason!r} is not one of {list(REASONS)}")
            elif not facts[reason]:
                add("REASON_CONTRADICTS_FACTS", f"{f}.reason", f"{reason} is false for {oid}")
            else:
                infeasible.append({"objective_id": oid, "reason": reason})
    for oid in list(known) + list(pending):
        if oid not in seen:
            add("OBJECTIVE_NOT_COVERED", "proposal.decisions", f"no decision for {oid}")
    accepted = not findings
    return {"accepted": accepted, "findings": findings,
            "normalized": {"tasks": tasks, "conditional_tasks": conditional, "infeasible": infeasible,
                           "insufficient_information": []} if accepted else None}
