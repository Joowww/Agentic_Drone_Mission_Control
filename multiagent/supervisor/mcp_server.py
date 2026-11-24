"""Hermes-facing MCP server of the supervisor (stdio). Hermes is the conversational interface: it reads the
operator's natural-language mission, may produce a structured intent, and calls ``supervisor_plan_mission``; the
LangGraph supervisor does the rest (agents, .plan files, validation, manifest) and returns a structured outcome that
Hermes explains to the operator (including blocks and replanning decisions).

Exposed tools (planning and read-only):
  supervisor_registry          vehicles, capabilities with their evidence status, availability, executors
  supervisor_plan_mission      text (+ optional Hermes intent) -> mission directory, status, reasons, decisions
  supervisor_mission_status    the global result and per-vehicle state of a mission
NOT exposed: approval and execution. A model can never approve or execute; the operator uses the CLI
(``python -m multiagent.supervisor approve|execute``).

Environment: TFG_SUPERVISOR_OUT (absolute private directory OUTSIDE the repository, chmod 700) and optionally
TFG_SUPERVISOR_SCENARIO (default: the synthetic three-vehicle parcel). ``hermes_profile_entry`` prints the
``mcp_servers`` entry for a Hermes profile with tools.include limited to these three names.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
SERVER = "tfg-supervisor"
TOOLS = ("supervisor_registry", "supervisor_plan_mission", "supervisor_mission_status", "supervisor_get_manifest")
CALL_LOG = "mcp_calls.jsonl"   # server-side record of every tool call: name, argument digest, outcome, duration
DEFAULT_SCENARIO = ROOT / "multiagent/fixtures/supervisor/agri_parcel_3v.scenario.json"
MISSION_ID = re.compile(r"^SUP-\d{8}T\d{6}Z-[0-9a-f]{10}$")


def out_root(environ=os.environ) -> Path:
    raw = environ.get("TFG_SUPERVISOR_OUT", "")
    if not raw or not Path(raw).is_absolute():
        raise SystemExit("TFG_SUPERVISOR_OUT must be an absolute private directory outside the repository")
    root = Path(raw).resolve()
    if root == ROOT or ROOT in root.parents:
        raise SystemExit(f"TFG_SUPERVISOR_OUT must be outside the repository ({ROOT})")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.stat().st_mode & 0o077:
        raise SystemExit("TFG_SUPERVISOR_OUT must not be accessible by group or others (chmod 700)")
    return root


def _supervisor(environ=os.environ):
    from multiagent.supervisor.graph import Supervisor
    return Supervisor(environ.get("TFG_SUPERVISOR_SCENARIO") or DEFAULT_SCENARIO, out_root=out_root(environ))


def _logged(name):
    """Every call is appended to <out>/mcp_calls.jsonl (tool name, sha256 of the arguments, status, mission id,
    duration, server pid). Argument VALUES are not stored, only their digest; no credential reaches this server."""
    import functools
    import hashlib
    import time
    from datetime import datetime, timezone

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            started, record = time.perf_counter(), {"tool": name, "at": datetime.now(timezone.utc).isoformat(),
                                                    "pid": os.getpid(), "run_id": os.environ.get("TFG_SUPERVISOR_RUN_ID")}
            record["arguments_sha256"] = hashlib.sha256(json.dumps(kwargs, sort_keys=True, default=str)
                                                        .encode()).hexdigest()
            try:
                out = fn(*args, **kwargs)
                record.update(status="OK", mission_id=(out or {}).get("mission_id"),
                              result_status=(out or {}).get("status"),
                              interpretation=((out or {}).get("interpretation") or {}).get("provider"))
                return out
            except Exception as exc:
                record.update(status="ERROR", error=f"{type(exc).__name__}: {str(exc)[:200]}")
                raise
            finally:
                record["duration_s"] = round(time.perf_counter() - started, 3)
                try:
                    with open(out_root() / CALL_LOG, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(record, sort_keys=True) + "\n")
                except OSError:
                    pass
        return inner
    return wrap


def supervisor_registry() -> dict:
    """Compact: one entry per vehicle with class, availability and the status of its execution capability."""
    sup = _supervisor()
    vehicles = [{"vehicle_id": v["vehicle_id"], "role": v["role"], "vehicle_class": v["vehicle_class"],
                 "availability": v["availability"]["status"], "availability_reason": v["availability"]["reason"],
                 "actions_forbidden": v["actions_forbidden"],
                 "execution_capability": v["executor"]["capability"], "execution_status": v["executor"]["status"],
                 "constraints": v["constraints"]} for v in sup.registry["vehicles"]]
    return {"scenario_id": sup.scenario.scenario_id, "vehicles": vehicles,
            "declared_parcel": sup.scenario.parcel.model_dump(),
            "notice": "availability is declared, not a live readiness check; capability statuses come from "
                      "sealed evidence (DEMONSTRATED_SITL) or are not demonstrated"}


MODEL_CALL_LOG = "model_calls.jsonl"   # tfg.multiagent.model-call/1 records of the supervisor's interpretation model


def _model_interpretation(text: str, hermes_intent: dict | None) -> tuple[dict | None, dict | None]:
    """When the server is configured with TFG_LLM_PROVIDER (e.g. eetac), the supervisor's interpretation model is
    called HERE, inside the MCP server process (Hermes never sees its credential). (None, None) when no provider is
    configured: the behaviour is then the one of the planning-only server (Hermes intent, if any, plus the
    deterministic reading). A configured provider that fails returns a BLOCKED provenance: the caller must not plan."""
    if not os.environ.get("TFG_LLM_PROVIDER"):
        return hermes_intent, ({"source": "HERMES_INTENT_ARGUMENT"} if hermes_intent is not None else None)
    from multiagent.supervisor import providers
    import uuid
    client = providers.ProviderClient.from_env(log_path=out_root() / MODEL_CALL_LOG)
    intent, prov = providers.model_intent(client, text, run_id="mcp-" + uuid.uuid4().hex[:12])
    prov = {**prov, "configured_provider": client.chain[0].name,
            "fallback_chain": [s.name for s in client.chain[1:]],
            "hermes_intent_received": hermes_intent is not None,
            "hermes_intent_use": "NOT_USED: the configured interpretation model is the only model intent"}
    return intent, prov


def supervisor_plan_mission(text: str, intent: dict | None = None) -> dict:
    model_intent, provenance = _model_interpretation(text, intent)
    if provenance is not None and os.environ.get("TFG_LLM_PROVIDER") and provenance.get("status") != "MODEL_INTENT":
        last = (provenance.get("records") or [{}])[-1]
        return {"mission_id": None, "status": "BLOCKED_INTERPRETATION_MODEL",
                "reasons": [f"{provenance.get('configured_provider')}: {provenance.get('status')} "
                            f"({last.get('error_class') or provenance.get('error') or provenance.get('error_class')})",
                            "no plan was generated: the deterministic reading is not used in place of the "
                            "configured model"],
                "interpretation": {k: provenance.get(k) for k in ("status", "configured_provider", "fallback_chain")},
                "movement_authorized": False}
    sup = _supervisor()
    result = sup.plan(text, model_intent=model_intent, intent_provenance=provenance)
    mdir = Path(result["mission_dir"])
    proposal = json.loads((mdir / "proposal.json").read_bytes())
    decisions = json.loads((mdir / "decisions.json").read_bytes())
    manifest = json.loads((mdir / "manifest.json").read_bytes()) if (mdir / "manifest.json").exists() else None
    return {"mission_id": result["mission_id"], "status": result["status"], "reasons": result["reasons"],
            "decisions": [{k: d[k] for k in ("stage", "decision")} for d in decisions],
            "deviations_from_request": proposal["deviations_from_request"],
            "vehicles": [{k: v[k] for k in ("vehicle_id", "vehicle_class", "task_id", "validation")}
                         | {"plan_sha256": v["plan"]["sha256"], "plan": v["plan"]["path"],
                            "route": _route(proposal, v["vehicle_id"])}
                         for v in (manifest or {}).get("vehicles", [])],
            "dependencies": (manifest or {}).get("dependencies", []),
            "mission_dir": result["mission_dir"],
            "manifest_sha256": (manifest or {}).get("manifest_sha256"),
            "interpretation": _interpretation_summary(provenance),
            "next_step": "the operator reviews and approves each vehicle with the CLI; nothing has been executed",
            "movement_authorized": False}


def _interpretation_summary(prov: dict | None) -> dict | None:
    if not prov:
        return None
    ok = next((r for r in prov.get("records") or [] if r.get("status") == "OK"), {})
    return {"status": prov.get("status") or prov.get("source"), "provider": prov.get("provider"),
            "model": prov.get("model"), "response_model": ok.get("response_model"),
            "latency_s": ok.get("latency_s"), "run_id": ok.get("run_id"),
            "fallback_used": bool(ok.get("fallback"))}


def _route(proposal: dict, vehicle_id: str) -> list[str]:
    plan = proposal.get("plan") or {}
    for t in plan.get("aerial_tasks") or []:
        if t["vehicle_id"] == vehicle_id:
            return [t["takeoff_point"], *t["poi_sequence"], t["takeoff_point"]]
    g = plan.get("ground_task") or {}
    if g.get("vehicle_id") == vehicle_id:
        return [g["start_point"], *g["point_sequence"]] + ([g["start_point"]] if g.get("return_to_start") else [])
    return []


def supervisor_get_manifest(mission_id: str) -> dict:
    """The manifest of a planned mission, re-checked on disk (digest and every file hash)."""
    from multiagent.supervisor.plans import check_manifest
    if not MISSION_ID.fullmatch(mission_id or ""):
        raise ValueError("unknown mission id format")
    manifest, problems = check_manifest(out_root() / mission_id)
    if manifest is None:
        raise ValueError(f"no manifest for {mission_id}: {problems}")
    return {"mission_id": mission_id, "status": "INTACT" if not problems else "MODIFIED", "problems": problems,
            "manifest": manifest}


def supervisor_mission_status(mission_id: str) -> dict:
    if not MISSION_ID.fullmatch(mission_id or ""):
        raise ValueError("unknown mission id format")
    path = out_root() / mission_id / "results" / "global_result.json"
    if not path.exists():
        raise ValueError(f"no such mission {mission_id}")
    return json.loads(path.read_bytes())


def build_server():
    from mcp.server import MCPServer
    server = MCPServer(name=SERVER, title="TFG Hermes supervisor (planning)",
                       description="Multi-vehicle mission planning through the LangGraph supervisor",
                       instructions="Planning and status only. Nothing here approves, uploads, arms or moves a "
                                    "vehicle. Report blocked vehicles and replanning decisions to the operator; never "
                                    "invent positions, wind, battery or availability.")
    server.add_tool(_logged("supervisor_registry")(supervisor_registry), name="supervisor_registry",
                    description="Call FIRST. Lists the declared vehicles (drones, rover), their availability, "
                                "forbidden actions and whether their executor is demonstrated in SITL.")
    server.add_tool(_logged("supervisor_plan_mission")(supervisor_plan_mission), name="supervisor_plan_mission",
                    description="Plans a multi-vehicle mission with the LangGraph supervisor and writes one .plan "
                                "per vehicle plus a manifest. Pass the operator's request VERBATIM in 'text'. "
                                "Optional 'intent' object with integer/boolean fields only when you are sure: "
                                "drones_requested, rovers_requested, aerial_sectors, ground_point_count, "
                                "return_to_start. Facts stated in the text always prevail. Returns status, "
                                "reasons, decisions, per-vehicle plan path, sha256 and route.")
    server.add_tool(_logged("supervisor_get_manifest")(supervisor_get_manifest), name="supervisor_get_manifest",
                    description="Manifest of a planned mission (files, sha256, dependencies, execution order), "
                                "re-checked on disk. Argument: mission_id returned by supervisor_plan_mission.")
    server.add_tool(_logged("supervisor_mission_status")(supervisor_mission_status), name="supervisor_mission_status",
                    description="Global and per-vehicle status of a planned mission (mission_id).")
    return server


def hermes_profile_entry(python: str, out: str, scenario: str | None = None) -> dict:
    env = {"PYTHONPATH": str(ROOT), "TFG_SUPERVISOR_OUT": out}
    if scenario:
        env["TFG_SUPERVISOR_SCENARIO"] = scenario
    return {SERVER: {"command": python, "args": ["-m", "multiagent.supervisor.mcp_server"], "env": env,
                     "enabled": True, "tools": {"include": list(TOOLS), "resources": False, "prompts": False}}}


def main() -> None:
    out_root()
    build_server().run(transport="stdio")


if __name__ == "__main__":
    sys.exit(main())
