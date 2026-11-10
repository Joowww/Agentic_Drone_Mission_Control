"""Bounded scenario flow for agri_demo_001.

artifacts -> binding/validation -> aerial sequence -> scenario view -> recorded Hermes evidence -> R1 preparation
-> R1 coordination -> deterministic report.

The graph orders stages and carries identifiers; it executes nothing itself. Aerial execution belongs to the
sequence coordinator (tools.preflight_sequences) and R1 to the ground coordinator (tools.agri_ground_coordinator),
each with its own persistence, idempotency and gates; the executors keep theirs. Two modes:
- query (default): read-only over REAL records; no admission, start or command is reachable (no executor object
  is ever handed to this mode).
- demo: offline SYNTHETIC run with its own identity and storage; only the model provider and the physical
  executor are substituted, by labelled TEST_DOUBLEs.
Real operations stay in their existing entries, behind their own authorizations and gates.
Every terminal path reaches report; a FAILED or UNCERTAIN stage is reported, never retried.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from planning.artifact_store import fingerprint
from reporting import agri_scenario_summary as summary
from tools import agri_ground_coordinator as coordinator

FLOW_SCHEMA = "tfg.agri-scenario-flow/1"
STOP = {"REJECTED", "BLOCKED", "ERROR"}  # stage outcomes that end the flow at report


class ScenarioState(TypedDict, total=False):
    mode: str                 # "query" | "demo"
    source: str               # "archive" | "local" | "synthetic"
    origin: str               # REAL_HISTORICAL | SYNTHETIC
    variant: str | None       # demo variant
    aerial_request_key: str | None
    r1_request_key: str
    r1_root: str
    out_dir: str | None
    capture: dict | None      # labelled analyze_capture result (measured facts only)
    rover_identity: dict | None  # facts of a closed rover identity session (reporting.rover_identity_facts); never a gate
    resume: dict              # {"resumed": bool, "after_interruption": bool}
    status: str
    stage: str
    reasons: list[str]
    artifacts: dict
    associations: dict
    expected_sha256: dict
    binding_record: dict
    binding: dict
    sequence: dict
    view: dict
    hermes: dict
    preparation: dict
    r1: dict
    scenario: dict
    report_path: str | None
    report_text: str | None
    previous_report_kept: str | None
    r1_dimensions: dict | None
    transitions: list[dict]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def flow_record(state: ScenarioState) -> dict:
    """Durable, provider-safe summary: identifiers, hashes, stage outcomes. No samples or coordinates."""
    view, preparation, r1 = state.get("view") or {}, state.get("preparation") or {}, state.get("r1") or {}
    return {"schema": FLOW_SCHEMA, "scenario_id": summary.SCENARIO_ID, "mode": state.get("mode"),
            "source": state.get("source"), "origin": state.get("origin"), "variant": state.get("variant"),
            "resume": state.get("resume"), "status": state.get("status"), "stage": state.get("stage"), "reasons": state.get("reasons", []),
            "artifacts": state.get("artifacts"), "sequence": (view.get("scenario") or {}).get("sequence"),
            "view_sha256": fingerprint(view) if view else None, "hermes": state.get("hermes"),
            "r1": {"request_key": state.get("r1_request_key"), "stages": preparation.get("stages"),
                   "blockers": preparation.get("blockers"), "candidate_sha256": preparation.get("candidate_sha256"),
                   "state": r1.get("state"), "run_id": r1.get("run_id"),
                   "acceptance": (r1.get("acceptance") or {}).get("outcome"), "admit_calls": r1.get("admit_calls"),
                   "request_status": r1.get("request_status"), "repeat_request_status": r1.get("repeat_request_status"),
                   "reason": r1.get("reason")},
            "r1_dimensions": state.get("r1_dimensions"), "scenario": state.get("scenario"),
            "report_path": state.get("report_path"), "previous_report_kept": state.get("previous_report_kept"),
            "transitions": state.get("transitions", []), "movement_authorized": False}


def _persist(state: ScenarioState) -> None:
    if state.get("out_dir"):
        path = Path(state["out_dir"]) / "flow_record.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(flow_record(state), indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)


def step(name: str, waiting_on: str):
    """Record each transition (what the stage waits on, its result and reason), emit it, persist progress, and
    turn unexpected exceptions into ERROR so the flow still reaches report."""
    def decorate(fn):
        # No functools.wraps: LangGraph inspects this signature to pass `config` (wraps would expose fn's).
        def run(state, config=None):
            emit = ((config or {}).get("configurable") or {}).get("emit") or (lambda event: None)
            emit({"node": name, "event": "start", "waiting_on": waiting_on, "origin": state.get("origin")})
            started = utc_now()
            try:
                update = fn(state, (config or {}).get("configurable") or {})
            except Exception as exc:  # infrastructure failure: reported, never retried
                update = {"status": "ERROR", "reasons": [*state.get("reasons", []), f"{name}: {type(exc).__name__}: {exc}"],
                          "result": "ERROR", "reason": f"{type(exc).__name__}: {exc}"}
            result, reason = update.pop("result", update.get("status", state.get("status"))), update.pop("reason", None)
            transition = {"node": name, "started_at": started, "finished_at": utc_now(), "waiting_on": waiting_on,
                          "result": result, "reason": reason}
            new = {**update, "stage": name, "transitions": [*state.get("transitions", []), transition]}
            emit({"node": name, "event": "finish", "result": result, "reason": reason, "origin": state.get("origin")})
            _persist({**state, **new})
            return new
        run.__name__ = fn.__name__
        return run
    return decorate


@step("load_artifacts", "conserved H1/H2 artifacts, verified by their manifests")
def load_artifacts_node(state, cfg):
    try:
        associations, expected, record, provenance = cfg["sources"].artifacts(state)
    except (ValueError, OSError, KeyError) as exc:  # unverifiable or absent sources are BLOCKED, not guessed
        return {"status": "BLOCKED", "reasons": [f"SOURCE_UNAVAILABLE: {exc}"], "result": "BLOCKED",
                "reason": str(exc)}
    return {"associations": associations, "expected_sha256": expected, "binding_record": record,
            "artifacts": provenance, "status": "OK", "result": "LOADED",
            "reason": f"{len(associations)} missions; binding record {str(record.get('sha256'))[:12]}"}


@step("bind_and_validate", "deterministic validation, execution compatibility and H0 geometry of each mission")
def bind_node(state, cfg):
    try:
        binding = summary._bind_expected(state["associations"], state["expected_sha256"])
    except (summary.ScenarioBindingError, ValueError, OSError, TypeError) as exc:
        return {"status": "REJECTED", "reasons": [f"ARTIFACT_REJECTED: {exc}"], "result": "REJECTED",
                "reason": str(exc)}
    return {"binding": binding, "result": "BOUND",
            "reason": ", ".join(f"{v} {b['mission_sha256'][:12]}" for v, b in sorted(binding.items()))}


@step("aerial_sequence", "the sequence coordinator's record (read-only; no admission or launch)")
def aerial_node(state, cfg):
    try:
        sequence, note = cfg["sources"].sequence(state)
    except (ValueError, OSError, KeyError) as exc:  # an unverifiable record is never interpreted
        return {"status": "BLOCKED", "reasons": [f"SEQUENCE_UNAVAILABLE: {exc}"], "result": "BLOCKED",
                "reason": str(exc)}
    return {"sequence": sequence, "result": f"{sequence.get('job_state')}/{sequence.get('result_status')}",
            "reason": note}


@step("scenario_view", "the scenario interpretation of the sequence against the binding")
def view_node(state, cfg):
    view = summary.scenario_view(state["sequence"], state["binding"], binding_record=state["binding_record"])
    view = cfg["sources"].adjust_view(state, view)
    scenario = view.get("scenario") or {}
    return {"view": view, "result": view.get("status"),
            "reason": f"scenario {scenario.get('status')}; R1 dependency {(scenario.get('ground_task') or {}).get('dependency')}"}


@step("hermes_evidence", "recorded Hermes captures (no inference)")
def hermes_node(state, cfg):
    hermes = cfg["sources"].hermes(state)
    return {"hermes": hermes, "result": hermes["origin"], "reason": hermes.get("summary")}


@step("r1_prepare", "R1 inputs, current executor facts and measured facts (dry-run)")
def r1_prepare_node(state, cfg):
    sources = cfg["sources"]
    facts = sources.executor_facts(state)
    preparation = summary.prepare_ground_task(state["view"], inputs=sources.r1_inputs(state), executor_facts=facts,
                                              capture=state.get("capture"), identity=state.get("rover_identity"))
    stages = preparation["stages"]
    return {"preparation": preparation, "result": f"{stages['dependency']}/{stages['eligibility']}",
            "reason": "blockers: " + (", ".join(preparation["blockers"]) or "none")}


@step("r1_coordinate", "the ground coordinator's record (query: read-only; demo: TEST_DOUBLE executor)")
def r1_coordinate_node(state, cfg):
    r1 = cfg["sources"].coordinate(state)
    return {"r1": r1, "result": r1.get("state"), "reason": r1.get("reason") or r1.get("request_reason")}


@step("report", "deterministic rendering of the view, the R1 preparation and the R1 record")
def report_node(state, cfg):
    view = state.get("view")
    record = (state.get("r1") or {}).get("record")
    scenario = coordinator.scenario_result(view, record) if view else None
    dimensions = summary.r1_dimensions(view, state.get("preparation"), record) if view else None
    text = None
    if view:
        text = (ORIGIN_BANNER.get(state.get("origin"), "") + summary.render_scenario_report(view) + "\n"
                + summary.render_ground_report(view, state.get("preparation") or
                                               summary.prepare_ground_task(view), record))
    final = state.get("status") if state.get("status") in STOP else "COMPLETED_FLOW"
    update = {"scenario": scenario, "r1_dimensions": dimensions, "report_text": text, "report_path": None}
    if state.get("out_dir") and text:
        try:
            update.update(_write_report(Path(state["out_dir"]), text))
        except OSError as exc:  # the flow outcome stands, but without a written report it is not COMPLETED
            return {**update, "status": "ERROR",
                    "reasons": [*state.get("reasons", []), f"REPORT_NOT_WRITTEN: {type(exc).__name__}: {exc}"],
                    "result": "ERROR", "reason": f"report not written: {exc}"}
    return {**update, "status": final, "result": (scenario or {}).get("scenario_status", final),
            "reason": f"scenario complete: {(scenario or {}).get('scenario_complete', False)}"}


def _write_report(out_dir: Path, text: str) -> dict:
    """Atomic write. A previous, DIFFERENT report is kept beside it (never silently overwritten)."""
    path = out_dir / "scenario_report.md"
    kept = None
    if path.is_file() and path.read_text(encoding="utf-8") != text:
        previous = path.read_bytes()
        kept = out_dir / f"scenario_report.previous-{hashlib.sha256(previous).hexdigest()[:12]}.md"
        kept.write_bytes(previous)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return {"report_path": str(path), "previous_report_kept": str(kept) if kept else None}


ORIGIN_BANNER = {
    "REAL_HISTORICAL": "> **Origen: REAL HISTÓRICO.** Registros conservados de H1/H2, verificados por manifiesto; "
                       "R1 no se ha ejecutado. Consulta de solo lectura.\n\n",
    "SYNTHETIC": "> **Origen: SINTÉTICO (demostración offline).** La parte aérea es una copia REIDENTIFICADA del registro "
                 "H2 conservado: sus horas, hashes y errores son los del ensayo real del 24/10, no de una ejecución "
                 "nueva. R1 usa un ejecutor TEST_DOUBLE. No es una ejecución real y no completa ningún escenario.\n\n",
}


def _continue(state) -> str:
    return "report" if state.get("status") in STOP else "next"


builder = StateGraph(ScenarioState)
ORDER = [("load_artifacts", load_artifacts_node), ("bind_and_validate", bind_node), ("aerial_sequence", aerial_node),
         ("scenario_view", view_node), ("hermes_evidence", hermes_node), ("r1_prepare", r1_prepare_node),
         ("r1_coordinate", r1_coordinate_node)]
for node_name, node in ORDER + [("report", report_node)]:
    builder.add_node(node_name, node)
builder.add_edge(START, ORDER[0][0])
for (node_name, _), (following, _) in zip(ORDER, ORDER[1:] + [("report", None)]):
    builder.add_conditional_edges(node_name, _continue, {"next": following, "report": "report"})
builder.add_edge("report", END)
agri_scenario_graph = builder.compile()
