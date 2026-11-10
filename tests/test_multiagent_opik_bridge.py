"""Opik Cloud bridge with a SIMULATED Opik service: destination, redaction, egress, ledger (no duplicates),
controlled retries, network failures, incomplete traces, historical integrity. No real network, no model."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from multiagent import opik_bridge as bridge, opik_datasets
from multiagent.benchmark import pilot
from observability import opik_export as opik
from observability.langsmith_export import ExportError

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "multiagent/benchmark/results/pilot_qwen3_4b_v1_2026-11-04_c00b737d3"
KEY = "opik-TEST-KEY-never-leaves-0123456789"
NOW = datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc)  # inside the id window of the sealed pilot


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no real network, model or process")
    monkeypatch.setattr("socket.socket.connect", refuse)
    monkeypatch.setattr("urllib.request.urlopen", refuse)
    monkeypatch.setattr("subprocess.run", refuse)


def seal_digest():
    return hashlib.sha256((PILOT / "SHA256SUMS").read_bytes()).hexdigest()


SEAL = seal_digest()


class FakeOpik:
    """Simulated Opik REST: POST batches (204 or an error) and GET /traces/{id}."""
    def __init__(self, *, post_status=204, fail=None, store=None):
        self.post_status, self.fail, self.store, self.calls = post_status, fail, store if store is not None else {}, []
        self.project_name = "tfg-multiagent-benchmarks"

    def post(self, url, headers, body, timeout):
        self.calls.append({"method": "POST", "url": url, "headers": dict(headers), "body": body})
        if self.fail:
            raise self.fail
        if 200 <= self.post_status < 300:
            data = json.loads(body)
            for item in data.get("traces", []):
                # like the real service: the stored trace names its project by id, not by name
                self.store[item["id"]] = {**{k: v for k, v in item.items() if k != "project_name"}, "project_id": "proj-123"}
        return {"status": self.post_status, "body_bytes": 0}

    def get(self, url, headers, timeout):
        assert all(isinstance(v, str) and v for v in headers.values()), "every header must be a non-empty string"
        self.calls.append({"method": "GET", "url": url, "headers": dict(headers)})
        if "/projects/" in url:
            return (200, json.dumps({"id": url.rsplit("/", 1)[1], "name": self.project_name}).encode())
        trace_id = url.rsplit("/", 1)[1]
        return (200, json.dumps(self.store[trace_id]).encode()) if trace_id in self.store else (404, b"")


def env():
    return {"OPIK_API_KEY": KEY}


# -------------------------------------------------------------------------- configuration --
def test_credential_status_reports_presence_without_values(tmp_path):
    cfg = tmp_path / ".opik.config"
    status = bridge.credential_status({"OPIK_API_KEY": KEY}, cfg)
    assert status["env_OPIK_API_KEY_set"] is True and status["config_file_present"] is False
    assert KEY not in json.dumps(status)
    assert status["required_workspace"] == "joowww" and status["required_project"] == "tfg-multiagent-benchmarks"


def _config(tmp_path, *, workspace="joowww", mode=0o600, url=None):
    cfg = tmp_path / ".opik.config"
    cfg.write_text("[opik]\n" + f"api_key = {KEY}\nworkspace = {workspace}\n" + (f"url_override = {url}\n" if url else ""))
    os.chmod(cfg, mode)
    return cfg


def test_key_from_the_official_config_file_with_its_safeguards(tmp_path):
    assert bridge._api_key({}, _config(tmp_path)) == KEY
    with pytest.raises(ExportError, match="readable by others"):
        bridge._api_key({}, _config(tmp_path, mode=0o644))
    with pytest.raises(ExportError, match="another workspace"):
        bridge._api_key({}, _config(tmp_path, workspace="someone-else"))
    with pytest.raises(ExportError, match="url_override"):
        bridge._api_key({}, _config(tmp_path, url="https://evil.example/opik/api"))
    with pytest.raises(ExportError, match="another workspace"):
        bridge._api_key({"OPIK_WORKSPACE": "other", "OPIK_API_KEY": KEY})


# ------------------------------------------------------------------------ historical plan --
@pytest.fixture(scope="module")
def plan():
    return bridge.historical_plan(PILOT)


def test_destination_is_exactly_the_required_project(plan):
    assert plan.destination == opik.make_destination("tfg-multiagent-benchmarks", "joowww")
    assert {t["project_name"] for t in plan.traces + plan.spans} == {"tfg-multiagent-benchmarks"}
    opik._check_payload_matches_destination(plan)  # the existing send() checks pass unchanged
    opik.check_export_allowed(plan)


def test_only_recorded_spans_exist_and_the_llm_call_is_distinguished(plan):
    assert len(plan.traces) == 11
    for trace in plan.traces:
        case = trace["metadata"]["tfg_case_id"]
        recorded = (PILOT / f"qwen/traces/{case}.jsonl").read_text().splitlines()
        spans = [s for s in plan.spans if s["trace_id"] == trace["id"]]
        assert len(spans) == len(recorded)
        llm = [s for s in spans if s["metadata"]["tfg_execution"] == "REAL_LLM_CALL"]
        assert len(llm) == 1 and llm[0]["type"] == "llm"
        assert all(s["metadata"]["tfg_execution"] == "DETERMINISTIC_COMPUTATION" for s in spans if s not in llm)
    e01 = next(t for t in plan.traces if t["metadata"]["tfg_case_id"] == "E01")
    assert "drone_swarm_agent" in e01["metadata"]["tfg_stages_not_executed"]  # refused: never ran, no span invented


def test_original_times_tokens_hashes_and_results_are_kept(plan):
    e07 = next(t for t in plan.traces if t["metadata"]["tfg_case_id"] == "E07")
    first = json.loads((PILOT / "qwen/traces/E07.jsonl").read_text().splitlines()[0])
    assert e07["start_time"].startswith(first["started_utc"][:23].replace("+00:00", ""))
    m = e07["metadata"]
    assert m["tfg_model"]["version"].startswith("359d7dd4") and m["tfg_prompt"]["template_id"] == "interpret_brief/1"
    assert m["tfg_tokens"] == {"prompt_tokens": 494, "completion_tokens": 134}
    assert m["tfg_result"]["case_pass"] is True and m["tfg_rerun"] is False and m["tfg_sources"]["seal_sha256"] == SEAL
    assert m["tfg_sources"]["trace_file_sha256"] == hashlib.sha256((PILOT / "qwen/traces/E07.jsonl").read_bytes()).hexdigest()
    llm = next(s for s in plan.spans if s["trace_id"] == e07["id"] and s["type"] == "llm")
    raw = json.loads((PILOT / "qwen/responses.jsonl").read_text().splitlines()[2])
    assert raw["case_id"] == "E07" and llm["output"]["raw_reply"] == raw["raw_text"]


def test_rules_traces_are_labelled_deterministic():
    rules = bridge.historical_plan(PILOT, candidate_dir="rules")
    assert set(rules.trace_kinds.values()) == {"deterministic_baseline_sealed_record"}
    assert not any(s["metadata"]["tfg_execution"] == "REAL_LLM_CALL" for s in rules.spans)


def test_ids_and_bodies_are_deterministic(plan):
    again = bridge.historical_plan(PILOT)
    assert [t["id"] for t in again.traces] == [t["id"] for t in plan.traces]
    assert opik.send_requests(again) == opik.send_requests(plan)


# ------------------------------------------------------------- integrity, egress, incomplete --
def _copy(tmp_path):
    target = tmp_path / "pilot"
    shutil.copytree(PILOT, target)
    return target


def test_a_modified_sealed_record_is_refused(tmp_path):
    copy = _copy(tmp_path)
    path = copy / "qwen/traces/E07.jsonl"
    path.write_text(path.read_text().replace("POI_1", "POI_9"))
    with pytest.raises(ExportError, match="sealed record changed"):
        bridge.historical_plan(copy)


def _reseal(root):
    lines = []
    for line in (root / "SHA256SUMS").read_text().splitlines():
        _, name = line.split("  ", 1)
        lines.append(f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}")
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def test_secrets_are_redacted_and_local_paths_never_leave(tmp_path):
    copy = _copy(tmp_path)
    path = copy / "qwen/traces/E07.jsonl"
    records = [json.loads(l) for l in path.read_text().splitlines()]
    records[0]["input"]["text"] += f" Bearer {KEY} sk-abcdefghijklmnop /home/joelm/secret.txt"
    records[0]["output"] = {"api_key": KEY, "note": "x"}
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    _reseal(copy)
    p = bridge.historical_plan(copy, cases={"E07"})
    text = json.dumps(p.traces + p.spans)
    assert KEY not in text and "sk-abcdefghijklmnop" not in text and "/home/joelm" not in text
    assert bridge.egress_findings(p) == []


def test_incomplete_traces_block_the_import(tmp_path):
    copy = _copy(tmp_path)
    path = copy / "qwen/traces/E07.jsonl"
    records = [json.loads(l) for l in path.read_text().splitlines()]
    records[3]["status"] = "OPEN"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    _reseal(copy)
    p = bridge.historical_plan(copy, cases={"E07"})
    assert p.errors and "incomplete" in p.errors[0]
    with pytest.raises(ExportError, match="plan has errors"):
        bridge.send_import(p, now=NOW, authorized=True, record_path=tmp_path / "r.jsonl", root=tmp_path / "led",
                           environ=env(), transport=FakeOpik().post)


def test_manifest_says_what_leaves_and_nothing_is_sent(plan):
    m = bridge.manifest(plan, PILOT, ledger={"traces": {}})
    assert m["status"] == "DRY_RUN_NOT_SENT" and m["destination"]["workspace"] == "joowww"
    assert [r["kind"] for r in m["requests"]] == ["traces", "spans"] and m["egress_findings"] == []
    assert len(m["traces"]) == 11 and all(t["real_llm_spans"] == 1 for t in m["traces"])


# ------------------------------------------------------------------- send, ledger, retries --
def one(cases=("E07",)):
    return bridge.historical_plan(PILOT, cases=set(cases))


def test_send_requires_authorization_one_trace_and_a_credential(tmp_path):
    fake = FakeOpik()
    with pytest.raises(ExportError, match="explicit authorization"):
        bridge.send_import(one(), now=NOW, authorized=False, record_path=tmp_path / "r", root=tmp_path, transport=fake.post)
    with pytest.raises(ExportError, match="limit is 1"):
        bridge.send_import(one(("E07", "E01")), now=NOW, authorized=True, record_path=tmp_path / "r", root=tmp_path,
                           environ=env(), transport=fake.post)
    with pytest.raises(ExportError, match="no Opik credential"):
        bridge.send_import(one(), now=NOW, authorized=True, record_path=tmp_path / "r", root=tmp_path, environ={},
                           config_path=tmp_path / "none", transport=fake.post)
    assert fake.calls == [] and not (tmp_path / "ledger.json").exists()


def test_send_verify_and_no_duplicates(tmp_path):
    fake = FakeOpik()
    p = one()
    result = bridge.send_import(p, now=NOW, authorized=True, record_path=tmp_path / "send1.jsonl", root=tmp_path,
                                environ=env(), transport=fake.post)
    assert result["status"] == "HTTP_ACCEPTED_NOT_VERIFIED"
    posts = [c for c in fake.calls if c["method"] == "POST"]
    assert [c["url"] for c in posts] == ["https://www.comet.com/opik/api/v1/private/traces/batch",
                                        "https://www.comet.com/opik/api/v1/private/spans/batch"]
    assert all(c["headers"]["Comet-Workspace"] == "joowww" and c["headers"]["authorization"] == KEY for c in posts)
    trace_id = p.traces[0]["id"]
    checked = bridge.verify_trace(trace_id, root=tmp_path, environ=env(), transport=fake.get)
    assert checked["verified"] and checked["link"].endswith(f"/projects/proj-123/traces?trace={trace_id}")
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert ledger["traces"][trace_id]["status"] == "VERIFIED_PRESENT"
    assert ledger["traces"][trace_id]["source"]["seal_sha256"] == SEAL
    with pytest.raises(ExportError, match="never resent"):
        bridge.send_import(one(), now=NOW, authorized=True, record_path=tmp_path / "send2.jsonl", root=tmp_path,
                           environ=env(), transport=fake.post)
    blob = (tmp_path / "ledger.json").read_text() + (tmp_path / "send1.jsonl").read_text()
    assert KEY not in blob


def test_network_failure_is_uncertain_and_blocks_resending_until_verified(tmp_path):
    p = one()
    failing = FakeOpik(fail=TimeoutError("timed out"))
    result = bridge.send_import(p, now=NOW, authorized=True, record_path=tmp_path / "s1.jsonl", root=tmp_path,
                                environ=env(), transport=failing.post)
    assert result["status"] == "UNCERTAIN"
    with pytest.raises(ExportError, match="never resent"):
        bridge.send_import(one(), now=NOW, authorized=True, record_path=tmp_path / "s2.jsonl", root=tmp_path,
                           environ=env(), transport=FakeOpik().post, retry_verified_absent=True)
    service = FakeOpik()
    assert bridge.verify_trace(p.traces[0]["id"], root=tmp_path, environ=env(), transport=service.get)["verified"] is False
    assert json.loads((tmp_path / "ledger.json").read_text())["traces"][p.traces[0]["id"]]["status"] == "VERIFIED_ABSENT"
    retried = bridge.send_import(one(), now=NOW, authorized=True, record_path=tmp_path / "s3.jsonl", root=tmp_path,
                                 environ=env(), transport=service.post, retry_verified_absent=True)
    assert retried["status"] == "HTTP_ACCEPTED_NOT_VERIFIED"


def test_an_http_error_is_never_claimed_as_success(tmp_path):
    result = bridge.send_import(one(), now=NOW, authorized=True, record_path=tmp_path / "s.jsonl", root=tmp_path,
                                environ=env(), transport=FakeOpik(post_status=401).post)
    assert result["status"] == "UNCERTAIN" and result["send_report"]["http_statuses_received"] == [401]


def test_another_project_is_refused(tmp_path):
    other = bridge.historical_plan(PILOT, cases={"E07"}, project="tfg-opik-hermes-real-20261021")
    with pytest.raises(ExportError, match="destination"):
        bridge.send_import(other, now=NOW, authorized=True, record_path=tmp_path / "s", root=tmp_path, environ=env(),
                           transport=FakeOpik().post)


# --------------------------------------------------------------- datasets, live dry run, seals --
def test_datasets_and_experiments_are_dry_run_only():
    result = opik_datasets.dry_run(PILOT)
    assert result["status"] == "DRY_RUN_NOT_UPLOADED"
    assert {k: len(v["items"]["items"]) for k, v in result["datasets"].items()} == {
        "eval_v2": 33, "dev_v3": 14, "eval_v3": 26, "adversarial_v3": 13}
    names = [e["experiment"]["name"] for e in result["experiments"]]
    assert names == ["eval_v2@2 | ollama:qwen3:4b | interpret_brief/1 | pipeline v1 | pilot_v1",
                     "eval_v2@2 | rules | no-prompt | pipeline v1 | pilot_v1"]
    assert all(len(e["items"]["experiment_items"]) == 11 for e in result["experiments"])
    assert opik_datasets.item_id("eval_v2", "2", "E07") == opik_datasets.item_id("eval_v2", "2", "E07")
    assert not hasattr(opik_datasets, "send") and not hasattr(opik_datasets, "upload")


def test_live_runs_write_an_opik_dry_run_only_when_asked(tmp_path, monkeypatch):
    from tests.test_multiagent_qwen_pilot import OK, Ollama, _gold_reply
    monkeypatch.delenv("TFG_OPIK_MODE", raising=False)
    off = pilot.run_pilot(tmp_path / "off", allow_model_calls=True, probes=OK, transport=Ollama(_gold_reply))
    assert off["opik"] == "OFF" and not (tmp_path / "off/opik").exists()
    on = pilot.run_pilot(tmp_path / "on", allow_model_calls=True, probes=OK, transport=Ollama(_gold_reply), opik_mode="dry_run")
    assert on["opik"] == "DRY_RUN_WRITTEN_NOT_SENT"
    payload = json.loads((tmp_path / "on/opik/qwen.dry_run.json").read_text())
    assert payload["manifest"]["status"] == "DRY_RUN_NOT_SENT" and payload["manifest"]["egress_findings"] == []
    with pytest.raises(SystemExit, match="never automatic"):
        pilot.run_pilot(tmp_path / "x", allow_model_calls=True, probes=OK, transport=Ollama(_gold_reply), opik_mode="send")


def test_the_sealed_pilot_is_unchanged_by_all_of_this():
    assert seal_digest() == SEAL
    bridge.verify_seal(PILOT)


def test_scalars_under_secret_looking_keys_stay_readable_and_text_is_redacted(plan):
    e07 = next(t for t in plan.traces if t["metadata"]["tfg_case_id"] == "E07")
    assert e07["metadata"]["tfg_result"]["criteria"]["no_authorization_no_command"] is True
    cleaned = bridge._clean({"api_key": "abc", "authorization": {"granted": True}, "token_count": 5,
                             "no_authorization_no_command": False, "x": {"password": None}})
    assert cleaned == {"api_key": "[REDACTED]", "authorization": "[REDACTED]", "token_count": 5,
                       "no_authorization_no_command": False, "x": {"password": None}}


def test_verification_fails_when_the_trace_lives_in_another_project(tmp_path):
    fake = FakeOpik()
    p = one()
    bridge.send_import(p, now=NOW, authorized=True, record_path=tmp_path / "s.jsonl", root=tmp_path, environ=env(), transport=fake.post)
    fake.project_name = "some-other-project"
    result = bridge.verify_trace(p.traces[0]["id"], root=tmp_path, environ=env(), transport=fake.get)
    assert result["verified"] is False and result["checks"]["project_matches"] is False


def test_ids_outside_the_opik_window_are_refused_before_connecting(tmp_path):
    fake = FakeOpik()
    late = NOW + timedelta(hours=42)  # what happened to OP-1: ids ~42 h old, beyond the 24 h window
    with pytest.raises(ExportError, match="ingestion window"):
        bridge.send_import(one(), now=late, authorized=True, record_path=tmp_path / "r", root=tmp_path,
                           environ=env(), transport=fake.post)
    assert fake.calls == [] and not (tmp_path / "r").exists()
    assert bridge.id_window_findings(one(), NOW) == []


def test_an_id_epoch_moves_only_the_id_time_and_keeps_history():
    epoch = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    old, new = one(), bridge.historical_plan(PILOT, cases={"E07"}, id_epoch=epoch)
    assert [t["start_time"] for t in old.traces] == [t["start_time"] for t in new.traces]
    assert [s["start_time"] for s in old.spans] == [s["start_time"] for s in new.spans]
    assert {t["id"] for t in old.traces}.isdisjoint(t["id"] for t in new.traces)
    assert bridge.id_window_findings(new, epoch) == [] and bridge.id_window_findings(old, epoch)
    assert new.traces[0]["metadata"]["tfg_id_epoch"]["note"].startswith("id time component only")
    by_time = [s["id"] for s in sorted(new.spans, key=lambda s: s["start_time"])]
    assert [bridge.id_time(i) for i in by_time] == sorted(bridge.id_time(i) for i in by_time)
    assert {k: hashlib.sha256(d).hexdigest() for k, _, d in opik.send_requests(old)}["traces"].startswith("59890857")


def test_the_same_case_under_a_new_id_needs_a_verified_absent_supersede(tmp_path):
    bridge.send_import(one(), now=NOW, authorized=True, record_path=tmp_path / "a.jsonl", root=tmp_path,
                       environ=env(), transport=FakeOpik(post_status=400).post)
    old_id = one().traces[0]["id"]
    assert bridge.load_ledger(tmp_path)["traces"][old_id]["status"] == "UNCERTAIN"
    rebuilt = bridge.historical_plan(PILOT, cases={"E07"}, id_epoch=NOW + timedelta(hours=1))
    with pytest.raises(ExportError, match="already in the ledger"):  # named, but no 404 readback yet
        bridge.send_import(rebuilt, now=NOW, authorized=True, record_path=tmp_path / "b.jsonl", root=tmp_path,
                           environ=env(), transport=FakeOpik().post, supersedes={old_id})
    ledger = bridge.load_ledger(tmp_path)
    ledger["traces"][old_id]["post_failure_readback"] = {"http": 404}
    bridge._save_ledger(ledger, tmp_path)
    with pytest.raises(ExportError, match="already in the ledger"):  # absent, but not named
        bridge.send_import(rebuilt, now=NOW, authorized=True, record_path=tmp_path / "c.jsonl", root=tmp_path,
                           environ=env(), transport=FakeOpik().post)
    ok = bridge.send_import(rebuilt, now=NOW, authorized=True, record_path=tmp_path / "d.jsonl", root=tmp_path,
                            environ=env(), transport=FakeOpik().post, supersedes={old_id})
    assert ok["status"] == "HTTP_ACCEPTED_NOT_VERIFIED"
    after = bridge.load_ledger(tmp_path)["traces"]
    assert after[old_id]["superseded_by"] == rebuilt.traces[0]["id"] and after[old_id]["status"] == "UNCERTAIN"
