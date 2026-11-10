"""Runs the rover's REAL contract and executor code from an immutable snapshot (git archive of a pinned commit), in its own
process, and answers JSON-line requests. Standalone: imports nothing from this project, so it runs with python -I and
the snapshot as the only rover code on the path. Never called with a sitl_trial declaration, never with the
operational policy enabled: the executor's admission returns BLOCKED before touching any file.

    <python> -I -B rover_snapshot_runner.py <snapshot_dir>      (one JSON request per stdin line)

Operations: bridge_check(view) | adapt_v2(view, kwargs, receipt) | validate_v2(payload) | plan_scope(payload) |
            executor_request_check(request) | executor_admit(request, authorization) | info()
"""
import json
import sys


def _load(snapshot):
    sys.path.insert(0, snapshot)
    from tools import rover_agent_adapter as adapter, rover_ground_executor as executor, rover_mission_payload as v2
    return adapter, executor, v2


def serve(snapshot):
    adapter, executor, v2 = _load(snapshot)
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        op, args = req["op"], req.get("args", {})
        try:
            if op == "info":
                out = {"v2_schema": v2.SCHEMA, "operational_rover_enabled": executor.OPERATIONAL_ROVER_ENABLED}
            elif op == "rover_adapter_presence":   # only reports whether the snapshot CONTAINS the adapter
                from pathlib import Path as _P
                out = {"present": (_P(snapshot) / "tools/rover_payload_executor_adapter.py").is_file()}
            elif op == "bridge_check":
                out = {"reasons": adapter.validate_bridge_request(args["view"])}
            elif op == "adapt_v2":
                out = adapter.adapt_request(args["view"], **args["kwargs"], operator_verification=args.get("receipt"))
            elif op == "validate_v2":
                out = v2.validate(args["payload"])
            elif op == "schema_v2":
                import jsonschema
                from pathlib import Path
                schema = json.loads(Path(snapshot, "schemas/rover-mission-execution-v2.schema.json").read_text())
                out = {"errors": sorted(f"{list(e.absolute_path)}: {e.message[:160]}"
                                        for e in jsonschema.Draft202012Validator(schema).iter_errors(args["payload"]))}
            elif op in ("auth_issue_fixture", "auth_consume", "auth_revoke"):
                from tools import rover_local_authorization as la  # reviewed snapshot only
                provider = la.LocalAuthorizationProvider(args["ledger"], fixture_mode=True)
                principal = la.Principal(**args["principal"])
                if op == "auth_issue_fixture":
                    out = provider.issue_fixture(principal, args["binding"], valid_for_s=args.get("valid_for_s", 60))
                elif op == "auth_consume":
                    out = provider.consume(args["authorization"], principal, args["binding"])
                else:
                    out = provider.revoke(args["authorization_id"], principal)
            elif op == "plan_scope":
                payload = dict(args["payload"])
                payload["plan_sha256"] = v2.plan_sha256(payload)
                out = {"plan_sha256": payload["plan_sha256"], "scope_sha256": v2.authorization_scope_sha256(payload)}
            elif op == "executor_request_check":
                limits = executor._request(args["request"])
                out = {"ok": True, "limits": dict(vars(limits)) if hasattr(limits, "__dict__") else str(limits)}
            elif op == "executor_admit":
                if isinstance(args.get("request"), dict) and "sitl_trial" in args["request"]:
                    raise ValueError("refused by the runner: a sitl_trial declaration is never sent offline")
                out = executor.admit_ground_trial(None, "offline-handoff-check", args.get("request"),
                                                  args.get("authorization"))
            else:
                raise ValueError(f"unknown op {op}")
            sys.stdout.write(json.dumps({"ok": True, "result": out}, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001 - every refusal is returned as data
            sys.stdout.write(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    serve(sys.argv[1])
