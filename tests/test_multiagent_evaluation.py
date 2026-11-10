"""Independent eval set, common result contract, task x model matrix, Opik instrumentation, swarm demo."""
import json

import pytest

from multiagent import demo, evaluation, models
from multiagent.benchmark import run as bench
from multiagent.contracts import load_context
from multiagent.interpreters import ModelInterpreter
from multiagent.orchestrator import MissionOrchestrator
from multiagent.tracing import Tracer, opik_dry_run

SECRET = "sk-eval-NEVER-IN-TRACES-424242"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("offline only")
    monkeypatch.setattr("socket.socket.connect", refuse)
    monkeypatch.setattr("urllib.request.urlopen", refuse)
    monkeypatch.setattr("subprocess.run", refuse)
    monkeypatch.setattr("subprocess.Popen", refuse)


# --------------------------------------------------------------------------- datasets --
def test_datasets_keep_v1_intact_and_add_dev_and_eval_splits():
    v1, dev, ev = bench.dataset("v1"), bench.dataset("dev_v2"), bench.dataset("eval_v2")
    assert v1["sha256"] == dev["sha256"]  # dev reuses the 34 historical cases byte for byte
    assert len(v1["suite"]["cases"]) == 34 and v1["split"] == "historical" and dev["split"] == "dev"
    eval_ids = {c["case_id"] for c in ev["suite"]["cases"]}
    assert len(eval_ids) >= 30 and not eval_ids & {c["case_id"] for c in v1["suite"]["cases"]}
    assert {"adversarial", "paraphrase", "incomplete", "contradictory", "multi_drone", "drone_rover", "safety",
            "swarm_coordination"} <= {c["category"] for c in ev["suite"]["cases"]}


def test_eval_set_is_frozen_against_the_interpreter():
    assert bench.dataset("eval_v2")["frozen_check"] == {"multiagent/interpreters.py": "MATCH"}


def test_eval_expectations_hold_for_the_gold_briefs_except_the_documented_gap():
    report = bench.run("oracle", dataset_name="eval_v2")
    assert report["aggregate"]["failures"] == bench.dataset("eval_v2")["suite"]["known_gaps"] == ["E19"]
    assert report["aggregate"]["unsafe_missed"] == 0 and report["aggregate"]["safe_refused"] == 0


def test_metrics_separate_extraction_validity_feasibility_safety_allocation_conflicts():
    report = bench.run("rules", dataset_name="eval_v2")
    a = report["aggregate"]
    for key in ("extraction_accuracy", "structural_validity", "status_match", "safety", "coverage_match",
                "conflicts_ok", "case_pass", "latency_s", "cost", "consistency"):
        assert key in a, key
    assert report["dataset"]["split"] == "eval" and report["data_kind"] == "SYNTHETIC_DETERMINISTIC_BASELINE"
    assert all(set(r["criteria"]) >= {"status", "no_authorization_no_command"} for r in report["rows"])
    assert all(r["criteria"]["no_authorization_no_command"] for r in report["rows"])


# ------------------------------------------------------------------ contract and matrix --
def test_clef_is_never_evaluated_as_a_plan_or_brief_generator():
    for task in ("INTERPRET_BRIEF", "ALLOCATE"):
        with pytest.raises(evaluation.TaskNotApplicable):
            evaluation.require_fit("aida-clef", task)
    assert evaluation.fit("aida-clef", "SELECT_ALLOCATION") == "PRIMARY"
    assert evaluation.fit("aida-qwen", "INTERPRET_BRIEF") == "PRIMARY"
    assert evaluation.fit("ollama:qwen3:4b", "CLASSIFY_REQUEST") == "SECONDARY"
    with pytest.raises(evaluation.TaskNotApplicable):
        evaluation.require_fit("rules", "ALLOCATE")
    assert evaluation.matrix_markdown().count("\n| ") == len(evaluation.MATRIX) + 1


def test_benchmark_rows_become_valid_comparable_records():
    report = bench.run("rules", dataset_name="eval_v2", only={"E07", "E18"}, experiment_id="EXP-test")
    assert len(report["records"]) == 2
    for record in report["records"]:
        evaluation.EvaluationRecord.model_validate(record)
        assert record["experiment_id"] == "EXP-test" and record["task"] == "INTERPRET_BRIEF"
        assert record["dataset"]["id"] == "eval_v2" and record["dataset"]["sha256"]
        assert record["cost"]["status"] == "NOT_APPLICABLE" and record["resources"]["gpu_memory"] == "NOT_MEASURED"


def test_select_allocation_task_for_a_structured_decision_model():
    from contextlib import redirect_stdout
    import io
    from multiagent import scenarios
    from multiagent.swarm import Objective, SwarmProblem, allocate
    context = load_context(scenarios.FIXTURES / "swarm_3.context.json")
    site, fleet = scenarios._world(context)
    problem = SwarmProblem(site, fleet, context, [Objective("O1", "POI_1"), Objective("O2", "POI_4")],
                           list(context.drones), 0.0)
    with redirect_stdout(io.StringIO()):
        options = evaluation.allocation_options(allocate(problem))
    reply = json.dumps({"probabilities": {o["label"]: (0.7 if o["label"] == "B" else 0.3 / (len(options) - 1))
                                          for o in options}})
    clef_double = models.ScriptedAdapter(responder=lambda p: reply, model="clef-double")
    record = evaluation.select_allocation_record(experiment_id="EXP-sel", dataset={"id": "scenarios"},
                                                 case_id="swarm3-2obj", adapter=clef_double, options=options)
    assert record["task"] == "SELECT_ALLOCATION" and record["metrics"]["chosen"] == "B"
    assert record["metrics"]["picked_reference_best"] is False and record["metrics"]["brier"] > 0
    assert record["data_kind"] == "SYNTHETIC"


# ------------------------------------------------------------------------ instrumentation --
class Transport:
    def __init__(self, reply):
        self.reply, self.requests = reply, []

    def __call__(self, url, headers, body, timeout):
        self.requests.append(headers)
        return 200, json.dumps(self.reply).encode()


def test_model_run_trace_records_everything_but_never_the_credential(monkeypatch):
    monkeypatch.setenv(models.AIDA_KEY_ENV, SECRET)
    brief = {"schema": "tfg.multiagent.mission-brief/1", "aerial_objectives": [{"objective_id": "A1", "point_id": "POI_1"}]}
    transport = Transport({"model": "qwen", "choices": [{"message": {"content": json.dumps(brief)}}],
                           "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
    adapter = models.aida_qwen(enabled=True, transport=transport)
    experiment = {"experiment_id": "EXP-cred", "dataset_id": "eval_v2", "dataset_version": "2", "split": "eval"}
    tracer = Tracer(mission_id="m", data_kind="MODEL_OUTPUT", experiment=experiment)
    context = load_context(bench.ROOT / "multiagent/fixtures/orchard_two_drones_v2.context.json")
    proposal = MissionOrchestrator(context, ModelInterpreter(adapter, site_points=["POI_1"]), tracer=tracer).run(
        "Inspect POI_1.")
    assert transport.requests[0]["Authorization"] == f"Bearer {SECRET}"  # sent, and only there
    llm = next(r for r in tracer.records if r["kind"] == "llm")
    call = llm["model_call"]
    assert call["generation"]["temperature"] == 0.0 and call["prompt"]["template_id"] == "interpret_brief/1"
    assert len(call["prompt"]["sha256"]) == 64 and call["usage"]["prompt_tokens"] == 100
    assert all(r["experiment"]["experiment_id"] == "EXP-cred" for r in tracer.records)
    dry = opik_dry_run(tracer.records)
    trace = dry["bodies"]["traces"][0]["traces"][0]
    assert "experiment:EXP-cred" in trace["tags"] and "dataset:eval_v2@2" in trace["tags"]
    assert trace["metadata"]["tfg_cost"] == "UNKNOWN" and trace["metadata"]["tfg_generation"]["temperature"] == 0.0
    assert dry["trace_kinds"] == ["unknown_provenance"] and dry["status"] == "DRY_RUN_NOT_SENT"
    blob = json.dumps(tracer.records) + json.dumps(dry) + json.dumps(proposal, default=str)
    assert SECRET not in blob and "Bearer" not in blob


def test_synthetic_traces_stay_labelled_synthetic():
    result = demo.run_demo(None)
    assert result["proposal"]["data_kind"] == "SYNTHETIC" and result["trace"]["data_kind"] == "SYNTHETIC"


# ------------------------------------------------------------------------------ swarm demo --
def test_swarm_demo_conflict_replanning_rover_and_no_authorization(tmp_path):
    result = demo.run_demo(tmp_path / "swarm", text=demo.SWARM_REQUEST, context_path=demo.SWARM_CONTEXT)
    p = result["proposal"]
    attempts = p["aerial"]["evidence"]["coordination_attempts"]
    assert attempts[0]["candidate"] == "CHOSEN" and attempts[0]["status"] == "UNRESOLVED"
    assert p["swarm_coordination"]["replanned"] is True and p["swarm_coordination"]["residual_conflicts"] == 0
    assert p["status"] == "PARTIAL_PENDING_AUTHORIZATION"
    assert any("COORDINATION_CONFLICT" in r for r in p["reasons"])
    assert [g["target_point"] for g in p["ground"]["proposals"]] == ["POI_4"]
    assert p["coordination"]["status"] == "PASS"
    assert p["authorization"]["granted"] is False and p["movement_authorized"] is False and p["commands_sent"] == 0
    spans = [json.loads(line) for line in (tmp_path / "swarm/trace.jsonl").read_text().splitlines()]
    assert any(s["name"].startswith("deconfliction:") and s["status"] == "UNRESOLVED" for s in spans)
    lines = demo.summary_lines(result)
    assert any("swarm coordination" in line for line in lines) and any("attempt CHOSEN" in line for line in lines)
