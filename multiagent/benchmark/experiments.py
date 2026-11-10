"""Experiment plan (experiments/plan_v1.json): list, validate and turn a local experiment into a runnable manifest.
Nothing here calls a model.

    python -m multiagent.benchmark.experiments --list
    python -m multiagent.benchmark.experiments --check            # every experiment, exit 1 on any problem
    python -m multiagent.benchmark.experiments --write-manifest EXP-01-... OUT.json
    # then, only with authorization and the pilot preconditions:
    python -m multiagent.benchmark.pilot --run --allow-model-calls --manifest OUT.json --out <new dir>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from multiagent import evaluation, prompts
from multiagent.benchmark import run as bench

PLAN = Path(__file__).with_name("experiments") / "plan_v1.json"
LOCAL = ("ollama:",)


def load_plan(path: Path = PLAN) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def problems(exp: dict) -> list[str]:
    out = []
    if exp.get("status", "").startswith("RUN"):
        out.append("status claims a run: plans never record results")
    tasks = exp["task"] if isinstance(exp["task"], list) else [exp["task"]]
    for task in tasks:
        if task == "EXPORT":
            continue
        try:
            evaluation.require_fit(exp["candidate"], task)
        except evaluation.TaskNotApplicable as exc:
            out.append(str(exc))
    if "dataset" in exp:
        try:
            data = bench.dataset(exp["dataset"])
        except KeyError:
            out.append(f"unknown dataset {exp['dataset']}")
            data = None
        if data is not None:
            if data["split"] in ("eval", "adversarial") and set((data["frozen_check"] or {}).values()) != {"MATCH"}:
                out.append(f"{exp['dataset']} is not frozen or its frozen sources changed")
            if exp.get("pipeline") and data.get("pipeline", "v1") != exp["pipeline"]:
                out.append(f"pipeline {exp['pipeline']} differs from the dataset's {data.get('pipeline', 'v1')}")
            prompt_id = exp.get("prompt_id")
            if prompt_id:
                if prompt_id not in prompts.PROMPTS:
                    out.append(f"unknown prompt {prompt_id}")
                elif prompts.PROMPTS[prompt_id]["brief_schema"].endswith("/2") and data.get("pipeline", "v1") != "v2":
                    out.append("prompt /2 produces brief /2: it needs a pipeline v2 dataset")
    gen = exp.get("generation") or {}
    runs = exp.get("runs_per_case", 1)
    if not isinstance(runs, int) or runs < 1:
        out.append("runs_per_case must be a positive integer")
    if runs > 1 and gen.get("temperature", 0) > 0 and len(gen.get("seeds") or []) != runs:
        out.append("a variability experiment needs one seed per run")
    if not str(exp.get("results_dir", "")).startswith(("multiagent/benchmark/results/", "<source results_dir>")):
        out.append("results_dir must be a new directory under multiagent/benchmark/results/")
    return out


def check(plan: dict) -> dict:
    return {e["id"]: problems(e) for e in plan["experiments"]}


def manifest(exp: dict) -> dict:
    """Pilot-runner manifest for a LOCAL experiment (cases ALL or a list). Remote ones are refused."""
    if not exp["candidate"].startswith(LOCAL):
        raise SystemExit(f"{exp['id']}: only local experiments get a runnable manifest ({exp['status']})")
    found = problems(exp)
    if found:
        raise SystemExit(f"{exp['id']}: {found}")
    data = bench.dataset(exp["dataset"])
    cases = [{"case_id": c["case_id"], "category": c["category"], "why": "full dataset"} for c in data["suite"]["cases"]] \
        if exp["cases"] == "ALL" else exp["cases"]
    return {"schema": "tfg.multiagent.pilot/1", "pilot_id": exp["id"], "dataset": exp["dataset"],
            "dataset_file": data["file"], "dataset_sha256": data["sha256"], "cases": cases,
            "candidates": ["rules", exp["candidate"]], "runs_per_case": exp.get("runs_per_case", 1),
            "prompt_id": exp.get("prompt_id"), "generation": exp["generation"],
            "expected_model": {"name": exp["model"]["name"], "digest": exp["model"]["digest"]},
            "stop_rules": exp.get("finish_when"), "note": f"generated from {PLAN.name}; NOT RUN"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Experiment plan (configurations only)")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write-manifest", nargs=2, metavar=("EXPERIMENT_ID", "OUT"))
    args = parser.parse_args(argv)
    plan = load_plan()
    if args.write_manifest:
        exp = next(e for e in plan["experiments"] if e["id"] == args.write_manifest[0])
        Path(args.write_manifest[1]).write_text(json.dumps(manifest(exp), indent=1) + "\n")
        return 0
    result = check(plan)
    for exp in plan["experiments"]:
        print(f"{exp['id']:<45} {exp['status']:<38} {'OK' if not result[exp['id']] else result[exp['id']]}")
    return 0 if not any(result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())


MATRIX = Path(__file__).with_name("experiments") / "multiagent_matrix_v1.json"


def check_matrix(path: Path = MATRIX) -> dict:
    """Every configuration parses as a MultiAgentConfig, uses known candidates whose task fits, keeps dev and
    evaluation datasets apart, and claims no real run."""
    from multiagent.llm_agents import MultiAgentConfig
    matrix = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    dev, ev = set(matrix["datasets"]["development"]), set(matrix["datasets"]["evaluation"])
    shared = ["development and evaluation datasets overlap"] if dev & ev else []
    for name in dev | ev:
        data = bench.dataset(name)
        if name in ev and set((data["frozen_check"] or {}).values()) != {"MATCH"}:
            shared.append(f"{name} is not frozen")
        if data.get("pipeline") != matrix["pipeline"]:
            shared.append(f"{name} is not a pipeline {matrix['pipeline']} dataset")
    for item in matrix["configurations"]:
        found = list(shared)
        if "RUN" in item["status"].replace("NOT_RUN", "").replace("RUNNABLE", ""):
            found.append("status claims a run")
        real = any(a.get("mode") == "llm" for a in item["agents"].values())
        try:
            MultiAgentConfig.model_validate({"config_id": item["id"], "data_kind": "REAL_MODELS" if real else "DETERMINISTIC",
                                             **item["agents"]})
        except Exception as exc:  # noqa: BLE001
            found.append(f"invalid config: {exc}")
        for role, agent in item["agents"].items():
            if agent.get("mode") == "llm":
                task = "INTERPRET_BRIEF" if role == "mission_orchestrator" else "ALLOCATE"
                try:
                    evaluation.require_fit(agent["candidate"], task)
                except evaluation.TaskNotApplicable as exc:
                    found.append(f"{role}: {exc}")
        out[item["id"]] = found
    return out
