"""Common contract for comparable results across models, and the task x model compatibility matrix.

Every result, whatever the model, is an EvaluationRecord (``tfg.multiagent.eval-record/1``): experiment, dataset
(id, version, split, sha256), case, TASK, model (provider, model, version, kind), generation parameters, prompt
(template id and sha256), structured output, validator results, metrics, latency, cost (value or UNKNOWN),
resources and data kind. Records of different tasks are NOT pooled: metrics are only compared within a task.

Tasks fit what each model is:
- INTERPRET_BRIEF  text -> MissionBrief                                  (chat/generative models, rules baseline)
- ALLOCATE         swarm problem -> assignment map                       (chat models, deterministic reference)
- CLASSIFY_REQUEST text -> decision among FEASIBLE/PARTIAL/... with p    (Clef; chat models only secondarily)
- SELECT_ALLOCATION labelled candidate allocations -> choice with p      (Clef: structured decision among options)
Clef is never asked to write a plan or a brief: those cells are NOT_APPLICABLE and the runner refuses them.
"""
from __future__ import annotations

import hashlib
import json
import resource
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RECORD_SCHEMA = "tfg.multiagent.eval-record/1"
TASKS = ("INTERPRET_BRIEF", "ALLOCATE", "CLASSIFY_REQUEST", "SELECT_ALLOCATION")
Fit = Literal["PRIMARY", "SECONDARY", "NOT_APPLICABLE"]

# model id -> (kind, {task: fit}). SECONDARY: technically possible through a prompt, not what the model is for.
MATRIX: dict[str, tuple[str, dict[str, str]]] = {
    "rules": ("DETERMINISTIC_BASELINE", {"INTERPRET_BRIEF": "PRIMARY", "ALLOCATE": "NOT_APPLICABLE",
                                         "CLASSIFY_REQUEST": "NOT_APPLICABLE", "SELECT_ALLOCATION": "NOT_APPLICABLE"}),
    "reference-allocator": ("DETERMINISTIC_REFERENCE", {"INTERPRET_BRIEF": "NOT_APPLICABLE", "ALLOCATE": "PRIMARY",
                                                        "CLASSIFY_REQUEST": "NOT_APPLICABLE",
                                                        "SELECT_ALLOCATION": "PRIMARY"}),
    "ollama-qwen": ("CHAT", {"INTERPRET_BRIEF": "PRIMARY", "ALLOCATE": "PRIMARY", "CLASSIFY_REQUEST": "SECONDARY",
                             "SELECT_ALLOCATION": "SECONDARY"}),
    "aida-qwen": ("CHAT", {"INTERPRET_BRIEF": "PRIMARY", "ALLOCATE": "PRIMARY", "CLASSIFY_REQUEST": "SECONDARY",
                           "SELECT_ALLOCATION": "SECONDARY"}),
    "aida-clef": ("STRUCTURED_DECISION", {"INTERPRET_BRIEF": "NOT_APPLICABLE", "ALLOCATE": "NOT_APPLICABLE",
                                          "CLASSIFY_REQUEST": "PRIMARY", "SELECT_ALLOCATION": "PRIMARY"}),
    "hermes-provider": ("CHAT_AGENT_PROVIDER", {"INTERPRET_BRIEF": "PRIMARY", "ALLOCATE": "SECONDARY",
                                                "CLASSIFY_REQUEST": "SECONDARY", "SELECT_ALLOCATION": "NOT_APPLICABLE"}),
    "scripted-double": ("TEST_DOUBLE", {t: "PRIMARY" for t in TASKS}),
}


class TaskNotApplicable(ValueError):
    """This model is not evaluated on this task (e.g. Clef asked to write a brief)."""


def model_family(candidate: str) -> str:
    if candidate in ("oracle", "rules"):
        return "rules" if candidate == "rules" else "reference-allocator"
    if candidate.startswith("ollama:"):
        return "ollama-qwen"
    if candidate.startswith("scripted"):
        return "scripted-double"
    return {"aida-qwen": "aida-qwen", "aida-clef": "aida-clef", "clef": "aida-clef", "hermes": "hermes-provider"}.get(
        candidate, candidate)


def fit(candidate: str, task: str) -> str:
    family = model_family(candidate)
    if family not in MATRIX or task not in TASKS:
        raise TaskNotApplicable(f"unknown model {candidate!r} or task {task!r}")
    return MATRIX[family][1][task]


def require_fit(candidate: str, task: str) -> str:
    value = fit(candidate, task)
    if value == "NOT_APPLICABLE":
        raise TaskNotApplicable(f"{candidate} is not evaluated on {task} ({MATRIX[model_family(candidate)][0]})")
    return value


def matrix_markdown() -> str:
    lines = ["| model | kind | " + " | ".join(TASKS) + " |", "|" + " --- |" * (len(TASKS) + 2)]
    for model, (kind, cells) in MATRIX.items():
        lines.append(f"| {model} | {kind} | " + " | ".join(cells[t] for t in TASKS) + " |")
    return "\n".join(lines) + "\n"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Cost(_Strict):
    status: Literal["KNOWN", "UNKNOWN", "NOT_APPLICABLE"]
    value: float | None = None
    currency_or_unit: str | None = None
    basis: str


class EvaluationRecord(_Strict):
    schema_: Literal["tfg.multiagent.eval-record/1"] = Field(RECORD_SCHEMA, alias="schema")
    experiment_id: str
    dataset: dict
    case_id: str
    run_index: int = Field(ge=0)
    task: Literal["INTERPRET_BRIEF", "ALLOCATE", "CLASSIFY_REQUEST", "SELECT_ALLOCATION"]
    model: dict  # provider, model, version, kind, family
    task_fit: Fit
    generation: dict  # temperature, seed, json mode... as sent; {} for deterministic candidates
    prompt: dict  # template_id, sha256 (the text stays in the trace, redacted)
    output: dict  # structured output (brief / assignment / decision), and raw sha256 when a model replied
    validators: list[dict]
    metrics: dict
    latency_s: float | None
    cost: Cost
    resources: dict
    data_kind: str
    trace_sha256: str | None = None

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)


def _cost(tokens, price_per_1k, family) -> Cost:
    if family in ("rules", "reference-allocator", "scripted-double"):
        return Cost(status="NOT_APPLICABLE", basis="no model call")
    if tokens is not None and price_per_1k is not None:
        return Cost(status="KNOWN", value=tokens / 1000 * price_per_1k, currency_or_unit="declared price per 1k tokens",
                    basis="reported tokens x declared price")
    return Cost(status="UNKNOWN", basis="no declared price" if tokens is not None else "tokens not reported")


def records_from_rows(rows, *, experiment_id, dataset, candidate, data_kind, price_per_1k=None) -> list[dict]:
    """INTERPRET_BRIEF records of a benchmark run (one per case and run)."""
    family = model_family(candidate)
    task_fit = require_fit(candidate, "INTERPRET_BRIEF") if candidate != "oracle" else "PRIMARY"
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    out = []
    for row in rows:
        spans = row.get("_records") or []
        interpret = next((s for s in spans if s["name"] == "interpret"), {})
        call = interpret.get("model_call") or {}
        proposal = row.get("_proposal") or {}
        record = EvaluationRecord(
            experiment_id=experiment_id, dataset=dataset, case_id=row["case_id"], run_index=row.get("run_index", 0),
            task="INTERPRET_BRIEF", task_fit=task_fit,
            model={"candidate": candidate, "family": family, "kind": MATRIX.get(family, ("UNKNOWN",))[0],
                   "provider": call.get("provider") or (interpret.get("model") or {}).get("provider"),
                   "model": call.get("model") or (interpret.get("model") or {}).get("model"),
                   "version": (interpret.get("model") or {}).get("version")},
            generation=call.get("generation") or {}, prompt=call.get("prompt") or {"template_id": None, "sha256": None},
            output={"brief": proposal.get("brief"), "raw_sha256": call.get("raw_sha256"),
                    "parse_error": call.get("parse_error"), "parse_detail": call.get("parse_detail"),
                    "extra_text": call.get("extra_text"), "finish_reason": call.get("finish_reason"),
                    "mission_status": proposal.get("status"), "proposal_sha256": proposal.get("proposal_sha256"),
                    "outcome": row.get("outcome"), "error_kind": row.get("error_kind")},
            validators=[{"name": s["name"], "agent": s["agent"], "status": s["status"]} for s in spans
                        if s["kind"] == "validation"],
            metrics={k: row[k] for k in ("case_pass", "status_match", "extraction_accuracy", "structural_validity",
                                         "constraint_compliance", "safety_ok", "coverage_match", "conflicts_ok",
                                         "makespan_ratio")} | {"criteria": row["criteria"], "outcome": row.get("outcome"),
                                                               "invented_fields": row.get("invented_fields", []),
                                                               "tokens": row.get("tokens")},
            latency_s=row["latency_s"], cost=_cost(row.get("tokens"), price_per_1k, family),
            resources={"max_rss_mib_this_process": rss, "gpu_memory": "NOT_MEASURED", **(row.get("resources") or {})},
            data_kind=data_kind,
            trace_sha256=row["trace"]["trace_sha256"])
        out.append(record.model_dump(mode="json", by_alias=True))
    return out


# ------------------------------------------------------------------ SELECT_ALLOCATION (Clef-shaped) --
def allocation_options(reference: dict, limit: int = 4) -> list[dict]:
    """Labelled candidate allocations (A, B, ...) from the reference ranking; the reference best is not marked."""
    alternatives = reference.get("_alternatives") or []
    options = []
    for label, alt in zip("ABCDEFGH", alternatives[:limit]):
        options.append({"label": label, "assignment": {v: a["objective_ids"] for v, a in sorted(alt["assignments"].items())},
                        "covered": alt["covered"], "makespan_min": round(alt["makespan_min"], 4)})
    return options


def option_text(options: list[dict]) -> str:
    return json.dumps({"question": "Which allocation should the planner keep?", "options": options}, sort_keys=True)


def score_selection(options: list[dict], decision: dict) -> dict:
    """Option A is the reference best (rank 0). Brier score against that one-hot target."""
    labels = [o["label"] for o in options]
    probs = {d["label"]: d["probability"] for d in decision["decisions"] if d["label"] in labels}
    rank = labels.index(decision["top"]) if decision["top"] in labels else None
    brier = sum((probs.get(l, 0.0) - (1.0 if l == labels[0] else 0.0)) ** 2 for l in labels)
    return {"chosen": decision["top"], "chosen_rank": rank, "picked_reference_best": rank == 0,
            "valid_label": rank is not None, "brier": brier}


def select_allocation_record(*, experiment_id, dataset, case_id, adapter, options, candidate="aida-clef") -> dict:
    require_fit(candidate, "SELECT_ALLOCATION")
    text = option_text(options)
    response = adapter.classify(text, [o["label"] for o in options])
    score = score_selection(options, response.structured)
    family = model_family(candidate)
    return EvaluationRecord(
        experiment_id=experiment_id, dataset=dataset, case_id=case_id, run_index=0, task="SELECT_ALLOCATION",
        task_fit=fit(candidate, "SELECT_ALLOCATION"),
        model={"candidate": candidate, "family": family, "kind": MATRIX[family][0], **{k: adapter.info.get(k)
               for k in ("provider", "model", "version")}},
        generation={}, prompt={"template_id": "select_allocation/1", "sha256": hashlib.sha256(text.encode()).hexdigest()},
        output={"decision": response.structured}, validators=[{"name": "label_in_options", "status":
                                                                "PASS" if score["valid_label"] else "FAIL"}],
        metrics=score, latency_s=response.latency_s, cost=_cost(None, None, family),
        resources={"gpu_memory": "NOT_MEASURED"}, data_kind=response.data_kind).model_dump(mode="json", by_alias=True)
