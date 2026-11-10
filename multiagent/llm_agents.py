"""LLM mode of the three agents: per-role model configuration, a bounded tool loop and deterministic gates.

Every role (mission_orchestrator, drone_swarm_agent, rover_agent) is either ``deterministic`` (the existing
behaviour) or ``llm`` with its own candidate model (one shared model or one per role). In llm mode:
- the Mission Orchestrator interprets the request with ModelInterpreterV2 (brief /2); the brief is its
  decomposition (aerial vs ground objectives, which specialist gets what); it requests revisions from the
  Drone/Swarm Agent when the deterministic gate rejects a proposal;
- the Drone/Swarm Agent loops: it may call its tools (agent_tools.drone_tools) and ends with a proposal
  {"assignments": {drone: [objective ids]}}; the gate is the EXISTING evaluate_proposal (site, sensors,
  battery, wind) plus deconfliction; a rejected proposal goes back with the gate's findings (revision);
  an accepted one is handed to plan_aerial through its existing allocator interface, which validates it AGAIN,
  builds the .plan files and falls back to the deterministic reference otherwise;
- the Rover Agent loops with its tools and ends with {"tasks": [...], "insufficient_information": [...]};
  the gate compares it with the deterministic rover agent, which keeps the last word.
No role can authorize, command or publish anything: the tools are read-only and the proposal stays pending.

Loop step contract (one JSON object per model call):
  {"action": "tool", "tool": "<name>", "arguments": {...}, "reason": "..."}
  {"action": "final", "proposal": {...}, "explanation": "...", "evidence": ["<tool call index>", ...]}
Bounds per agent: max_iterations, max_llm_calls, max_tool_calls, max_revisions, a wall-clock budget.

Single-shot contract (``step_contract="single_shot"``, prompts agent_drone_single/1, agent_rover_single/1), for
budgets of ONE model call per agent and case: the runtime first runs the role's read-only context tools (recorded
as tool spans requested_by="runtime"), the model replies once
  {"proposal": {...}, "verify": [{"tool": "<name>", "arguments": {...}}], "explanation": "..."}
and the runtime then runs the verification calls the model asked for (requested_by="model"). The model does not
see those results in that step; the deterministic gate decides as in the loop. A reply that is not exactly this
object, is larger than max_reply_chars or exceeds max_total_tokens is INVALID: no repair, no silent acceptance.
"""
from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from multiagent import models
from multiagent.agent_prompts import render as render_prompt, render_single_v
from multiagent.agent_tools import ToolRunner, drone_tools, rover_tools
from multiagent.interpreters import extract_json

ROLES = ("mission_orchestrator", "drone_swarm_agent", "rover_agent")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AgentModelConfig(_Strict):
    # "oracle" (mission_orchestrator only): the case's hand-written gold brief is the delegation; a labelled
    # reference to isolate a specialist in a pilot, never a model
    mode: Literal["deterministic", "llm", "oracle"] = "deterministic"
    candidate: str | None = None  # scripted:<name> | ollama:<model> | aida-qwen | hermes
    prompt_id: str | None = None  # orchestrator: interpret_brief/2 (default); specialists: agent_*_single/1 or /2
    generation: dict = Field(default_factory=dict)
    max_iterations: int = Field(6, ge=1, le=20)
    max_llm_calls: int = Field(8, ge=1, le=40)
    max_tool_calls: int = Field(10, ge=0, le=40)
    max_revisions: int = Field(2, ge=0, le=5)
    budget_s: float = Field(300.0, gt=0)
    step_contract: Literal["loop", "single_shot"] = "loop"
    max_reply_chars: int = Field(20000, ge=100, le=200000)
    max_total_tokens: int | None = Field(None, ge=1)  # per model call
    max_agent_tokens: int | None = Field(None, ge=1)  # cumulative over the agent's calls (all rounds)
    # what a revision round shows the model: the gate's findings only, or also its own verification results (data)
    revision_feedback: Literal["findings", "findings_and_verifications"] = "findings"


class MultiAgentConfig(_Strict):
    schema_: Literal["tfg.multiagent.agents-config/1"] = Field("tfg.multiagent.agents-config/1", alias="schema")
    config_id: str
    data_kind: Literal["SIMULATED_MODELS", "REAL_MODELS", "DETERMINISTIC"]
    mission_orchestrator: AgentModelConfig = AgentModelConfig()
    drone_swarm_agent: AgentModelConfig = AgentModelConfig()
    rover_agent: AgentModelConfig = AgentModelConfig()

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    def role(self, name) -> AgentModelConfig:
        return getattr(self, name)


def load_config(path) -> MultiAgentConfig:
    return MultiAgentConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def make_adapter(config: AgentModelConfig, *, allow_model_calls=False, allow_remote=False, simulated=None):
    """Adapter for one role. Real adapters stay DISABLED unless explicitly allowed (then calls happen)."""
    candidate = config.candidate or ""
    if candidate.startswith("scripted:"):
        if simulated is None or candidate[9:] not in simulated:
            raise ValueError(f"no simulated responder {candidate!r}")
        return models.ScriptedAdapter(responder=simulated[candidate[9:]], model=candidate)
    options = {k: v for k, v in config.generation.items() if k in ("temperature", "seed", "num_predict", "think",
                                                                    "num_ctx", "timeout_s", "json_mode")}
    if candidate.startswith("ollama:"):
        options.pop("json_mode", None)
        return models.OllamaChatAdapter(model=candidate[7:], enabled=allow_model_calls, **options)
    options.pop("num_predict", None), options.pop("think", None), options.pop("num_ctx", None), options.pop("seed", None)
    if candidate == "aida-qwen":
        return models.aida_qwen(enabled=allow_model_calls and allow_remote, **options)
    if candidate == "hermes":
        return models.hermes_provider(enabled=allow_model_calls and allow_remote, **options)
    raise ValueError(f"unknown candidate {candidate!r}")


class AgentStep(_Strict):
    action: Literal["tool", "final"]
    tool: str | None = None
    arguments: dict = Field(default_factory=dict)
    reason: str | None = None
    proposal: dict | None = None
    explanation: str | None = None
    evidence: list = Field(default_factory=list)


class VerifyRequest(_Strict):
    tool: str = Field(min_length=1, max_length=60)
    arguments: dict = Field(default_factory=dict)


class SingleShotStep(_Strict):
    proposal: dict
    verify: list[VerifyRequest] = Field(default_factory=list, max_length=8)
    explanation: str | None = Field(None, max_length=2000)


def _llm_meta(adapter, response, prompt_text, raw):
    import hashlib
    return {**adapter.info, **response.metadata(), "generation": dict(getattr(adapter, "generation", {}) or {}),
            "prompt": {"sha256": hashlib.sha256(prompt_text.encode()).hexdigest(), "text": prompt_text},
            "raw_text": raw, "raw_sha256": hashlib.sha256(raw.encode()).hexdigest()}


class AgentLoop:
    """One agent's bounded loop. Every model call is an ``llm`` span of that agent; every tool call a ``tool``
    span (via ToolRunner). The span's data_kind tells a TEST DOUBLE from a real model."""

    def __init__(self, role, adapter, runner: ToolRunner, config: AgentModelConfig, *, tracer=None):
        self.role, self.adapter, self.runner, self.config, self.tracer = role, adapter, runner, config, tracer
        self.llm_calls, self.steps, self.errors = 0, [], []
        self.tokens, self.started, self._context = 0, None, None

    def run(self, task: dict, *, feedback: list | None = None) -> dict:
        started = time.perf_counter()
        transcript = []
        invalid = 0
        for iteration in range(1, self.config.max_iterations + 1):
            if self.llm_calls >= self.config.max_llm_calls:
                return self._end("FAILED", "LLM_CALL_BUDGET_EXHAUSTED")
            if time.perf_counter() - started > self.config.budget_s:
                return self._end("FAILED", "TIME_BUDGET_EXHAUSTED")
            prompt = render_prompt(self.role, task=task, tools=self.runner.catalog(), transcript=transcript,
                                   feedback=feedback or [])
            self.llm_calls += 1
            with (self.tracer.span(self.role, "llm", f"{self.role}:step{iteration}", model=self.adapter.info,
                                   inputs={"iteration": iteration}) if self.tracer else _null()) as span:
                try:
                    response = self.adapter.complete([{"role": "user", "content": prompt}], json_output=True)
                except (models.AdapterUnavailable, models.AdapterDisabled, models.AdapterSchemaError) as exc:
                    if self.tracer:
                        self.tracer.output(span, {"error": f"{type(exc).__name__}: {exc}"}, status="ERROR_INFRASTRUCTURE",
                                           model_call={**self.adapter.info, "error_kind": "INFRASTRUCTURE"})
                    return self._end("FAILED", f"INFRASTRUCTURE: {type(exc).__name__}: {exc}")
                raw = response.text or ""
                meta = _llm_meta(self.adapter, response, prompt, raw)
                value = extract_json(raw)
                try:
                    step = AgentStep.model_validate(value) if value is not None else None
                except ValidationError:
                    step = None
                if self.tracer:
                    self.tracer.output(span, value if step else {"invalid_reply": raw[:300]},
                                       status="OK" if step else "INVALID_STEP", model_call=meta)
            if step is None:
                invalid += 1
                self.errors.append(f"step {iteration}: invalid reply")
                transcript.append({"iteration": iteration, "error": "INVALID_STEP: reply is not a valid step object"})
                if invalid >= 2:
                    return self._end("FAILED", "INVALID_STEPS")
                continue
            invalid = 0
            self.steps.append(step.model_dump())
            if step.action == "final":
                if not isinstance(step.proposal, dict):
                    transcript.append({"iteration": iteration, "error": "FINAL_WITHOUT_PROPOSAL"})
                    continue
                return self._end("FINAL", None, proposal=step.proposal, explanation=step.explanation,
                                 evidence=step.evidence)
            entry = self.runner.call(step.tool or "", step.arguments)
            transcript.append({"iteration": iteration, "tool_call": entry["index"], "tool": entry["tool"],
                               "status": entry["status"], "data": entry["output"], "notice": entry["notice"]})
        return self._end("FAILED", "ITERATION_LIMIT")

    def run_single_shot(self, task: dict, *, context_tools: list[str], feedback: list | None = None) -> dict:
        """ONE model call: runtime context tools first (once per agent run, reused by revision rounds), then the
        reply, then the verification calls it asked for. Budgets: calls, cumulative tokens, wall clock."""
        self.started = self.started or time.perf_counter()
        if self.llm_calls >= self.config.max_llm_calls:
            return self._end("FAILED", "LLM_CALL_BUDGET_EXHAUSTED")
        if self.config.max_agent_tokens and self.tokens >= self.config.max_agent_tokens:
            return self._end("FAILED", "AGENT_TOKEN_BUDGET_EXHAUSTED")
        if time.perf_counter() - self.started > self.config.budget_s:
            return self._end("FAILED", "TIME_BUDGET_EXHAUSTED")
        if self._context is None:
            self._context = []
            for name in context_tools:
                entry = self.runner.call(name, {}, requested_by="runtime")
                self._context.append({"tool_call": entry["index"], "tool": name, "status": entry["status"],
                                      "data": entry["output"], "notice": entry["notice"]})
        context = self._context
        offered = [t for t in self.runner.catalog() if t["name"] not in context_tools]
        prompt = render_single_v(self.role, self.config.prompt_id, task=task, tools=offered, context=context,
                                 feedback=feedback or [])
        self.llm_calls += 1
        with (self.tracer.span(self.role, "llm", f"{self.role}:single_shot", model=self.adapter.info,
                               inputs={"contract": "single_shot", "context_tools": context_tools})
              if self.tracer else _null()) as span:
            try:
                response = self.adapter.complete([{"role": "user", "content": prompt}], json_output=True)
            except (models.AdapterUnavailable, models.AdapterDisabled, models.AdapterSchemaError) as exc:
                if self.tracer:
                    self.tracer.output(span, {"error": f"{type(exc).__name__}: {exc}"}, status="ERROR_INFRASTRUCTURE",
                                       model_call={**self.adapter.info, "error_kind": "INFRASTRUCTURE"})
                return self._end("FAILED", f"INFRASTRUCTURE: {type(exc).__name__}: {exc}")
            raw = response.text or ""
            meta = _llm_meta(self.adapter, response, prompt, raw)
            usage = response.usage or {}
            total = (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
            self.tokens += total
            problem, step, value = None, None, None
            if len(raw) > self.config.max_reply_chars:
                problem = f"REPLY_TOO_LARGE: {len(raw)} > {self.config.max_reply_chars} characters"
            elif self.config.max_total_tokens and total > self.config.max_total_tokens:
                problem = f"TOKEN_BUDGET_EXCEEDED: {total} > {self.config.max_total_tokens}"
            else:
                value = extract_json(raw)
                try:
                    step = SingleShotStep.model_validate(value) if value is not None else None
                except ValidationError as exc:
                    problem = "INVALID_STEP: " + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['type']}"
                                                           for e in exc.errors()[:4])
                if step is None and problem is None:
                    problem = "INVALID_STEP: the reply holds no JSON object"
            meta["parse_error"] = problem
            if self.tracer:
                self.tracer.output(span, value if step else {"invalid_reply": raw[:300], "problem": problem},
                                   status="OK" if step else "INVALID_STEP", model_call=meta)
        if step is None:
            self.errors.append(problem)
            return self._end("FAILED", problem.split(":")[0], parse_error=problem)
        self.steps.append(step.model_dump())
        verifications = []
        for request in step.verify:
            entry = self.runner.call(request.tool, request.arguments, requested_by="model")
            verifications.append({"tool_call": entry["index"], "tool": entry["tool"], "status": entry["status"],
                                  "data": entry["output"]})
        return self._end("FINAL", None, proposal=step.proposal, explanation=step.explanation,
                         evidence=[v["tool_call"] for v in verifications], verifications=verifications,
                         context=[{k: c[k] for k in ("tool_call", "tool", "status")} for c in context])

    def _end(self, status, reason, **kw):
        return {"role": self.role, "status": status, "reason": reason, "llm_calls": self.llm_calls,
                "tool_calls": len(self.runner.calls), "tool_log": [{k: c[k] for k in ("index", "tool", "status")}
                                                                   for c in self.runner.calls],
                "errors": self.errors, **kw}


class _null:
    def __enter__(self):
        return {}

    def __exit__(self, *exc):
        return False


# ------------------------------------------------------------------------------- drone agent --
def drone_allocator(config: AgentModelConfig, adapter, *, tracer=None):
    """allocator(problem) -> (proposal, meta) for plan_aerial. Gate + revision requests happen here."""
    def allocator(problem):
        from multiagent.deconfliction import deconflict
        from multiagent.swarm import allocate, evaluate_proposal, route_candidate
        from multiagent.agent_tools import _quiet
        tools = drone_tools(problem)
        if config.step_contract == "single_shot":  # the model decides alone: the reference answer is not offered
            tools = [t for t in tools if t.name != "reference_allocation"]
        runner = ToolRunner("drone_swarm_agent", tools, tracer=tracer, max_calls=config.max_tool_calls)
        loop = AgentLoop("drone_swarm_agent", adapter, runner, config, tracer=tracer)
        reference = _quiet(allocate, problem)
        task = {"objectives": [{"objective_id": o.objective_id, "point_id": o.point_id, "required_sensor": o.required_sensor}
                               for o in problem.objectives],
                "drones": [d.vehicle_id for d in problem.drones], "wind_speed_kmh": problem.wind_speed_kmh,
                "goal": "assign each objective to at most one capable drone; routes must pass validation and separation"}
        feedback, rounds = [], []
        v3 = (config.prompt_id or "").startswith("agent_drone_single/3")
        rejected = []  # assignments the gate already rejected (contract /3: resubmitting one is refused at once)
        for revision in range(config.max_revisions + 1):
            outcome = loop.run_single_shot(task, context_tools=["drone_capabilities"], feedback=feedback) \
                if config.step_contract == "single_shot" else loop.run(task, feedback=feedback)
            rounds.append({k: outcome.get(k) for k in ("status", "reason", "proposal", "explanation", "evidence",
                                                       "verifications", "parse_error")})
            if outcome["status"] != "FINAL":
                break
            proposal = outcome["proposal"]
            if not isinstance(proposal.get("assignments"), dict) or not all(
                    isinstance(v, list) for v in proposal["assignments"].values()):
                rounds[-1].update(accepted=False, findings=["PROPOSAL_SHAPE: assignments must map drone -> [objective ids]"])
                if tracer is not None:
                    tracer.validation("mission_orchestrator", f"gate:drone_proposal:round{revision}", "REJECTED",
                                      {"proposal": proposal, "violations": ["PROPOSAL_SHAPE"]})
                break
            if v3:
                pre = _v3_findings(problem, proposal, rejected)
                if pre:
                    # never evaluated by the gate: it must not become the plan (a resubmission of an assignment the
                    # gate already evaluated is handled by deconfliction like any rejected proposal)
                    rounds[-1].update(accepted=False, findings=pre, contract_rejected=any(
                        not f.startswith("REPEATED_REJECTED_ASSIGNMENT") for f in pre))
                    if tracer is not None:
                        tracer.validation("mission_orchestrator", f"gate:drone_proposal:round{revision}", "REJECTED",
                                          {"proposal": proposal, "violations": pre})
                    if revision < config.max_revisions:
                        feedback = [json.dumps({"revision": {"rejected_assignment": proposal.get("assignments"),
                                                             "violated_constraint": "CONTRACT",
                                                             "findings": pre}}, sort_keys=True)]
                        continue
                    break
            check = _quiet(evaluate_proposal, problem, proposal, reference)
            separation = None
            if check["valid"]:
                plans = {}
                for vehicle_id, objective_ids in (proposal.get("assignments") or {}).items():
                    points = []
                    for objective_id in objective_ids:
                        point = problem.objective(objective_id).point_id
                        points.append(point) if point not in points else None
                    if points:
                        c = _quiet(route_candidate, problem, problem.drone(vehicle_id), points)
                        plans[vehicle_id] = {k: c[k] for k in ("route_local", "labels", "leg_minutes")}
                separation = deconflict(plans, problem.context.separation_policy)
            accepted = check["valid"] and separation["status"] != "UNRESOLVED"
            findings = check["violations"] + ([f"SEPARATION {separation['status']}: {separation.get('reason')}"]
                                              + [f"conflict {c['vehicles']} {c['segments']}" for c in
                                                 separation["initial_conflicts"][:3]]
                                              if separation and separation["status"] == "UNRESOLVED" else [])
            if tracer is not None:
                tracer.validation("mission_orchestrator", f"gate:drone_proposal:round{revision}",
                                  "ACCEPTED" if accepted else "REJECTED",
                                  {"proposal": proposal, "violations": check["violations"],
                                   "separation": separation and separation["status"],
                                   "same_as_reference": check.get("same_assignment_as_reference")})
            rounds[-1].update(accepted=accepted, findings=findings, separation=separation and separation["status"])
            if accepted and v3 and proposal.get("unassigned"):
                # a declared impossibility is checked, not believed; the verified reason reaches the plan
                verification = verify_unassigned(problem, proposal)
                rounds[-1]["unassigned_verification"] = verification
                unconfirmed = [f"UNASSIGNED_REASON_NOT_CONFIRMED: {oid}: {v['declared']} ({v['detail']})"
                               for oid, v in sorted(verification.items()) if not v["verified"]]
                if unconfirmed:
                    accepted = False
                    rounds[-1].update(accepted=False, findings=unconfirmed, contract_rejected=True)
                    if tracer is not None:
                        tracer.validation("mission_orchestrator", f"gate:drone_unassigned:round{revision}", "REJECTED",
                                          unconfirmed)
                    rejected.append(_norm_assign(proposal.get("assignments")))
                    if revision < config.max_revisions:
                        feedback = [json.dumps({"revision": {"rejected_assignment": proposal.get("assignments"),
                                                             "violated_constraint": "CONTRACT",
                                                             "findings": unconfirmed}}, sort_keys=True)]
                        continue
                    break
            if accepted:
                return proposal, _summary(loop, rounds, adapter, accepted=True)
            if v3 and not accepted:
                rejected.append(_norm_assign(proposal.get("assignments")))
            if v3 and revision < config.max_revisions:
                feedback = [json.dumps({"revision": _structured_revision(problem, proposal, check, separation)},
                                       sort_keys=True)]
            elif revision < config.max_revisions:
                feedback = [f"REVISION_REQUESTED by mission_orchestrator: {f}" for f in findings]
                if any(f.startswith("SEPARATION") for f in findings):
                    feedback.append("REVISION_OPTIONS: change the assignment or the visiting order, or leave out one of the "
                                    "conflicting objectives and name it in the explanation; the conflict cannot be ignored")
                if config.revision_feedback == "findings_and_verifications":
                    feedback += [f"YOUR VERIFICATION {v['tool']} -> {v['status']}: "
                                 + json.dumps(_compact(v["data"]), sort_keys=True)[:400]
                                 for v in outcome.get("verifications") or []]
                if tracer is not None:
                    tracer.validation("mission_orchestrator", f"revision_request:drone_swarm_agent:{revision + 1}",
                                      "REQUESTED", feedback)
        last = rounds[-1].get("proposal") if rounds else None
        meta = _summary(loop, rounds, adapter, accepted=False)
        meta["contract_rejected"] = bool(rounds and rounds[-1].get("contract_rejected"))
        return (last if isinstance(last, dict) else {"assignments": None}), meta
    return allocator


def verify_unassigned(problem, proposal) -> dict:
    """{objective_id: {declared, verified, detail}} for the agent's unassigned objectives, re-derived with the same
    deterministic tools: NO_ELIGIBLE_DRONE (no eligible drone), ROUTE_INFEASIBLE (no eligible drone can add it to
    its route), SEPARATION_CONFLICT (every eligible, route-feasible option conflicts with the accepted plan)."""
    from multiagent.deconfliction import deconflict
    from multiagent.swarm import eligibility, route_candidate
    from multiagent.agent_tools import _quiet
    assignments = {d: list(o) for d, o in (proposal.get("assignments") or {}).items() if o}

    def points(objective_ids):
        out = []
        for oid in objective_ids:
            pt = problem.objective(oid).point_id
            out.append(pt) if pt not in out else None
        return out

    def plan_of(vehicle_id, objective_ids):
        c = _quiet(route_candidate, problem, problem.drone(vehicle_id), points(objective_ids))
        return c if c.get("status") == "FEASIBLE" else None
    base = {d: plan_of(d, objs) for d, objs in assignments.items()}
    out = {}
    for u in proposal.get("unassigned") or []:
        o = problem.objective(u.get("objective_id"))
        if o is None:
            continue
        capable = [d.vehicle_id for d in problem.drones if not eligibility(problem, o, d)]
        reason, options = u.get("reason"), []
        for d in capable:
            route = plan_of(d, assignments.get(d, []) + [o.objective_id])
            if route is None:
                options.append((d, "ROUTE_INFEASIBLE"))
                continue
            plans = {v: {k: c[k] for k in ("route_local", "labels", "leg_minutes")} for v, c in base.items() if c and v != d}
            plans[d] = {k: route[k] for k in ("route_local", "labels", "leg_minutes")}
            sep = deconflict(plans, problem.context.separation_policy)
            options.append((d, "SEPARATION_CONFLICT" if sep["status"] == "UNRESOLVED" else "VIABLE"))
        viable = [d for d, r in options if r == "VIABLE"]
        if reason == "NO_ELIGIBLE_DRONE":
            verified, detail = not capable, f"eligible: {capable}"
        elif reason == "ROUTE_INFEASIBLE":
            verified, detail = bool(capable) and all(r == "ROUTE_INFEASIBLE" for _, r in options), f"options: {options}"
        else:  # SEPARATION_CONFLICT
            verified = bool(capable) and not viable and any(r == "SEPARATION_CONFLICT" for _, r in options)
            detail = f"options: {options}"
        if not verified and viable:
            detail = f"an eligible drone can take it without conflict: {viable}"
        out[o.objective_id] = {"declared": reason, "verified": verified, "detail": detail}
    return out


def _norm_assign(assignments) -> dict:
    return {d: list(o) for d, o in sorted((assignments or {}).items()) if o}


def _v3_findings(problem, proposal, rejected) -> list[str]:
    """Contract /3 checks before the usual gate: every objective exactly once, closed unassigned reasons, and no
    resubmission of an assignment the gate already rejected (it would be rejected again)."""
    out = []
    assigned = [o for objs in (proposal.get("assignments") or {}).values() for o in objs]
    unassigned = proposal.get("unassigned") or []
    if not isinstance(unassigned, list) or not all(isinstance(u, dict) for u in unassigned):
        return ["CONTRACT: unassigned must be a list of {objective_id, reason}"]
    reasons = {"NO_ELIGIBLE_DRONE", "SEPARATION_CONFLICT", "ROUTE_INFEASIBLE"}
    from multiagent.swarm import eligibility
    any_assigned = any(objs for objs in (proposal.get("assignments") or {}).values())
    for u in unassigned:
        if u.get("reason") not in reasons:
            out.append(f"INVALID_UNASSIGNED_REASON: {u.get('objective_id')}: {u.get('reason')!r}")
            continue
        # the declared reason must agree with the context (an impossibility is checked, not believed)
        o = problem.objective(u.get("objective_id")) if u.get("objective_id") else None
        if o is not None and u["reason"] == "NO_ELIGIBLE_DRONE":
            capable = [d.vehicle_id for d in problem.drones if not eligibility(problem, o, d)]
            if capable:
                out.append(f"UNASSIGNED_REASON_CONTRADICTS_CONTEXT: {o.objective_id}: NO_ELIGIBLE_DRONE but eligible {capable}")
        if o is not None and u["reason"] == "SEPARATION_CONFLICT" and not any_assigned:
            out.append(f"UNASSIGNED_REASON_CONTRADICTS_CONTEXT: {o.objective_id}: SEPARATION_CONFLICT with no assigned drone")
    listed = assigned + [u.get("objective_id") for u in unassigned]
    for o in problem.objectives:
        if listed.count(o.objective_id) != 1:
            out.append(f"INCONSISTENT_UNASSIGNED: {o.objective_id} appears {listed.count(o.objective_id)} times "
                       "(each objective exactly once: assigned or unassigned)")
    if _norm_assign(proposal.get("assignments")) in rejected:
        out.append("REPEATED_REJECTED_ASSIGNMENT: identical to an assignment the gate already rejected")
    return out


def _structured_revision(problem, proposal, check, separation) -> dict:
    """The rejection as data: the violated constraint, conflicts mapped to objectives, and the allowed actions."""
    assignments = proposal.get("assignments") or {}
    point_to_obj = {}
    for drone, objs in assignments.items():
        for oid in objs:
            o = problem.objective(oid)
            if o is not None:
                point_to_obj[(drone, o.point_id)] = oid
    conflicts = []
    for c in (separation or {}).get("initial_conflicts", [])[:4]:
        objs = sorted({point_to_obj.get((v, pt)) for v, seg in zip(c.get("vehicles", []), c.get("segments", []))
                       for pt in seg.replace(" (return)", "").split(" -> ") if point_to_obj.get((v, pt))})
        conflicts.append({"drones": c.get("vehicles"), "segments": c.get("segments"), "objectives": objs,
                          "min_distance_m": c.get("min_distance_m"), "required_m": c.get("required_m")})
    in_conflict = sorted({o for c in conflicts for o in c["objectives"]})
    violated = "SEPARATION" if separation and separation.get("status") == "UNRESOLVED" else "ELIGIBILITY_OR_ROUTE"
    actions = (["REASSIGN_ONE_OBJECTIVE_TO_ANOTHER_ELIGIBLE_DRONE", "CHANGE_VISITING_ORDER"]
               + [f"LEAVE_OUT_ONE_OF {in_conflict} AS SEPARATION_CONFLICT"] if violated == "SEPARATION" else
               ["ASSIGN_ONLY_ELIGIBLE_DRONES", "LEAVE_OUT_WITH_REASON NO_ELIGIBLE_DRONE"])
    return {"rejected_assignment": assignments, "violated_constraint": violated,
            "violations": (check or {}).get("violations", [])[:5], "conflicts": conflicts,
            "objectives_in_conflict": in_conflict, "allowed_actions": actions,
            "forbidden": "resubmitting the rejected assignment: it is rejected without checks"}


def _compact(data):
    """What a revision round needs from a tool result: status, reasons, conflicts (no full routes)."""
    if not isinstance(data, dict):
        return data
    keep = ("status", "reasons", "problems", "initial_conflicts", "conflict_examples", "reason", "error")
    out = {k: data[k] for k in keep if k in data}
    if isinstance(out.get("conflict_examples"), list):
        out["conflict_examples"] = [{k: c.get(k) for k in ("vehicles", "segments", "min_distance_m", "required_m")}
                                    for c in out["conflict_examples"][:2]]
    return out


def decision_record(rounds) -> dict:
    """LLM proposals per round kept apart from what the deterministic side did with them."""
    accepted = next((i for i, r in enumerate(rounds) if r.get("accepted")), None)
    return {"llm_proposals": [{"round": i, "status": r.get("status"), "proposal": r.get("proposal"),
                               "accepted": bool(r.get("accepted")), "findings": r.get("findings") or [],
                               "reason": r.get("reason"),
                               **({"unassigned_verification": r["unassigned_verification"]}
                                  if r.get("unassigned_verification") else {})} for i, r in enumerate(rounds)],
            "accepted_round": accepted, "accepted_first_round": accepted == 0,
            "accepted_after_revision": accepted is not None and accepted > 0}


def _summary(loop, rounds, adapter, *, accepted):
    return {**adapter.info, "agent": loop.role, "accepted_by_gate": accepted, "rounds": rounds,
            "decision_record": decision_record(rounds), "agent_tokens": loop.tokens,
            "llm_calls": loop.llm_calls, "tool_calls": len(loop.runner.calls),
            "tool_log": [{k: c[k] for k in ("index", "tool", "status")} for c in loop.runner.calls]}


# ------------------------------------------------------------------------------- rover agent --
def rover_reviewer(config: AgentModelConfig, adapter, *, tracer=None):
    """reviewer(objectives, site, context, fleet, rover_id, aerial_points) -> review dict (never authoritative)."""
    def review(objectives, *, site, context, fleet, rover_id, aerial_points, awaiting=()):
        from multiagent import rover_gate
        pid = config.prompt_id or ""
        v3 = pid.startswith("agent_rover_single/3")
        v2 = pid.startswith("agent_rover_single/2") or v3
        awaiting = [a if isinstance(a, dict) else a.model_dump() for a in awaiting]
        dumped = [o.model_dump() if hasattr(o, "model_dump") else dict(o) for o in objectives]
        runner = ToolRunner("rover_agent", rover_tools(site=site, context=context, fleet=fleet, rover_id=rover_id,
                                                       aerial_points=aerial_points,
                                                       contract="v3" if v3 else ("v2" if v2 else "v1"),
                                                       awaiting=awaiting, objectives=dumped),
                            tracer=tracer, max_calls=config.max_tool_calls)
        loop = AgentLoop("rover_agent", adapter, runner, config, tracer=tracer)
        task = {"ground_objectives": dumped, "rover": rover_id, "aerial_points_proposed": aerial_points,
                "goal": "propose each ground task (declared target, wait point) or list what is missing"}
        if v2:
            task["awaiting_observation"] = awaiting
        rovers = context.rovers if context is not None else []
        profile = next((r for r in rovers if r.vehicle_id == rover_id), None) if rover_id else (rovers[0] if rovers else None)
        pois = {p.point_id for p in site.points if p.kind == "poi"} if site is not None else set()
        feedback, rounds, outcome = [], [], {}
        for revision in range(config.max_revisions + 1):
            outcome = loop.run_single_shot(task, context_tools=["rover_capabilities"], feedback=feedback) \
                if config.step_contract == "single_shot" else loop.run(task, feedback=feedback)
            rounds.append({k: outcome.get(k) for k in ("status", "reason", "proposal", "explanation", "verifications",
                                                       "parse_error")})
            if outcome["status"] != "FINAL":
                break
            check = rover_gate.check_v3 if v3 else rover_gate.check
            gate = check(outcome["proposal"], objectives=dumped, awaiting=awaiting,
                         rover_available=bool(profile and profile.available), declared_pois=pois,
                         aerial_points=set(aerial_points))
            rounds[-1].update(accepted=gate["accepted"],
                              findings=[f"{f['kind']}" + (f" at {f['field']}" if f.get("field") else "") + f": {f['detail']}"
                                        for f in gate["findings"]], normalized=gate.get("normalized"))
            if tracer is not None:
                tracer.validation("mission_orchestrator", f"gate:rover_llm_proposal:round{revision}",
                                  "ACCEPTED" if gate["accepted"] else "REJECTED", gate)
            if gate["accepted"] or revision >= config.max_revisions:
                break
            feedback = [f"REVISION_REQUESTED by mission_orchestrator: {f}" for f in rounds[-1]["findings"]]
            if config.revision_feedback == "findings_and_verifications":
                feedback += [f"YOUR VERIFICATION {v['tool']} -> {v['status']}: "
                             + json.dumps(_compact(v["data"]), sort_keys=True)[:400]
                             for v in outcome.get("verifications") or []]
        return {"agent": "rover_agent", **{k: outcome.get(k) for k in ("status", "reason", "proposal", "explanation",
                                                                     "evidence", "verifications", "parse_error")},
                "contract": "v3" if v3 else ("v2" if v2 else "v1"),
                "normalized_proposal": (rounds[-1].get("normalized") if rounds else None) if v3 else None,
                "accepted_by_gate": bool(rounds and rounds[-1].get("accepted")), "rounds": rounds,
                "decision_record": decision_record(rounds), "agent_tokens": loop.tokens,
                "llm_calls": loop.llm_calls, "tool_calls": len(runner.calls),
                "tool_log": [{k: c[k] for k in ("index", "tool", "status")} for c in runner.calls], **adapter.info}
    return review


# ---------------------------------------------------------------------------------- assembly --
def build_orchestrator(context, config: MultiAgentConfig, *, tracer=None, pipeline="v2", simulated=None,
                       allow_model_calls=False, allow_remote=False, oracle_brief=None, adapter_wrapper=None,
                       safety_policy="safety/2"):
    """MissionOrchestrator wired per role. Deterministic roles keep the existing behaviour.
    ``oracle_brief``: the gold brief used when the orchestrator role is in "oracle" mode. ``adapter_wrapper(role,
    adapter)``: e.g. a pilot-wide call budget around every model adapter."""
    from models.site import Site
    from multiagent.interpreters import RulesInterpreter
    from multiagent.model_interpretation import ModelInterpreterV2
    from multiagent.orchestrator import MissionOrchestrator
    from multiagent.prompts import PROMPT_V2_ID
    from multiagent import supervisor_prompts  # noqa: F401  registers interpret_brief/3 (prompts.py unchanged)
    site = Site.model_validate_json(Path(context.resolve(context.site_path)).read_text(encoding="utf-8"))
    points = [f"{p.point_id} ({p.kind}, x={p.x_m}, y={p.y_m})" for p in site.points]
    kw = dict(allow_model_calls=allow_model_calls, allow_remote=allow_remote, simulated=simulated)
    roles = {r: config.role(r) for r in ROLES}
    for role in ("drone_swarm_agent", "rover_agent"):
        if roles[role].mode == "oracle":
            raise ValueError(f"{role}: oracle mode exists only for the mission_orchestrator delegation")

    def adapter(role):
        a = make_adapter(roles[role], **kw)
        return adapter_wrapper(role, a) if adapter_wrapper else a
    mode = roles["mission_orchestrator"].mode
    if mode == "oracle":
        if oracle_brief is None:
            raise ValueError("oracle mode needs the case's gold brief")
        from multiagent.benchmark.run import GoldInterpreter
        interpreter = GoldInterpreter(oracle_brief)
    elif mode == "deterministic":
        interpreter = RulesInterpreter()
    elif roles["mission_orchestrator"].prompt_id == "interpret_brief/4":  # provenance contract (brief_provenance)
        from multiagent.brief_provenance import ProvenanceInterpreter
        interpreter = ProvenanceInterpreter(adapter("mission_orchestrator"), site_points=points, context=context)
    else:
        interpreter = ModelInterpreterV2(adapter("mission_orchestrator"), site_points=points,
                                         prompt_id=roles["mission_orchestrator"].prompt_id or PROMPT_V2_ID)
    allocator = None if roles["drone_swarm_agent"].mode == "deterministic" else \
        drone_allocator(roles["drone_swarm_agent"], adapter("drone_swarm_agent"), tracer=tracer)
    reviewer = None if roles["rover_agent"].mode == "deterministic" else \
        rover_reviewer(roles["rover_agent"], adapter("rover_agent"), tracer=tracer)
    return MissionOrchestrator(context, interpreter, allocator=allocator, tracer=tracer, pipeline=pipeline,
                               rover_reviewer=reviewer, safety_policy=safety_policy)


def agent_metrics(records: list[dict]) -> dict:
    """Per-agent counts and durations from a trace: llm calls (real vs test double), tool calls, revisions,
    gates, conflicts and the agent span duration. Only recorded spans are counted."""
    out = {}
    for role in ROLES:
        mine = [r for r in records if r["agent"] == role]
        llm = [r for r in mine if r["kind"] == "llm"]
        out[role] = {"llm_calls_real": sum((r.get("model_call") or {}).get("data_kind") == "MODEL_OUTPUT" for r in llm),
                     "llm_calls_test_double": sum((r.get("model_call") or {}).get("data_kind") == "SYNTHETIC" for r in llm),
                     "tool_calls": sum(r["kind"] == "tool" for r in mine),
                     "tool_failures": sum(r["kind"] == "tool" and r["status"] != "OK" for r in mine),
                     "agent_span_s": sum(r.get("duration_s", 0.0) for r in mine if r["kind"] == "agent"),
                     "tokens": sum(((r.get("model_call") or {}).get("usage") or {}).get("completion_tokens") or 0 for r in llm)
                     + sum(((r.get("model_call") or {}).get("usage") or {}).get("prompt_tokens") or 0 for r in llm)}
    out["mission_orchestrator"].update(
        revision_requests=sum(r["name"].startswith("revision_request:") for r in records),
        gates_rejected=sum(r["name"].startswith("gate:") and r["status"] == "REJECTED" for r in records),
        gates_accepted=sum(r["name"].startswith("gate:") and r["status"] == "ACCEPTED" for r in records))
    out["drone_swarm_agent"]["unresolved_deconfliction"] = sum(
        r["name"].startswith("deconfliction:") and r["status"] == "UNRESOLVED" for r in records)
    return out
