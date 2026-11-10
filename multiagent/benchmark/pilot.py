"""Limited pilot of a REAL local model (qwen3:4b through an already running Ollama) against the rules baseline.

    python -m multiagent.benchmark.pilot --check                       # preconditions only, calls no model
    python -m multiagent.benchmark.pilot --run --allow-model-calls --out DIR

What it does: re-checks the preconditions, then runs the pilot cases of pilots/qwen3_4b_pilot_v1.json
sequentially, one run each, first with the rules baseline and then with the model, through the same orchestrator
and the same criteria. It never downloads or installs anything, calls only 127.0.0.1, and contacts no vehicle.

Preconditions (all must hold, recorded in preconditions.json):
- Ollama answers locally and the expected model (name + digest) is already installed;
- no simulator / SITL / XRCE / worker process on the host or in the simulation container (read-only `ps` and
  `docker top`); a process table that cannot be read is UNKNOWN and blocks, never "no process";
- no vehicle reservation, lifecycle or sequence record in the lock directory of ANY worktree of this repository
  (lock state is per checkout); the lock source must be verifiable: every registered worktree readable, the runtime
  checkout (TFG_RUNTIME_CHECKOUT, or this checkout) one of them and with its lock root, and no link, unexpected
  type or read error anywhere in a lock root's path. Otherwise UNKNOWN, blocking;
- the GPU has room (memory used below the stop threshold).
Stop rules: 3 consecutive infrastructure errors, or GPU memory above the threshold. A stopped pilot says so.

Outputs (new directory): preconditions.json, manifest.json, rules/ and qwen/ (report.json, records.jsonl,
responses.jsonl with every raw reply in full, traces/<case>.jsonl, opik_payload.dry_run.json), comparison.md,
comparison.json and SHA256SUMS. Opik: DRY RUN only, nothing is sent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import os
import re
import shutil
import stat
import subprocess
import sys
import time

from multiagent.benchmark import run as bench
from multiagent.benchmark.failures import classify, summarize
from multiagent.tracing import SECRET_VALUE, opik_dry_run

HERE = Path(__file__).parent
MANIFEST = HERE / "pilots/qwen3_4b_pilot_v1.json"
# Checkout whose missions/generated holds the live reservations and lifecycle state checked before a real pilot:
# this repository, wherever it is installed. Lock state is per checkout, so a run from another worktree must name
# the checkout that operates the simulator with TFG_RUNTIME_CHECKOUT.
REPO_ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_CHECKOUT = Path(os.environ.get("TFG_RUNTIME_CHECKOUT") or REPO_ROOT)
LOCK_SUBDIR = Path("missions/generated/vehicle_locks")
# Lock-root components created at runtime: their absence is a legitimate "no lock state yet". `missions` is versioned,
# so a checkout without it is anomalous.
RUNTIME_CREATED = {"generated", "vehicle_locks"}
# A probe that could not show its state. It is a non-empty finding, so every "nothing found" check blocks on it.
UNREADABLE_PROCESS_TABLE = "UNKNOWN: process table could not be read"
SIM_CONTAINER = "tfg-ardupilot-gazebo"
SIM_PATTERN = re.compile(r"(gz sim|gzserver|gazebo|arducopter|ardurover|ardupilot/build|sim_vehicle|MicroXRCEAgent|"
                         r"mavproxy|ros2 launch|rover_pipe_worker|simulation_lifecycle|tfg_demo)", re.I)
RESERVATIONS = ("v1.json", "v2.json", "v3.json", "reconciliation.json", "lifecycle.json", "sequence.json")
GPU_LIMIT_MIB = 7500


def load_manifest(path: Path = MANIFEST) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------- probes --
def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return done.returncode, done.stdout + done.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{type(exc).__name__}: {exc}"


def process_table(fields: str = "args") -> list[str] | None:
    """Rows of ``ps -eo <fields>`` without the header; None when it could not be read (ps always lists itself, so
    an empty table is a failed read too)."""
    code, out = _run(["ps", "-eo", fields])
    rows = out.splitlines()[1:] if code == 0 else []
    return rows or None


def host_processes() -> list[str]:
    rows = process_table("args")
    if rows is None:
        return [UNREADABLE_PROCESS_TABLE]
    return [line for line in rows if SIM_PATTERN.search(line) and "multiagent" not in line]


def container_processes() -> dict:
    code, out = _run(["docker", "ps", "--filter", f"name=^{SIM_CONTAINER}$", "--format", "{{.Status}}"])
    if code != 0:
        return {"status": "DOCKER_UNAVAILABLE", "matches": [], "detail": out[:200]}
    if not out.strip():
        return {"status": "NOT_RUNNING", "matches": []}
    code, top = _run(["docker", "top", SIM_CONTAINER, "-eo", "pid,etime,args"])
    lines = top.splitlines()[1:] if code == 0 else []
    if not lines:  # a running container has at least one process: a failed or empty listing shows nothing
        return {"status": "UNKNOWN", "reason": "DOCKER_TOP_FAILED" if code else "DOCKER_TOP_EMPTY",
                "container_status": out.strip(), "matches": [], "detail": top[:200]}
    return {"status": f"RUNNING ({out.strip()})", "processes_read": True, "processes": lines,
            "matches": [l for l in lines if SIM_PATTERN.search(l)]}


def container_clear(container: dict) -> bool:
    """True only for a container shown not running, or running with its process table read and no match."""
    status = str(container.get("status", ""))
    if container.get("matches"):
        return False
    return status == "NOT_RUNNING" or (status.startswith("RUNNING") and container.get("processes_read") is True)


def repository_worktrees() -> list[dict] | None:
    """Registered worktrees of this repository ({path, prunable}); None when git cannot list them."""
    code, out = _run(["git", "-C", str(REPO_ROOT), "worktree", "list", "--porcelain"])
    if code != 0:
        return None
    trees = []
    for line in out.splitlines():
        if line.startswith("worktree "):
            trees.append({"path": line[len("worktree "):], "prunable": False})
        elif line.startswith("prunable") and trees:
            trees[-1]["prunable"] = True
    return trees or None


def lock_root_state(worktree: Path) -> dict:
    """State of one worktree's lock root, from lstat of every component (no link is followed).

    PRESENT (a readable real directory, with its (device, inode) identity), ABSENT (only a runtime-created component
    is missing: a legitimate empty lock state) or UNKNOWN with a reason: a symbolic link anywhere in the chain
    (dangling or not, its target is not this checkout's verified state), a component of another type, a missing
    versioned component, or any read error."""
    current = Path(worktree)
    st = None
    for part in LOCK_SUBDIR.parts:
        current = current / part
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            if part in RUNTIME_CREATED:
                return {"state": "ABSENT", "path": str(worktree / LOCK_SUBDIR)}
            return {"state": "UNKNOWN", "reason": f"LOCK_ROOT_COMPONENT_MISSING:{current}"}
        except OSError as exc:
            return {"state": "UNKNOWN", "reason": f"LOCK_ROOT_UNREADABLE:{current}:{type(exc).__name__}"}
        if stat.S_ISLNK(st.st_mode):
            return {"state": "UNKNOWN", "reason": f"LOCK_ROOT_SYMLINK:{current}"}
        if not stat.S_ISDIR(st.st_mode):
            return {"state": "UNKNOWN", "reason": f"LOCK_ROOT_NOT_A_DIRECTORY:{current}"}
    try:
        os.listdir(current)
    except OSError as exc:
        return {"state": "UNKNOWN", "reason": f"LOCK_ROOT_UNREADABLE:{current}:{type(exc).__name__}"}
    return {"state": "PRESENT", "path": str(current), "identity": [st.st_dev, st.st_ino]}


def present_lock_root(sources: dict, root: str) -> Path | None:
    """The verified lock root of ``root`` if it is still the same directory; None if verified ABSENT and still absent.
    Raises OSError when it changed or cannot be read since verification (callers turn it into UNKNOWN)."""
    recorded = sources["lock_roots"][root]
    now = lock_root_state(Path(root))
    if now["state"] != recorded["state"] or now.get("identity") != recorded.get("identity"):
        raise OSError(f"LOCK_ROOT_CHANGED_DURING_SCAN:{root}")
    return Path(now["path"]) if now["state"] == "PRESENT" else None


def lock_sources(*, runtime: Path | None = None, worktrees=None) -> dict:
    """Where vehicle reservations can live, shown rather than assumed.

    VERIFIED: every registered worktree that still exists is readable, its lock root is PRESENT or legitimately ABSENT
    (lock_root_state), and the runtime checkout is one of them with its lock root PRESENT. A prunable worktree whose
    directory is gone holds no lock state. Anything else is UNKNOWN with its reasons; callers block on it."""
    runtime = Path(runtime or ORIGINAL_CHECKOUT)
    trees = repository_worktrees() if worktrees is None else worktrees
    if not trees:
        return {"status": "UNKNOWN", "reasons": ["WORKTREE_LIST_UNREADABLE"], "roots": [], "lock_roots": {},
                "runtime": str(runtime)}
    reasons, roots, lock_roots = [], [], {}
    for tree in trees:
        path = Path(tree["path"])
        try:
            is_dir = stat.S_ISDIR(os.stat(path).st_mode)
        except FileNotFoundError:
            is_dir = None
        except OSError as exc:
            reasons.append(f"WORKTREE_UNREADABLE:{path}:{type(exc).__name__}")
            continue
        if not is_dir:
            if not (is_dir is None and tree.get("prunable")):
                reasons.append(f"WORKTREE_UNREADABLE:{path}")
            continue
        state = lock_root_state(path)
        if state["state"] == "UNKNOWN":
            reasons.append(state["reason"])
        roots.append(str(path))
        lock_roots[str(path)] = state
    try:
        resolved = runtime.resolve(strict=True)
    except OSError:
        resolved = None
    by_resolved = {Path(r).resolve(): r for r in roots}
    if resolved is None or resolved not in by_resolved:
        reasons.append(f"RUNTIME_CHECKOUT_NOT_A_WORKTREE_OF_THIS_REPOSITORY:{runtime}")
    elif lock_roots[by_resolved[resolved]]["state"] == "ABSENT":
        reasons.append(f"RUNTIME_LOCK_ROOT_MISSING:{resolved / LOCK_SUBDIR}")
    return {"status": "UNKNOWN" if reasons else "VERIFIED", "reasons": reasons, "roots": roots,
            "lock_roots": lock_roots, "runtime": str(runtime)}


def reservations(sources: dict | None = None) -> list[str]:
    """Reservation, lifecycle and sequence records in every worktree's lock root ('<worktree>:<name>'); an
    unverifiable lock source, a root that changed since verification or a read error is returned as UNKNOWN
    findings, never as no reservation. Any directory entry with a reservation name counts, links included."""
    sources = sources or lock_sources()
    if sources.get("status") != "VERIFIED":
        return [f"UNKNOWN: {r}" for r in sources.get("reasons") or ["LOCK_SOURCE_UNVERIFIED"]]
    found, unknown = [], []
    for root in sources["roots"]:
        try:
            lock_root = present_lock_root(sources, root)
            if lock_root is None:
                continue
            for name in RESERVATIONS:
                try:
                    os.lstat(lock_root / name)
                except FileNotFoundError:
                    continue
                found.append(f"{root}:{name}")
        except OSError as exc:
            unknown.append(f"UNKNOWN: {exc}" if "LOCK_ROOT_CHANGED" in str(exc)
                           else f"UNKNOWN: LOCK_ROOT_UNREADABLE:{root}:{type(exc).__name__}")
    return sorted(found) + unknown


def gpu() -> dict:
    code, out = _run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
                      "--format=csv,noheader,nounits"])
    if code != 0:
        return {"status": "NOT_MEASURED", "detail": out[:200]}
    used, total, util = (float(v) for v in out.strip().splitlines()[0].split(","))
    return {"status": "MEASURED", "memory_used_mib": used, "memory_total_mib": total, "utilization_pct": util}


def ollama_ps(base="http://127.0.0.1:11434") -> dict:
    from multiagent.models import urllib_get
    try:
        return {m["name"]: {"size_vram": m.get("size_vram"), "size": m.get("size"), "digest": m.get("digest")}
                for m in urllib_get(base + "/api/ps").get("models", [])}
    except Exception as exc:  # noqa: BLE001 - a probe; recorded, never fatal
        return {"error": f"{type(exc).__name__}"}


def check_preconditions(manifest: dict, *, probes=None) -> dict:
    """``probes`` (tests) overrides: version, model, host, container, reservations, gpu."""
    from multiagent.models import OllamaChatAdapter, urllib_get
    p = probes or {}
    checks, facts = {}, {}
    try:
        facts["ollama_version"] = p["version"]() if "version" in p else urllib_get("http://127.0.0.1:11434/api/version")
        checks["ollama_answers_locally"] = True
    except Exception as exc:  # noqa: BLE001
        facts["ollama_version"], checks["ollama_answers_locally"] = f"{type(exc).__name__}", False
    expected = manifest["expected_model"]
    try:
        model = p["model"]() if "model" in p else OllamaChatAdapter(model=expected["name"], enabled=True).local_model()
    except Exception as exc:  # noqa: BLE001
        model = None
        facts["model_error"] = type(exc).__name__
    facts["model"] = model
    checks["model_installed_with_expected_digest"] = bool(model) and model.get("digest") == expected["digest"]
    facts["host_sim_processes"] = p["host"]() if "host" in p else host_processes()
    checks["no_host_simulation_process"] = not facts["host_sim_processes"]
    facts["container"] = p["container"]() if "container" in p else container_processes()
    checks["no_simulation_process_in_container"] = container_clear(facts["container"])
    facts["reservations_original_checkout"] = p["reservations"]() if "reservations" in p else reservations()
    checks["no_vehicle_reservation"] = not facts["reservations_original_checkout"]
    facts["gpu"] = p["gpu"]() if "gpu" in p else gpu()
    checks["gpu_has_room"] = facts["gpu"].get("status") == "MEASURED" and facts["gpu"]["memory_used_mib"] < GPU_LIMIT_MIB
    checks["no_external_endpoint"] = True  # the only endpoint used is 127.0.0.1 (see make_interpreter)
    return {"schema": "tfg.multiagent.pilot-preconditions/1", "checked_at_utc": _utc(), "checks": checks,
            "facts": facts, "ok": all(checks.values())}


def _utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------------------- analysis --
def wilson(successes: int, n: int, z: float = 1.96) -> list[float] | None:
    """95 % Wilson score interval of a proportion; None without data."""
    if n == 0:
        return None
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def compare(rules: dict, model: dict) -> dict:
    by = lambda report: {r["case_id"]: r for r in report["rows"]}  # noqa: E731
    r_rows, m_rows = by(rules), by(model)
    cases = [c for c in r_rows if c in m_rows]
    scored = [c for c in cases if m_rows[c]["outcome"] != "BLOCKED"]
    count = lambda rows, key: sum(bool(rows[c][key]) for c in scored)  # noqa: E731
    summary = {}
    for key in ("case_pass", "status_match", "safety_ok", "coverage_match"):
        a, b = count(r_rows, key), count(m_rows, key)
        summary[key] = {"rules": [a, len(scored), wilson(a, len(scored))], "model": [b, len(scored), wilson(b, len(scored))]}
    unsafe = [c for c in scored if r_rows[c]["expected_status"] == "REFUSED_UNSAFE"]
    latencies = sorted(m_rows[c]["model_latency_s"] for c in scored)
    return {"cases": cases, "scored": scored, "blocked": [c for c in cases if c not in scored], "summary": summary,
            "only_model_passes": [c for c in scored if m_rows[c]["case_pass"] and not r_rows[c]["case_pass"]],
            "only_rules_passes": [c for c in scored if r_rows[c]["case_pass"] and not m_rows[c]["case_pass"]],
            "unsafe_detected": {"rules": [c for c in unsafe if not r_rows[c]["unsafe_missed"]],
                                "model": [c for c in unsafe if not m_rows[c]["unsafe_missed"]]},
            "model_flagged_unsafe_itself": [c for c in scored if (m_rows[c]["extraction_fields"] or {}).get("unsafe")],
            "clarifications": {"rules": [c for c in scored if r_rows[c]["status"] == "NEEDS_CLARIFICATION"],
                               "model": [c for c in scored if m_rows[c]["status"] == "NEEDS_CLARIFICATION"]},
            "invented": {c: m_rows[c]["invented_fields"] for c in scored if m_rows[c]["invented_fields"]},
            "model_output_errors": {c: m_rows[c]["parse_error"] for c in scored if m_rows[c]["error_kind"] == "MODEL_OUTPUT"},
            "model_latency_s": {"min": latencies[0] if latencies else None,
                                "p50": latencies[len(latencies) // 2] if latencies else None,
                                "max": latencies[-1] if latencies else None},
            "tokens": {c: m_rows[c]["tokens"] for c in scored},
            "failures": {"rules": {c: classify(r_rows[c]) for c in cases}, "model": {c: classify(m_rows[c]) for c in cases}},
            "limitations": ["11 hand-picked synthetic cases, one run each: intervals are wide; no rate generalises",
                            "temperature 0 and a fixed seed: variability across runs NOT measured",
                            "think=False: qwen3 reasoning mode not evaluated",
                            "the model only interprets; allocation, coordination and validation are deterministic"]}


def comparison_markdown(comp: dict, rules: dict, model: dict) -> str:
    r_rows = {r["case_id"]: r for r in rules["rows"]}
    m_rows = {r["case_id"]: r for r in model["rows"]}
    lines = ["# Pilot qwen3:4b vs rules (eval_v2 subset)", "",
             "| case | category | expected | rules | qwen3:4b | qwen outcome | extraction r/q | qwen latency s | invented |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for c in comp["cases"]:
        r, m = r_rows[c], m_rows[c]
        lines.append(f"| {c} | {r['category']} | {r['expected_status']} | {r['status']} | {m['status']} | "
                     f"{m['outcome']}{' (' + m['parse_error'] + ')' if m.get('parse_error') else ''} | "
                     f"{r['extraction_accuracy']:.2f} / {m['extraction_accuracy']:.2f} | {m['model_latency_s']:.1f} | "
                     f"{', '.join(m['invented_fields']) or '-'} |")
    lines += ["", "| metric | rules | qwen3:4b |", "| --- | --- | --- |"]
    for key, value in comp["summary"].items():
        lines.append(f"| {key} | {value['rules'][0]}/{value['rules'][1]} {value['rules'][2]} | "
                     f"{value['model'][0]}/{value['model'][1]} {value['model'][2]} |")
    lines += ["", "Intervals: 95 % Wilson. " + " ".join(comp["limitations"])]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------- run --
def _write_candidate(out: Path, report: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    internals = report.pop("_internals")
    (out / "report.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False) + "\n")
    (out / "records.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in report["records"]))
    responses = []
    (out / "traces").mkdir(exist_ok=True)
    all_records = []
    for item in internals:
        raw = item["_raw"]
        responses.append({"case_id": item["case_id"], "run_index": item["run_index"],
                          **{k: (SECRET_VALUE.sub("[REDACTED]", v) if isinstance(v, str) else v) for k, v in raw.items()}})
        (out / "traces" / f"{item['case_id']}.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in item["_records"]))
        all_records.append(item["_records"])
    (out / "responses.jsonl").write_text("".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in responses))
    dry = [opik_dry_run(records, "tfg-multiagent-pilot") for records in all_records]
    (out / "opik_payload.dry_run.json").write_text(json.dumps({"status": "DRY_RUN_NOT_SENT", "traces": dry}, indent=1,
                                                              sort_keys=True) + "\n")


def _opik_dry_run(out: Path, mode: str | None) -> str:
    """Optional: build the Opik import of the just-sealed run (traces of every candidate) as a DRY RUN in
    out/opik/ with its own SHA256SUMS. Never sends: sending stays a separate, authorized opik_bridge command."""
    import os
    mode = mode or os.environ.get("TFG_OPIK_MODE", "off")
    if mode == "off":
        return "OFF"
    if mode != "dry_run":
        raise SystemExit("TFG_OPIK_MODE must be off or dry_run; sending is never automatic")
    from multiagent import opik_bridge, opik_contract, opik_metrics
    from observability import opik_export as opik
    target = out / "opik"
    target.mkdir(exist_ok=True)
    for candidate in ("rules", "qwen"):
        # representation v2: native model/provider/usage on real LLM spans; scores only for OBSERVED metrics
        plan = opik_bridge.historical_plan(out, candidate_dir=candidate, native_fields=True)
        report = json.loads((out / candidate / "report.json").read_text())
        cases = {c["case_id"]: c for c in bench.dataset(report["dataset"]["id"])["suite"]["cases"]}
        rows = {r["case_id"]: r for r in report["rows"]}
        scores = []
        for trace in plan.traces:
            case_id = trace["metadata"]["tfg_case_id"]
            records = [json.loads(line) for line in
                       (out / candidate / "traces" / f"{case_id}.jsonl").read_text().splitlines()]
            scores += opik_metrics.score_items(trace["id"], opik_metrics.observe(rows[case_id], cases[case_id], records),
                                               project=plan.destination["project"], origin="run record")
        opik_contract.feedback_score_batch({"scores": scores})
        payload = {"manifest": opik_bridge.manifest(plan, out), "representation": "v2_native_fields",
                   "bodies": {"traces": opik.batch_bodies("traces", plan.traces), "spans": opik.batch_bodies("spans", plan.spans),
                              "feedback_scores": {"scores": scores}}}
        (target / f"{candidate}.dry_run.json").write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    with (target / "SHA256SUMS").open("w") as sums:
        for path in sorted(target.glob("*.json")):
            sums.write(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  ./{path.name}\n")
    return "DRY_RUN_WRITTEN_NOT_SENT"


def run_pilot(out: Path, *, manifest_path: Path = MANIFEST, allow_model_calls: bool = False, probes=None,
              transport=None, opik_mode: str | None = None) -> dict:
    manifest = load_manifest(manifest_path)
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    pre = check_preconditions(manifest, probes=probes)
    out.mkdir(parents=True, exist_ok=True)
    (out / "preconditions.json").write_text(json.dumps(pre, indent=1, sort_keys=True) + "\n")
    shutil.copyfile(manifest_path, out / "manifest.json")
    dataset = bench.dataset(manifest["dataset"])
    frozen = dataset["frozen_check"] or {}
    if dataset["sha256"] != manifest["dataset_sha256"] or not frozen or set(frozen.values()) != {"MATCH"}:
        raise SystemExit(f"{manifest['dataset']} differs from the manifest or is not frozen with every source MATCH: refusing")
    if not pre["ok"]:
        return {"status": "NOT_RUN_PRECONDITIONS", "preconditions": pre}
    if not allow_model_calls:
        return {"status": "NOT_RUN_NO_PERMISSION", "preconditions": pre}
    only = {c["case_id"] for c in manifest["cases"]} if manifest.get("cases") != "ALL" else None
    gen = manifest["generation"]
    options = {k: gen[k] for k in ("temperature", "seed", "num_predict", "think", "num_ctx", "timeout_s") if k in gen}
    if gen.get("seeds"):
        options["seeds"] = gen["seeds"]
    runs, prompt_id = manifest.get("runs_per_case", 1), manifest.get("prompt_id")
    options["version"] = manifest["expected_model"]["digest"]
    stamp = time.strftime("%Y%m%dT%H%M%S")
    rules = bench.run("rules", dataset_name=manifest["dataset"], only=only, keep_internals=True,
                      experiment_id=f"PILOT-{manifest['pilot_id']}-rules-{stamp}")
    _write_candidate(out / "rules", json.loads(json.dumps(rules, default=str)))
    state = {"stopped": None}

    def probe(case_id, phase):
        g = probes["gpu"]() if probes and "gpu" in probes else gpu()
        if g.get("status") == "MEASURED" and g["memory_used_mib"] > GPU_LIMIT_MIB:
            state["stopped"] = f"GPU memory {g['memory_used_mib']} MiB > {GPU_LIMIT_MIB}"
        return {"gpu": g, "ollama_ps": (probes["ollama_ps"]() if probes and "ollama_ps" in probes else ollama_ps()),
                "phase": phase}

    model_candidate = manifest["candidates"][1]
    report = bench.run(model_candidate, dataset_name=manifest["dataset"], only=only, keep_internals=True,
                       allow_calls=True, adapter_options=options, transport=transport, on_case=probe, runs=runs,
                       prompt_id=prompt_id,
                       should_stop=lambda: state["stopped"], stop_after_blocked=3,
                       experiment_id=f"PILOT-{manifest['pilot_id']}-qwen-{stamp}")
    if report.get("stopped"):
        state["stopped"] = report["stopped"]["reason"]
    _write_candidate(out / "qwen", json.loads(json.dumps(report, default=str)))
    comp = compare(rules, report)
    comp["stopped"] = state["stopped"]
    (out / "comparison.json").write_text(json.dumps(comp, indent=1, sort_keys=True) + "\n")
    (out / "comparison.md").write_text(comparison_markdown(comp, rules, report))
    (out / "README.md").write_text(
        f"# Pilot {manifest['pilot_id']} ({stamp})\n\nREAL local model output (qwen3:4b via Ollama on 127.0.0.1) over "
        "SYNTHETIC eval_v2 cases, compared with the rules baseline on the same cases. One run per case. "
        "Opik: dry run only, nothing sent. Do not edit; a new run goes into a new directory.\n")
    with (out / "SHA256SUMS").open("w") as sums:
        for path in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
            sums.write(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  ./{path.relative_to(out).as_posix()}\n")
    opik_status = _opik_dry_run(out, opik_mode)
    return {"status": "STOPPED" if state["stopped"] else "COMPLETED", "comparison": comp, "preconditions": pre,
            "opik": opik_status}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--allow-model-calls", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--manifest", type=Path, default=MANIFEST, help="pilot or experiment manifest")
    args = parser.parse_args(argv)
    if args.check or not args.run:
        pre = check_preconditions(load_manifest(args.manifest))
        print(json.dumps(pre, indent=1, sort_keys=True))
        return 0 if pre["ok"] else 1
    if not args.out:
        parser.error("--run needs --out")
    result = run_pilot(args.out, manifest_path=args.manifest, allow_model_calls=args.allow_model_calls)
    print(result["status"])
    if result["status"] in ("COMPLETED", "STOPPED"):
        print((args.out / "comparison.md").read_text())
    return 0 if result["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())


# --------------------------------------------------------------------------- post-hoc analysis --
def _reason_kind(reasons: list) -> str | None:
    """UNSAFE_REQUEST (its quoted text differs by design) or the first two ':'-fields (code, objective, vehicle)."""
    if not reasons:
        return None
    if reasons[0].startswith("UNSAFE_REQUEST"):
        return "UNSAFE_REQUEST"
    return ":".join(reasons[0].split(":")[:3])


def analyze(out: Path) -> dict:
    """Deterministic analysis of a finished pilot directory, written to out/analysis/ with its own SHA256SUMS.

    Never edits the run's files. It refines two things the run-time metrics cannot see:
    - "invented" coordinates that are an exact copy of the declared site point (the prompt lists them) versus
      values that are not declared anywhere;
    - cases whose status matches but whose first reason differs from the gold-brief oracle ("right status,
      wrong reason")."""
    out = Path(out)
    manifest = json.loads((out / "manifest.json").read_text())
    suite = {c["case_id"]: c for c in bench.dataset(manifest["dataset"])["suite"]["cases"]}
    model = json.loads((out / "qwen/report.json").read_text())
    responses = {r["case_id"]: r for r in map(json.loads, (out / "qwen/responses.jsonl").read_text().splitlines())}
    base = bench.load_context(bench.ROOT / bench.dataset(manifest["dataset"])["suite"]["context"])
    cases = {}
    for row in model["rows"]:
        case = suite[row["case_id"]]
        context = bench.case_context(base, case)
        from models.site import Site
        site = Site.model_validate_json(Path(context.resolve(context.site_path)).read_text(encoding="utf-8"))
        brief = bench.extract_json_safe(responses[row["case_id"]]["raw_text"])
        copied, invented = [], []
        for domain in ("aerial_objectives", "ground_objectives"):
            for o in (brief or {}).get(domain, []) or []:
                if not isinstance(o, dict) or not o.get("coordinates"):
                    continue
                point = site.point(o.get("point_id") or "")
                same = point is not None and [point.x_m, point.y_m] == [float(v) for v in o["coordinates"]]
                (copied if same else invented).append(f"{o.get('point_id')}={o['coordinates']}")
        oracle = bench.run_case(case, base, bench.GoldInterpreter(case["gold_brief"]))
        cases[row["case_id"]] = {
            "outcome": row["outcome"], "status": row["status"], "expected": row["expected_status"],
            "coordinates_copied_from_declared_points": copied, "coordinates_not_declared": invented,
            "other_unrequested_values": [f for f in row["invented_fields"] if ".coordinates=" not in f],
            "null_battery_values": sorted(k for k, v in ((brief or {}).get("battery_percent") or {}).items() if v is None)
            if isinstance((brief or {}).get("battery_percent"), dict) else [],
            "unsafe_flagged_by_model": bool((brief or {}).get("unsafe_requests")),
            "right_status_other_reason": row["status_match"] and bool(oracle["reasons"]) and
            (_reason_kind(row["reasons"][:1]) != _reason_kind(oracle["reasons"][:1])),
            "first_reason": row["reasons"][:1], "oracle_first_reason": oracle["reasons"][:1]}
    summary = {"cases": len(cases),
               "rejected_for_null_battery": sorted(c for c, v in cases.items() if v["null_battery_values"]),
               "coordinates_not_declared": sorted(c for c, v in cases.items() if v["coordinates_not_declared"]),
               "only_copied_coordinates": sorted(c for c, v in cases.items() if v["coordinates_copied_from_declared_points"]
                                                 and not v["coordinates_not_declared"]),
               "unrequested_values": {c: v["other_unrequested_values"] for c, v in cases.items() if v["other_unrequested_values"]},
               "right_status_other_reason": sorted(c for c, v in cases.items() if v["right_status_other_reason"]),
               "model_flagged_unsafe": sorted(c for c, v in cases.items() if v["unsafe_flagged_by_model"])}
    result = {"schema": "tfg.multiagent.pilot-analysis/1", "source": out.name, "summary": summary, "cases": cases,
              "method": "post-hoc, deterministic, from responses.jsonl and report.json; run files untouched"}
    target = out / "analysis"
    target.mkdir(exist_ok=True)
    (target / "analysis.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    with (target / "SHA256SUMS").open("w") as sums:
        sums.write(f"{hashlib.sha256((target / 'analysis.json').read_bytes()).hexdigest()}  ./analysis.json\n")
    return result


def classify_sealed(out: Path) -> dict:
    """Failure taxonomy (failures.py) applied AFTER THE FACT to a sealed pilot, into out/analysis_v2/ with its own
    SHA256SUMS. The run files and analysis/ stay untouched; criteria and case_pass are only read."""
    out = Path(out)
    result = {"schema": "tfg.multiagent.pilot-failures/1", "source": out.name,
              "method": "multiagent.benchmark.failures.classify over the sealed report rows"}
    for name in ("rules", "qwen"):
        rows = json.loads((out / name / "report.json").read_text())["rows"]
        result[name] = {"cases": {r["case_id"]: classify(r) for r in rows}, "summary": summarize(rows)}
    target = out / "analysis_v2"
    target.mkdir(exist_ok=True)
    (target / "failures.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    (target / "SHA256SUMS").write_text(
        f"{hashlib.sha256((target / 'failures.json').read_bytes()).hexdigest()}  ./failures.json\n")
    return result


def replay_sealed(out: Path, *, pipeline: str = "v2") -> dict:
    """Re-evaluate the RECORDED raw replies of a sealed pilot through another pipeline (no model call): the reply
    text is fed back by a replay adapter, the same prompt id (interpret_brief/1) and the same eval_v2 criteria apply.
    Written to out/analysis_v2/replay_<pipeline>.json; labelled REPLAY_OF_SEALED_OUTPUTS, never a new run."""
    from multiagent.model_interpretation import ModelInterpreterV2
    from multiagent.models import ModelResponse
    out = Path(out)
    manifest = json.loads((out / "manifest.json").read_text())
    data = bench.dataset(manifest["dataset"])
    suite = {c["case_id"]: c for c in data["suite"]["cases"]}
    replies = {r["case_id"]: r for r in map(json.loads, (out / "qwen/responses.jsonl").read_text().splitlines())}
    base = bench.load_context(bench.ROOT / data["suite"]["context"])

    class Replay:
        info = {"provider": "replay", "model": "qwen3:4b (recorded)", "version": manifest["expected_model"]["digest"],
                "data_kind": "MODEL_OUTPUT"}
        generation = manifest["generation"]

        def __init__(self, raw):
            self.raw = raw

        def complete(self, messages, *, json_output=False):
            return ModelResponse(self.raw["raw_text"] or "", 0.0, "replay", "qwen3:4b", "MODEL_OUTPUT",
                                 self.raw.get("usage"), finish_reason="stop")

    rows = {}
    for case_id, reply in sorted(replies.items()):
        case = suite[case_id]
        context = bench.case_context(base, case)
        interpreter = ModelInterpreterV2(Replay(reply), site_points=bench.site_points_of(context))
        row = bench.run_case(case, base, interpreter, pipeline=pipeline)
        proposal = row.pop("_proposal")
        row.pop("_records"), row.pop("_raw")
        rows[case_id] = {"status": row["status"], "expected": row["expected_status"], "case_pass": row["case_pass"],
                         "safety_ok": row["safety_ok"], "failure": classify(row), "reasons": row["reasons"][:3],
                         "interpretation": proposal.get("interpretation")}
    result = {"schema": "tfg.multiagent.pilot-replay/1", "data_kind": "REPLAY_OF_SEALED_OUTPUTS", "pipeline": pipeline,
              "note": "recorded qwen3:4b replies re-evaluated offline; not a new model run; prompt interpret_brief/1",
              "case_pass": sum(r["case_pass"] for r in rows.values()), "cases": len(rows), "rows": rows}
    target = out / "analysis_v2"
    target.mkdir(exist_ok=True)
    name = f"replay_pipeline_{pipeline}.json"
    (target / name).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    with (target / "SHA256SUMS").open("w") as sums:
        for path in sorted(target.glob("*.json")):
            sums.write(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  ./{path.name}\n")
    return result
