"""Scenario package: one ``.plan`` per compatible drone, a common manifest and an export report.

Offline only: no simulation, upload, control or inference. A package records each artifact's state
explicitly (GENERATED, BLOCKED_MISSING_DATA, BLOCKED_VALIDATION_FAILED, COMPATIBILITY_PENDING,
UNSUPPORTED_FORMAT) and is never "ready to deploy": exported is not imported in QGroundControl, uploaded,
read back from the vehicle or executed, and those steps are listed as NOT_DONE.

Four separate layers, none of which implies the next:
1. operator declaration: ``status``/``verification`` fields typed into site.json (a declaration, not a check);
2. measurement provenance: ``provenance`` (who measured, when, how);
3. geometric validation: ``validate_site`` and the route checks (planned lines only);
4. deployment approval: an ``approval.json`` whose hashes match this instance (BOUND). It binds a declared name
   to exact files; it does not authenticate anyone and does not perform any of the NOT_DONE steps.

Usage (from the repository root):
  python -m tools.scenario_package validate-site missions/sites/synthetic_orchard_v1.site.json
  python -m tools.scenario_package validate-fleet missions/fleets/agri_demo_fleet.json
  python -m tools.scenario_package instantiate --template T --site S --fleet F
  python -m tools.scenario_package package --template T --site S --fleet F --target sitl --out NEW_DIR [--approval A]
  python -m tools.scenario_package package-historical --fleet F --out NEW_DIR
  python -m tools.scenario_package package-finalized --store STORE --site S --fleet F --target sitl --out NEW_DIR \
      --assign drone_01=DRAFT_ID/FINALIZATION_ID@TAKEOFF_POINT [--assign ...] [--rover rover_01@ROVER_START_POINT] \
      [--scenario-binding BINDING.json] [--hermes-evidence RUN_DIR] [--planning-margin-m M] [--approval A]
  python -m tools.scenario_package approval-draft --package DIR --out FILE
  python -m tools.scenario_package verify DIR
  python -m tools.scenario_package summary DIR
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from inputs.qgc_plan_export import (
    PROFILE, SUPERSEDED_PROFILES, ExportRefused, build_plan, plan_bytes, verify_plan,
)
from models.fleet import QGC_PROFILE, Fleet
from models.mission_definition import MissionDefinition
from models.site import Site
from planning.scenario_instance import (
    approval_draft, canonical, check_approval, finalized_instance, historical_h2_instance, instantiate, sha256,
)
from planning.site_validation import validate_site

MANIFEST_SCHEMA = "tfg.scenario-package/1"
NOT_DONE_STEPS = ("imported_in_qgroundcontrol", "uploaded_to_vehicle", "read_back_from_vehicle", "executed")
VERSIONS = {
    "ardupilot_executed": "ArduCopter/ArduRover V4.8.0-dev (755258db) as reported by SITL in logs of 20-26/10/2026 "
                          "(e.g. results/gui_control_two_drones_2026_10_25, rover_identity_trial_2026_10_26; image "
                          "sha256:5d5de3c6...); the H2 record of 24/10 keeps no firmware version or image id",
    "ardupilot_source_consulted": "local clean tree at 755258dbb452 (~/TFG/ardupilot_ros2_ws/src/ardupilot)",
    "qgroundcontrol": "UNKNOWN: no installation found; plan format from the QGC master documentation (27/10/2026)",
    "physical_vehicles": "UNKNOWN",
}
UNVERIFIED_PARAMETERS = ("WP_RADIUS_M (waypoint acceptance)", "WP_YAW_BEHAVIOR (yaw)", "WP_SPD (default speed)",
                         "FS_* (failsafe actions)", "LAND_SPD_MS / descent (landing rate)")


def _artifact_state(entry: dict, fleet: Fleet | None, target: str, site_report: dict | None) -> tuple[str, list[str]]:
    blocks = [reason for _, reason in entry.get("blocks", [])]
    kinds = [kind for kind, _ in entry.get("blocks", [])]
    for kind in ("COMPATIBILITY_PENDING", "UNSUPPORTED_FORMAT", "BLOCKED_MISSING_DATA"):
        if kind in kinds:
            return kind, blocks
    if target == "field":
        field_blocks = (site_report or {}).get("export_blocks", {}).get("field") or (
            ["historical SITL missions are not field missions"] if site_report is None else [])
        if field_blocks:
            return "BLOCKED_MISSING_DATA", field_blocks
    vehicle = fleet.vehicle(entry["vehicle_id"]) if fleet else None
    if fleet is not None and vehicle is None:
        return "BLOCKED_MISSING_DATA", [f"{entry['vehicle_id']} is not in the fleet"]
    if vehicle is not None and vehicle.export_profile != QGC_PROFILE:
        return "UNSUPPORTED_FORMAT", [f"{vehicle.vehicle_id}: export profile {vehicle.export_profile}"]
    failures = []
    deterministic = entry.get("deterministic_validation") or {}
    if deterministic.get("execution_status") != "APPROVED" or deterministic.get("errors"):
        failures.append(f"deterministic validation {deterministic.get('mission_status')}/"
                        f"{deterministic.get('execution_status')}")
    if entry["spatial_validation"]["status"] == "FAIL":
        failures.extend(c["check"] + ": " + c["detail"] for c in entry["spatial_validation"]["checks"]
                        if c["status"] == "FAIL")
    return ("BLOCKED_VALIDATION_FAILED", failures) if failures else ("GENERATED", [])


def _pending(instance: dict, artifacts: list[dict], approval: dict) -> list[str]:
    """Everything still conditioned or unknown, for the summary and the report (not only the JSON)."""
    pending = [f"operator approval {approval['status']}"]
    for entry in instance["aerial"]:
        margin = (entry.get("spatial_validation") or {}).get("margin")
        if margin:
            pending.append(f"{entry['task_id']}: margin {margin['status']} ({margin['kind']} "
                           f"{margin['planning_margin_m']} m)")
        if (entry.get("spatial_validation") or {}).get("status") == "NOT_CHECKABLE":
            pending.append(f"{entry['task_id']}: spatial checks NOT_CHECKABLE "
                           f"({entry['spatial_validation'].get('detail', 'no site')})")
        unchecked = (entry.get("spatial_validation") or {}).get("unchecked") or []
        if unchecked:
            pending.append(f"{entry['task_id']}: not checkable: {', '.join(unchecked)}")
    conditioned = sorted({row["element"] for a in artifacts for row in (a.get("conversion") or {}).get("semantics", [])
                          if row["status"] != "EXACT"})
    if conditioned:
        pending.append("conditioned or not in the .plan: " + ", ".join(conditioned))
    if any(a.get("plan_file") for a in artifacts):
        pending.append("autopilot parameters not read: " + ", ".join(UNVERIFIED_PARAMETERS))
        pending.append("QGroundControl version unknown; " + ", ".join(f"{s}: NOT_DONE" for s in NOT_DONE_STEPS))
    return pending


def build_package(bundle: dict, out: Path, *, target: str, approval: dict | None = None) -> dict:
    """Write a new package directory atomically; an existing directory is never overwritten."""
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"{out} exists; packages are never overwritten")
    instance, fleet = bundle["instance"], bundle["fleet"]
    site_report = instance.get("site_validation")
    scope = {"sitl": "SITL_REHEARSAL", "field": "FIELD"}[target]
    files: dict[str, bytes] = {name: data for name, data in bundle["sources"].items() if data is not None}
    artifacts = []
    for entry in instance["aerial"]:
        state, reasons = _artifact_state(entry, fleet, target, site_report)
        record = {"task_id": entry["task_id"], "vehicle_id": entry["vehicle_id"], "state": state, "reasons": reasons,
                  "mission_id": entry.get("mission_id"), "mission_sha256": entry.get("mission_sha256"),
                  "profile": PROFILE if state == "GENERATED" else None}
        mission_data = bundle["missions"].get(entry["task_id"]) or bundle["missions"].get(entry["vehicle_id"])
        if mission_data is not None:
            mission_name = f"missions/{entry['task_id']}.{entry['vehicle_id']}.mission.json"
            files[mission_name] = mission_data
            record["mission_file"] = mission_name
        if state == "GENERATED":
            mission = MissionDefinition.model_validate_json(mission_data)
            observed = entry["planned_home"].get("return_coordinate_is_observed_launch", False)
            try:
                plan, log = build_plan(mission, planned_home_amsl_m=entry["planned_home"]["amsl_m"],
                                       return_coordinate_is_observed_launch=observed)
            except ExportRefused as exc:
                record.update(state="UNSUPPORTED_FORMAT", reasons=exc.reasons, profile=None)
            else:
                plan_name = f"plans/{entry['vehicle_id']}.plan"
                files[plan_name] = plan_bytes(plan)
                record.update(plan_file=plan_name, plan_sha256=sha256(files[plan_name]), conversion=log,
                              planned_home=entry["planned_home"])
        artifacts.append(record)
    approval_check = check_approval(approval, instance, scope)
    if approval is not None:
        files["approval.json"] = canonical(approval)
    generated = [a for a in artifacts if a["state"] == "GENERATED"]
    complete = len(generated) == len(artifacts) and instance["coordination"]["status"] == "PASS"
    manifest = {
        "schema": MANIFEST_SCHEMA, "instance_id": instance["instance_id"], "provenance": instance["provenance"],
        "target": scope, "inputs": instance["inputs"], "versions": VERSIONS,
        "site": None if site_report is None else {"id": site_report["site_id"], "version": site_report["version"],
                                                  "status": site_report["site_status"],
                                                  "sha256": instance["inputs"]["site"]["sha256"],
                                                  "validation": site_report["status"]},
        "vehicles": sorted({a["vehicle_id"] for a in artifacts} | {g["vehicle_id"] for g in instance["ground"]}),
        "artifacts": artifacts, "ground_tasks": instance["ground"], "coordination": instance["coordination"],
        "joint_spatial": instance["joint_spatial"], "references": instance["references"],
        "approval": approval_check,
        "layers": {"operator_declaration": None if site_report is None else site_report["site_status"],
                   "measurement_provenance": None if site_report is None else
                   (bundle["site"].provenance.kind if bundle.get("site") else None),
                   "geometric_validation": None if site_report is None else site_report["status"],
                   "deployment_approval": approval_check["status"]},
        "package_status": "COMPLETE_OFFLINE" if complete else "PARTIAL",
        "deployment_ready": False,
        "lifecycle": {"exported": "DONE" if generated else "NOT_DONE", "file_checks": "PENDING",
                      **{step: "NOT_DONE" for step in NOT_DONE_STEPS}},
        "limitations": [
            "checks cover planned straight lines, not flown trajectories, unknown obstacles or collisions",
            "relative altitudes refer to the EFFECTIVE home set at arming, not to plannedHomePosition",
            "requested speeds are DO_CHANGE_SPEED requests, not validated speeds",
            "the .plan returns to a planned COORDINATE and lands (NAV_LAND); it does not use RTL",
            "no geofence exported",
            "individual .plan files do not coordinate vehicles; order and dependencies live in the coordinator",
            "our importer reads the file back with losses (TAKEOFF dropped, LAND reduced to a waypoint)",
        ],
    }
    manifest["pending_conditions"] = _pending(instance, artifacts, approval_check)
    # Every task that cannot run as recorded, so a structurally valid sequence is never read as executable.
    task_blockers = [*(f"{a['task_id']} {a['state']}" for a in artifacts if a["state"] != "GENERATED"),
                     *(f"{g['task_id']} {g['export'].split(':', 1)[0]}" for g in instance["ground"]
                       if g["export"].startswith("FORMAT_PENDING"))]
    manifest["deployment_blockers"] = [*(["PARTIAL package"] if not complete else []), *task_blockers,
                                       f"operator approval {approval_check['status']}",
                                       *[f"{step}: NOT_DONE" for step in NOT_DONE_STEPS]]
    files["instance.json"] = canonical(instance)
    # Check the written bytes before publishing the directory.
    staging = Path(tempfile.mkdtemp(prefix=".package-", dir=out.parent))
    try:
        for name, data in files.items():
            (staging / name).parent.mkdir(parents=True, exist_ok=True)
            (staging / name).write_bytes(data)
        for record in artifacts:
            if record.get("plan_file"):
                mission = MissionDefinition.model_validate_json(files[record["mission_file"]])
                record["verification"] = verify_plan(staging / record["plan_file"], mission,
                                                     planned_home_amsl_m=record["planned_home"]["amsl_m"])
        results = {r["verification"]["status"] for r in artifacts if r.get("verification")}
        readback = sorted({r["verification"]["importer_readback"]["status"] for r in artifacts if r.get("verification")})
        manifest["lifecycle"]["file_checks"] = ("NOT_APPLICABLE" if not results else
                                                f"{'FAILED' if 'FAILED' in results else 'FILE_MATCHES_EXPECTATIONS'}; "
                                                f"importer readback {'/'.join(readback)}")
        report = render_report(manifest)
        (staging / "export_report.md").write_bytes(report.encode("utf-8"))
        files["export_report.md"] = report.encode("utf-8")
        manifest["files"] = {name: sha256(data) for name, data in sorted(files.items())}
        (staging / "manifest.json").write_bytes(canonical(manifest))
        sums = {**manifest["files"], "manifest.json": sha256((staging / "manifest.json").read_bytes())}
        (staging / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for n, h in sorted(sums.items())), encoding="utf-8")
        os.rename(staging, out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest


def render_report(manifest: dict) -> str:
    lines = [f"# Informe de exportación {manifest['instance_id']}", "",
             f"- Procedencia: **{manifest['provenance']}**; destino: {manifest['target']}.",
             f"- Estado del paquete: **{manifest['package_status']}**; listo para desplegar: **no**.",
             f"- Aprobación del operador: {manifest['approval']['status']}"
             + (f" ({', '.join(manifest['approval']['mismatches'])})" if manifest["approval"]["mismatches"] else "")
             + " (vincula hashes; no autentica).",
             f"- Comprobación de archivos: {manifest['lifecycle']['file_checks']}.",
             ""]
    if manifest["site"]:
        s = manifest["site"]
        lines += [f"Emplazamiento `{s['id']}` v{s['version']} (declarado {s['status']}), validación {s['validation']}, "
                  f"sha256 `{s['sha256'][:12]}…`.", ""]
    finalized = manifest["inputs"].get("finalized_missions")
    if finalized:
        run = manifest["inputs"].get("hermes_run")
        derived = {a["vehicle_id"]: a.get("mission_sha256") for a in manifest["artifacts"]}
        takeoff = {a["vehicle_id"]: a["takeoff_point"] for a in manifest["inputs"]["assignments"]}
        lines += ["## Origen: misiones finalizadas por Hermes", "",
                  f"- Ejecución: {run['run_id']} ({run['provider']} / {run['model']}, retorno {run['return_code']}, "
                  f"revisión {run['review_verdict']})." if run else "- Ejecución de Hermes: no vinculada (solo el almacén)."]
        lines += [f"- {v}: finalización `{f['finalization_id']}` (borrador `{f['draft_id']}`), misión original "
                  f"`{f['mission_sha256'][:12]}…` → derivada sobre {takeoff[v]} "
                  f"`{(derived.get(v) or '—')[:12]}`. La aprobación de la original **no** se hereda."
                  for v, f in finalized.items()]
        lines.append("")
    lines += ["| Tarea | Vehículo | Estado | Misión | .plan | Motivos |", "| --- | --- | --- | --- | --- | --- |"]
    for a in manifest["artifacts"]:
        lines.append(f"| {a['task_id']} | {a['vehicle_id']} | {a['state']} | "
                     f"{(a.get('mission_sha256') or '—')[:12]} | {a.get('plan_file') or '—'} | "
                     f"{'; '.join(a['reasons']) or '—'} |")
    for a in manifest["artifacts"]:
        if a.get("conversion"):
            lines += ["", f"## Semántica {a['task_id']} ({a['profile']})", "",
                      f"Alcance de las etiquetas: {a['conversion'].get('label_scope', '—')}", "",
                      "| Elemento | Estado | Detalle |", "| --- | --- | --- |"]
            lines += [f"| {r['element']} | {r['status']} | {r['detail']} |" for r in a["conversion"]["semantics"]]
            rb = a["verification"]["importer_readback"]
            lines.append(f"\nLectura con nuestro importador: {rb['status']}; pérdidas: {'; '.join(rb.get('losses') or []) or '—'}.")
    lines += ["", "## Tareas terrestres", ""]
    for g in manifest["ground_tasks"]:
        lines.append(f"- {g['task_id']} ({g['vehicle_id']} → {g['target_point']}): línea "
                     f"{g['spatial_validation']['status']}; {g['export']}; transformación {g['frame_transform_to_rover']}.")
    c = manifest["coordination"]
    lines += ["", "## Coordinación", "",
              f"- Estructura de dependencias: {c['status']} {c['errors'] or ''}(solo estructura: tareas, vehículos, "
              "orden y ciclos; no indica que los artefactos estén disponibles, aprobados ni listos para ejecutar)",
              f"- Orden {c['mode']}: {' → '.join(c['order'])}"]
    lines += [f"- {d['task_id']} tras {d['after']}: {d['condition']}" + (f" {d['point']}" if d.get("point") else "")
              for d in c["dependencies"]]
    lines += [f"- Separación mínima planificada {p['pair'][0]}–{p['pair'][1]}: {p['min_horizontal_distance_m']} m; "
              f"simultaneidad {p['simultaneous_execution']}" for p in manifest["joint_spatial"]["pairs"]]
    lines += ["", "## Bloqueos de despliegue (deployment_ready: false)", ""] + [
        f"- {x}" for x in manifest.get("deployment_blockers", [])]
    lines += ["", "## Pendiente o condicionado", ""] + [f"- {x}" for x in manifest["pending_conditions"]]
    lines += ["", "## Versiones", ""] + [f"- {k}: {v}" for k, v in manifest["versions"].items()]
    lines += ["", "## Ciclo de vida", ""] + [f"- {k}: {v}" for k, v in manifest["lifecycle"].items()]
    lines += ["", "## Limitaciones", ""] + [f"- {x}" for x in manifest["limitations"]]
    return "\n".join(lines) + "\n"


def verify_package(root: Path) -> dict:
    """Integrity always; .plan semantics only for the profile this code implements (older profiles are reported)."""
    root = Path(root)
    problems = []
    sums = {}
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        sums[name] = digest
        path = root / name
        if not path.is_file() or path.is_symlink() or sha256(path.read_bytes()) != digest:
            problems.append(f"altered or missing: {name}")
    listed = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()} - {"SHA256SUMS"}
    problems.extend(f"unlisted file: {n}" for n in sorted(listed - set(sums)))
    manifest = json.loads((root / "manifest.json").read_bytes())
    if manifest.get("deployment_ready") is not False:
        problems.append("deployment_ready must be false")
    plans = []
    for a in manifest["artifacts"]:
        if a.get("mission_file") and sha256((root / a["mission_file"]).read_bytes()) != a["mission_sha256"]:
            problems.append(f"{a['task_id']}: mission hash differs from the manifest")
        if not a.get("plan_file"):
            continue
        if a.get("profile") != PROFILE:
            plans.append({"task_id": a["task_id"], "status": "PROFILE_SUPERSEDED",
                          "detail": SUPERSEDED_PROFILES.get(a.get("profile"), "unknown profile")
                          + "; integrity checked, semantics not re-verified"})
            continue
        mission = MissionDefinition.model_validate_json((root / a["mission_file"]).read_bytes())
        result = verify_plan(root / a["plan_file"], mission, planned_home_amsl_m=a["planned_home"]["amsl_m"])
        plans.append({"task_id": a["task_id"], "status": result["status"],
                      "importer_readback": result["importer_readback"]["status"]})
        if result["status"] != "FILE_MATCHES_EXPECTATIONS":
            problems.append(f"{a['task_id']}: plan check {result['status']}")
    instance = json.loads((root / "instance.json").read_bytes())
    approval = json.loads((root / "approval.json").read_bytes()) if (root / "approval.json").is_file() else None
    recheck = check_approval(approval, instance, manifest["target"])
    if recheck["status"] != manifest["approval"]["status"]:
        problems.append("approval binding differs from the manifest")
    return {"status": "INTEGRITY_VERIFIED" if not problems else "FAILED", "problems": problems, "plans": plans,
            "approval": recheck["status"], "package_status": manifest["package_status"],
            "deployment_ready": manifest["deployment_ready"],
            "compatibility": "NOT_ESTABLISHED (no QGroundControl import, upload or vehicle read-back)"}


def summary_lines(root: Path) -> list[str]:
    manifest = json.loads((Path(root) / "manifest.json").read_bytes())
    lines = [f"Package {manifest['instance_id']} [{manifest['provenance']}, {manifest['target']}]: "
             f"{manifest['package_status']}, deployment_ready={manifest['deployment_ready']}, "
             f"approval {manifest['approval']['status']}"]
    for a in manifest["artifacts"]:
        detail = ""
        if a.get("plan_file"):
            v = a.get("verification") or {}
            detail = (f" -> {a['plan_file']} ({v.get('status', a.get('profile'))}; importer "
                      f"{(v.get('importer_readback') or {}).get('status', '-')})")
        lines.append(f"  {a['task_id']} {a['vehicle_id']}: {a['state']}{detail}"
                     + (f" | {'; '.join(a['reasons'])}" if a["reasons"] else ""))
    lines += [f"  {g['task_id']} {g['vehicle_id']}: line {g['spatial_validation']['status']}, {g['export']}"
              for g in manifest["ground_tasks"]]
    lines.append(f"  dependency structure {manifest['coordination']['status']} (structural only: not artifact "
                 f"availability, approval or execution readiness): {' -> '.join(manifest['coordination']['order'])}")
    lines.append(f"  deployment_ready={manifest['deployment_ready']}; blockers: "
                 + "; ".join(manifest.get("deployment_blockers", [])))
    lines += [f"  PENDING: {x}" for x in manifest.get("pending_conditions", [])]
    return lines


def parse_assignment(text: str) -> dict:
    """VEHICLE=DRAFT_ID/FINALIZATION_ID@TAKEOFF_POINT: every part explicit, nothing inferred."""
    vehicle, sep1, rest = text.partition("=")
    reference, sep2, takeoff = rest.partition("@")
    draft_id, sep3, finalization_id = reference.partition("/")
    if not all((sep1, sep2, sep3, vehicle, draft_id, finalization_id, takeoff)):
        raise ValueError(f"--assign {text!r}: expected VEHICLE=DRAFT_ID/FINALIZATION_ID@TAKEOFF_POINT")
    return {"vehicle_id": vehicle, "draft_id": draft_id, "finalization_id": finalization_id, "takeoff_point": takeoff}


def parse_rover(text: str) -> dict:
    vehicle, sep, start = text.partition("@")
    if not (sep and vehicle and start):
        raise ValueError(f"--rover {text!r}: expected VEHICLE@ROVER_START_POINT")
    return {"vehicle_id": vehicle, "start_point": start}


def _print(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-site").add_argument("site", type=Path)
    sub.add_parser("validate-fleet").add_argument("fleet", type=Path)
    for name in ("instantiate", "package"):
        p = sub.add_parser(name)
        p.add_argument("--template", type=Path, required=True)
        p.add_argument("--site", type=Path, required=True)
        p.add_argument("--fleet", type=Path, required=True)
        if name == "package":
            p.add_argument("--target", choices=("sitl", "field"), required=True)
            p.add_argument("--out", type=Path, required=True)
            p.add_argument("--approval", type=Path, default=None)
    h = sub.add_parser("package-historical")
    h.add_argument("--fleet", type=Path, required=True)
    h.add_argument("--out", type=Path, required=True)
    h.add_argument("--approval", type=Path, default=None)
    f = sub.add_parser("package-finalized", help="finalized Hermes missions over an explicitly selected site")
    f.add_argument("--store", type=Path, required=True, help="planning store holding drafts/ (TFG_PLANNING_STORE)")
    f.add_argument("--assign", action="append", required=True, metavar="VEHICLE=DRAFT_ID/FINALIZATION_ID@TAKEOFF",
                   help="one finalized mission per vehicle and the site's planned_takeoff point it is placed on")
    f.add_argument("--rover", metavar="VEHICLE@ROVER_START_POINT", default=None)
    f.add_argument("--scenario-binding", type=Path, default=None, help="scenario point links (e.g. H1's binding)")
    f.add_argument("--hermes-evidence", type=Path, default=None, help="sealed run evidence containing the store")
    f.add_argument("--planning-margin-m", type=float, default=1.0,
                   help="declared planning margin (default 1.0 m, the value of agri_poi_visit_v1)")
    f.add_argument("--site", type=Path, required=True)
    f.add_argument("--fleet", type=Path, required=True)
    f.add_argument("--target", choices=("sitl", "field"), required=True)
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--approval", type=Path, default=None)
    d = sub.add_parser("approval-draft")
    d.add_argument("--package", type=Path, required=True)
    d.add_argument("--out", type=Path, required=True)
    sub.add_parser("verify").add_argument("package", type=Path)
    sub.add_parser("summary").add_argument("package", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-site":
            report = validate_site(Site.model_validate_json(args.site.read_bytes()))
            _print(report)
            return 0 if report["status"] == "VALID" else 1
        if args.command == "validate-fleet":
            fleet = Fleet.model_validate_json(args.fleet.read_bytes())
            _print({"status": "VALID", "fleet_id": fleet.fleet_id,
                    "vehicles": {v.vehicle_id: [v.category, v.export_profile, v.compatibility] for v in fleet.vehicles}})
            return 0
        if args.command == "instantiate":
            bundle = instantiate(args.template, args.site, args.fleet)
            _print(bundle["instance"])
            return 0
        if args.command in ("package", "package-historical", "package-finalized"):
            approval = json.loads(args.approval.read_bytes()) if args.approval else None
            if args.command == "package":
                bundle, target = instantiate(args.template, args.site, args.fleet), args.target
            elif args.command == "package-finalized":
                bundle = finalized_instance(args.store, [parse_assignment(a) for a in args.assign], args.site,
                                            args.fleet, rover=parse_rover(args.rover) if args.rover else None,
                                            scenario_binding=args.scenario_binding,
                                            hermes_evidence=args.hermes_evidence,
                                            planning_margin_m=args.planning_margin_m)
                target = args.target
            else:
                bundle, target = historical_h2_instance(fleet_path=args.fleet), "sitl"
            build_package(bundle, args.out, target=target, approval=approval)
            print("\n".join(summary_lines(args.out)))
            return 0
        if args.command == "approval-draft":
            if args.out.exists():
                raise FileExistsError(f"{args.out} exists; not overwritten")
            manifest = json.loads((args.package / "manifest.json").read_bytes())
            instance = json.loads((args.package / "instance.json").read_bytes())
            args.out.write_bytes(canonical(approval_draft(instance, manifest["target"])))
            print(f"Draft written to {args.out}: approved_by is empty until a person fills it.")
            return 0
        if args.command == "verify":
            result = verify_package(args.package)
            _print(result)
            return 0 if result["status"] == "INTEGRITY_VERIFIED" else 1
        print("\n".join(summary_lines(args.package)))
        return 0
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        print(f"[REFUSED] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
