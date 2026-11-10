"""OP-1 after the fact, offline: the rejected ids are refused before connecting, OP-1b only re-stamps the id time,
the ledger keeps E07 and the ten rejected ids as they are, and nothing here can reach the network."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from multiagent import opik_bridge as bridge, opik_op1 as op1
from observability import opik_export as opik

EPOCH = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def refuse(*a, **k):
        raise AssertionError("no real network")
    monkeypatch.setattr("socket.socket.connect", refuse)
    monkeypatch.setattr("urllib.request.urlopen", refuse)
    monkeypatch.setattr(bridge, "CONFIG_PATH", tmp_path / "absent")
    monkeypatch.delenv("OPIK_API_KEY", raising=False)


def test_the_original_op1_cannot_pass_its_preflight_again():
    r = op1.preflight(remote=False, now=EPOCH)
    failed = {k for k, v in r["checks"].items() if not v["passed"]}
    assert not r["passed"] and failed == {"id_window", "not_in_ledger"}
    assert r["checks"]["hashes"]["passed"]  # the same authorized bytes: it is the clock, not the content


def test_op1b_changes_only_ids_and_declares_the_shift():
    old, new = op1.plan(), op1.plan(EPOCH)
    assert [t["metadata"]["tfg_case_id"] for t in old.traces] == [t["metadata"]["tfg_case_id"] for t in new.traces]
    strip = lambda x: {k: v for k, v in x.items() if k not in ("id", "trace_id", "parent_span_id", "metadata")}  # noqa: E731
    assert [strip(t) for t in old.traces] == [strip(t) for t in new.traces]
    assert [strip(s) for s in old.spans] == [strip(s) for s in new.spans]
    for a, b in zip(old.traces, new.traces):
        extra = {k: v for k, v in b["metadata"].items() if k not in a["metadata"]}
        assert set(extra) == {"tfg_id_epoch", "_import_id"} and {k: b["metadata"][k] for k in a["metadata"]} == a["metadata"]
    assert bridge.id_window_findings(new, EPOCH) == [] and bridge.id_window_findings(new, EPOCH + timedelta(hours=24))
    opik._check_payload_matches_destination(new)  # declared shifts pass the exporter's own id derivation check


def test_op1b_preflight_passes_except_the_unauthorized_hashes():
    r = op1.preflight(remote=False, id_epoch=EPOCH, authorized={"traces": "not-yet", "spans": "not-yet"}, now=EPOCH)
    failed = {k for k, v in r["checks"].items() if not v["passed"]}
    assert failed == {"hashes"}
    assert set(r["checks"]["not_in_ledger"]["detail"]["supersedes"]) == set(op1.original_ids().values())


def test_prepare_writes_bodies_whose_hashes_rebuild(tmp_path):
    summary = op1.prepare(EPOCH, tmp_path / "op1b")
    data = json.loads((tmp_path / "op1b/op1b.dry_run.json").read_text())
    assert data["operation"].startswith("OP-1b (PREPARED, NOT AUTHORIZED, NOT SENT)")
    for kind in ("traces", "spans"):
        assert op1.sha(opik.body_bytes(data["bodies"][kind])) == summary["body_sha256"][kind]
    assert {c["supersedes"] for c in data["cases"]} == set(op1.original_ids().values())
    assert all(c["start_time"] < c["id_time"] for c in data["cases"])
    with pytest.raises(SystemExit, match="not empty"):
        op1.prepare(EPOCH, tmp_path / "op1b")


def test_the_cli_never_resends_the_rejected_ids_and_needs_hashes_for_op1b():
    with pytest.raises(SystemExit, match="can never be"):
        op1.main(["send", "--i-authorize-op1"])
    with pytest.raises(SystemExit, match="needs --i-authorize-op1b"):
        op1.main(["send", "--id-epoch", EPOCH.isoformat()])


def test_the_ledger_records_the_failed_attempt_honestly():
    ledger = json.loads((bridge.IMPORTS / "ledger.json").read_text())["traces"]
    assert ledger[op1.E07]["status"] == "VERIFIED_PRESENT"
    for case, tid in op1.original_ids().items():
        e = ledger[tid]
        assert e["case_id"] == case and e["status"] == "UNCERTAIN" and e["http_statuses"] == [400]
        assert e["post_failure_readback"]["http"] == 404 and e["authorization"]["operation"] == "OP-1"
        assert e["diagnosis"]["status"].startswith("INFERRED_NOT_CONFIRMED")
    sums = (bridge.IMPORTS / "op1_2026-11-06/SHA256SUMS").read_text().splitlines()
    for line in sums:
        digest, name = line.split("  ./")
        assert op1.sha((bridge.IMPORTS / "op1_2026-11-06" / name).read_bytes()) == digest


# --------------------------------------------------------------------------------------- OP-1b --
def test_the_content_hash_is_independent_of_the_ids():
    a, b = op1.plan(), op1.plan(EPOCH)
    c = op1.plan(EPOCH + timedelta(hours=7))
    assert bridge.content_sha256(a) == bridge.content_sha256(b) == bridge.content_sha256(c)
    assert {t["id"] for t in b.traces}.isdisjoint(t["id"] for t in c.traces)
    m = json.loads((op1.OP1B_DIR / "manifest.json").read_text())
    assert m["content_sha256"] == bridge.content_sha256(a) and m["status"] == "PREPARED_NOT_AUTHORIZED"
    assert m["totals"] == {"traces": 10, "spans": 62, "real_llm_spans": 10}
    assert [x["case_id"] for x in m["cases"]] == list(op1.CASES) and "E07" in m["source"]["excluded"]


def test_restamping_keeps_times_hierarchy_and_original_ids():
    old, new = op1.plan(), op1.plan(EPOCH)
    mapping = {x["original_id"]: x["import_id"] for x in bridge.id_mapping(old, new)}
    assert len(mapping) == 72 and None not in mapping
    for o, n in zip(old.spans, new.spans):
        assert n["start_time"] == o["start_time"] and n["end_time"] == o["end_time"]
        assert n["trace_id"] == mapping[o["trace_id"]] and n["metadata"]["_import_id"] == o["id"]
        if o.get("parent_span_id"):
            assert n["parent_span_id"] == mapping[o["parent_span_id"]]
    for o, n in zip(old.traces, new.traces):
        assert n["metadata"]["_import_id"] == o["id"] and n["start_time"] == o["start_time"]
        assert n["metadata"]["tfg_import"] == "HISTORICAL_SEALED_RECORD"  # still a historical import, not a new run


def test_old_new_and_invalid_uuids():
    assert bridge.import_id_findings(op1.plan(), EPOCH)  # rejected OP-1 ids are too old
    assert bridge.import_id_findings(op1.plan(EPOCH), EPOCH) == []
    bad = op1.plan(EPOCH)
    bad.traces[0]["id"] = "not-a-uuid"
    bad.spans[0]["id"] = "01a1a76e-42f9-42ce-8408-9907fcd429f3"  # version 4
    bad.spans[1]["parent_span_id"] = "01a1b53c-0000-7000-8000-000000000000"
    found = " ".join(bridge.import_id_findings(bad, EPOCH))
    assert "not a canonical UUIDv7" in found and "outside the plan" in found


def test_prepare_refuses_changed_content_and_writes_mapping(tmp_path, monkeypatch):
    out = op1.prepare(EPOCH, tmp_path / "p")
    data = json.loads((tmp_path / "p/op1b.dry_run.json").read_text())
    assert data["content_sha256"] == bridge.content_sha256(op1.plan()) and len(data["id_mapping"]) == 72
    assert out["body_sha256"]["traces"] != "0ce48bc0133542083f9ec9b7e8066bc0c32129d6db3c49f542c3fc526a058b00"
    real = op1.plan

    def tampered(epoch=None):
        p = real(epoch)
        p.traces[0]["metadata"]["tfg_case_id"] = "E99"
        return p
    monkeypatch.setattr(op1, "plan", tampered)
    with pytest.raises(SystemExit, match="content differs"):
        op1.prepare(EPOCH, tmp_path / "q")


def test_the_ledger_tells_the_rejected_attempt_from_a_future_import():
    ledger = json.loads((bridge.IMPORTS / "ledger.json").read_text())["traces"]
    for tid in op1.original_ids().values():
        assert ledger[tid]["import_generation"] == 1 and ledger[tid]["attempt_outcome"] == "REJECTED_HTTP_400_READ_BACK_404"
        assert ledger[tid]["status"] == "UNCERTAIN"
    assert "import_generation" not in ledger[op1.E07] and ledger[op1.E07]["status"] == "VERIFIED_PRESENT"
