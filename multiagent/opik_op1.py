"""OP-1: the ONE authorized historical import of the 10 pending qwen3:4b pilot traces (E07 excluded).

Authorization (Joel, 2026-11-06): only OP-1, to joowww/tfg-multiagent-benchmarks, with
  traces/batch sha256 0ce48bc0133542083f9ec9b7e8066bc0c32129d6db3c49f542c3fc526a058b00
  spans/batch  sha256 5399a70196a26f490795a36495de66aea69ca3d24c8eb70b8132d8210bb1e92a
conditional on every integrity and privacy check passing. One attempt per batch, no automatic retry; each trace is
then verified individually with read-only GETs. OP-2..OP-7 and any change to E07 are NOT covered.

    python -m multiagent.opik_op1 preflight --out <file>     # read-only (local checks + 3 kinds of GET)
    python -m multiagent.opik_op1 send --i-authorize-op1      # preflight again, then the single send
    python -m multiagent.opik_op1 verify --out <file>         # per-trace readback, ledger update

OUTCOME (2026-11-06T10:30Z): traces/batch answered HTTP 400, spans/batch not attempted, all 10 ids read back 404.
Inferred cause: the ids embed the historical 2026-11-04T16:4xZ and Opik rejects UUIDv7 ids older than its 24 h
window. The original ids can never be accepted again. OP-1b (NOT authorized, NOT sent) re-stamps only the id time:

    python -m multiagent.opik_op1 prepare --id-epoch <ISO UTC, within 23 h of the planned send> --out <dir>
    # Joel authorizes the printed hashes; then, inside the window:
    python -m multiagent.opik_op1 send --i-authorize-op1b --id-epoch <same ISO> --traces-sha <h> --spans-sha <h>
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.parse

from observability import opik_export as opik

from multiagent import opik_bridge as bridge, opik_phase2 as phase2

PILOT = phase2.PILOT
PROJECT_ID = "01a1a77c-fb97-72f1-b2d7-376183ac994b"
E07 = "01a1a76e-e360-7b24-9ca0-f4088fe20e36"
AUTHORIZED = {"traces": "0ce48bc0133542083f9ec9b7e8066bc0c32129d6db3c49f542c3fc526a058b00",
              "spans": "5399a70196a26f490795a36495de66aea69ca3d24c8eb70b8132d8210bb1e92a"}
CASES = ("E01", "E04", "E11", "E12", "E18", "E19", "E20", "E21", "E22", "E27")
PHASE2_FILE = bridge.IMPORTS / "phase2_2026-11-04_cd1c772b0/qwen_pending_10.dry_run.json"
TRACE_KEYS = {"id", "project_name", "name", "start_time", "end_time", "input", "output", "metadata", "tags"}
SPAN_KEYS = {"id", "trace_id", "project_name", "type", "name", "start_time", "end_time", "input", "output", "metadata",
             "tags", "parent_span_id", "error_info", "model", "provider", "usage"}
EXTRA_PRIVATE = {"private ip": re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}"),
                 "home dir": re.compile(r"~/|\\\\Users\\\\|C:\\\\"), "ssh/key material": re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
                 "opik config": re.compile(r"\.opik\.config|api_key\s*=")}
AUTHORIZATION = {"by": "Joel", "at": "2026-11-06", "operation": "OP-1",
                 "scope": "only the 10 pending qwen3:4b pilot traces (E01 E04 E11 E12 E18 E19 E20 E21 E22 E27), E07 excluded",
                 "authorized_sha256": AUTHORIZED, "max_traces": 10, "attempts": "one per batch, no automatic retry",
                 "not_authorized": "OP-2..OP-7, any change to E07, other traces, projects or workspaces"}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def plan(id_epoch=None):
    return bridge.historical_plan(PILOT, candidate_dir="qwen", exclude={"E07"}, native_fields=True, id_epoch=id_epoch)


def original_ids() -> dict:
    """case -> the OP-1 trace id rejected on 2026-11-06 (no id_epoch)."""
    return {t["metadata"]["tfg_case_id"]: t["id"] for t in plan().traces}


def local_checks(p, *, authorized=AUTHORIZED, supersede=False, now=None) -> dict:
    """Everything that can be checked without the network. Each entry is (passed, detail).
    ``supersede``: OP-1b, the cases are in the ledger under their rejected OP-1 ids, which must read back 404."""
    c = {}
    c["seal"] = (bridge.verify_seal(PILOT) is not None and
                 sha((PILOT / "SHA256SUMS").read_bytes()) == "a843976e24f485b886521318d1365f81b6bf27d4309e0361dd703d843fdfa679",
                 "pilot SHA256SUMS verified and equal to the sealed digest")
    requests = opik.send_requests(p)
    got = {k: sha(d) for k, _, d in requests}
    c["hashes"] = (got == authorized and [k for k, _, _ in requests] == ["traces", "spans"], got)
    outside = bridge.id_window_findings(p, now)
    c["id_window"] = (not outside, outside[:3] or "every id within the Opik window (24 h, 1 h margin)")
    c["destination"] = (p.destination == opik.make_destination(bridge.PROJECT, bridge.WORKSPACE) and
                        all(t["project_name"] == bridge.PROJECT for t in p.traces) and
                        all(s["project_name"] == bridge.PROJECT for s in p.spans), p.destination["key"])
    cases = [t["metadata"]["tfg_case_id"] for t in p.traces]
    c["cases"] = (sorted(cases) == sorted(CASES) and len(p.traces) == 10, cases)
    ids = {t["id"] for t in p.traces}
    c["e07_excluded"] = (E07 not in ids and "E07" not in cases and
                         not any(s["trace_id"] == E07 for s in p.spans), "no E07 trace or span")
    prepared = {x["case_id"]: x for x in json.loads(PHASE2_FILE.read_text())["cases"]}
    per = {}
    for t in p.traces:
        case = t["metadata"]["tfg_case_id"]
        spans = [s for s in p.spans if s["trace_id"] == t["id"]]
        records = (PILOT / "qwen/traces" / f"{case}.jsonl").read_text().splitlines()
        single = {k: sha(d) for k, _, d in opik.send_requests(bridge.subset(p, {t["id"]}))}
        src = t["metadata"]["tfg_sources"]
        per[case] = {"trace_id": t["id"], "spans": len(spans), "sealed_records": len(records),
                     "llm_spans": sum(s["type"] == "llm" for s in spans),
                     "matches_phase2_table": prepared[case]["spans"] == len(spans) and (supersede or (
                         prepared[case]["trace_id"] == t["id"] and prepared[case]["traces_body_sha256"] == single["traces"]
                         and prepared[case]["spans_body_sha256"] == single["spans"])),
                     "trace_file_sha256_matches": sha((PILOT / "qwen/traces" / f"{case}.jsonl").read_bytes()) == src.get("trace_file_sha256"),
                     "span_ids": sorted(s["id"] for s in spans)}
    c["correspondence"] = (all(v["spans"] == v["sealed_records"] and v["llm_spans"] == 1 and v["matches_phase2_table"]
                               and v["trace_file_sha256_matches"] for v in per.values()), per)
    ledger = bridge.load_ledger()
    sent_spans = set()
    for entry in ledger["traces"].values():
        sent_spans |= set((entry.get("readback") or {}).get("span_ids") or [])
    e07_ok = ledger["traces"][E07]["status"] == "VERIFIED_PRESENT"
    if not supersede:
        c["not_in_ledger"] = (not (ids & set(ledger["traces"])) and set(ledger["traces"]) == {E07} and e07_ok,
                              sorted(ledger["traces"]))
    else:
        old = original_ids()
        olds = [ledger["traces"].get(old[x]) or {} for x in CASES]
        c["not_in_ledger"] = (not (ids & set(ledger["traces"])) and e07_ok and all(
            o.get("status") == "UNCERTAIN" and (o.get("post_failure_readback") or {}).get("http") == 404
            and not o.get("superseded_by") for o in olds),
            {"new_ids_in_ledger": sorted(ids & set(ledger["traces"])), "supersedes": sorted(old.values())})
    c["egress"] = (bridge.egress_findings(p) == [], bridge.egress_findings(p))
    blob = b"".join(d for _, _, d in requests)
    text = blob.decode("utf-8")
    try:
        key = bridge._api_key(config_path=bridge.CONFIG_PATH)
    except opik.ExportError:
        key = None
    found = phase2.scan(blob, key)
    found.update({k: bool(r.search(text)) for k, r in EXTRA_PRIVATE.items()})
    key = None
    c["privacy"] = (not any(found.values()), found)
    bad_keys = sorted({k for t in p.traces for k in t if k not in TRACE_KEYS} |
                      {k for s in p.spans for k in s if k not in SPAN_KEYS})
    executions = sorted({s["metadata"].get("tfg_execution") for s in p.spans})
    llm = [s for s in p.spans if s["type"] == "llm"]
    c["content"] = (not bad_keys and {s["type"] for s in p.spans} <= {"llm", "general", "tool"}
                    and all(s["metadata"]["tfg_execution"] == "REAL_LLM_CALL" and s["model"] == "qwen3:4b"
                            and s["provider"] == "ollama" for s in llm)
                    and all("usage" not in s and "model" not in s for s in p.spans if s["type"] != "llm")
                    and "total_estimated_cost" not in text
                    and all(t["metadata"]["tfg_import"] == "HISTORICAL_SEALED_RECORD" for t in p.traces)
                    and all(t["metadata"]["tfg_data_kind"] == "real_model_output_sealed_record" for t in p.traces),
                    {"unexpected_keys": bad_keys, "executions": executions, "span_types": sorted({s["type"] for s in p.spans}),
                     "llm_spans": len(llm), "total_spans": len(p.spans)})
    return c


def _headers():
    key = bridge._api_key(config_path=bridge.CONFIG_PATH)
    if not key:
        raise SystemExit("no Opik credential")
    return key, {"authorization": key, "Comet-Workspace": bridge.WORKSPACE, "accept": "application/json"}


def _get(path, key, headers):
    status, raw = bridge.get_transport(bridge.ENDPOINT + path, headers, 30.0)
    text = raw.decode("utf-8", "replace") if raw else ""
    return status, (json.loads(raw) if status == 200 and raw else None), (key in text if text else False)


def remote_checks(p, *, supersede=False) -> dict:
    """Read-only: the destination project exists with the right name, and none of the 10 traces is there yet
    (with ``supersede``, neither the new ids nor the rejected OP-1 ids)."""
    key, headers = _headers()
    c = {}
    s, project, leak = _get(f"/v1/private/projects/{PROJECT_ID}", key, headers)
    c["project"] = (s == 200 and (project or {}).get("name") == bridge.PROJECT and not leak,
                    {"http": s, "name": (project or {}).get("name"), "id": PROJECT_ID})
    absent = {}
    for t in p.traces:
        st, _, lk = _get(f"/v1/private/traces/{t['id']}", key, headers)
        absent[t["metadata"]["tfg_case_id"]] = st
    if supersede:
        for case, old in original_ids().items():
            st, _, lk = _get(f"/v1/private/traces/{old}", key, headers)
            absent[f"{case} (rejected OP-1 id)"] = st
    key = headers = None
    c["traces_absent_remotely"] = (set(absent.values()) == {404}, absent)
    return c


def preflight(*, remote=True, id_epoch=None, authorized=AUTHORIZED, now=None) -> dict:
    p = plan(id_epoch)
    supersede = id_epoch is not None
    checks = local_checks(p, authorized=authorized, supersede=supersede, now=now)
    if remote:
        checks.update(remote_checks(p, supersede=supersede))
    return {"at_utc": datetime.now(timezone.utc).isoformat(), "passed": all(v[0] for v in checks.values()),
            "checks": {k: {"passed": bool(v[0]), "detail": v[1]} for k, v in checks.items()}}


OP1B_DIR = bridge.IMPORTS / "op1b_2026-11-06"


def op1b_manifest() -> dict:
    """What OP-1b would import, independent of the final ids: cases, original (rejected) ids, span counts, the
    canonical id-independent content hashes, the id rule and what the import must keep. Valid until the sealed
    pilot changes (it cannot: it is sealed). The exact body hashes exist only once the ids are minted (prepare)."""
    p = plan()
    spans = {t["metadata"]["tfg_case_id"]: sum(s["trace_id"] == t["id"] for s in p.spans) for t in p.traces}
    return {"schema": "tfg.multiagent.op1b-manifest/1", "operation": "OP-1b", "status": "PREPARED_NOT_AUTHORIZED",
            "destination": {"workspace": bridge.WORKSPACE, "project": bridge.PROJECT, "project_id": PROJECT_ID},
            "source": {"results_dir": bridge._rel(PILOT), "seal_sha256": sha((PILOT / "SHA256SUMS").read_bytes()),
                       "candidate": "qwen", "representation": "v2_native_fields", "excluded": ["E07"]},
            "cases": [{"case_id": t["metadata"]["tfg_case_id"], "original_trace_id": t["id"],
                       "spans": spans[t["metadata"]["tfg_case_id"]]} for t in p.traces],
            "totals": {"traces": len(p.traces), "spans": len(p.spans),
                       "real_llm_spans": sum(s["type"] == "llm" for s in p.spans)},
            "content_sha256": bridge.content_sha256(p),
            "id_rule": "trace/span id = deterministic UUIDv7 of the same scope with its time component shifted so the "
                       "earliest pilot run maps to id_epoch (relative order kept); start_time/end_time historical; "
                       "metadata._import_id = original id (Opik's import convention); tfg_id_epoch declares the shift",
            "kept": ["start_time and end_time", "parent/child span links (remapped)", "inputs, outputs, metadata, tags",
                     "secret redaction and egress checks", "project", "E07 excluded"],
            "supersedes": [{"case_id": t["metadata"]["tfg_case_id"], "rejected_id": t["id"],
                            "attempt": "OP-1 2026-11-06T10:30Z, HTTP 400, read-back 404"} for t in p.traces],
            "not_a_new_run": "a historical import of sealed records: no model is called, nothing is re-executed",
            "authorization_steps": ["1. Joel authorizes this content (content_sha256 + cases + destination)",
                                    "2. at import time: prepare --id-epoch <now>, which checks content_sha256 and prints "
                                    "the exact traces/spans body sha256; Joel authorizes those two hashes",
                                    "3. one send per batch, no retry, then per-trace read-back"]}


def prepare(id_epoch: datetime, out: Path) -> dict:
    """OP-1b dry run: the same 10 sealed traces, ids re-stamped at ``id_epoch``. Exact bodies and hashes for a NEW
    authorization; nothing is sent."""
    p = plan(id_epoch)
    if p.errors:
        raise SystemExit(f"plan errors: {p.errors}")
    opik._check_payload_matches_destination(p)
    expected = json.loads((OP1B_DIR / "manifest.json").read_text())["content_sha256"]
    if bridge.content_sha256(p) != expected:
        raise SystemExit("the content differs from the OP-1b manifest: not prepared")
    findings = bridge.import_id_findings(p, id_epoch)
    if findings:
        raise SystemExit(f"ids not importable at the epoch: {findings[:2]}")
    requests = opik.send_requests(p)
    old = original_ids()
    cases = [{"case_id": t["metadata"]["tfg_case_id"], "trace_id": t["id"], "supersedes": old[t["metadata"]["tfg_case_id"]],
              "spans": sum(s["trace_id"] == t["id"] for s in p.spans), "start_time": t["start_time"],
              "id_time": bridge.id_time(t["id"]).isoformat()} for t in p.traces]
    hashes = {k: sha(d) for k, _, d in requests}
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    out.mkdir(parents=True, exist_ok=True)
    payload = {"operation": "OP-1b (PREPARED, NOT AUTHORIZED, NOT SENT)", "id_epoch": id_epoch.isoformat(),
               "send_window_utc": [(id_epoch - bridge.ID_WINDOW + bridge.ID_WINDOW_MARGIN).isoformat(),
                                   (id_epoch + bridge.ID_WINDOW - bridge.ID_WINDOW_MARGIN).isoformat()],
               "body_sha256": hashes, "body_bytes": {k: len(d) for k, _, d in requests}, "cases": cases,
               "bodies": {k: json.loads(d) for k, _, d in requests},
               "content_sha256": expected, "id_mapping": bridge.id_mapping(plan(), p),
               "difference_from_op1": "only the time component of trace/span ids (and parent/trace references) plus "
                                      "metadata.tfg_id_epoch; start/end times, inputs, outputs and the rest are the sealed ones"}
    (out / "op1b.dry_run.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    return {k: payload[k] for k in ("operation", "id_epoch", "send_window_utc", "body_sha256", "body_bytes")}


def send(record_path: Path, *, id_epoch=None, authorized=AUTHORIZED, authorization=AUTHORIZATION) -> dict:
    pre = preflight(id_epoch=id_epoch, authorized=authorized)
    if not pre["passed"]:
        return {"status": "NOT_SENT_PREFLIGHT_FAILED", "preflight": pre}
    p = plan(id_epoch)
    if id_epoch is not None:
        manifest = json.loads((OP1B_DIR / "manifest.json").read_text())
        if bridge.content_sha256(p) != manifest["content_sha256"] or bridge.import_id_findings(p):
            return {"status": "NOT_SENT_CONTENT_OR_IDS_CHANGED", "preflight": pre}
    supersedes = set(original_ids().values()) if id_epoch is not None else ()
    result = bridge.send_import(p, authorized=True, record_path=record_path, max_traces=10, supersedes=supersedes,
                                error_body_path=record_path.with_suffix(".error_body"))
    ledger = bridge.load_ledger()
    for t in (t for t in p.traces if t["id"] in ledger["traces"]):  # NOT_SENT removes the entries
        ledger["traces"][t["id"]]["authorization"] = authorization
        ledger["traces"][t["id"]]["operation"] = authorization["operation"]
        ledger["traces"][t["id"]]["representation"] = "v2_native_fields"
        ledger["traces"][t["id"]]["import_generation"] = 2 if id_epoch is not None else 1
    bridge._save_ledger(ledger)
    rep = result["send_report"]
    return {"status": result["status"], "send_status": rep["status"], "http_statuses": rep.get("http_statuses_received"),
            "uncertain_reason": rep.get("uncertain_reason"),
            "batches": [{k: x.get(k) for k in ("kind", "items", "http_status", "outcome", "elapsed_wall_s")}
                        for x in rep["batches"]],
            "record": bridge._rel(record_path), "trace_ids": [t["id"] for t in p.traces], "preflight": pre}


def verify(id_epoch=None) -> dict:
    """Per trace: bridge.verify_trace (trace, project, metadata, no secret) + spans readback compared with the sent body."""
    p = plan(id_epoch)
    out = {}
    for t in p.traces:
        case = t["metadata"]["tfg_case_id"]
        v = bridge.verify_trace(t["id"])
        key, headers = _headers()
        q = urllib.parse.urlencode({"trace_id": t["id"], "project_id": PROJECT_ID, "size": 100})
        s, page, leak = _get(f"/v1/private/spans?{q}", key, headers)
        st, trace, leak2 = _get(f"/v1/private/traces/{t['id']}", key, headers)
        key = headers = None
        items = (page or {}).get("content") or []
        sent = {s_["id"]: s_ for s_ in p.spans if s_["trace_id"] == t["id"]}
        llm_remote = [x for x in items if x.get("type") == "llm"]
        llm_sent = next(x for x in sent.values() if x["type"] == "llm")
        r = llm_remote[0] if llm_remote else {}
        readback = {"spans_http": s, "spans_found": len(items), "spans_sent": len(sent),
                    "span_ids_match_sent": sorted(x.get("id") for x in items) == sorted(sent),
                    "span_ids": sorted(sent),
                    "real_llm_spans": [x.get("name") for x in llm_remote],
                    "native_model": r.get("model"), "native_provider": r.get("provider"),
                    "native_usage_matches": {k: (r.get("usage") or {}).get(k) for k in llm_sent["usage"]} == llm_sent["usage"],
                    "remote_total_estimated_cost": r.get("total_estimated_cost"),
                    "trace_tags_match": sorted((trace or {}).get("tags") or []) == sorted(t["tags"]),
                    "original_times_kept": (trace or {}).get("start_time", "")[:19] == t["start_time"][:19],
                    "executions": sorted({(x.get("metadata") or {}).get("tfg_execution") for x in items}),
                    "api_key_echoed": bool(leak or leak2),
                    "method": "read-only GET traces/{id}, projects/{id}, spans?trace_id&project_id (2026-11-06)"}
        complete = v["verified"] and readback["span_ids_match_sent"] and readback["spans_found"] == len(sent) and \
            readback["native_usage_matches"] and readback["trace_tags_match"] and not readback["api_key_echoed"]
        ledger = bridge.load_ledger()
        entry = ledger["traces"][t["id"]]
        entry["readback"] = readback
        if v["verified"] and not complete:  # the trace exists but its spans do not match: never call it verified
            entry["status"] = "PRESENT_INCOMPLETE_UNCERTAIN"
        bridge._save_ledger(ledger)
        out[case] = {"trace_id": t["id"], "verified": bool(complete), "ledger_status": entry["status"],
                     "checks": v["checks"], "readback": {k: v_ for k, v_ in readback.items() if k != "span_ids"},
                     "link": v.get("link")}
    return {"at_utc": datetime.now(timezone.utc).isoformat(), "all_verified": all(x["verified"] for x in out.values()),
            "traces": out}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    epoch = lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)  # noqa: E731
    for name in ("preflight", "verify"):
        q = sub.add_parser(name)
        q.add_argument("--out", type=Path)
        q.add_argument("--id-epoch", type=epoch)
    q = sub.add_parser("prepare")
    q.add_argument("--id-epoch", type=epoch, required=True)
    q.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("send")
    s.add_argument("--i-authorize-op1", action="store_true")
    s.add_argument("--i-authorize-op1b", action="store_true")
    s.add_argument("--id-epoch", type=epoch)
    s.add_argument("--traces-sha")
    s.add_argument("--spans-sha")
    a = ap.parse_args(argv)
    if a.cmd == "prepare":
        print(json.dumps(prepare(a.id_epoch, a.out), indent=1))
        return 0
    if a.cmd == "send":
        if a.id_epoch is None:
            raise SystemExit("OP-1 (original ids) was attempted on 2026-11-06 and rejected; its ids can never be "
                             "accepted. Only OP-1b (--id-epoch, new hashes, new authorization) remains")
        if not (a.i_authorize_op1b and a.traces_sha and a.spans_sha):
            raise SystemExit("OP-1b needs --i-authorize-op1b and the two authorized hashes")
        auth = {"traces": a.traces_sha, "spans": a.spans_sha}
        record = bridge.IMPORTS / f"send_OP1b_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
        result = send(record, id_epoch=a.id_epoch, authorized=auth,
                      authorization={**AUTHORIZATION, "operation": "OP-1b", "authorized_sha256": auth,
                                     "id_epoch": a.id_epoch.isoformat(), "by": "Joel (named on the command line)"})
    else:
        result = preflight(id_epoch=a.id_epoch) if a.cmd == "preflight" else verify(a.id_epoch)
    text = json.dumps(result, indent=1, sort_keys=True, default=str)
    if getattr(a, "out", None):
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text + "\n")
    print(text if a.cmd != "preflight" else json.dumps({"passed": result["passed"], **{
        k: v["passed"] for k, v in result["checks"].items()}}, indent=1))
    return 0 if result.get("passed", result.get("all_verified", result.get("status") == "HTTP_ACCEPTED_NOT_VERIFIED")) else 1


if __name__ == "__main__":
    sys.exit(main())
