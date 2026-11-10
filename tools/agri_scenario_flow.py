"""Entry for the agri_demo_001 scenario flow (graph.agri_scenario_graph): query, offline demo, interactive menu.

a) query (default): read-only over REAL records. ``--source archive`` (default) uses the conserved, manifest-verified
   copies distributed with the repository; ``--source local`` reads the local stores under missions/generated
   (ignored by Git, so only on the machine that produced them). Never admits, starts or commands anything.
b) demo: offline SYNTHETIC run with its own identity (sequence, request keys) and storage (``--out``). The aerial
   record is a re-identified copy of the conserved H2 record; the R1 executor is a labelled TEST_DOUBLE whose state
   is persisted next to the demo, so a re-run resumes without a second admission.
c) real operations are NOT reachable here: the aerial sequence starts only through
   tools.preflight_sequences.start_preflight_sequence and R1 only through tools.agri_ground_coordinator.request with
   the real adapter, each behind its own authorization and gates.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

from graph.agri_scenario_graph import agri_scenario_graph, flow_record
from observability.hermes_capture_run import CaptureError, verify_manifest
from reporting import agri_scenario_summary as summary
from tools import agri_ground_coordinator as coordinator
from tools import agri_ground_demo as demo

ROOT = summary.PROJECT_ROOT
ARCHIVE = ROOT / "simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24"  # conserved H2 copies (REAL, read-only)
BINDING_RECORD = ROOT / summary.SCENARIOS[summary.SCENARIO_ID]["binding_record"]
H3B_EVIDENCE = ROOT / "evaluation/observability/agri_scenario_h3b_nous_2026_10_24"
DEMO_VARIANTS = {name: (view, transform, authorized, options)
                 for name, view, transform, authorized, options in demo.VARIANTS}
DEMO_VARIANTS["sequence_pending"] = ("base", True, True, {})  # aerial sequence still RUNNING
DEMO_VARIANTS["invalid_mission"] = ("base", True, True, {})  # a mission that fails deterministic validation
DEMO_VARIANTS["artifact_modified"] = ("base", True, True, {})  # an approved mission changed afterwards (same geometry)


class SourceUnavailable(ValueError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rel(path: Path) -> str:
    path = Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def _verified_copies(archive: Path) -> dict:
    """Every copy listed in the archive manifest must exist with its size and SHA-256."""
    manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
    copies = {}
    for entry in manifest["copies"]:
        path = archive / entry["copy"]
        if (not path.is_file() or path.is_symlink() or path.stat().st_size != entry["bytes"]
                or _sha(path.read_bytes()) != entry["sha256"]):
            raise SourceUnavailable(f"ARCHIVE_COPY_MISMATCH: {entry['copy']}")
        copies[entry["copy"]] = entry
    return copies


def archived_sequence(archive: Path = ARCHIVE) -> tuple[dict, dict]:
    """Rebuild the sequence query result from the conserved copies, with the identity checks of the sequence
    loader (plan digest, mission snapshots, child admissions, final report digests). No live store is read."""
    copies = _verified_copies(archive)
    plan_bytes = (archive / "sequence/plan.json").read_bytes()
    plan = json.loads(plan_bytes)
    op = json.loads((archive / "sequence/operation.json").read_text(encoding="utf-8"))
    if (op.get("plan_sha256") != _sha(plan_bytes) or op.get("sequence_id") != plan.get("sequence_id")
            or len(plan.get("children") or []) != 2 or len(op.get("children") or []) != 2):
        raise SourceUnavailable("ARCHIVE_SEQUENCE_INTEGRITY: plan/operation identity")
    children = []
    for index, (planned, saved) in enumerate(zip(plan["children"], op["children"])):
        child = f"child_{index + 1}_{planned['run_id'][:8]}"
        for name in (f"sequence/mission_{index + 1}.json", f"{child}/mission.json", f"{child}/job.json"):
            if name not in copies:
                raise SourceUnavailable(f"ARCHIVE_COPY_NOT_LISTED: {name}")
        mission = (archive / f"sequence/mission_{index + 1}.json").read_bytes()
        job = json.loads((archive / child / "job.json").read_text(encoding="utf-8"))
        if (_sha(mission) != planned["mission_sha256"] or _sha((archive / child / "mission.json").read_bytes())
                != planned["mission_sha256"] or job.get("run_id") != planned["run_id"]
                or job.get("sequence_id") != plan["sequence_id"] or job.get("sequence_index") != index
                or job.get("input_sha256") != planned["mission_sha256"]):
            raise SourceUnavailable(f"ARCHIVE_SEQUENCE_INTEGRITY: child {index + 1}")
        report = None
        if saved.get("report_sha256"):
            content = (archive / child / "report.json").read_bytes()
            if f"{child}/report.json" not in copies or _sha(content) != saved["report_sha256"]:
                raise SourceUnavailable(f"ARCHIVE_REPORT_MISMATCH: child {index + 1}")
            report = json.loads(content)
        children.append({**planned, **saved, "detail": {"report": report}})
    provenance = {"archive": _rel(archive), "archive_manifest_sha256": _sha((archive / "manifest.json").read_bytes()),
                  "copies_verified": len(copies), "sequence_id": plan["sequence_id"],
                  "plan_sha256": op["plan_sha256"]}
    return {**op, "plan": plan, "children": children}, provenance


def _binding_record(path: Path) -> tuple[dict, dict, dict]:
    verify_manifest(path.parent)  # the H1 evidence directory's own SHA256SUMS
    associations, expected = summary.record_associations(path)
    configured = summary.SCENARIOS[summary.SCENARIO_ID]["binding_record"]
    return associations, expected, {"path": configured, "sha256": _sha(path.read_bytes())}


class QuerySources:
    """REAL records, read-only. Holds no executor: nothing here can admit, start or command."""

    def __init__(self, *, source="archive", archive=ARCHIVE, binding_record=BINDING_RECORD,
                 r1_root=coordinator.TASK_ROOT):
        self.source, self.archive, self.binding_record, self.r1_root = source, Path(archive), Path(binding_record), r1_root

    def artifacts(self, state):
        associations, expected, record = _binding_record(self.binding_record)
        provenance = {"binding_record": record}
        if self.source == "archive":
            missions = {_sha(p.read_bytes()): p for p in sorted((self.archive / "sequence").glob("mission_*.json"))}
            for vehicle, sha in expected.items():
                if sha not in missions:
                    raise SourceUnavailable(f"NO_CONSERVED_COPY of the {vehicle} mission {sha[:12]}")
                associations[vehicle]["mission_path"] = str(missions[sha])
            provenance["missions"] = {v: _rel(missions[sha]) for v, sha in expected.items()}
        else:
            missing = [a["mission_path"] for a in associations.values() if not Path(a["mission_path"]).is_file()]
            if missing:
                raise SourceUnavailable("LOCAL_STORE_UNAVAILABLE: missions/generated is not distributed; "
                                        "use --source archive")
            provenance["missions"] = {v: _rel(a["mission_path"]) for v, a in associations.items()}
        return associations, expected, record, provenance

    def sequence(self, state):
        if self.source == "archive":
            sequence, provenance = archived_sequence(self.archive)
            return sequence, f"conserved copies verified ({provenance['copies_verified']} files)"
        from tools.preflight_sequences import get_preflight_sequence
        key = state.get("aerial_request_key") or summary.H2_REQUEST_KEY
        sequence = get_preflight_sequence(request_key=key, detail=True)
        if sequence.get("job_state") == "NOT_FOUND":
            check = summary.check_h2(self.binding_record, request_key=key)
            return sequence, (f"no sequence under {key}; read-only precheck {check['status']}; starting it needs an "
                              "operator authorization through start_preflight_sequence (not reachable from here)")
        return sequence, f"local sequence store, key {key}"

    def adjust_view(self, state, view):
        return view

    def hermes(self, state):
        """Recorded captures only: H1 produced the bound artifacts; H3b received a view that is compared with the
        one rebuilt here. No model is called and nothing is re-evaluated."""
        try:
            verify_manifest(H3B_EVIDENCE)
            received = json.loads((H3B_EVIDENCE / "tool_result_as_received.json").read_text(encoding="utf-8"))
            accepted = json.loads((H3B_EVIDENCE / "accept_h3b.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, CaptureError) as exc:
            return {"origin": "RECORDED_CAPTURE_UNAVAILABLE", "inference_performed": False,
                    "summary": f"{type(exc).__name__}"}
        same = len(received) == 1 and received[0].get("result") == state["view"]
        return {"origin": "RECORDED_CAPTURE", "inference_performed": False,
                "h1_planning": {"binding_status": "BOUND", "evidence": _rel(self.binding_record.parent)},
                "h3b_explanation": {"acceptance": accepted.get("status"), "view_received_equals_this_view": same,
                                    "explanation_review": "pending human review", "evidence": _rel(H3B_EVIDENCE)},
                "summary": f"H1 BOUND; H3b {accepted.get('status')}; view received by H3b "
                           f"{'equals' if same else 'DIFFERS FROM'} this view"}

    def executor_facts(self, state):
        return coordinator.RoverGroundExecutorAdapter().facts()  # the executor's own read-only facts

    def r1_inputs(self, state):
        return None  # no accredited R1 datum exists for the real scenario

    def coordinate(self, state):
        record = coordinator.query(Path(self.r1_root), state["r1_request_key"])  # read-only
        if record.get("state") == "NOT_FOUND":
            return {"state": "NOT_REQUESTED", "record": None,
                    "reason": "no R1 record under this key; a request needs an authorization and the ground "
                              "coordinator's request entry with the real adapter (not reachable from here)"}
        return {"state": record.get("state"), "record": record, "run_id": record.get("run_id"),
                "acceptance": record.get("acceptance"), "reason": record.get("reason")}


class PersistentDemoExecutor(demo.TestDoubleGroundExecutor):
    """The labelled TEST_DOUBLE executor with its jobs persisted next to the demo, so a restarted flow meets the
    same executor state (as a separate real executor would) and is never admitted twice."""

    def __init__(self, path: Path, **options):
        super().__init__(**options)
        self.path = Path(path)
        if self.path.is_file():
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.jobs, self.reservations, self.admit_calls = saved["jobs"], set(saved["reservations"]), saved["admit_calls"]

    def _save(self):
        self.path.write_text(json.dumps({"kind": self.kind, "jobs": self.jobs, "reservations": sorted(self.reservations),
                                         "admit_calls": self.admit_calls}, indent=2), encoding="utf-8")

    def admit(self, task):
        try:
            return super().admit(task)
        finally:
            self._save()

    def query(self, run_id):
        try:
            return super().query(run_id)
        finally:
            self._save()


class DemoSources(QuerySources):
    """SYNTHETIC scenario with its own identity. The model provider is substituted (no call; the conserved H1
    finalizations are the inputs) and the physical executor is a labelled TEST_DOUBLE."""

    def __init__(self, variant: str, out_dir: Path, *, archive=ARCHIVE, binding_record=BINDING_RECORD):
        if variant not in DEMO_VARIANTS:
            raise ValueError(f"unknown demo variant {variant}")
        super().__init__(source="archive", archive=archive, binding_record=binding_record, r1_root=Path(out_dir) / "r1")
        self.variant = variant
        self.view_name, self.transform, self.authorized, options = DEMO_VARIANTS[variant]
        self.executor = PersistentDemoExecutor(Path(out_dir) / "executor_test_double.json", **options)

    def artifacts(self, state):
        associations, expected, _, provenance = super().artifacts(state)
        if self.variant in ("invalid_mission", "artifact_modified"):  # SYNTHETIC alterations of a copy
            original = Path(associations["drone_02"]["mission_path"])
            altered = Path(state["out_dir"]) / "altered_drone_02_mission.json"
            data = json.loads(original.read_text(encoding="utf-8"))
            if self.variant == "invalid_mission":
                data["route"]["waypoints"] = []
                provenance["synthetic_alteration"] = "drone_02 mission without waypoints"
            else:
                data["name"] = data.get("name", "") + " (edited after approval)"
                provenance["synthetic_alteration"] = "drone_02 mission name edited after approval; geometry unchanged"
            altered.write_text(json.dumps(data), encoding="utf-8")
            associations["drone_02"]["mission_path"] = str(altered)
        return associations, expected, {"path": None, "sha256": "SYNTHETIC_DEMO"}, provenance

    def sequence(self, state):
        sequence, _ = archived_sequence(self.archive)
        sequence = copy.deepcopy(sequence)
        sequence["sequence_id"] = demo.DEMO_SEQUENCE_ID
        if self.view_name == "first_drone_failed":
            summary._synthetic_failed_first(sequence)
        if self.variant == "sequence_pending":
            sequence.update(job_state="RUNNING", result_status=None, finished_at=None)
            second = sequence["children"][1]
            second.update(state="RUNNING", result_status=None, report_sha256=None, finished_at=None)
            second["detail"] = {"report": None}
        return sequence, f"SYNTHETIC copy of the conserved H2 record, re-identified as {demo.DEMO_SEQUENCE_ID[:8]}"

    def adjust_view(self, state, view):
        if self.view_name == "poi_not_reached" and view.get("scenario"):
            view = copy.deepcopy(view)
            view["scenario"]["points"]["POI_A1"]["status"] = "NOT_REACHED"
            view["scenario"]["ground_task"]["dependency"] = "NOT_MET"
        return view

    def hermes(self, state):
        return {"origin": "SUBSTITUTED", "inference_performed": False,
                "summary": "model provider substituted: no call; the conserved H1 finalizations are the inputs"}

    def executor_facts(self, state):
        return self.executor.facts()

    def r1_inputs(self, state):
        return demo.demo_inputs(transform=self.transform)

    def coordinate(self, state):
        root, key, view = Path(self.r1_root), state["r1_request_key"], state["view"]
        inputs = self.r1_inputs(state)
        prepared = coordinator.prepare(view, inputs, self.executor)
        authorization = demo.demo_authorization(prepared) if self.authorized and prepared["candidate"] else None
        first = coordinator.request(root, key, view, inputs, authorization, self.executor)
        repeated = coordinator.request(root, key, view, inputs, authorization, self.executor)  # never a 2nd job
        if self.executor.admit_mode == "LOSE_RESPONSE":
            self.executor.admit_mode = "ADMIT"  # the executor recovered; the coordinator must still not re-admit
        tracked = []
        for _ in range(4):  # each call reads only the durable record, like a restarted coordinator
            record = coordinator.track(root, key, self.executor)
            tracked.append(record.get("state"))
            if record.get("state") in coordinator.TERMINAL or record.get("state") == "NOT_FOUND":
                break
        final = coordinator.query(root, key)
        found = final.get("state") != "NOT_FOUND"
        return {"state": final.get("state") if found else "NOT_REQUESTED", "record": final if found else None,
                "run_id": final.get("run_id"), "acceptance": final.get("acceptance"),
                "request_status": first.get("request_status"), "request_reason": first.get("reason"),
                "repeat_request_status": repeated.get("request_status"), "tracked_states": tracked,
                "admit_calls": self.executor.admit_calls, "reservations_held": sorted(self.executor.reservations),
                "reason": first.get("reason") or final.get("reason")}


def terminal(print_fn=print):
    """Stage lines in the project's terminal style: what works, what it waits on, its result and reason."""
    def emit(event):
        if event["event"] == "begin":
            print_fn(f"\n[ESCENARIO {summary.SCENARIO_ID}] modo {event['mode']} · origen {event['origin']}"
                     + (f" · variante {event['variant']}" if event.get("variant") else "")
                     + " · sin órdenes ni procesos operativos · Ctrl+C para salir")
        elif event["event"] == "start":
            print_fn(f"\n[{event['node']}] trabajando · espera: {event['waiting_on']}")
        else:
            print_fn(f"[{event['node']}] resultado: {event['result']}"
                     + (f" · motivo: {event['reason']}" if event.get("reason") else ""))
    return emit


OUTPUTS_MANIFEST = "outputs_manifest.json"
OUTPUTS_SCHEMA = "tfg.agri-scenario-flow-outputs/1"


class ResumeRefused(ValueError):
    pass


def _output_files(out_dir: Path) -> dict:
    return {p.relative_to(out_dir).as_posix(): _sha(p.read_bytes()) for p in sorted(out_dir.rglob("*"))
            if p.is_file() and p.name != OUTPUTS_MANIFEST and p.suffix != ".tmp"}


def _write_outputs(out_dir: Path, identity: dict, state: str, **extra) -> None:
    body = {"schema": OUTPUTS_SCHEMA, "state": state, "identity": identity, **extra,
            "files": _output_files(out_dir) if state == "FINISHED" else None}
    temporary = out_dir / (OUTPUTS_MANIFEST + ".tmp")
    temporary.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(out_dir / OUTPUTS_MANIFEST)


def _check_resume(out_dir: Path, identity: dict) -> dict:
    """A resume continues THE SAME flow over unaltered outputs; it never permits a new admission (the coordinator's
    idempotency and the executor's own state decide that). Interrupted runs are resumable but marked as such."""
    manifest_path = out_dir / OUTPUTS_MANIFEST
    if not manifest_path.is_file():
        if any(out_dir.iterdir()):
            raise ResumeRefused("NO_OUTPUTS_MANIFEST: the directory holds files of no recorded flow")
        return {"resumed": False}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != OUTPUTS_SCHEMA or manifest.get("identity") != identity:
        raise ResumeRefused(f"IDENTITY_MISMATCH: recorded {manifest.get('identity')}, requested {identity}")
    if manifest.get("state") == "IN_PROGRESS":
        return {"resumed": True, "after_interruption": True}
    current = _output_files(out_dir)
    altered = sorted(name for name in set(current) | set(manifest.get("files") or {})
                     if current.get(name) != (manifest.get("files") or {}).get(name))
    if altered:
        raise ResumeRefused("DERIVED_FILES_ALTERED: " + ", ".join(altered))
    return {"resumed": True, "after_interruption": False}


def run_flow(sources, *, mode: str, origin: str, r1_request_key: str, out_dir: Path | None = None,
             capture: dict | None = None, aerial_request_key: str | None = None, variant: str | None = None,
             rover_identity: dict | None = None,
             emit=None, resume: dict | None = None) -> dict:
    state = {"mode": mode, "source": sources.source if mode == "query" else "synthetic", "origin": origin,
             "variant": variant, "aerial_request_key": aerial_request_key, "r1_request_key": r1_request_key,
             "out_dir": str(out_dir) if out_dir else None, "capture": capture, "rover_identity": rover_identity, "status": "OK", "reasons": [],
             "transitions": [], "resume": resume or {"resumed": False}}
    if emit:
        emit({"event": "begin", "mode": mode, "origin": origin, "variant": variant})
    return agri_scenario_graph.invoke(state, config={"configurable": {"sources": sources, "emit": emit}})


def query(*, source="archive", out_dir=None, capture=None, aerial_request_key=None, emit=None, rover_identity=None,
          r1_request_key="agri-demo-001-r1", **kw) -> dict:
    """Read-only. ``out_dir`` must be NEW: a query is repeated into a new directory, never over an older one."""
    identity = {"mode": "query", "source": source, "r1_request_key": r1_request_key}
    if out_dir is not None:
        Path(out_dir).mkdir(parents=True, exist_ok=False)
        _write_outputs(Path(out_dir), identity, "IN_PROGRESS")
    final = run_flow(QuerySources(source=source, **kw), mode="query", origin="REAL_HISTORICAL",
                     r1_request_key=r1_request_key, out_dir=out_dir, capture=capture, rover_identity=rover_identity,
                     aerial_request_key=aerial_request_key, emit=emit)
    if out_dir is not None:
        _write_outputs(Path(out_dir), identity, "FINISHED", flow_status=final.get("status"))
    return final


def run_demo(variant: str, out_dir: Path, *, resume=False, emit=None, **kw) -> dict:
    """SYNTHETIC. A new directory, or ``resume=True`` over the outputs of the SAME flow (same variant and identity),
    unaltered since it finished, or left by an interrupted run."""
    out_dir = Path(out_dir)
    identity = {"mode": "demo", "variant": variant, "r1_request_key": f"synthetic-r1-{variant}",
                "sequence_id": demo.DEMO_SEQUENCE_ID}
    if variant not in DEMO_VARIANTS:
        raise ValueError(f"unknown demo variant {variant}")
    out_dir.mkdir(parents=True, exist_ok=resume)
    resumed = _check_resume(out_dir, identity) if resume else {"resumed": False}
    _write_outputs(out_dir, identity, "IN_PROGRESS", resume=resumed)
    final = run_flow(DemoSources(variant, out_dir, **kw), mode="demo", origin="SYNTHETIC",
                     r1_request_key=identity["r1_request_key"], out_dir=out_dir, variant=variant, emit=emit,
                     resume=resumed)
    _write_outputs(out_dir, identity, "FINISHED", resume=resumed, flow_status=final.get("status"))
    return final


def _dimension_lines(d: dict | None) -> list[str]:
    if not d:
        return []
    prep = d["eligibility"]["this_preparation"]
    return [f"R1 · dependencia: {d['dependency']} · elegibilidad (vista histórica): "
            f"{d['eligibility']['historical_view']['status']} · elegibilidad (esta preparación): {prep['eligibility']}"
            + (f" [{', '.join(prep['blockers'])}]" if prep.get("blockers") else ""),
            f"R1 · autorización: {d['authorization']} · solicitud: {d['request']['status']} · ejecución: "
            f"{d['execution']['status']}"
            + (f" (aceptación {d['execution']['acceptance']})" if d["execution"].get("acceptance") else "")]


def _summary_lines(final: dict) -> list[str]:
    record = flow_record(final)
    scenario = record.get("scenario") or {}
    return ["", f"[ESCENARIO {summary.SCENARIO_ID}] origen: {final.get('origin')} · modo: {final.get('mode')}",
            f"Estado del flujo: {final.get('status')} (última etapa {final.get('stage')})",
            f"Escenario: {scenario.get('scenario_status', 'sin vista')}; completo: "
            f"{'sí' if scenario.get('scenario_complete') else 'no'}"
            + ("; completo solo como demostración sintética" if scenario.get("synthetic_complete") else ""),
            *_dimension_lines(record.get("r1_dimensions")),
            *([f"Hechos medidos (captura /3): {final['preparation']['measured_facts']['status']}"]
              if final.get("capture") is not None and final.get("preparation") else []),
            *([f"Hechos de identidad (sesión {(final['rover_identity'] or {}).get('session_id', '—')}): "
               f"{final['preparation']['identity_facts']['status']}"]
              if final.get("rover_identity") is not None and final.get("preparation") else []),
            f"Coordinador R1: {record['r1']['state']}; aceptación: {record['r1']['acceptance'] or 'sin resultado'}"
            + (f"; motivo: {record['r1']['reason']}" if record["r1"].get("reason") else ""),
            *(["Reanudado tras una interrupción: el registro del coordinador y el estado del ejecutor deciden; "
               "no se readmite"] if (final.get("resume") or {}).get("after_interruption") else []),
            *([f"Informe anterior distinto conservado: {final['previous_report_kept']}"]
              if final.get("previous_report_kept") else []),
            *(f"Motivo: {reason}" for reason in final.get("reasons", [])),
            f"Informe: {final.get('report_path') or 'no escrito (sin --out)'}",
            f"Registro del flujo: {str(Path(final['out_dir']) / 'flow_record.json') if final.get('out_dir') else 'no escrito'}"]


EXIT_WORDS = {"exit", "quit", "salir"}


def _package_menu(input_fn, print_fn) -> bool:
    """Prompts for tools.scenario_package; the same CLI does the work. Returns False to close the program."""
    from contextlib import redirect_stdout
    import io

    from tools import scenario_package

    fleet = "missions/fleets/agri_demo_fleet.json"
    print_fn("\na. Validate a site.json   b. Package a template over a site   c. Package the historical H2 missions")
    print_fn("d. Verify a package       e. Summarize a package")
    print_fn("f. Package missions finalized by Hermes over an explicitly selected site")
    choice = input_fn("Action: ").strip().lower()
    if choice in EXIT_WORDS:
        return False
    prompts = {"a": [("site.json", None)],
               "b": [("template", "missions/templates/agri_poi_visit_v1.json"), ("site.json", None),
                     ("fleet", fleet), ("target sitl|field", "sitl"), ("NEW output directory", None)],
               "c": [("NEW output directory", None)], "d": [("package directory", None)],
               "e": [("package directory", None)],
               "f": [("planning store (holds drafts/)", None),
                     ("assignments VEHICLE=DRAFT_ID/FINALIZATION_ID@TAKEOFF_POINT, separated by spaces", None),
                     ("rover VEHICLE@ROVER_START_POINT or 'none'", "rover_01@ROVER_START"),
                     ("scenario binding or 'none'",
                      "evaluation/observability/agri_planning_h1_nous_2026_10_24/h1_binding.json"),
                     ("Hermes run evidence directory or 'none'", "none"), ("site.json", None), ("fleet", fleet),
                     ("target sitl|field", "sitl"), ("NEW output directory", None)]}
    if choice not in prompts:
        print_fn("\nInvalid action.")
        return True
    values = []
    for label, default in prompts[choice]:
        value = input_fn(f"{label}{f' [{default}]' if default else ''}: ").strip() or default
        if value in EXIT_WORDS:
            return False
        if not value:
            print_fn("\nA value is required.")
            return True
        values.append(value)
    argv = {"a": lambda v: ["validate-site", v[0]],
            "b": lambda v: ["package", "--template", v[0], "--site", v[1], "--fleet", v[2], "--target", v[3],
                            "--out", v[4]],
            "c": lambda v: ["package-historical", "--fleet", fleet, "--out", v[0]],
            "d": lambda v: ["verify", v[0]], "e": lambda v: ["summary", v[0]],
            "f": lambda v: ["package-finalized", "--store", v[0], *[x for a in v[1].split() for x in ("--assign", a)],
                            *(["--rover", v[2]] if v[2] != "none" else []),
                            *(["--scenario-binding", v[3]] if v[3] != "none" else []),
                            *(["--hermes-evidence", v[4]] if v[4] != "none" else []),
                            "--site", v[5], "--fleet", v[6], "--target", v[7], "--out", v[8]]}[choice](values)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = scenario_package.main(argv)
    for line in buffer.getvalue().splitlines():
        print_fn(line)
    print_fn(f"[exit code {code}]")
    return True


def run_interactive(input_fn=input, print_fn=print) -> bool:
    """Menu entry from main.py. Returns False to close the program, True to go back to the main menu.
    'exit', Ctrl+C or Ctrl+D close it at any prompt or during a run; 'menu' returns."""
    print_fn("\nAGRICULTURAL SCENARIO agri_demo_001")
    print_fn("Read-only and offline: no order, admission or process is started from this menu.")
    print_fn("Write 'menu' to return to the main menu, 'exit' (or Ctrl+C) to close the program.")
    while True:
        print_fn("\n1. Historical H2 (REAL, conserved copies): query and R1 preparation")
        print_fn("2. Offline SYNTHETIC demo (own identity and storage)")
        print_fn("3. Site, fleet and scenario package (offline: validate, instantiate, export, verify)")
        print_fn("4. Back to main menu")
        try:
            option = input_fn("\nSelect option: ").strip().lower()
            if option in EXIT_WORDS:
                return False
            if option in {"4", "menu"}:
                return True
            if option == "3":
                if not _package_menu(input_fn, print_fn):
                    return False
                continue
            if option == "1":
                final = query(emit=terminal(print_fn))
            elif option == "2":
                print_fn("Variants: " + ", ".join(DEMO_VARIANTS))
                variant = input_fn("Variant [complete]: ").strip() or "complete"
                if variant in EXIT_WORDS:
                    return False
                out = input_fn("NEW output directory: ").strip()
                if out in EXIT_WORDS:
                    return False
                if variant not in DEMO_VARIANTS or not out:
                    print_fn("\nInvalid variant or directory.")
                    continue
                try:
                    final = run_demo(variant, Path(out), emit=terminal(print_fn))
                except FileExistsError:
                    print_fn("\nThe directory exists; the demo needs a new one (or the CLI's --resume).")
                    continue
                except OSError as exc:
                    print_fn(f"\nCould not write ({exc}). The outputs are NOT marked finished; *.tmp files are not "
                             "records. Use a writable directory (in the container: /work/<new name>), or the CLI's "
                             "--resume over the same directory once writing is possible.")
                    continue
            else:
                print_fn("\nInvalid option.")
                continue
        except (KeyboardInterrupt, EOFError):  # durable records are kept; nothing is retried
            print_fn("\nInterrupted. Durable records are kept; nothing is retried.")
            return False
        for line in _summary_lines(final):
            print_fn(line)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    q = sub.add_parser("query", help="read-only flow over REAL records (default: conserved copies)")
    q.add_argument("--source", choices=("archive", "local"), default="archive")
    q.add_argument("--aerial-request-key", default=None, help="local source only (default: the H2 key)")
    q.add_argument("--out", type=Path, default=None, help="NEW directory for the report and the flow record")
    q.add_argument("--capture-trial-root", type=Path, default=None, help="finished passive capture: measured facts")
    q.add_argument("--capture-dir", default=None)
    q.add_argument("--identity-trial-root", type=Path, default=None,
                   help="closed rover identity session (manifest-verified): facts shown, never a gate")
    d = sub.add_parser("demo", help="offline SYNTHETIC flow with its own identity and storage")
    d.add_argument("--variant", choices=sorted(DEMO_VARIANTS), default="complete")
    d.add_argument("--out", type=Path, required=True, help="NEW directory (or an existing one with --resume)")
    d.add_argument("--resume", action="store_true", help="re-run over the same storage: no second admission")
    sub.add_parser("variants", help="list the demo variants")
    args = parser.parse_args(argv)
    if args.command == "variants":
        print("\n".join(DEMO_VARIANTS))
        return 0
    emit = terminal()
    capture = rover_identity = None
    if args.command == "query":
        if args.identity_trial_root is not None:
            from reporting.rover_identity_facts import identity_facts
            rover_identity = identity_facts(args.identity_trial_root)
        if args.capture_trial_root is not None:
            from tools.rover_passive_journal import analyze_capture
            capture = {"value": analyze_capture(args.capture_trial_root, args.capture_dir or ""),
                       "source": f"PASSIVE_CAPTURE {_rel(args.capture_trial_root)} (origin as declared by its trial)"}
    try:
        if args.command == "query":
            final = query(source=args.source, out_dir=args.out, capture=capture, rover_identity=rover_identity,
                          aerial_request_key=args.aerial_request_key, emit=emit)
        else:
            final = run_demo(args.variant, args.out, resume=args.resume, emit=emit)
    except FileExistsError:
        print(f"{args.out} exists: use a new directory" + (" or --resume" if args.command == "demo" else ""),
              file=sys.stderr)
        return 2
    except ResumeRefused as exc:
        print(f"resume refused: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted: durable records are kept; resume the demo with --resume over the same directory "
              "(no second admission)", file=sys.stderr)
        return 130
    except OSError as exc:  # disk full, read-only or no permission while persisting
        print(f"\nwrite failed: {exc}. The outputs are NOT marked finished. Any *.tmp left behind is not a record "
              "(never read; replaced by the next successful write) and may remain if the storage does not allow "
              "removing it. Once writing is possible, resume the demo with --resume over the same directory "
              "(no second admission) or run the query into a new directory.", file=sys.stderr)
        return 4
    for line in _summary_lines(final):
        print(line)
    return 0 if final.get("status") == "COMPLETED_FLOW" else 3


if __name__ == "__main__":
    raise SystemExit(main())
