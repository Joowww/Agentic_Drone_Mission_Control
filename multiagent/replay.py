"""REPLAY of a sealed integrated pilot: shows what was RECORDED, in order, without calling any model and without
recomputing anything. Three modes never mix:

  OFFLINE_DETERMINISTIC  python -m multiagent.demo --scenario <name>   scripted test doubles, no LLM
  REAL_LOCAL_LLM         python -m multiagent.benchmark.m4_pilot --run   real local model calls (authorized pilots)
  REPLAY                 python -m multiagent.demo --replay <dir>         sealed evidence only (this module)

The evidence is verified first (every SHA256SUMS, the manifest against its registration commit and the summary,
each prompt/reply digest); a failed verification refuses the replay. Event times are the recorded console offsets
and offsets DERIVED from the recorded call timestamps; nothing is invented, and what the run did not record is
said so.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import sys

MODE = ("REPLAY (of sealed evidence): no model is called, nothing is recomputed; events are the recorded ones; the "
        "recorded calls were REAL_LOCAL_LLM")


def _j(path: Path):
    return json.loads(path.read_text()) if path.is_file() else None


def replay(results: Path, *, out=None) -> dict:
    from multiagent.benchmark import milestone
    results = Path(results).resolve()
    w = (out or sys.stdout).write  # resolved at call time (a redirected stdout is followed)
    v = milestone.verify(results)
    if not v["ok"]:
        w(f"REFUSED: the evidence does not verify: {json.dumps({k: v[k] for k in v if k != 'exchange_digests'})}\n")
        return {"status": "REFUSED_UNVERIFIED", "verification": v}
    summary, manifest = _j(results / "summary.json"), _j(results / "manifest.json")
    exchanges = [json.loads(l) for l in (results / "exchanges.jsonl").read_text().splitlines()]
    demo = results / "demo"
    r = _j(demo / "result.json") or {}
    start = datetime.fromisoformat(summary["started_utc"])
    latency = {e["n"]: e.get("latency_s") for e in summary["budget"]["log"]}
    w(f"[replay] mode          {MODE}\n")
    w(f"[replay] source        {results.name} (manifest {manifest['pilot_id']}, run commit {summary['commit'][:9]}, "
      f"model {manifest['model']['candidate']} {manifest['model']['digest'][:12]})\n")
    w(f"[replay] verification  seals {v['seals']}; manifest registered at {v['manifest_registration_commit']}; "
      f"{len(exchanges)} call digest(s) OK\n")
    events = []
    for line in r.get("console") or []:
        m = re.match(r"\[\s*([0-9.]+)s\] (.*)", line)
        if m:
            events.append((float(m.group(1)), 1, "recorded", m.group(2)))
    for e in exchanges:
        off = (datetime.fromisoformat(e["at_utc"]) - start).total_seconds()
        reply = json.loads(e["raw_reply"]) if e["raw_reply"].strip().startswith("{") else None
        gist = _gist(e["role"], reply)
        events.append((off, 0, "llm_call", f"#{e['n']} {e['role']}: {e['usage']['prompt_tokens']}+"
                       f"{e['usage']['completion_tokens']} tokens, {round(latency.get(e['n']) or 0, 2)} s, prompt "
                       f"{e['prompt_sha256'][:12]}, reply {e['raw_reply_sha256'][:12]} -> {gist}"))
    w("[replay] ---- timeline (recorded console offsets; LLM call offsets derived from recorded timestamps) ----\n")
    for off, _, kind, text in sorted(events, key=lambda x: (x[0], x[1])):
        w(f"[{off:7.2f}s] {kind:<9} {text}\n")
    rec = r.get("agent_records") or {}
    w("[replay] ---- agents ----\n")
    for role, label in (summary.get("role_outcomes") or {}).items():
        w(f"[replay] {role:<22} {label}\n")
    w("[replay] ---- safety decisions ----\n")
    prov = (rec.get("supervisor") or {}).get("provenance")
    w(f"[replay] policy {manifest.get('safety_policy')}; supervisor phase A {(rec.get('supervisor') or {}).get('status')}; "
      f"reasons {(rec.get('supervisor') or {}).get('reasons')}\n")
    if prov:
        w(f"[replay] brief provenance {prov.get('status')} (clean: {prov.get('llm_provenance_clean')}, "
          f"corrections: {len(prov.get('corrections') or [])})\n")
    w("[replay] ---- detection (SYNTHETIC_TEST image, TEST_FIXTURE events) ----\n")
    det = r.get("detection") or {}
    w(f"[replay] {det.get('status')} {[(d.get('object_class'), d.get('center_px')) for d in det.get('detections') or []]}; "
      f"gate {(r.get('observation_gate') or {}).get('status')} {(r.get('observation_gate') or {}).get('target')}\n")
    w("[replay] ---- proposals and final plan ----\n")
    pa, pb = _j(demo / "phase_a_proposal.json"), _j(demo / "phase_b_proposal.json")
    for p in ((pa or {}).get("aerial") or {}).get("proposals", []):
        w(f"[replay] aerial  {p['vehicle_id']} -> {p['poi_sequence']} start delay {p.get('start_delay_s')} s\n")
    if pa and pa.get("swarm_coordination"):
        sc = pa["swarm_coordination"]
        w(f"[replay] separation {sc['status']}: {sc['initial_conflicts']} initial, {sc['residual_conflicts']} residual "
          "(resolved by the deterministic deconfliction)\n")
    for g in ((pb or {}).get("ground") or {}).get("proposals", []):
        w(f"[replay] ground  {g['task_id']} -> {g['target_point']} after {g['after_aerial_point']} ({g['state']})\n")
    w(f"[replay] final   {r.get('classification')}; commands sent {r.get('commands_sent')}; physical effect "
      f"{r.get('physical_effect')}; execution request {(r.get('execution_request') or {}).get('state')}\n")
    w("[replay] ---- tools (as recorded) ----\n")
    alloc = ((((pa or {}).get("aerial") or {}).get("evidence") or {}).get("model_proposal_check") or {}).get("allocator") or {}
    review_b = ((((pb or {}).get("ground") or {}).get("evidence") or {}).get("llm_review")) or {}
    review_a = _j(demo / "phase_a_rover_review.json") or {}
    for who, log_ in (("drone agent", alloc.get("tool_log")), ("rover agent phase A", review_a.get("tool_log")),
                      ("rover agent phase B", review_b.get("tool_log"))):
        w(f"[replay] {who:<20} " + (", ".join(f"{t['tool']}={t['status']}" for t in log_) if log_ else
                                    "NOT RECORDED in this run") + "\n")
    log = _j(demo / "coordinator_log.json") or []
    w(f"[replay] coordinator events: {[(e['event']['type'], e['outcome']) for e in log]}\n")
    missing = _missing(results, exchanges, rec)
    w("[replay] ---- not recorded by the run ----\n")
    for m in missing or ["nothing known to be missing"]:
        w(f"[replay] {m}\n")
    return {"status": "REPLAYED", "mode": MODE, "verification": v, "events": len(events), "missing": missing,
            "llm_calls": len(exchanges)}


def _gist(role, reply):
    if not isinstance(reply, dict):
        return "reply not a JSON object"
    if role == "mission_orchestrator":
        return (f"aerial {[(o.get('point_id'), o.get('required_sensor')) for o in reply.get('aerial_objectives') or []]}, "
                f"ground {[(g.get('vehicle_id'), g.get('waits_for')) for g in reply.get('ground_objectives') or []]}, "
                f"unsafe {reply.get('unsafe_requests')}")
    prop = reply.get("proposal") or {}
    if "assignments" in prop:
        return f"assignments {prop['assignments']}, verify {[x.get('tool') for x in reply.get('verify') or []]}"
    return f"decisions {[(d.get('decision'), d.get('target_point')) for d in prop.get('decisions') or []]}, " \
           f"verify {[x.get('tool') for x in reply.get('verify') or []]}"


def _missing(results: Path, exchanges, rec) -> list[str]:
    out = []
    rover_calls = [e for e in exchanges if e["role"] == "rover_agent"]
    if rover_calls and not (results / "demo/phase_a_rover_review.json").is_file() and \
            not (rec.get("rover_phase_a") or {}).get("tool_log"):
        out.append("phase-A rover tool results (requested in its reply) were not written by this run")
    out.append("tool calls are recorded as results, not as timed events: they appear only in the proposals")
    return out
