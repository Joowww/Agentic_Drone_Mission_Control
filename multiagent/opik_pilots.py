"""DRY-RUN Opik plans for the sealed integrated pilots M4 and M4b (one trace per pilot, one LLM span per real call).
Nothing here sends, reads a credential or creates a client: there is no send path in this module. Publishing any of
these needs its own explicit authorization (it is NOT part of OP-1b, and E07's ledger entry is untouched).

    python -m multiagent.opik_pilots --out <dir>     # writes dry_run_<pilot>.json and a manifest, nothing else
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

from multiagent import opik_bridge as ob
from observability import opik_export as opik

PILOTS = {"m4": "m4_integrated_v1_2026-11-06_b9da2e22b", "m4b": "m4b_integrated_v1_2026-11-06_07db60a37",
          "m4c_r1": "m4c_r1_integrated_v1_2026-11-07_f1ec396c9"}


def _root():
    return ob.ROOT / "multiagent/benchmark/results"


def plan(pilot: str) -> opik.OpikPlan:
    d = _root() / PILOTS[pilot]
    seal = ob.verify_seal(d)
    summary = json.loads((d / "summary.json").read_text())
    manifest = json.loads((d / "manifest.json").read_text())
    exchanges = [json.loads(l) for l in (d / "exchanges.jsonl").read_text().splitlines()]
    latency = {e["n"]: e.get("latency_s") for e in summary["budget"]["log"] if e.get("real")}
    dest = opik.make_destination(ob.PROJECT, ob.WORKSPACE)
    p = opik.OpikPlan(destination=dest)
    start = datetime.fromisoformat(summary["started_utc"]).astimezone(timezone.utc)
    end = datetime.fromisoformat(summary["finished_utc"]).astimezone(timezone.utc)
    scope = f"trace|multiagent-pilot|{PILOTS[pilot]}"
    tid = opik.deterministic_uuid7(dest["key"], scope, start)
    rel = str(d.relative_to(ob.ROOT))
    p.traces.append(ob._clean({
        "id": tid, "project_name": ob.PROJECT, "name": f"multiagent-pilot:{manifest['pilot_id']}",
        "start_time": opik._iso(start), "end_time": opik._iso(end),
        "input": {"operator_text": manifest["dataset"].get("text") or "see manifest case"},
        "output": {"classification": summary["classification"], "commands_sent": summary["commands_sent"],
                   "physical_effect": summary["physical_effect"]},
        "metadata": {"tfg_import": "HISTORICAL_SEALED_RECORD", "tfg_rerun": False, "tfg_pilot": manifest["pilot_id"],
                     "tfg_experiment_kind": "INTEGRATED_PILOT_EXISTENCE_PROOF_NOT_A_STATISTIC",
                     "tfg_prompt_ids": {r: a.get("prompt_id") for r, a in manifest["agents"].items()},
                     "tfg_safety_policy": manifest.get("safety_policy"), "tfg_model": manifest["model"],
                     "tfg_generation": manifest["generation"], "tfg_criteria": summary["criteria"],
                     "tfg_role_outcomes": summary.get("role_outcomes"), "tfg_budget": {
                         "limit": summary["budget"]["limit"], "used": summary["budget"]["real_calls_used"],
                         "per_role": summary["budget"]["per_role"]},
                     "tfg_status_ladder": summary["status_ladder"],
                     "tfg_sources": {"results_dir": rel, "seal_sha256": seal, "manifest_sha256": summary["manifest_sha256"]}},
        "tags": ["tfg-multiagent", "historical-import", "integrated-pilot", f"pilot:{manifest['pilot_id']}",
                 f"outcome:{summary['classification']}", "DRY_RUN_PREPARED_NOT_AUTHORIZED"]}))
    p.trace_kinds[tid] = "MODEL_OUTPUT_LOCAL_LLM"
    p.id_scopes[tid] = scope
    for e in exchanges:
        s0 = datetime.fromisoformat(e["at_utc"]).astimezone(timezone.utc)
        sscope = f"span|multiagent-pilot|{PILOTS[pilot]}|call{e['n']}"
        sid = opik.deterministic_uuid7(dest["key"], sscope, s0)
        p.spans.append(ob._clean({
            "id": sid, "trace_id": tid, "project_name": ob.PROJECT, "type": "llm", "name": f"llm:{e['role']}",
            "start_time": opik._iso(s0), "end_time": opik._iso(s0 + timedelta(seconds=latency.get(e["n"]) or 0)),
            "input": {"prompt": e["prompt"]}, "output": {"raw_reply": e["raw_reply"]},
            "metadata": {"tfg_execution": "REAL_LLM_CALL", "tfg_role": e["role"], "tfg_call_n": e["n"],
                         "tfg_prompt_sha256": e["prompt_sha256"], "tfg_raw_reply_sha256": e["raw_reply_sha256"],
                         "tfg_finish_reason": e["finish_reason"], "tfg_tokens": e["usage"],
                         "tfg_latency_s": latency.get(e["n"]), "tfg_cost": "NOT_APPLICABLE_LOCAL_MODEL"},
            "tags": ["real-llm-call", f"role:{e['role']}"]}))
        p.id_scopes[sid] = sscope
    return p


def dry_run(out: Path) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    ledger = ob.load_ledger()
    rows = {}
    for pilot in PILOTS:
        p = plan(pilot)
        body = {"traces": p.traces, "spans": p.spans}
        data = json.dumps(body, indent=1, sort_keys=True).encode()
        (out / f"dry_run_{pilot}.json").write_bytes(data + b"\n")
        rows[pilot] = {"source": PILOTS[pilot], "traces": [t["id"] for t in p.traces], "spans": len(p.spans),
                       "already_in_ledger": [ledger["traces"].get(t["id"], {}).get("status") for t in p.traces],
                       "egress_findings": ob.egress_findings(p), "id_window_findings": ob.id_window_findings(p),
                       "plan_sha256": hashlib.sha256(data).hexdigest()}
    manifest = {"schema": "tfg.multiagent.opik-pilot-dry-run/1", "status": "DRY_RUN_NOT_SENT_NOT_AUTHORIZED",
                "destination": {"workspace": ob.WORKSPACE, "project": ob.PROJECT}, "pilots": rows,
                "note": "M4 and M4b are separate traces with their own pilot tag; M4b is never merged into M4. Sending "
                        "needs a new explicit authorization; ids embed the original run times: id_window_findings is "
                        "measured at preparation time, and after Opik's 24 h ingestion window they would need "
                        "re-stamping (as OP-1b)."}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    with (out / "SHA256SUMS").open("w") as sums:
        for f in sorted(x for x in out.iterdir() if x.name != "SHA256SUMS"):
            sums.write(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  ./{f.name}\n")
    return manifest


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--out", type=Path, required=True)
    m = dry_run(a.parse_args(argv).out)
    print(json.dumps({k: {x: v[x] for x in ("spans", "egress_findings", "already_in_ledger")} for k, v in m["pilots"].items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
