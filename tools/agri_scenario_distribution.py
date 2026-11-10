"""Minimal distributable set of the agri_demo_001 scenario flow: what a clone needs, beyond the files Git already
tracks at HEAD, for the historical query, the synthetic demo, the integrity checks and the report.

Established empirically on 26/10/2026: HEAD contents + exactly these entries, with an isolated venv
(requirements-dev.txt + constraints-verified.txt), an empty HOME and no missions/generated, run the query, the demo
and tests/test_agri_scenario_flow.py. Evidence directories are listed by their OWN manifest (not file by file).

    python -m tools.agri_scenario_distribution write <inventory.json> [--set agri_flow_site_export]
    python -m tools.agri_scenario_distribution check <inventory.json> [--root DIR]

Sets: ``agri_flow`` (default; the 26/10 set) and ``agri_flow_site_export`` (27/10: agri_flow plus site, fleet,
scenario package, the strict .plan exporter and the entries that now delegate to it). A historical inventory that
no longer describes the current tree is not evidence of altered evidence: it describes the tree it was written for.

``app_image`` (27/10, later) is what the application image (deploy/app) contains: every project module in the static
import closure of APP_ENTRYPOINTS, the example inputs and the evidence the offline walkthrough reads. The same list
generates the build-context allowlist, so the image and its inventory cannot drift apart:

    python -m tools.agri_scenario_distribution dockerignore [--check deploy/app/Dockerfile.dockerignore]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "tfg.agri-scenario-distribution/1"
H3B = "evaluation/observability/agri_scenario_h3b_nous_2026_10_24"
ENTRIES = [  # (path, kind, purpose)
    ("main.py", "entry", "main menu option 5 opens the scenario flow"),
    ("tools/agri_scenario_flow.py", "code", "scenario entry: query, demo, menu, resume checks, outputs manifest"),
    ("graph/agri_scenario_graph.py", "code", "LangGraph scenario flow: stages, transitions, report"),
    ("reporting/agri_scenario_summary.py", "code", "binding, validation, scenario view, R1 preparation and dimensions, report"),
    ("tools/agri_ground_coordinator.py", "code", "R1 coordinator: durable records, idempotency, acceptance"),
    ("tools/agri_ground_demo.py", "code", "TEST_DOUBLE ground executor and demo inputs (synthetic only)"),
    ("observability/hermes_capture_run.py", "code", "SHA256SUMS verification of the evidence directories"),
    ("observability/mission_query_cases.py", "code", "imported by the scenario summary (answer parsing)"),
    ("tools/rover_passive_journal.py", "code", "measured facts from a finished /3 capture (query --capture-*)"),
    ("tools/agri_scenario_distribution.py", "code", "this inventory and its check"),
    ("reporting/rover_identity_facts.py", "code", "facts of a closed rover identity session (query --identity-trial-root)"),
    ("tools/rover_ground_executor.py", "code_rover_uncommitted",
     "executor facts read by the R1 preparation; the HEAD version reports navigation unsupported (owner: rover subsystem)"),
    ("tools/rover_control.py", "code_rover_uncommitted",
     "NavigationGoal/limits used by the coordinator; the HEAD version is incompatible (owner: rover subsystem)"),
    ("tests/test_agri_scenario_flow.py", "test", "stage boundaries, capability separation, resume and recovery"),
    ("requirements.txt", "dependencies", "direct runtime dependencies (pydantic and PyYAML declared)"),
    ("constraints-verified.txt", "dependencies", "exact versions verified in a clean isolated install"),
    ("missions/examples/agri_demo_001_sector_a.json", "reference", "H0 reference of drone_01 (geometry check)"),
    ("missions/examples/agri_demo_001_sector_b.json", "reference", "H0 reference of drone_02 (geometry check)"),
    ("simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24", "evidence", "conserved H2 copies (archive source)"),
    ("evaluation/observability/agri_planning_h1_nous_2026_10_24", "evidence", "H1 binding record (BOUND)"),
    (H3B, "evidence", "recorded H3b capture: view received and acceptance (no inference)"),
    ("evaluation/observability/agri_scenario_view_h2_2026_10_24", "evidence", "saved H2 view (regression)"),
    ("simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-8fad-457e-918e-253483a2d728",
     "optional_evidence", "closed /3 capture for the measured facts (owner: rover subsystem). Without it the query and the "
     "demo run unchanged and requested metrics are NOT_AVAILABLE"),
    ("simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f",
     "optional_evidence", "closed rover identity session (owner: rover subsystem). Without it the identity facts are "
     "NOT_AVAILABLE and nothing else changes"),
]
EXPORT_ENTRIES = [  # 27/10/2026, added to ENTRIES for the agri_flow_site_export set
    ("inputs/qgc_plan_export.py", "code", "strict QGC_PLAN_ARDUCOPTER_V2 exporter, MAVLink expectations, verifier"),
    ("inputs/qgroundcontrol_exporter.py", "code", "session/Hermes export entry, delegates to the strict exporter"),
    ("sessions/structured_mission_session.py", "code", "session export: REFUSED/EXPORTED with reasons"),
    ("tools/hermes_mission_validation.py", "code", "validation result carries qgc_export"),
    ("models/site.py", "code", "site.json model"),
    ("models/fleet.py", "code", "fleet.json model"),
    ("models/scenario_template.py", "code", "scenario template model"),
    ("planning/site_geometry.py", "code", "geometry and local frame conversion"),
    ("planning/site_validation.py", "code", "site and route checks"),
    ("planning/scenario_instance.py", "code", "instantiation, historical H2 rebase, approval binding"),
    ("tools/scenario_package.py", "code", "package/verify/summary CLI"),
    ("missions/sites/synthetic_orchard_v1.site.json", "example", "SYNTHETIC site"),
    ("missions/sites/synthetic_orchard_v2.site.json", "example", "SYNTHETIC site, POI_1 moved"),
    ("missions/sites/synthetic_hermes_rehearsal_v1.site.json", "example",
     "SYNTHETIC rehearsal site for the two Hermes-finalized missions (not DroneLab, not a field)"),
    ("missions/sites/dronelab.template.site.json", "example", "DroneLab template pending measurement"),
    ("missions/fleets/agri_demo_fleet.json", "example", "logical fleet"),
    ("missions/templates/agri_poi_visit_v1.json", "example", "scenario template"),
    ("missions/templates/agri_poi_visit_crossing_v1.json", "example", "test variant: exclusion crossing"),
    ("missions/templates/agri_poi_visit_unresolved_fleet_v1.json", "example", "test variant: unresolved fleet"),
    ("tests/test_site_geometry.py", "test", "geometry, site, fleet"),
    ("tests/test_scenario_package.py", "test", "packages a-f, exporter expectations, layers, menu"),
    ("tests/test_qgroundcontrol_exporter.py", "test", "session entry refusals and strict bytes"),
    ("tests/test_hermes_mission_validation.py", "test", "validation export result"),
    ("tools/qgc_plan_compare.py", "code", "offline semantic comparison original vs QGC-saved .plan"),
    ("tests/test_qgc_plan_compare.py", "test", "comparator with synthetic changes"),
    ("docs/site-fleet-export.md", "doc", "site, fleet and export documentation"),
    ("docs/integrated-trial-protocol.md", "doc", "integrated trial protocol (not executed)"),
    ("docs/qgc-first-import-procedure.md", "doc", "procedure for the first QGroundControl import"),
    ("evaluation/observability/agri_site_fleet_export_2026_10_27", "optional_evidence",
     "first packages (profile V1, superseded): verify reports PROFILE_SUPERSEDED after integrity"),
]
APP_ENTRYPOINTS = ("main", "tools.agri_scenario_flow", "tools.scenario_package", "tools.qgc_plan_compare",
                   "reporting.agri_scenario_summary", "reporting.agri_experiment_comparison",
                   "tools.agri_scenario_distribution")
APP_DATA_ENTRIES = [  # 27/10/2026: inputs and evidence of the offline walkthrough inside the application image
    ("requirements.txt", "dependencies", "direct runtime dependencies"),
    ("requirements-observability.txt", "dependencies", "capture validation (jsonschema) used by the evidence checks"),
    ("constraints-verified.txt", "dependencies", "exact versions verified in a clean isolated install"),
    ("deploy/app/entry.py", "entry", "image ENTRYPOINT: python3 -m/-c/script with a clean early Ctrl+C"),
    *[(rel, kind, purpose) for rel, kind, purpose in ENTRIES + EXPORT_ENTRIES
      if kind in {"reference", "example", "evidence"}],
    ("evaluation/observability/agri_scenario_h3_nous_2026_10_24", "evidence", "H3 turn (experimental comparison)"),
    ("evaluation/observability/agri_scenario_pilot_nous_2026_10_24", "evidence", "pilot runs (experimental comparison)"),
    ("evaluation/observability/agri_scenario_pilot_audit_2026_10_25", "evidence",
     "pilot audit and post-fix acceptance (experimental comparison)"),
    ("evaluation/observability/agri_export_semantics_2026_10_27", "evidence",
     "sealed V2 packages, including the .plan of the first QGroundControl import"),
    ("evaluation/observability/qgc_first_import_2026_10_27", "evidence",
     "first QGroundControl import: original and QGC-saved .plan, comparison, screenshots"),
    *[(rel, kind, purpose) for rel, kind, purpose in ENTRIES + EXPORT_ENTRIES if kind == "optional_evidence"],
    # recipe and documentation: distributed with the sources, not copied into the image
    ("deploy/compose.yaml", "distribution", "services app, app-dev and qgc (project tfg-dist)"),
    ("deploy/app/Dockerfile", "distribution", "application image recipe"),
    ("deploy/app/Dockerfile.dockerignore", "distribution", "generated build-context allowlist"),
    ("deploy/app/student_walkthrough.sh", "distribution", "offline walkthrough with expected outcomes"),
    ("deploy/vscode/tasks.json", "distribution", "VS Code tasks template (copy or merge into .vscode/tasks.json)"),
    ("deploy/qgc/Dockerfile", "distribution", "QGroundControl 5.1.5 image recipe"),
    ("deploy/qgc/QGroundControl.ini", "distribution", "QGC settings: every AutoConnect disabled"),
    ("deploy/qgc/entrypoint.sh", "distribution", "QGC entrypoint"),
    ("tests/test_agri_scenario_flow.py", "test", "flow, inventory and app image allowlist"),
    ("docs/student-environment.md", "doc", "student guide of the containerized environment"),
    ("docs/simulator-distribution-handoff.md", "doc", "pending simulator distribution (handoff)"),
    ("docs/qgc-first-import-procedure.md", "doc", "first QGroundControl import (executed 27/10/2026)"),
]
IMAGE_KINDS = {"entry", "code", "code_rover_uncommitted", "dependencies", "reference", "example", "evidence"}
# 27/10/2026, planning profile (deploy/planner): the offline set plus the project's MCP server, the existing Hermes
# capture runner and its plugin, the example inputs and the profile's own launcher and config template.
PLANNER_ENTRYPOINTS = APP_ENTRYPOINTS + ("tools.hermes_mcp_server", "observability.hermes_capture_run")
PLANNER_DATA_ENTRIES = [
    *[(rel, kind, purpose) for rel, kind, purpose in APP_DATA_ENTRIES if kind != "distribution"],
    *[(f"observability/hermes_capture/{name}", "code", "Hermes capture plugin data (existing runner)")
      for name in ("plugin.yaml", "event.schema.json", "tool-offer.schema.json", "tool-result-check.schema.json")],
    *[(f"missions/examples/{name}", "example", "example mission input (menu option 2)")
      for name in ("precision_agriculture_demo.json", "simulation_navigation_3waypoint.json",
                   "simulation_navigation_drone02.json", "simulation_navigation_smoke.json")],
    ("deploy/planner/hermes_home.py", "entry", "planning launcher: prepares and checks HERMES_HOME, runs Hermes"),
    ("deploy/planner/hermes-config.base.yaml", "entry", "Hermes config template: provider, model, project MCP"),
    ("deploy/planner/hermes_source.py", "entry", "frozen Hermes source: export/fetch and tree verification"),
    ("deploy/planner/Dockerfile", "distribution", "planning image recipe"),
    ("deploy/planner/Dockerfile.dockerignore", "distribution", "generated build-context allowlist"),
    ("deploy/planner/doubles/fake_provider.py", "distribution", "TEST DOUBLE of an OpenAI-compatible provider"),
    ("deploy/planner/planning_checks.sh", "distribution", "checks of the planning profile with test doubles"),
    ("tests/test_planning_profile.py", "test", "planning launcher, test-double provider and trial case"),
    ("deploy/compose.yaml", "distribution", "services app, app-dev, qgc and the planning profile"),
    ("docs/student-environment.md", "doc", "student guide of the containerized environment"),
    ("docs/planning-first-real-test.md", "doc", "procedure of the single pending real inference"),
]
DOCKERFILES = {"app_image": "deploy/app/Dockerfile", "planner_image": "deploy/planner/Dockerfile"}


def module_closure(root: Path = ROOT, entrypoints=APP_ENTRYPOINTS) -> list[str]:
    """Project .py files reachable by static imports (including function-level ones) from the entrypoints, plus the
    __init__.py of their packages. Third-party and standard-library imports are not followed."""
    def source(name):
        for candidate in (root / (name.replace(".", "/") + ".py"), root / name.replace(".", "/") / "__init__.py"):
            if candidate.is_file():
                return candidate
        return None

    seen, todo = {}, list(entrypoints)
    while todo:
        name = todo.pop()
        path = source(name)
        if name in seen or path is None:
            continue
        seen[name] = path
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                todo += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parent = package.split(".")[:len(package.split(".")) - node.level + 1] if package else []
                    base = ".".join([*parent, *([node.module] if node.module else [])])
                todo += [base, *(f"{base}.{alias.name}" for alias in node.names)]
    files = {path.relative_to(root).as_posix() for path in seen.values()}
    for rel in list(files):
        parts = rel.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            init = "/".join(parts[:i]) + "/__init__.py"
            if (root / init).is_file():
                files.add(init)
    return sorted(files)


def _set_entries(entry_set: str, root: Path = ROOT) -> list[tuple[str, str, str]]:
    if entry_set == "app_image":
        entrypoints, data, label = APP_ENTRYPOINTS, APP_DATA_ENTRIES, "offline"
    elif entry_set == "planner_image":
        entrypoints, data, label = PLANNER_ENTRYPOINTS, PLANNER_DATA_ENTRIES, "planning"
    else:
        return SETS[entry_set]
    code = [(rel, "entry" if rel == "main.py" else "code", f"static import closure of the {label} entrypoints")
            for rel in module_closure(root, entrypoints)]
    listed = {rel for rel, _, _ in code}
    unique = []
    for entry in data:  # first occurrence wins: a path is listed once even if two lists name it
        if entry[0] not in listed:
            listed.add(entry[0])
            unique.append(entry)
    return code + unique


def dockerignore_text(root: Path = ROOT, entry_set: str = "app_image") -> str:
    """Build-context allowlist of an image: everything excluded except the set's required entries. Optional
    evidence stays out of the image (its consumers report NOT_AVAILABLE)."""
    keep = [rel for rel, kind, _ in _set_entries(entry_set, root) if kind in IMAGE_KINDS]
    command = "dockerignore" + ("" if entry_set == "app_image" else f" --set {entry_set}")
    return (f"# GENERATED by `python -m tools.agri_scenario_distribution {command}`; do not edit by hand.\n"
            f"# Allowlist for {DOCKERFILES[entry_set]} (context: repository root).\n*\n"
            + "".join(f"!{rel}\n" for rel in keep)
            + "".join(f"**/{name}\n" for name in ("__pycache__", "*.pyc", ".env", ".venv")))


SETS = {"agri_flow": ENTRIES, "agri_flow_site_export": ENTRIES + EXPORT_ENTRIES, "app_image": None,
        "planner_image": None}
OPTIONAL_KINDS = {"optional_evidence"}
MANIFESTS = ("SHA256SUMS", "manifest.json")
FORBIDDEN_PREFIXES = ("missions/generated", ".venv", ".env")
SECRET_PATTERNS = [re.compile(p) for p in (r"OPIK_API_KEY\s*=\s*['\"]?[A-Za-z0-9]", r"Bearer\s+[A-Za-z0-9._-]{16,}",
                                           r"\bsk-[A-Za-z0-9]{20,}", r"LANGSMITH_API_KEY\s*=\s*['\"]?[A-Za-z0-9]")]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_problems(directory: Path, name: str) -> list[str]:
    """Verify a directory against its own manifest, in whichever of the three formats it uses."""
    path = directory / name
    if name == "SHA256SUMS":
        lines = path.read_text(encoding="utf-8").splitlines()
        entries = [(line.split("  ", 1)[1], line.split("  ", 1)[0], None) for line in lines if line.strip()]
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "copies" in data:  # conserved-copy archive
            entries = [(c["copy"], c["sha256"], c["bytes"]) for c in data["copies"]]
        else:  # trial manifest
            entries = [(f["path"], f["sha256"], f["size_bytes"]) for f in data["files"]]
    problems = []
    for rel, digest, size in entries:
        target = directory / rel
        if not target.is_file() or (size is not None and target.stat().st_size != size) or _sha(target.read_bytes()) != digest:
            problems.append(f"{directory.name}: {rel}")
    return problems


def _git_state(root: Path, rel: str) -> str:
    try:
        tracked = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", rel],
                                 capture_output=True).returncode == 0
        if not tracked:
            return "untracked"
        changed = subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--", rel],
                                 capture_output=True).returncode != 0
        return "tracked_modified" if changed else "tracked"
    except OSError:
        return "unknown"


def build_inventory(root: Path = ROOT, entry_set: str = "agri_flow") -> dict:
    entries = []
    for rel, kind, purpose in _set_entries(entry_set, root):
        path = root / rel
        entry = {"path": rel, "kind": kind, "purpose": purpose, "git": _git_state(root, rel),
                 "required": kind not in OPTIONAL_KINDS}
        if not path.exists() and kind in OPTIONAL_KINDS:
            entries.append({**entry, "type": "absent_optional", "size_bytes": 0})
            continue
        if path.is_dir():
            manifest = next(name for name in MANIFESTS if (path / name).is_file())
            files = [p for p in path.rglob("*") if p.is_file()]
            entry.update(type="directory", manifest=manifest, manifest_sha256=_sha((path / manifest).read_bytes()),
                         files=len(files), size_bytes=sum(p.stat().st_size for p in files))
        else:
            data = path.read_bytes()
            entry.update(type="file", size_bytes=len(data), sha256=_sha(data))
        entries.append(entry)
    return {"schema": SCHEMA, **({"set": entry_set} if entry_set != "agri_flow" else {}),
            "base": "git HEAD contents", "entries": entries,
            "total_size_bytes": sum(e["size_bytes"] for e in entries),
            "required_size_bytes": sum(e["size_bytes"] for e in entries if e["required"]),
            "not_needed": ["missions/generated (local stores)", "private Hermes sessions (~/.hermes)",
                           "credentials or API keys", "live container temporaries", ".venv (use the requirements)"]}


def check_inventory(inventory: dict, root: Path = ROOT) -> list[str]:
    """Problems: absent or changed entries, manifests that do not verify, forbidden paths, credential patterns."""
    problems = []
    for entry in inventory["entries"]:
        rel, path = entry["path"], root / entry["path"]
        if Path(rel).is_absolute() or rel.startswith(FORBIDDEN_PREFIXES):
            problems.append(f"FORBIDDEN_PATH: {rel}")
            continue
        if entry.get("required") is False and not path.exists():
            continue  # optional evidence not distributed: its consumers report NOT_AVAILABLE
        if entry["type"] == "absent_optional":
            continue
        if entry["type"] == "directory":
            if not (path / entry["manifest"]).is_file():
                problems.append(f"MISSING: {rel}/{entry['manifest']}")
                continue
            if _sha((path / entry["manifest"]).read_bytes()) != entry["manifest_sha256"]:
                problems.append(f"MANIFEST_CHANGED: {rel}")
            problems += [f"MANIFEST_MISMATCH: {p}" for p in _manifest_problems(path, entry["manifest"])]
            files = [p for p in path.rglob("*") if p.is_file()]
        else:
            if not path.is_file():
                problems.append(f"MISSING: {rel}")
                continue
            data = path.read_bytes()
            if len(data) != entry["size_bytes"] or _sha(data) != entry["sha256"]:
                problems.append(f"CHANGED: {rel}")
            files = [path]
        for file in files:
            if file.stat().st_size > 5 * 1024 * 1024:
                continue
            text = file.read_bytes().decode("utf-8", errors="ignore")
            if any(p.search(text) for p in SECRET_PATTERNS):
                problems.append(f"CREDENTIAL_PATTERN: {file.relative_to(root).as_posix()}")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write")
    write.add_argument("inventory", type=Path)
    write.add_argument("--set", choices=sorted(SETS), default="agri_flow")
    check = sub.add_parser("check")
    check.add_argument("inventory", type=Path)
    check.add_argument("--root", type=Path, default=ROOT)
    ignore = sub.add_parser("dockerignore", help="print an image's build-context allowlist")
    ignore.add_argument("--set", choices=sorted(DOCKERFILES), default="app_image")
    ignore.add_argument("--check", type=Path, default=None, help="exit 1 if this file differs from the generated text")
    args = parser.parse_args(argv)
    if args.command == "dockerignore":
        text = dockerignore_text(entry_set=args.set)
        if args.check is None:
            print(text, end="")
            return 0
        same = args.check.is_file() and args.check.read_text(encoding="utf-8") == text
        print("OK" if same else f"DIFFERS: regenerate {args.check}")
        return 0 if same else 1
    if args.command == "write":
        if args.inventory.exists():
            parser.error(f"{args.inventory} exists; inventories are never overwritten")
        args.inventory.write_text(json.dumps(build_inventory(entry_set=args.set), indent=2, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
        return 0
    problems = check_inventory(json.loads(args.inventory.read_text(encoding="utf-8")), args.root)
    print(json.dumps({"status": "OK" if not problems else "PROBLEMS", "problems": problems}, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
