"""In-process access to this repository's rover contract, adapter, offline authorization ledger and executor admission.

This is the normal path of the multi-agent hand-off in the unified repository: the rover modules under ``tools/`` are
imported directly, with no Git snapshot. It offers the same operation interface as the historical snapshot runner
(``call(op, **args) -> {"ok": True, "result": ...} | {"ok": False, "error": ...}``), so ``rover_handoff.handoff`` and
the integration battery run unchanged against either source. The snapshot runner and ``rover_handoff.ensure_snapshot``
remain only to reproduce sealed evidence produced against earlier pinned revisions of the rover code.

Guards (the same as the snapshot runner, plus one): a ``sitl_trial`` declaration is never forwarded; the executor is
only asked for admission, which returns BLOCKED while the operational rover policy is disabled; and if that policy
were ever enabled in the imported module, admission is refused here instead of being attempted. Nothing in this module
starts a process, opens a socket or sends a command.

Provenance: ``info()`` reports the repository HEAD, whether the contract files differ from HEAD, and the SHA-256 of
every imported contract file, so a recorded result can be tied to the exact code that produced it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_FILES = ("tools/rover_mission_payload.py", "tools/rover_agent_adapter.py", "tools/rover_ground_executor.py",
                  "tools/rover_control.py", "tools/rover_local_authorization.py",
                  "tools/rover_payload_executor_adapter.py", "schemas/rover-mission-execution-v2.schema.json")


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def provenance() -> dict:
    """Which code this process uses: repository HEAD, uncommitted contract changes and per-file SHA-256."""
    head = _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain", "--", *CONTRACT_FILES)
    files = {}
    for rel in CONTRACT_FILES:
        path = ROOT / rel
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return {"source": "LOCAL_REPOSITORY_IMPORT", "repository_head": head,
            "contract_files_modified_since_head": None if dirty is None else bool(dirty),
            "contract_sha256": files}


class LocalRoverContract:
    """The rover side of the hand-off, imported from this repository. Usable as a context manager like the
    historical snapshot runner."""

    def __init__(self):
        from tools import rover_agent_adapter as adapter, rover_ground_executor as executor
        from tools import rover_mission_payload as v2
        self.adapter, self.executor, self.v2 = adapter, executor, v2
        self.provenance_source = adapter.PROVENANCE_SOURCE  # written into every plan; part of the plan digest
        self.supports_final_adapter = True  # tools.rover_payload_executor_adapter is part of this repository
        prov = provenance()
        self.provenance = prov
        head = (prov["repository_head"] or "UNKNOWN")[:12]
        self.tag = f"local {head}" + ("+modified" if prov["contract_files_modified_since_head"] else "")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def call(self, op: str, **args) -> dict:
        try:
            out = self._dispatch(op, args)
        except Exception as exc:  # noqa: BLE001 - every refusal is returned as data, as in the snapshot runner
            return json.loads(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        # A JSON round trip gives exactly the shapes the subprocess runner returns (tuples -> lists, etc.).
        return json.loads(json.dumps({"ok": True, "result": out}, default=str))

    def _dispatch(self, op: str, args: dict):
        adapter, executor, v2 = self.adapter, self.executor, self.v2
        if op == "info":
            return {"v2_schema": v2.SCHEMA, "operational_rover_enabled": executor.OPERATIONAL_ROVER_ENABLED,
                    "provenance": self.provenance}
        if op == "rover_adapter_presence":   # operation name kept from the snapshot runner's interface
            return {"present": (ROOT / "tools/rover_payload_executor_adapter.py").is_file()}
        if op == "bridge_check":
            return {"reasons": adapter.validate_bridge_request(args["view"])}
        if op == "adapt_v2":
            return adapter.adapt_request(args["view"], **args["kwargs"], operator_verification=args.get("receipt"))
        if op == "validate_v2":
            return v2.validate(args["payload"])
        if op == "schema_v2":
            import jsonschema
            schema = json.loads((ROOT / "schemas/rover-mission-execution-v2.schema.json").read_text())
            return {"errors": sorted(f"{list(e.absolute_path)}: {e.message[:160]}"
                                     for e in jsonschema.Draft202012Validator(schema).iter_errors(args["payload"]))}
        if op in ("auth_issue_fixture", "auth_consume", "auth_revoke"):
            from tools import rover_local_authorization as la
            provider = la.LocalAuthorizationProvider(args["ledger"], fixture_mode=True)
            principal = la.Principal(**args["principal"])
            if op == "auth_issue_fixture":
                return provider.issue_fixture(principal, args["binding"], valid_for_s=args.get("valid_for_s", 60))
            if op == "auth_consume":
                return provider.consume(args["authorization"], principal, args["binding"])
            return provider.revoke(args["authorization_id"], principal)
        if op == "plan_scope":
            payload = dict(args["payload"])
            payload["plan_sha256"] = v2.plan_sha256(payload)
            return {"plan_sha256": payload["plan_sha256"], "scope_sha256": v2.authorization_scope_sha256(payload)}
        if op == "executor_request_check":
            limits = executor._request(args["request"])
            return {"ok": True, "limits": dict(vars(limits)) if hasattr(limits, "__dict__") else str(limits)}
        if op == "prepare_executor_request":
            from tools import rover_payload_executor_adapter as final
            evidence, satisfied = args.get("localization_evidence"), args.get("dependencies_satisfied") is True
            return final.prepare_executor_request(
                args.get("payload"), transform_provider=(lambda payload: evidence) if evidence is not None else None,
                executor_params=args.get("executor_params"), dependency_check=lambda dependencies: satisfied,
                expected_identity=args.get("expected_identity"), mode=args.get("mode", "OFFLINE_TEST"),
                stop_state=args.get("stop_state", "UNKNOWN"), rover_frame=args.get("rover_frame", "odom"))
        if op == "admit_executor_request":
            from tools import rover_payload_executor_adapter as final
            prepared = args.get("prepared")
            request = prepared.get("request") if isinstance(prepared, dict) else None
            if isinstance(request, dict) and "sitl_trial" in request:
                raise ValueError("refused: a sitl_trial declaration is never sent from the offline hand-off")
            if executor.OPERATIONAL_ROVER_ENABLED:
                raise PermissionError("refused: the operational rover policy is enabled; the offline hand-off only "
                                      "checks admission while it is disabled")
            return final.admit_executor_request(prepared, mission_path=None, request_key="offline-handoff-check",
                                                authorization=None)
        if op == "executor_admit":
            if isinstance(args.get("request"), dict) and "sitl_trial" in args["request"]:
                raise ValueError("refused: a sitl_trial declaration is never sent from the offline hand-off")
            if executor.OPERATIONAL_ROVER_ENABLED:
                raise PermissionError("refused: the operational rover policy is enabled; the offline hand-off only "
                                      "checks admission while it is disabled")
            return executor.admit_ground_trial(None, "offline-handoff-check", args.get("request"),
                                               args.get("authorization"))
        raise ValueError(f"unknown op {op}")
