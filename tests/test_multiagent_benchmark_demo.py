"""Benchmark suite and the reproducible offline demo. Only deterministic candidates and test doubles run here."""
import json
from pathlib import Path

import pytest

from multiagent import demo
from multiagent.benchmark import run as bench

FIXTURE = Path(__file__).resolve().parents[1] / "multiagent/benchmark/fixtures/scripted_double_v1.json"
REQUIRED_CATEGORIES = {"simple", "incomplete", "infeasible", "two_drones", "multi_assignment", "drone_rover",
                       "battery", "wind", "contradictory", "no_coordinates", "unsafe"}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("offline only")
    monkeypatch.setattr("socket.socket.connect", refuse)
    monkeypatch.setattr("urllib.request.urlopen", refuse)
    monkeypatch.setattr("subprocess.run", refuse)
    monkeypatch.setattr("subprocess.Popen", refuse)


@pytest.fixture(scope="module")
def oracle():
    return bench.run("oracle", dataset_name="dev_v2")  # the 34 v1 cases, unchanged, with the v2 context


def test_suite_has_at_least_twenty_labelled_synthetic_cases_covering_every_category():
    suite = bench.load_cases()
    assert suite["data_kind"] == "SYNTHETIC" and len(suite["cases"]) >= 20
    assert REQUIRED_CATEGORIES <= {c["category"] for c in suite["cases"]}
    assert len({c["case_id"] for c in suite["cases"]}) == len(suite["cases"])


def test_the_deterministic_pipeline_reproduces_every_specified_outcome(oracle):
    # Validates the hand-written expectations against the real checks; it is not a model result.
    assert oracle["data_kind"] == "SYNTHETIC_GOLD_REFERENCE" and oracle["dataset"]["split"] == "dev"
    assert oracle["aggregate"]["failures"] == []
    for metric in ("status_match", "extraction_accuracy", "structural_validity", "constraint_compliance", "coverage_match"):
        assert oracle["aggregate"][metric] == 1.0, metric


def test_rules_baseline_is_labelled_and_its_paraphrase_limits_are_visible():
    report = bench.run("rules", runs=2, dataset_name="dev_v2")
    assert report["data_kind"] == "SYNTHETIC_DETERMINISTIC_BASELINE"
    assert report["aggregate"]["consistency"] == 1.0
    assert report["aggregate"]["constraint_compliance"] == 1.0
    # The held-out paraphrases are reported as they are (not tuned away).
    assert {"B32", "B34"} <= set(report["aggregate"]["failures"])
    assert report["aggregate"]["cost"] == "NOT_MEASURABLE" and report["aggregate"]["gpu_memory"] == "NOT_MEASURED"


def test_metrics_discriminate_the_scripted_double_errors_and_safety_holds():
    report = bench.run(f"scripted:{FIXTURE}", dataset_name="dev_v2")
    assert report["data_kind"] == "SYNTHETIC_TEST_DOUBLE"
    assert report["aggregate"]["failures"] == ["B02", "B12", "B17"]
    rows = {r["case_id"]: r for r in report["rows"]}
    assert rows["B02"]["structural_validity"] is False and rows["B02"]["status"] == "NEEDS_CLARIFICATION"
    assert rows["B12"]["status"] == "NEEDS_CLARIFICATION"  # stated battery dropped -> not planned
    assert rows["B24"]["status"] == "REFUSED_UNSAFE" and rows["B24"]["extraction_fields"]["unsafe"] is False
    assert report["aggregate"]["constraint_compliance"] == 1.0


def test_model_candidates_require_explicit_permission():
    with pytest.raises(SystemExit, match="allow-model-calls"):
        bench.run("ollama:qwen3:4b", only={"B01"})
    with pytest.raises(SystemExit, match="allow-remote"):
        bench.run("aida-qwen", only={"B01"}, allow_calls=True)


def test_clef_benchmark_interface_with_a_double():
    from multiagent.models import ScriptedAdapter
    reply = json.dumps({"probabilities": {"FEASIBLE": 0.6, "UNSAFE": 0.1, "INFEASIBLE": 0.1,
                                          "NEEDS_CLARIFICATION": 0.1, "PARTIAL": 0.1}})
    report = bench.clef_benchmark(ScriptedAdapter(responder=lambda p: reply, model="clef-double"))
    assert report["data_kind"] == "SYNTHETIC" and len(report["rows"]) >= 20
    assert 0 < report["accuracy"] < 1 and report["brier_mean"] is not None


def test_markdown_report_has_one_row_per_case(oracle):
    text = bench.markdown(oracle)
    assert text.count("\n| B") == len(bench.load_cases()["cases"])


def test_v1_context_without_policy_turns_exactly_the_multi_drone_cases_pending():
    report = bench.run("oracle", dataset_name="v1")
    pending = {r["case_id"] for r in report["rows"] if r["status"] == "COORDINATION_PENDING"}
    assert pending == set(report["aggregate"]["failures"]) == {"B03", "B04", "B05", "B10", "B20", "B28", "B30", "B32"}


# ------------------------------------------------------------------------------------ demo --
def test_demo_end_to_end_two_drones_one_rover_pending_authorization(tmp_path):
    result = demo.run_demo(tmp_path / "out")
    proposal = result["proposal"]
    assert proposal["status"] == "PROPOSED_PENDING_AUTHORIZATION" and proposal["data_kind"] == "SYNTHETIC"
    aerial = {p["vehicle_id"]: p["poi_sequence"] for p in proposal["aerial"]["proposals"]}
    assert aerial == {"drone_01": ["POI_1", "POI_2"], "drone_02": ["POI_3", "POI_4"]}
    assert [g["target_point"] for g in proposal["ground"]["proposals"]] == ["POI_3"]
    assert proposal["plan_verification"] == {"drone_01": "FILE_MATCHES_EXPECTATIONS", "drone_02": "FILE_MATCHES_EXPECTATIONS"}
    assert proposal["authorization"]["granted"] is False and proposal["commands_sent"] == 0
    out = tmp_path / "out"
    written = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert written == ["missions/drone_01.json", "missions/drone_02.json", "opik_payload.dry_run.json",
                       "plans/drone_01.plan", "plans/drone_01.verification.json", "plans/drone_02.plan",
                       "plans/drone_02.verification.json", "proposal.json", "template.json", "trace.jsonl"]
    assert json.loads((out / "opik_payload.dry_run.json").read_text())["status"] == "DRY_RUN_NOT_SENT"
    spans = [json.loads(line) for line in (out / "trace.jsonl").read_text().splitlines()]
    assert {s["agent"] for s in spans} == {"mission_orchestrator", "drone_swarm_agent", "rover_agent"}


def test_demo_is_reproducible_and_refuses_a_non_empty_directory(tmp_path):
    a, b = demo.run_demo(tmp_path / "a"), demo.run_demo(tmp_path / "b")
    assert a["proposal"]["proposal_sha256"] == b["proposal"]["proposal_sha256"]
    assert (tmp_path / "a/plans/drone_01.plan").read_bytes() == (tmp_path / "b/plans/drone_01.plan").read_bytes()
    with pytest.raises(SystemExit, match="not empty"):
        demo.run_demo(tmp_path / "a")


def test_demo_without_out_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = demo.run_demo(None)
    assert result["proposal"]["status"] == "PROPOSED_PENDING_AUTHORIZATION" and list(tmp_path.iterdir()) == []
    assert any("authorization granted: False" in line for line in demo.summary_lines(result))
