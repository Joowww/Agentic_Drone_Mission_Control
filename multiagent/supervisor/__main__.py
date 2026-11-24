"""Single command for the multi-vehicle supervisor.

  python -m multiagent.supervisor registry  --scenario S
  python -m multiagent.supervisor plan      --scenario S --out DIR (--text T | --text-file F) [--hermes-intent J]
  python -m multiagent.supervisor approve   --mission M --vehicle V --operator ID --session SID --statement TEXT
                                            [--mode OFFLINE_TEST|OPERATIONAL] [--valid-minutes N] [--session-minutes N]
  python -m multiagent.supervisor execute   --mission M --session SID --executor test-double|real
                                            [--mode ...] [--outcome V=FAILED ...] [--receipt-key FILE]
  python -m multiagent.supervisor ingest    --mission M --vehicle V --report PREFLIGHT_REPORT [--receipt-key FILE]
  python -m multiagent.supervisor status    --mission M

``execute --executor real`` never moves anything: drones get the exact protected H2 request (READY_TO_REQUEST_EXECUTION)
for the operator to run; the rover stays BLOCKED until a .plan mission executor exists. ``ingest`` brings a real
protected-entry report back and writes the SafeFlight result (receipt only for real SITL and with a key file).
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys

from multiagent.supervisor import approval as appr
from multiagent.supervisor import executors as ex
from multiagent.supervisor import plans as pl
from multiagent.supervisor import results as res
from multiagent.supervisor.graph import Supervisor, _now


def _sup_for(mission: Path) -> Supervisor:
    req = json.loads((mission / "request.json").read_bytes())
    return Supervisor(req["scenario_path"], out_root=mission.parent)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m multiagent.supervisor")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("registry"); r.add_argument("--scenario", required=True)  # noqa: E702
    pp = sub.add_parser("plan")
    pp.add_argument("--scenario", required=True); pp.add_argument("--out", required=True)  # noqa: E702
    pp.add_argument("--text"); pp.add_argument("--text-file"); pp.add_argument("--hermes-intent")  # noqa: E702
    pp.add_argument("--llm-intent", action="store_true",
                    help="ask the provider selected by TFG_LLM_PROVIDER (and explicit TFG_LLM_FALLBACK) for the intent")
    a = sub.add_parser("approve")
    for k in ("--mission", "--vehicle", "--operator", "--session", "--statement"):
        a.add_argument(k, required=True)
    a.add_argument("--mode", default="OFFLINE_TEST", choices=sorted(appr.ACCEPTED_SOURCES))
    a.add_argument("--valid-minutes", type=float, default=30.0)
    a.add_argument("--session-minutes", type=float, default=60.0)
    e = sub.add_parser("execute")
    e.add_argument("--mission", required=True); e.add_argument("--session", required=True)  # noqa: E702
    e.add_argument("--executor", required=True, choices=("test-double", "real"))
    e.add_argument("--mode", default="OFFLINE_TEST", choices=sorted(appr.ACCEPTED_SOURCES))
    e.add_argument("--outcome", action="append", default=[], help="test double only: VEHICLE=FAILED|ABORTED|TIMEOUT")
    e.add_argument("--receipt-key")
    i = sub.add_parser("ingest")
    for k in ("--mission", "--vehicle", "--report"):
        i.add_argument(k, required=True)
    i.add_argument("--receipt-key")
    s = sub.add_parser("status"); s.add_argument("--mission", required=True)  # noqa: E702
    args = p.parse_args(argv)

    if args.cmd == "registry":
        sup = Supervisor(args.scenario, out_root=Path("."))
        print(json.dumps(sup.registry, indent=2))
        return 0
    if args.cmd == "plan":
        if bool(args.text) == bool(args.text_file):
            p.error("give exactly one of --text / --text-file")
        text = args.text or Path(args.text_file).read_text(encoding="utf-8")
        intent = json.loads(Path(args.hermes_intent).read_text()) if args.hermes_intent else None
        provenance = {"source": "HERMES_INTENT_FILE"} if intent is not None else None
        if args.llm_intent:
            if intent is not None:
                p.error("--hermes-intent and --llm-intent are exclusive")
            from multiagent.supervisor import providers
            client = providers.ProviderClient.from_env()
            intent, provenance = providers.model_intent(client, text)
        out = Supervisor(args.scenario, out_root=Path(args.out)).plan(text, model_intent=intent,
                                                                      intent_provenance=provenance)
        out["intent_provenance"] = {k: v for k, v in (provenance or {}).items() if k != "records"} or None
        print(json.dumps(out, indent=2))
        return 0 if out["status"] == "PLANNED" else 2
    mission = Path(args.mission).resolve()
    if args.cmd == "approve":
        manifest, problems = pl.check_manifest(mission)
        if problems:
            print(json.dumps({"status": "REFUSED", "problems": problems}, indent=2))
            return 3
        now = _now()
        rec = appr.record(manifest, args.vehicle, operator_id=args.operator, session_id=args.session,
                          session_expires_at=now + timedelta(minutes=args.session_minutes), at=now,
                          valid_for_s=args.valid_minutes * 60, statement=args.statement,
                          source="TEST_FIXTURE" if args.mode == "OFFLINE_TEST" else "OPERATOR_CLI")
        pl.write_json_once(mission / "approvals" / f"{args.vehicle}.approval.json", rec)
        print(json.dumps({"status": "APPROVAL_RECORDED", "approval_id": rec["approval_id"],
                          "source": rec["source"], "note": "an approval is not an execution"}, indent=2))
        return 0
    if args.cmd == "execute":
        outcomes = dict(o.split("=", 1) for o in args.outcome)
        if outcomes and args.executor != "test-double":
            p.error("--outcome only applies to the test double")
        key = res.load_key_file(Path(args.receipt_key)) if args.receipt_key else None
        glob = _sup_for(mission).execute(mission, mode=args.mode, executor=args.executor, session_id=args.session,
                                         double=ex.OfflineTestDouble(outcomes), receipt_key=key)
        print(json.dumps(glob, indent=2))
        return 0
    if args.cmd == "ingest":
        key = res.load_key_file(Path(args.receipt_key)) if args.receipt_key else None
        glob = _sup_for(mission).ingest_report(mission, vehicle_id=args.vehicle, report_path=Path(args.report),
                                               receipt_key=key)
        print(json.dumps(glob, indent=2))
        return 0
    if args.cmd == "status":
        print((mission / "results" / "global_result.json").read_text())
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
