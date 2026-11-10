"""Agents pilot M1/M2/M3 and the single-shot contract, OFFLINE: a fake Ollama transport stands in for the model (the
real adapter code runs; only its HTTP is faked). Budget enforcement, invalid replies, unknown and operational tools,
size and token limits, provider errors, delegation, fallback labelling, traces and no physical execution."""
import json

import pytest

from multiagent import models
from multiagent.agent_tools import ToolRunner, rover_tools
from multiagent.benchmark import agents_pilot as ap, run as bench
from multiagent.llm_agents import AgentLoop, AgentModelConfig, MultiAgentConfig, build_orchestrator
from multiagent.tracing import Tracer, opik_plan
from tests.test_multiagent_qwen_pilot import Ollama

MANIFEST = ap.load_manifest()
CASES = {c["case_id"]: c for c in bench.dataset("dev_v3")["suite"]["cases"]}
OK = {"version": lambda: {"version": "0.34.2"},
      "model": lambda: {"name": "qwen3:4b", "digest": MANIFEST["model"]["digest"]},
      "host": lambda: [], "container": lambda: {"status": "RUNNING", "processes_read": True, "matches": []}, "reservations": lambda: [],
      "gpu": lambda: {"status": "MEASURED", "memory_used_mib": 1.0, "memory_total_mib": 8192.0, "utilization_pct": 0},
      "gpu_apps": lambda: [], "locks": lambda: [], "git": lambda: "", "commit": lambda: "TEST",
      "sampled": lambda: [], "activity": lambda: []}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no real network or process")
    monkeypatch.setattr("socket.socket.connect", refuse)
    monkeypatch.setattr("urllib.request.urlopen", refuse)
    monkeypatch.setattr("subprocess.run", refuse)


def section(prompt, name):
    for line in prompt.splitlines():
        if line.startswith(f"{name} (data): "):
            return json.loads(line.split(": ", 1)[1])


def good_reply(prompt):
    """A well-formed reply for whichever role asks (a double: it reads the data it was given, nothing else)."""
    if "PROMPT_ID: agent_drone_single/" in prompt:
        caps = section(prompt, "CONTEXT")[0]["data"]
        assign = {}
        for o in caps["objectives"]:
            if o["eligible_drones"]:
                assign.setdefault(o["eligible_drones"][-1], []).append(o["objective_id"])
        verify = [{"tool": "check_separation", "arguments": {"assignments": assign}}] if assign else []
        return json.dumps({"proposal": {"assignments": assign}, "verify": verify, "explanation": "eligible drones"})
    if "PROMPT_ID: agent_rover_single/3" in prompt:
        caps = section(prompt, "CONTEXT")[0]["data"]
        out = []
        for o in caps["objectives"]:
            if o.get("target_from_future_observation"):
                out.append({"objective_id": o["objective_id"], "decision": "WAIT_FOR_OBSERVATION", "target_point": None, "reason": None})
            elif not caps["declared_available"]:
                out.append({"objective_id": o["objective_id"], "decision": "CANNOT_PLAN", "target_point": None, "reason": "ROVER_UNAVAILABLE"})
            elif o["waits_for_drone"] and not o["wait_point_reached_by_proposed_drone_task"]:
                out.append({"objective_id": o["objective_id"], "decision": "CANNOT_PLAN", "target_point": None,
                            "reason": "NO_DRONE_TASK_REACHES_WAIT_POINT"})
            else:
                out.append({"objective_id": o["objective_id"], "decision": "PLAN_TO_DECLARED_POI", "target_point": o["point_id"], "reason": None})
        return json.dumps({"proposal": {"decisions": out}, "verify": [], "explanation": "facts"})
    if "PROMPT_ID: agent_rover_single/" in prompt:
        caps, task = section(prompt, "CONTEXT")[0]["data"], section(prompt, "TASK")
        tasks, missing = [], []
        for o in task["ground_objectives"]:
            wait = o["point_id"] if o.get("after_aerial") else None
            if not caps.get("available"):
                missing.append(f"{caps['rover']} unavailable")
            elif wait and wait not in caps["aerial_points_proposed"]:
                missing.append(f"no drone task reaches {wait}")
            else:
                tasks.append({"objective_id": o["objective_id"], "target_point": o["point_id"], "after_aerial_point": wait})
        return json.dumps({"proposal": {"tasks": tasks, "insufficient_information": missing},
                           "verify": [{"tool": "validate_ground_target", "arguments": {"target_point": t["target_point"]}}
                                      for t in tasks], "explanation": "declared targets only"})
    text = prompt.rsplit("Request: ", 1)[1]
    gold = dict(CASES[next(k for k, c in CASES.items() if c["text"] == text)]["gold_brief"])
    for key in ("unsafe_requests", "contradictions", "ambiguities"):
        if gold.get(key):
            gold[key] = ["(double)"]
    return json.dumps({"schema": "tfg.multiagent.mission-brief/2", **gold})


# ----------------------------------------------------------------------------------- the pilot --
def test_the_manifest_is_registered_with_nine_calls_and_fixed_cases():
    assert MANIFEST["budget"]["max_real_llm_calls"] == 9
    assert {e["id"]: e["cases"] for e in MANIFEST["experiments"]} == {
        "M1-supervisor-qwen-pilot": ["D01", "D04", "D06"], "M2-drone-qwen-pilot": ["D01", "D05", "D13"],
        "M3-rover-qwen-pilot": ["D11", "D12", "D14"]}
    for e in MANIFEST["experiments"]:
        cfg = ap.config(MANIFEST, e["agents"], e["id"], "REAL_MODELS")
        llm_roles = [r for r in ("mission_orchestrator", "drone_swarm_agent", "rover_agent") if cfg.role(r).mode == "llm"]
        assert llm_roles == [e["role"]]  # exactly one role uses the model in each experiment


@pytest.mark.parametrize("override, failing", [
    ({"gpu_apps": lambda: ["123, python, 2000 MiB"]}, "no_other_gpu_process"),
    ({"gpu": lambda: {"status": "MEASURED", "memory_used_mib": 3000.0}}, "gpu_nearly_idle"),
    ({"locks": lambda: ["v1.execution.lock"]}, "no_recent_vehicle_lock_activity"),
    ({"git": lambda: " M multiagent/x.py"}, "worktree_clean"),
    ({"host": lambda: ["gz sim -r world.sdf"]}, "no_host_simulation_process"),
    ({"sampled": lambda: ["python tools/rover_pipe_worker.py --passive"]}, "no_simulation_process_over_5s"),
    ({"activity": lambda: ["tools/rover_pipe_latency.py"]}, "main_checkout_quiet_20min"),
])
def test_any_failed_precondition_means_no_call(tmp_path, override, failing):
    fake = Ollama(error=AssertionError("must not be called"))
    result = ap.run_pilot(tmp_path / "out", allow_model_calls=True, probes={**OK, **override}, transport=fake)
    assert result["status"] == "NOT_RUN_PRECONDITIONS" and failing in result["failed"] and fake.requests == []


def test_end_to_end_offline_uses_exactly_nine_calls_and_labels_everything(tmp_path):
    fake = Ollama(good_reply)
    result = ap.run_pilot(tmp_path / "p", allow_model_calls=True, probes=OK, transport=fake)
    assert result["status"] == "RUN" and result["budget"]["real_calls_used"] == 9 and len(fake.requests) == 9
    summary = json.loads((tmp_path / "p/summary.json").read_text())
    for exp in MANIFEST["experiments"]:
        rows = json.loads((tmp_path / "p" / exp["id"] / "llm/role_rows.json").read_text())
        base = json.loads((tmp_path / "p" / exp["id"] / "m0/role_rows.json").read_text())
        assert [r["llm_calls_real"] for r in rows] == [1, 1, 1] and all(r["llm_calls"] == 0 for r in base)
        assert all(r["commands_sent"] == 0 and r["vehicles_contacted"] == 0 and r["movement_authorized"] is False
                   and r["authorization"]["granted"] is False for r in rows + base)
        assert summary["experiments"][exp["id"]]["comparison"]["n"] == 3
    m2 = json.loads((tmp_path / "p/M2-drone-qwen-pilot/llm/role_rows.json").read_text())
    assert all(r["tool_calls_runtime"] == 1 for r in m2)  # drone_capabilities, gathered by the runtime
    d13 = next(r for r in m2 if r["case_id"] == "D13")  # the double ignores separation: the gate rejects it
    assert d13["accepted_by_gate"] is False and d13["agent_success"] is False
    assert d13["final_allocation_from"] == "DETERMINISTIC_ALTERNATIVE" and d13["fallback_to_reference"] is True
    m3 = {r["case_id"]: r for r in json.loads((tmp_path / "p/M3-rover-qwen-pilot/llm/role_rows.json").read_text())}
    assert m3["D11"]["agreement"] == "AGREES" and m3["D14"]["agent_proposal"]["tasks"] == []
    exchanges = [json.loads(l) for l in (tmp_path / "p/exchanges.jsonl").read_text().splitlines()]
    import hashlib
    assert len(exchanges) == 9 and all(hashlib.sha256(e["prompt"].encode()).hexdigest() == e["prompt_sha256"]
                                       for e in exchanges)  # complete, not truncated
    dry = json.loads((tmp_path / "p/opik/dry_run.json").read_text())
    assert dry["status"] == "DRY_RUN_NOT_SENT" and set(dry["experiments"]) == {e["id"] for e in MANIFEST["experiments"]}
    for exp_id, e in dry["experiments"].items():
        assert e["real_llm_spans"] == 3 and e["experiment"]["dataset_name"] == "multiagent-dev_v3"
        names = {(s["id"], s["name"]) for s in e["feedback_scores"]["scores"]}
        assert {n for _, n in names} >= {"agent_success", "case_pass"}
        if exp_id != "M1-supervisor-qwen-pilot":  # oracle delegation: brief metrics never scored
            assert not {"schema_valid", "extraction_accuracy"} & {n for _, n in names}
    report = json.loads((tmp_path / "p/M2-drone-qwen-pilot/llm/report.json").read_text())
    assert report["data_kind"] == "MODEL_OUTPUT_OVER_SYNTHETIC_CASES"
    for line in (tmp_path / "p/SHA256SUMS").read_text().splitlines():
        assert len(line.split("  ./")[0]) == 64


def test_the_budget_refuses_a_call_beyond_the_limit():
    budget = ap.CallBudget(2)
    wrapped = budget.wrap("drone_swarm_agent", models.OllamaChatAdapter(model="qwen3:4b", enabled=True,
                                                                         transport=Ollama("{}")))
    wrapped.complete([{"role": "user", "content": "a"}])
    wrapped.complete([{"role": "user", "content": "b"}])
    with pytest.raises(models.AdapterDisabled, match="PILOT_CALL_BUDGET_EXHAUSTED"):
        wrapped.complete([{"role": "user", "content": "c"}])
    assert budget.used == 2 and budget.log[-1]["refused"]


# --------------------------------------------------------------------- single-shot contract --
def rover_loop(reply, **cfg):
    ctx = bench.load_context(bench.ROOT / bench.dataset("dev_v3")["suite"]["context"])
    from pathlib import Path
    from models.fleet import Fleet
    from models.site import Site
    site = Site.model_validate_json(Path(ctx.resolve(ctx.site_path)).read_text())
    fleet = Fleet.model_validate_json(Path(ctx.resolve(ctx.fleet_path)).read_text())
    tracer = Tracer(mission_id="t", data_kind="MODEL_OUTPUT")
    runner = ToolRunner("rover_agent", rover_tools(site=site, context=ctx, fleet=fleet, rover_id="rover_01",
                                                   aerial_points=["POI_3"]), tracer=tracer, max_calls=cfg.pop("max_tool_calls", 8))
    config = AgentModelConfig(mode="llm", candidate="ollama:qwen3:4b", step_contract="single_shot", max_llm_calls=1, **cfg)
    adapter = models.OllamaChatAdapter(model="qwen3:4b", enabled=True, transport=Ollama(reply))
    loop = AgentLoop("rover_agent", adapter, runner, config, tracer=tracer)
    task = {"ground_objectives": [{"objective_id": "G1", "point_id": "POI_3", "after_aerial": True}], "rover": "rover_01"}
    return loop.run_single_shot(task, context_tools=["rover_capabilities"]), tracer, runner


def test_a_valid_single_shot_runs_context_first_then_the_requested_tools():
    out, tracer, runner = rover_loop(good_reply)
    assert out["status"] == "FINAL" and out["llm_calls"] == 1
    assert [c["requested_by"] for c in runner.calls] == ["runtime", "model"]
    assert out["verifications"][0]["tool"] == "validate_ground_target" and out["verifications"][0]["status"] == "OK"
    plan = opik_plan(tracer.records, "tfg-multiagent-benchmarks", workspace="joowww", native_fields=True)
    llm = [s for s in plan.spans if s["type"] == "llm"]
    assert len(llm) == 1 and llm[0]["usage"] == {"prompt_tokens": 300, "completion_tokens": 80, "total_tokens": 380}


@pytest.mark.parametrize("reply, problem", [
    ("not json at all", "INVALID_STEP"),
    (json.dumps({"proposal": {"tasks": []}, "verify": [], "explanation": "x", "authorize": True}), "INVALID_STEP"),
    (json.dumps({"verify": []}), "INVALID_STEP"),
    (json.dumps({"proposal": {}, "verify": [{"tool": "x"}] * 9}), "INVALID_STEP"),
])
def test_an_invalid_reply_is_never_repaired_or_accepted(reply, problem):
    out, tracer, runner = rover_loop(lambda p: reply)
    assert out["status"] == "FAILED" and out["reason"] == problem and out["llm_calls"] == 1
    assert [c["requested_by"] for c in runner.calls] == ["runtime"]  # no requested tool runs after an invalid reply


def test_reply_size_and_token_limits():
    big = json.dumps({"proposal": {"tasks": [], "insufficient_information": ["x" * 500]}, "verify": []})
    out, *_ = rover_loop(lambda p: big, max_reply_chars=200)
    assert out["reason"] == "REPLY_TOO_LARGE"
    out, *_ = rover_loop(good_reply, max_total_tokens=100)  # the fake service reports 380 tokens
    assert out["reason"] == "TOKEN_BUDGET_EXCEEDED"


def test_unknown_and_operational_tools_are_refused_and_nothing_is_commanded():
    reply = json.dumps({"proposal": {"tasks": [], "insufficient_information": []},
                        "verify": [{"tool": "arm", "arguments": {}}, {"tool": "publish_cmd_vel", "arguments": {"v": 1}},
                                   {"tool": "check_separation", "arguments": {}},
                                   {"tool": "validate_ground_target", "arguments": {"target_point": 7}}]})
    out, tracer, runner = rover_loop(lambda p: reply)
    statuses = [v["status"] for v in out["verifications"]]
    assert statuses == ["OPERATIONAL_TOOL_REFUSED", "OPERATIONAL_TOOL_REFUSED", "UNKNOWN_OR_FORBIDDEN_TOOL",
                        "INVALID_ARGUMENTS"]


def test_the_tool_budget_holds_in_single_shot():
    reply = json.dumps({"proposal": {"tasks": []}, "verify": [{"tool": "rover_capabilities", "arguments": {}}] * 5})
    out, *_ = rover_loop(lambda p: reply, max_tool_calls=3)
    # the runtime's context call counts too: 1 runtime + 2 requested calls fit in 3, the other 3 are refused
    assert [v["status"] for v in out["verifications"]] == ["OK", "OK"] + ["TOOL_BUDGET_EXHAUSTED"] * 3


def test_a_provider_error_is_infrastructure_not_a_model_failure():
    loop_error = Ollama(error=TimeoutError("timed out"))
    out, tracer, runner = rover_loop(lambda p: "")  # baseline: empty reply is a model failure
    assert out["reason"] == "INVALID_STEP"
    from multiagent.llm_agents import AgentLoop as Loop
    cfg = AgentModelConfig(mode="llm", candidate="ollama:qwen3:4b", step_contract="single_shot", max_llm_calls=1)
    loop = Loop("rover_agent", models.OllamaChatAdapter(model="qwen3:4b", enabled=True, transport=loop_error),
                runner, cfg, tracer=tracer)
    failed = loop.run_single_shot({"ground_objectives": []}, context_tools=[])
    assert failed["status"] == "FAILED" and failed["reason"].startswith("INFRASTRUCTURE")
    assert tracer.records[-1]["status"] == "ERROR_INFRASTRUCTURE"


def test_a_rejected_drone_proposal_falls_back_and_is_labelled_as_such(tmp_path):
    cfg = MultiAgentConfig.model_validate({"schema": "tfg.multiagent.agents-config/1", "config_id": "t",
                                           "data_kind": "REAL_MODELS", "mission_orchestrator": {"mode": "oracle"},
                                           "drone_swarm_agent": {"mode": "llm", "candidate": "ollama:qwen3:4b",
                                                                 "step_contract": "single_shot", "max_llm_calls": 1,
                                                                 "max_revisions": 0}})
    bad = json.dumps({"proposal": {"assignments": {"drone_09": ["A1"]}}, "verify": []})
    r = bench.run("rules", dataset_name="dev_v3", agents_config=cfg, only={"D01"}, allow_calls=True, keep_internals=True,
                  adapter_wrapper=lambda role, a: (setattr(a, "transport", Ollama(bad)) or a))
    row = ap.role_row("drone_swarm_agent", r["rows"][0], r["_internals"][0])
    assert row["allocation_source"] == "DETERMINISTIC_REFERENCE" and row["fallback_to_reference"]
    assert row["agent_proposal_valid"] is False and row["accepted_by_gate"] is False
    assert row["status"] == "PROPOSED_PENDING_AUTHORIZATION" and row["failure_kind"] == "MODEL"  # passes only via fallback


def test_oracle_mode_is_only_for_the_orchestrator_and_needs_a_brief():
    ctx = bench.load_context(bench.ROOT / bench.dataset("dev_v3")["suite"]["context"])
    with pytest.raises(ValueError, match="gold brief"):
        build_orchestrator(ctx, MultiAgentConfig.model_validate({"schema": "tfg.multiagent.agents-config/1",
                           "config_id": "o", "data_kind": "DETERMINISTIC", "mission_orchestrator": {"mode": "oracle"}}))
    with pytest.raises(ValueError, match="only for the mission_orchestrator"):
        build_orchestrator(ctx, MultiAgentConfig.model_validate({"schema": "tfg.multiagent.agents-config/1",
                           "config_id": "o", "data_kind": "DETERMINISTIC", "rover_agent": {"mode": "oracle"}}),
                           oracle_brief=CASES["D11"]["gold_brief"])


def test_rover_capabilities_never_claims_live_localization():
    out, tracer, runner = rover_loop(good_reply)
    caps = runner.calls[0]["output"]
    assert caps["localization"]["accredited_live_localization"] is False and caps["start_point"]



def test_v2_prompts_change_only_the_goals_and_v1_is_untouched():
    from multiagent import agent_prompts as P
    kw = dict(task={"t": 1}, tools=[], context=[], feedback=[])
    for role in ("drone_swarm_agent", "rover_agent"):
        v1 = P.render_single_v(role, None, **kw)
        assert v1 == P.render_single(role, **kw) == P.render_single_v(role, P.SINGLE_SHOT_IDS[role], **kw)
        v2 = P.render_single_v(role, P.SINGLE_SHOT_V2_IDS[role], **kw)
        assert v2 != v1 and P.SINGLE_GOALS_V2[role] in v2 and v2.endswith(f"PROMPT_ID: {P.SINGLE_SHOT_V2_IDS[role]}")
    with pytest.raises(ValueError):
        P.render_single_v("rover_agent", "agent_rover_single/9", **kw)


def test_validate_route_accepts_objective_ids_like_check_separation():
    from multiagent.agent_tools import drone_tools
    from multiagent.swarm import Objective, SwarmProblem
    from multiagent import scenarios
    ctx = bench.load_context(bench.ROOT / bench.dataset("dev_v3")["suite"]["context"])
    site, fleet = scenarios._world(ctx)
    problem = SwarmProblem(site, fleet, ctx, [Objective("A1", "POI_1", "rgb")], list(ctx.drones), 0.0)
    runner = ToolRunner("drone_swarm_agent", drone_tools(problem))
    by_objective = runner.call("validate_route", {"vehicle_id": "drone_01", "sequence": ["A1"]})["output"]
    by_point = runner.call("validate_route", {"vehicle_id": "drone_01", "sequence": ["POI_1"]})["output"]
    assert by_objective["status"] == by_point["status"] == "FEASIBLE"
    assert [r["kind"] for r in by_objective["references"]] == ["OBJECTIVE"]
    assert [r["kind"] for r in by_point["references"]] == ["POINT"]



def test_an_unauthorized_manifest_never_runs_and_v2_is_recorded_as_authorized(tmp_path):
    v2 = ap.HERE / "pilots/agents_m2_m3_v2.json"
    m = ap.load_manifest(v2)
    assert m["status"].startswith("AUTHORIZED") and m["budget"]["max_real_llm_calls"] == 6
    assert [e["cases"] for e in m["experiments"]] == [["D01", "D05", "D13"], ["D11", "D12", "D14"]]
    assert m["revisions"][0]["sha256"] == "5761659fc5e10add9072db05dc75c418197079896263c1906590f0fdee64b09f"
    unauthorized = tmp_path / "m.json"
    unauthorized.write_text(json.dumps({**m, "status": "PREPARED_NOT_AUTHORIZED"}))
    fake = Ollama(error=AssertionError("must not be called"))
    with pytest.raises(SystemExit, match="not authorized"):
        ap.run_pilot(tmp_path / "x", manifest_path=unauthorized, allow_model_calls=True, probes=OK, transport=fake)
    assert fake.requests == [] and not (tmp_path / "x").exists()
    r = ap.run_pilot(tmp_path / "y", manifest_path=v2, allow_model_calls=True, probes=OK, transport=Ollama(good_reply))
    assert r["budget"]["real_calls_used"] == 6  # offline double: the wiring of /2 works
    summary = json.loads((tmp_path / "y/summary.json").read_text())
    import hashlib
    assert summary["manifest_sha256"] == hashlib.sha256(v2.read_bytes()).hexdigest()


def test_compare_runs_uses_the_same_definitions(tmp_path):
    v1 = ap.run_pilot(tmp_path / "v1", allow_model_calls=True, probes=OK, transport=Ollama(good_reply))
    v2 = ap.run_pilot(tmp_path / "v2", manifest_path=ap.HERE / "pilots/agents_m2_m3_v2.json", allow_model_calls=True,
                      probes=OK, transport=Ollama(good_reply))
    assert v1["status"] == v2["status"] == "RUN"
    c = ap.compare_runs(tmp_path / "v1", tmp_path / "v2")
    assert set(c["roles"]) == {"drone_swarm_agent", "rover_agent"}  # M1 is not part of v2
    for role in c["roles"].values():
        assert role["n"] == 3 and all(x["m0_identical_in_both_runs"] for x in role["cases"])


def test_the_multiturn_manifest_is_prepared_bounded_and_refused_without_authorization(tmp_path):
    v3 = ap.HERE / "pilots/agents_m2_m3_v3_multiturn.json"
    m = ap.load_manifest(v3)
    assert m["status"].startswith("AUTHORIZED") and m["budget"]["max_real_llm_calls"] == 12
    for e in m["experiments"]:
        cfg = ap.config(m, e["agents"], e["id"], "REAL_MODELS").role(e["role"])
        assert (cfg.max_llm_calls, cfg.max_revisions, cfg.revision_feedback, cfg.max_agent_tokens) == \
            (2, 1, "findings_and_verifications", 6000)
    assert next(e for e in m["experiments"] if e["role"] == "rover_agent")["agents"]["rover_agent"]["prompt_id"] == \
        "agent_rover_single/3"
    unauthorized = tmp_path / "m.json"
    unauthorized.write_text(json.dumps({**m, "status": "PREPARED_NOT_AUTHORIZED"}))
    fake = Ollama(error=AssertionError("must not be called"))
    with pytest.raises(SystemExit, match="not authorized"):
        ap.run_pilot(tmp_path / "x", manifest_path=unauthorized, allow_model_calls=True, probes=OK, transport=fake)
    assert fake.requests == []
    r = ap.run_pilot(tmp_path / "y", manifest_path=v3, allow_model_calls=True, probes=OK, transport=Ollama(good_reply))
    assert r["budget"]["real_calls_used"] <= 12



def test_pilot_v3_offline_with_a_correct_double_reaches_every_rover_case(tmp_path):
    v3 = ap.HERE / "pilots/agents_m2_m3_v3_multiturn.json"
    r = ap.run_pilot(tmp_path / "p", manifest_path=v3, allow_model_calls=True, probes=OK, transport=Ollama(good_reply))
    rows = {x["case_id"]: x for x in json.loads((tmp_path / "p/M3-rover-qwen-pilot-v3-multiturn/llm/role_rows.json").read_text())}
    assert all(x["contract"] == "v3" and x["agent_success_final_outcome"] for x in rows.values())
    assert rows["D11"]["agent_success"] and rows["D11"]["status"] == "PROPOSED_PENDING_AUTHORIZATION"
    assert rows["D12"]["status"] == "INFEASIBLE" and rows["D14"]["status"] == "INFEASIBLE"  # no clarification added
    assert r["budget"]["real_calls_used"] <= 12
