"""Opik phase 2, all offline: the 10 pending qwen traces and the 11 rules traces prepared with exact hashes, E07
preserved, feedback scores (never inventing values), datasets, experiments, dashboards, contract validators, future
instrumentation. Every Opik shape here is checked against the PINNED OpenAPI/frontend source, not the service."""
import hashlib
import json
import math
import os
from pathlib import Path

import pytest

from multiagent import opik_bridge as bridge, opik_contract as contract, opik_dashboard, opik_datasets, opik_metrics
from multiagent import opik_phase2 as phase2, tracing
from multiagent.benchmark import pilot
from observability import opik_export as opik

ROOT = Path(__file__).resolve().parents[1]
PILOT = phase2.PILOT
E07 = "01a1a76e-e360-7b24-9ca0-f4088fe20e36"
E07_LLM_SPAN = "01a1a76e-e362-7a07-8e04-d5e753b9091b"
E07_V1 = {"traces": "59890857d6824f294c36951b9c1e7abc4fb8a5f03398dc54c2a00ac404323ff5",
          "spans": "09af3bc214bae06bc78098ad8593ae86a8959bc4ff840b86e3e710af72b6776e"}
KEY = "opik-TEST-KEY-phase2-0123456789abcdef"
LEDGER = bridge.IMPORTS / "ledger.json"


def _refuse(*a, **k):
    raise AssertionError("no real network, model or process")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr("socket.socket.connect", _refuse)
    monkeypatch.setattr("urllib.request.urlopen", _refuse)
    monkeypatch.setattr("subprocess.run", _refuse)


def sha(b):
    return hashlib.sha256(b).hexdigest()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """One offline build with a FAKE credential in a temporary config (the real one is never read here)."""
    tmp = tmp_path_factory.mktemp("phase2")
    cfg = tmp / ".opik.config"
    cfg.write_text(f"[opik]\napi_key = {KEY}\nworkspace = joowww\n")
    os.chmod(cfg, 0o600)
    ledger_before = LEDGER.read_bytes()
    with pytest.MonkeyPatch.context() as mp:
        for target in ("socket.socket.connect", "urllib.request.urlopen", "subprocess.run"):
            mp.setattr(target, _refuse)
        mp.setattr(bridge, "CONFIG_PATH", cfg)
        mp.delenv("OPIK_API_KEY", raising=False)
        mp.delenv("OPIK_WORKSPACE", raising=False)
        summary = phase2.build(tmp / "out")
    out = tmp / "out"
    files = {p.name: p for p in out.iterdir()}
    load = lambda n: json.loads(files[n].read_text())  # noqa: E731
    return {"out": out, "summary": summary, "files": files, "load": load, "ledger_before": ledger_before}


# ------------------------------------------------------------------------- E07 is preserved --
def test_e07_is_excluded_untouched_and_still_verified(built):
    qwen = built["load"]("qwen_pending_10.dry_run.json")
    assert len(qwen["cases"]) == 10 and "E07" not in {c["case_id"] for c in qwen["cases"]}
    sent = json.dumps(qwen["batches"])
    assert E07 not in sent and E07_LLM_SPAN not in sent
    v1 = bridge.historical_plan(PILOT, cases={"E07"})
    assert {k: sha(d) for k, _, d in opik.send_requests(v1)} == E07_V1  # representation v1 is byte-identical
    assert LEDGER.read_bytes() == built["ledger_before"]
    ledger = json.loads(LEDGER.read_text())
    assert ledger["traces"][E07]["status"] == "VERIFIED_PRESENT"
    assert all(entry.get("authorization") for entry in ledger["traces"].values())  # nothing enters unauthorized


def test_the_e07_native_patch_is_prepared_only_and_never_resends(built):
    patch = built["load"]("e07_native_patch.dry_run.json")
    assert patch["method"] == "PATCH" and patch["path"] == f"/v1/private/spans/{E07_LLM_SPAN}"
    contract.span_update(patch["body"])
    assert patch["body"]["usage"] == {"prompt_tokens": 494, "completion_tokens": 134, "total_tokens": 628}
    assert "total_estimated_cost" not in patch["body"] and patch["body"]["provider"] == "ollama"
    ops = {o["id"]: o for o in built["load"]("pending_operations.json")["operations"]}
    assert ops["OP-3"]["status"] == "PREPARED_NOT_SENT"
    assert ops["OP-3"]["authorization_needed"].startswith("explicit") and ops["OP-3"]["body_sha256"]["body"] == \
        phase2.sha(phase2.compact(patch["body"]))


# ---------------------------------------------------------------- pending traces, exact hashes --
def test_prepared_batches_are_exact_and_reproducible(built):
    for name, cand, exclude in (("qwen_pending_10.dry_run.json", "qwen", {"E07"}), ("rules_baseline_11.dry_run.json",
                                                                                    "rules", set())):
        recorded = {b["kind"]: b["body_sha256"] for b in built["load"](name)["batches"]}
        again = bridge.historical_plan(PILOT, candidate_dir=cand, exclude=exclude, native_fields=True)
        assert {k: sha(d) for k, _, d in opik.send_requests(again)} == recorded
        for b in built["load"](name)["batches"]:
            assert b["bytes"] == len(json.dumps(b["body"], separators=(",", ":"), ensure_ascii=False).encode())
    for name, d in built["load"]("datasets.dry_run.json").items():  # canonical hashes survive a write/read cycle
        assert phase2.sha(phase2.compact(d["items"])) == d["items_sha256"], name
    fs = built["load"]("feedback_scores.dry_run.json")
    assert phase2.sha(phase2.compact(fs["body"])) == fs["body_sha256"]
    assert built["summary"]["qwen"] == [(k, v) for k, v in
                                        ((b["kind"], b["body_sha256"]) for b in built["load"]("qwen_pending_10.dry_run.json")["batches"])]


def test_per_case_table_has_every_field_and_reports_the_live_ledger(built):
    for name, n in (("qwen_pending_10.dry_run.json", 10), ("rules_baseline_11.dry_run.json", 11)):
        cases = built["load"](name)["cases"]
        assert len(cases) == n and len({c["trace_id"] for c in cases}) == n
        for c in cases:
            live = (json.loads(LEDGER.read_text())["traces"].get(c["trace_id"]) or {}).get("status", "NOT_IN_LEDGER")
            assert c["ledger"] == live != "VERIFIED_PRESENT" and not any(c["sensitive_scan"].values())
            assert c["dataset"] == "eval_v2@2" and c["spans"] == c["real_llm_spans"] + c["deterministic_spans"]
            assert len(c["traces_body_sha256"]) == len(c["spans_body_sha256"]) == 64


def test_real_llm_spans_carry_native_fields_and_rules_never_do(built):
    qwen = built["load"]("qwen_pending_10.dry_run.json")
    spans = [s for b in qwen["batches"] if b["kind"] == "spans" for s in b["body"]["spans"]]
    llm = [s for s in spans if s["type"] == "llm"]
    assert len(llm) == 10 and all(s["metadata"]["tfg_execution"] == "REAL_LLM_CALL" for s in llm)
    for s in llm:
        u = s["usage"]
        assert s["model"] == "qwen3:4b" and s["provider"] == "ollama"
        assert u["total_tokens"] == u["prompt_tokens"] + u["completion_tokens"]
        assert u == {**s["metadata"]["tfg_usage"], "total_tokens": u["total_tokens"]}  # same as the sealed record
    rest = [s for s in spans if s["type"] != "llm"]
    assert rest and not any("usage" in s or "model" in s or "provider" in s for s in rest)
    rules = built["load"]("rules_baseline_11.dry_run.json")
    rspans = [s for b in rules["batches"] if b["kind"] == "spans" for s in b["body"]["spans"]]
    rtraces = [t for b in rules["batches"] if b["kind"] == "traces" for t in b["body"]["traces"]]
    assert not any(s["type"] == "llm" or "usage" in s for s in rspans)
    assert all("DETERMINISTIC_BASELINE" in t["tags"] and t["metadata"]["tfg_comparison_group"] == "DETERMINISTIC_BASELINE"
               for t in rtraces)
    blob = json.dumps(qwen) + json.dumps(rules)
    assert "total_estimated_cost" not in blob


def test_per_case_tokens_match_the_sealed_report(built):
    rows = {r["case_id"]: r for r in json.loads((PILOT / "qwen/report.json").read_text())["rows"]}
    for c in built["load"]("qwen_pending_10.dry_run.json")["cases"]:
        assert c["case_pass"] == rows[c["case_id"]]["case_pass"] and c["safety_ok"] == rows[c["case_id"]]["safety_ok"]
        assert isinstance(c["tokens"]["prompt_tokens"], int) and isinstance(c["tokens"]["completion_tokens"], int)


# --------------------------------------------------------------------------- feedback scores --
def test_scores_only_carry_observed_values_in_their_scale(built):
    fs = built["load"]("feedback_scores.dry_run.json")
    contract.feedback_score_batch(fs["body"])
    obs = {(t["candidate"], t["case_id"]): t["observations"] for t in fs["observations"]}
    trace_case = {t["trace_id"]: (t["candidate"], t["case_id"]) for t in fs["observations"]}
    assert len(obs) == 22 and E07 in trace_case
    for item in fs["body"]["scores"]:
        o = obs[trace_case[item["id"]]][item["name"]]
        assert o["status"] == "OBSERVED" and o["value"] == item["value"] and item["source"] == "sdk"
        assert opik_metrics.METRICS[item["name"]]["kind"] == "SCORE" and math.isfinite(item["value"])
        if opik_metrics.METRICS[item["name"]]["type"] == "binary":
            assert item["value"] in (0, 1)
    scored = {(i["id"], i["name"]) for i in fs["body"]["scores"]}
    for (cand, case), o in obs.items():
        trace = next(t for t, v in trace_case.items() if v == (cand, case))
        for name, entry in o.items():
            if entry["status"] != "OBSERVED":
                assert (trace, name) not in scored  # missing never becomes 0
    assert fs["items"] == len(fs["body"]["scores"]) == built["summary"]["scores"]


def test_not_evaluated_and_not_applicable_are_kept_apart(built):
    fs = built["load"]("feedback_scores.dry_run.json")
    obs = {(t["candidate"], t["case_id"]): t["observations"] for t in fs["observations"]}
    rejected = [c for (cand, c), o in obs.items() if cand == "qwen" and o["schema_valid"]["value"] == 0]
    assert rejected and all(obs[("qwen", c)]["extraction_accuracy"]["status"] == "NOT_EVALUATED" for c in rejected)
    assert all(o["schema_valid"]["status"] == "NOT_APPLICABLE" for (cand, _), o in obs.items() if cand == "rules")
    assert all(o["estimated_cost"]["status"] == "NOT_APPLICABLE" for o in obs.values())
    assert all(o["agent_success"]["status"] == "NOT_APPLICABLE" for o in obs.values())


def test_an_infrastructure_failure_yields_no_score():
    row = {"outcome": "BLOCKED", "error_kind": "INFRASTRUCTURE"}
    obs = opik_metrics.observe(row, {"case_id": "X"}, [])
    assert {o["status"] for o in obs.values()} == {"INFRA_ERROR"}
    assert opik_metrics.score_items(E07, obs, project=bridge.PROJECT) == []


def test_every_metric_is_fully_described():
    fields = {"kind", "type", "range", "unit", "source", "rule", "applies_when", "not_evaluated", "level", "aggregation",
              "description"}
    for name, m in opik_metrics.METRICS.items():
        assert fields <= set(m), name
    assert opik_metrics.METRICS["unsafe_request_missed"]["kind"] == "DERIVED"


# ------------------------------------------------------------------- datasets and experiments --
def test_datasets_are_valid_and_carry_provenance(built):
    ds = built["load"]("datasets.dry_run.json")
    assert {k: v["items_count"] for k, v in ds.items()} == {"eval_v2": 33, "dev_v3": 14, "eval_v3": 26,
                                                             "adversarial_v3": 13}
    for name, d in ds.items():
        contract.dataset_write(d["dataset"])
        contract.dataset_items(d["items"])
        assert d["dataset"]["visibility"] == "private" and len(d["dataset"]["description"]) <= 255
        assert all(i["data"]["provenance"]["dataset_id"] == name for i in d["items"]["items"])
    assert ds["eval_v2"]["provenance"]["frozen"] == "FROZEN_MATCH" and ds["dev_v3"]["provenance"]["frozen"] == "NOT_FROZEN"


def test_experiments_link_dataset_items_to_the_prepared_traces(built):
    ex = built["load"]("experiments.dry_run.json")
    items = {i["id"]: i["data"]["case_id"] for i in built["load"]("datasets.dry_run.json")["eval_v2"]["items"]["items"]}
    qwen = {c["trace_id"]: c["case_id"] for c in built["load"]("qwen_pending_10.dry_run.json")["cases"]} | {E07: "E07"}
    rules = {c["trace_id"]: c["case_id"] for c in built["load"]("rules_baseline_11.dry_run.json")["cases"]}
    assert [b["experiment"]["name"] for b in ex["opik_bodies"]] == [
        "eval_v2@2 | ollama:qwen3:4b | interpret_brief/1 | pipeline v1 | pilot_v1",
        "eval_v2@2 | rules | no-prompt | pipeline v1 | pilot_v1"]
    for body, traces in zip(ex["opik_bodies"], (qwen, rules)):
        contract.experiment_write(body["experiment"])
        contract.experiment_items(body["items"])
        assert body["experiment"]["status"] == "completed" and body["experiment"]["dataset_name"] == "multiagent-eval_v2"
        for it in body["items"]["experiment_items"]:
            assert it["experiment_id"] == body["experiment"]["id"]
            assert items[it["dataset_item_id"]] == traces[it["trace_id"]]  # same case on both sides


def test_only_really_executed_experiments_get_opik_bodies(built):
    ex = built["load"]("experiments.dry_run.json")
    reg = {e["id"]: e for e in ex["registry"]}
    assert {e["comparison"] for e in ex["registry"]} == set("ABCDEF")
    assert [e["id"] for e in ex["registry"] if e["status"] == "EXECUTED_HISTORICAL"] == ["A1-qwen-local-pilot",
                                                                                         "A2-rules-pilot"]
    assert all(not e["status"].startswith("EXECUTED") or e["comparison"] in "AE" for e in ex["registry"])
    assert reg["F1-clef-classify"]["task"] == "CLASSIFY_REQUEST" and reg["F2-clef-select-allocation"]["task"] == "SELECT_ALLOCATION"
    for e in ex["registry"]:
        assert {"dataset", "model", "agent_role", "prompt", "generation", "seed", "repetitions", "metrics", "status",
                "provenance"} <= set(e)


# ------------------------------------------------------------------------------- dashboards --
def test_dashboards_validate_and_are_deterministic(built):
    d = built["load"]("dashboards.dry_run.json")
    assert d["bodies"] == opik_dashboard.dashboard_bodies()
    names = [b["name"] for b in d["bodies"]]
    assert names == [opik_dashboard.NAME, opik_dashboard.NAME_EXPERIMENTS]
    for b in d["bodies"]:
        contract.dashboard_write(b)
    in_bodies = {w["id"] for b in d["bodies"] for s in b["config"]["sections"] for w in s["widgets"]}
    api = {w["id"] for w in d["spec"] if w["automation"] == "API_CONFIG"}
    local = {w["id"] for w in d["spec"] if w["automation"] == "LOCAL_PREVIEW"}
    assert api == in_bodies and not (local & in_bodies) and len(d["spec"]) == len(api) + len(local)
    assert {w["section"] for w in d["spec"]} == set("ABCDEFG")
    for w in d["spec"]:
        assert all(w.get(k) not in (None, "") for k in ("metric", "source", "unit", "visualization", "sufficiency",
                                                         "limitations")), w["id"]


def test_contract_validators_refuse_bad_bodies():
    good = {"id": E07, "project_name": bridge.PROJECT, "name": "case_pass", "value": 1, "source": "sdk"}
    contract.feedback_score_batch({"scores": [good]})
    for bad in ({**good, "value": float("nan")}, {**good, "source": "api"}, {**good, "id": "x"},
                {k: v for k, v in good.items() if k != "name"}):
        with pytest.raises(contract.ContractError):
            contract.feedback_score_batch({"scores": [bad]})
    with pytest.raises(contract.ContractError):
        contract.dataset_write({"name": "x", "visibility": "public"})
    with pytest.raises(contract.ContractError):
        contract.experiment_write({"name": "x"})
    body = opik_dashboard.dashboard_bodies()[0]
    section = body["config"]["sections"][0]
    wide = json.loads(json.dumps(body))
    wide["config"]["sections"][0]["layout"][0]["w"] = 7
    with pytest.raises(contract.ContractError):
        contract.dashboard_write(wide)
    ollie = json.loads(json.dumps(body))
    ollie["config"]["sections"][0]["widgets"][0]["type"] = "ollie_chart"
    with pytest.raises(contract.ContractError):
        contract.dashboard_write(ollie)
    assert section["widgets"]


# ---------------------------------------------------- pending operations, secrets, seals, files --
def test_every_remote_operation_is_prepared_and_hashed(built):
    ops = built["load"]("pending_operations.json")
    assert ops["status"] == "NOTHING_SENT" and [o["id"] for o in ops["operations"]] == [f"OP-{i}" for i in range(1, 8)]
    assert all(o["status"] == "PREPARED_NOT_SENT" and o["authorization_needed"] for o in ops["operations"])
    first = ops["operations"][0]["body_sha256"]
    assert first == {b["kind"]: b["body_sha256"] for b in built["load"]("qwen_pending_10.dry_run.json")["batches"]}


def test_no_secret_path_or_key_value_in_any_file(built):
    for name, path in built["files"].items():
        data = path.read_bytes()
        assert KEY.encode() not in data, name
        assert not any(phase2.scan(data, KEY).values()), name


def test_manifest_matches_and_rebuild_is_byte_identical(built, tmp_path, monkeypatch):
    lines = (built["out"] / "SHA256SUMS").read_text().splitlines()
    assert len(lines) == len(built["files"]) - 1
    for line in lines:
        digest, name = line.split("  ./")
        assert sha((built["out"] / name).read_bytes()) == digest
    monkeypatch.setattr(bridge, "CONFIG_PATH", tmp_path / "absent")
    monkeypatch.delenv("OPIK_API_KEY", raising=False)
    phase2.build(tmp_path / "again")
    assert (tmp_path / "again/SHA256SUMS").read_text() == (built["out"] / "SHA256SUMS").read_text()
    with pytest.raises(SystemExit, match="not empty"):
        phase2.build(tmp_path / "again")


def test_sealed_results_are_intact(built):
    assert all(built["load"]("local_preview.json")["seals_intact"].values())
    bridge.verify_seal(PILOT)


def test_local_preview_flags_small_samples(built):
    p = built["load"]("local_preview.json")
    assert p["summary"]["qwen"]["n_cases"] == p["summary"]["rules"]["n_cases"] == 11
    assert any("11 cases" in w for w in p["warnings"])
    assert p["summary"]["rules"]["schema_valid"] == {"n": 0, "status": "NO_OBSERVATION"}
    lo, hi = p["summary"]["qwen"]["case_pass"]["wilson95"]
    assert lo <= p["summary"]["qwen"]["case_pass"]["mean"] <= hi


# ------------------------------------------------------------------- future instrumentation --
def _e07_records():
    return [json.loads(line) for line in (PILOT / "qwen/traces/E07.jsonl").read_text().splitlines()]


def test_live_tracing_native_fields_are_opt_in_and_real_calls_only():
    records = _e07_records()
    default = tracing.opik_plan(records, bridge.PROJECT, workspace=bridge.WORKSPACE)
    assert not any("usage" in s for s in default.spans)
    native = tracing.opik_plan(records, bridge.PROJECT, workspace=bridge.WORKSPACE, native_fields=True)
    llm = [s for s in native.spans if s["type"] == "llm"]
    assert len(llm) == 1 and llm[0]["usage"]["total_tokens"] == 628 and llm[0]["provider"] == "ollama"
    assert native.traces[0]["metadata"]["tfg_experiment_id"] == records[0]["experiment"]["experiment_id"]
    assert all("usage" not in s for s in native.spans if s["type"] != "llm")
    doubles = json.loads(json.dumps(records))
    for r in doubles:
        if r["kind"] == "llm":
            r["model_call"]["data_kind"] = "SYNTHETIC"
    simulated = tracing.opik_plan(doubles, bridge.PROJECT, native_fields=True)
    assert not any(s["type"] == "llm" or "usage" in s or "model" in s for s in simulated.spans)


def test_a_new_pilot_run_prepares_v2_traces_and_scores_offline(tmp_path, monkeypatch):
    from tests.test_multiagent_qwen_pilot import OK, Ollama, _gold_reply
    monkeypatch.delenv("TFG_OPIK_MODE", raising=False)
    result = pilot.run_pilot(tmp_path / "run", allow_model_calls=True, probes=OK, transport=Ollama(_gold_reply),
                             opik_mode="dry_run")
    assert result["opik"] == "DRY_RUN_WRITTEN_NOT_SENT"
    payload = json.loads((tmp_path / "run/opik/qwen.dry_run.json").read_text())
    assert payload["representation"] == "v2_native_fields"
    scores = payload["bodies"]["feedback_scores"]
    contract.feedback_score_batch(scores)
    assert scores["scores"] and all(s["reason"].startswith("run record: ") for s in scores["scores"])
    rules = json.loads((tmp_path / "run/opik/rules.dry_run.json").read_text())
    assert not any("usage" in s for body in rules["bodies"]["spans"] for s in body["spans"])
