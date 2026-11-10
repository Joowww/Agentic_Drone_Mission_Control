"""Opik DATASETS and EXPERIMENTS for the benchmark: structure and dry-run payloads only. Nothing is uploaded here.

Three different things, never mixed:
- execution TRACES: what a run did (multiagent.opik_bridge; the only thing a send can carry today);
- DATASETS: the benchmark cases (input text, expected criteria, gold brief), one Opik dataset per frozen version:
  multiagent-eval_v2, multiagent-dev_v3, multiagent-eval_v3, multiagent-adversarial_v3;
- EXPERIMENTS: one candidate (model + prompt + pipeline + generation) over one dataset, linking each dataset item
  to the trace of the run that answered it. An experiment exists only for runs that really happened and have
  traces (today: the qwen3:4b pilot and its rules baseline on 11 eval_v2 items).

Comparison design: the same dataset items under experiments named
  <dataset>@<version> | <candidate> | <prompt id> | pipeline <v> | <run label>
so Opik's experiment comparison lines up qwen3:4b (local), rules, AIDA Qwen, the Hermes provider and prompt
versions item by item. Clef is compared only on its tasks (CLASSIFY_REQUEST, SELECT_ALLOCATION), in experiments
over the same items but with its own task tag, never next to brief-generation scores.

REST shapes are validated offline against the pinned Opik OpenAPI (multiagent.opik_contract) but NOT against the
service: before the first upload, one dataset with one item is created and read back, separately authorized.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from observability import opik_export as opik

from multiagent import opik_bridge
from multiagent.benchmark import run as bench

DATASETS = ("eval_v2", "dev_v3", "eval_v3", "adversarial_v3")
PATHS = {"datasets": "/v1/private/datasets", "dataset_items": "/v1/private/datasets/items",
         "experiments": "/v1/private/experiments", "experiment_items": "/v1/private/experiments/items"}
SHAPE_STATUS = "VALIDATED_AGAINST_PINNED_OPENAPI_NOT_SERVICE"
EPOCH = datetime(2026, 11, 4, tzinfo=timezone.utc)  # fixed id time component: ids must not depend on today


def dataset_name(dataset_id: str) -> str:
    return f"multiagent-{dataset_id}"


def item_id(dataset_id: str, version: str, case_id: str) -> str:
    key = opik.make_destination(opik_bridge.PROJECT, opik_bridge.WORKSPACE)["key"]
    return opik.deterministic_uuid7(key, f"dataset-item|{dataset_id}@{version}|{case_id}", EPOCH)


def _constraints(case: dict) -> dict:
    gold = case.get("gold_brief") or {}
    return {k: v for k, v in {
        "wind_speed_kmh": gold.get("wind_speed_kmh"), "battery_percent": gold.get("battery_percent") or None,
        "altitude_m": gold.get("altitude_m"), "drones_requested": gold.get("drones") or None,
        "vehicle_availability": gold.get("vehicle_availability") or None,
        "context_overrides": case.get("context_overrides"),
        "unsafe_request": bool(gold.get("unsafe_requests")), "contradiction": bool(gold.get("contradictions"))}.items()
        if v not in (None, False)}


def dataset_payload(dataset_id: str) -> dict:
    """Dataset_Write + DatasetItemBatch_Write (data/source shape of the pinned OpenAPI), validated offline."""
    from multiagent import opik_contract as contract
    data = bench.dataset(dataset_id)
    frozen = data["frozen_check"]
    provenance = {"dataset_id": dataset_id, "file": f"multiagent/benchmark/{data['file']}", "sha256": data["sha256"],
                  "version": data["version"], "split": data["split"], "pipeline": data.get("pipeline", "v1"),
                  "frozen": "FROZEN_MATCH" if frozen and set(frozen.values()) == {"MATCH"} else
                  ("FROZEN_CHANGED" if frozen else "NOT_FROZEN"), "data_kind": "SYNTHETIC_BENCHMARK_CASE"}
    items = [{"id": item_id(dataset_id, data["version"], c["case_id"]), "source": "sdk",
              "data": {"case_id": c["case_id"], "input": c["text"],
                       "expected_output": {"criteria": c["expected"], "gold_brief": c["gold_brief"]},
                       "category": c["category"], "constraints": _constraints(c),
                       "scenario": {"context": c.get("context") or data["suite"].get("context"),
                                    "context_overrides": c.get("context_overrides")},
                       "note": c.get("note"), "provenance": provenance},
              "tags": [f"case:{c['case_id']}", f"category:{c['category']}", f"split:{data['split']}"]}
             for c in data["suite"]["cases"]]
    dataset = {"name": dataset_name(dataset_id), "project_name": opik_bridge.PROJECT, "visibility": "private",
               "tags": [f"version:{data['version']}", f"split:{data['split']}", f"sha256:{data['sha256'][:16]}"],
               "description": (f"TFG multi-agent benchmark {dataset_id} v{data['version']} ({data['split']}), sha256 "
                               f"{data['sha256'][:16]}, {provenance['frozen']}; SYNTHETIC cases")[:255]}
    batch = {"dataset_name": dataset_name(dataset_id), "project_name": opik_bridge.PROJECT, "items": items}
    contract.dataset_write(dataset)
    contract.dataset_items(batch)
    return {"dataset": dataset, "items": batch, "provenance": provenance}


def experiment_name(dataset_id, version, candidate, prompt_id, pipeline, label) -> str:
    return f"{dataset_id}@{version} | {candidate} | {prompt_id or 'no-prompt'} | pipeline {pipeline} | {label}"


def experiment_id(name: str) -> str:
    key = opik.make_destination(opik_bridge.PROJECT, opik_bridge.WORKSPACE)["key"]
    return opik.deterministic_uuid7(key, f"experiment|{name}", EPOCH)


def experiment_payload(results_dir: Path, *, candidate_dir: str, label: str, tags=(), metadata=None) -> dict:
    """Experiment_Write + ExperimentItemsBatch of a sealed run: each dataset item linked to the trace id the bridge
    gives that case (same id whether or not the trace was sent). Status completed: the run really happened."""
    from multiagent import opik_contract as contract
    plan = opik_bridge.historical_plan(results_dir, candidate_dir=candidate_dir)
    report = json.loads((Path(results_dir) / candidate_dir / "report.json").read_text())
    ds = report["dataset"]
    prompt_id = ds.get("prompt_id") or next((t["metadata"]["tfg_prompt"].get("template_id") for t in plan.traces), None)
    name = experiment_name(ds["id"], ds["version"], report["candidate"], prompt_id, ds.get("pipeline", "v1"), label)
    eid = experiment_id(name)
    write = {"id": eid, "name": name, "dataset_name": dataset_name(ds["id"]), "project_name": opik_bridge.PROJECT,
             "type": "regular", "status": "completed", "tags": ["tfg-multiagent", "historical-import", *tags],
             "metadata": {"candidate": report["candidate"], "data_kind": report["data_kind"],
                          "experiment_id": report.get("experiment_id"), "prompt_id": prompt_id,
                          "pipeline": ds.get("pipeline", "v1"), "dataset_version": ds["version"],
                          "dataset_sha256": ds.get("sha256"), "source": opik_bridge._rel(results_dir),
                          "items": len(plan.traces), **(metadata or {})}}
    items = {"experiment_items": [{"experiment_id": eid, "project_name": opik_bridge.PROJECT, "trace_id": t["id"],
                                   "dataset_item_id": item_id(ds["id"], ds["version"], t["metadata"]["tfg_case_id"])}
                                  for t in plan.traces]}
    contract.experiment_write(write)
    contract.experiment_items(items)
    return {"experiment": write, "items": items, "cases": [t["metadata"]["tfg_case_id"] for t in plan.traces],
            "requires_traces_sent_first": True}


def comparison_design() -> dict:
    return {"axes": {"candidate": ["ollama:qwen3:4b", "rules", "aida-qwen", "hermes", "aida-clef (own tasks only)"],
                     "prompt": ["interpret_brief/1", "interpret_brief/2"], "pipeline": ["v1", "v2"],
                     "generation": ["think off", "think on", "temperature 0.7 x 3 seeds"]},
            "same_items_rule": "experiments are compared only over the same dataset name and version",
            "existing_experiments_with_traces": ["eval_v2@2 | ollama:qwen3:4b | interpret_brief/1 | pipeline v1 | pilot_v1 (11 items)",
                                                 "eval_v2@2 | rules | no-prompt | pipeline v1 | pilot_v1 (11 items)"],
            "not_yet_possible": ["sealed v2/v3 rules baselines: their result directories keep no traces (rerun with the "
                                 "pilot runner, which keeps traces, to make them experiments)",
                                 "any AIDA, Hermes or prompt /2 experiment: no run exists"],
            "scores": "metadata travels in the traces; feedback scores are mapped by multiagent.opik_metrics (only "
                      "OBSERVED values) and prepared by multiagent.opik_phase2, not uploaded",
            "rest_shape_status": SHAPE_STATUS}


def dry_run(results_dir: Path) -> dict:
    return {"status": "DRY_RUN_NOT_UPLOADED", "shape_status": SHAPE_STATUS, "paths": PATHS,
            "destination": {"workspace": opik_bridge.WORKSPACE, "project": opik_bridge.PROJECT},
            "datasets": {d: dataset_payload(d) for d in DATASETS},
            "experiments": [experiment_payload(results_dir, candidate_dir=c, label="pilot_v1") for c in ("qwen", "rules")],
            "comparison_design": comparison_design()}
