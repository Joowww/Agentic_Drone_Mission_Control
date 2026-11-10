"""Reproducible real Hermes capture with the TFG plugin, review and Opik dry-run. Offline by default.

Subcommands:

- ``capture``: offline preflight of the installed Hermes, its config and the plugin; creates and
  runs nothing. ``capture --execute`` performs ONE real oneshot turn with the habitual profile and
  its normal authentication (never read, copied or printed here): the plugin is enabled
  temporarily through ``plugins.enabled`` (Hermes has no supported per-run switch) and the
  config is restored afterwards only if it still holds exactly what this utility wrote.
  ``--mcp-tool-trial`` replaces the zero-tool ``catalog`` turn with ONE neutral call to the
  project's read-only ``get_mission_state``: ``--toolsets tfg-mission-control`` plus a temporary
  ``mcp_servers.tfg-mission-control.tools`` filter that registers only that tool (restored with
  the rest of the config). ``--trial-case agri-planning-h1`` uses the same isolation with the two
  planning tools of that case instead (prepared; its artifacts are judged by bind_scenario).
- ``review``: validates the capture JSONL, provenance records and hashes, copies the reviewed
  material into a NEW evidence directory and writes a local summary that keeps the main turn and
  Hermes' auxiliary title generation apart.
- ``opik-dry-run``: builds the Opik payload for an explicit destination with
  ``--provenance captured``. Never sends and never reads an API key; sending stays a separate
  ``observability.opik_export --send`` action.

Cross-process exclusion is NOT available: Hermes guards config writes with an in-process lock
only, so another process can edit config.yaml at any moment. The utility refuses to start when
another Hermes process is visible in /proc, writes atomically and restores only by compare-and-
replace; a concurrent edit is reported and never overwritten. A writer that races between the
final compare and the replace can still be lost (unavoidable without a shared lock).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from uuid import UUID

import yaml

from observability import capture_summary
from observability import mission_query_cases
from observability.hermes_capture import capture
from observability import langsmith_export as common
from observability import opik_export
from observability.langsmith_export import ExportError

UTILITY_VERSION = "1"
REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE = REPO_ROOT / "observability" / "hermes_capture"
PLUGIN_NAME = "tfg-observability-capture"
PLUGIN_FILES = ("plugin.yaml", "__init__.py", "capture.py", "event.schema.json", "tool-offer.schema.json",
                "tool-result-check.schema.json")
DEFAULT_HOME = Path.home() / ".hermes"
DEFAULT_BIN = Path.home() / ".local" / "bin" / "hermes"
DEFAULT_PRIVATE_ROOT = Path.home() / "tfg-hermes-capture-private"
DEFAULT_PROMPT = "Responde únicamente con la palabra OK."
DEFAULT_TIMEOUT_S = 120
MAX_TIMEOUT_S = 600
# Installed sources where `--toolsets catalog` was verified to select zero tools and no MCP server
# (evidence evaluation/hermes_native_usage_2026_10_21/a8fe21d9-.../cli_contract.json,
# Hermes commit d923a5eb487a17c0a68801bba9ef0f56c81040a8). Any change => refuse until re-verified.
VERIFIED_HERMES_COMMIT = "d923a5eb487a17c0a68801bba9ef0f56c81040a8"
VERIFIED_SOURCES = {
    "hermes_cli/_parser.py": "75fa3070d9cdcbeaa3fc1424e9c3dba06a403b9d43c74aaccc3b82829edf366c",
    "hermes_cli/oneshot.py": "ebd2bc6a320f24fa94249dab37a0776f4d32c92bb7ac3f6c7193f14eefecfdc9",
    "hermes_cli/mcp_startup.py": "1d36dc9ff5ba0d8f7a51b366aa7799a94316fc04c486a9252315ff5d4d034be6",
    "toolsets.py": "7674a11eeebcc06b7c83c816fca0bc6982107870f5615375d2ffc5dbe6044eaa",
    "model_tools.py": "fbb40d0058e3edd6c4e1608b8db9e922aaf38d2c9d0438c3811c6d6b01b45340",
    "agent/agent_init.py": "9f8c91db2ae36194dcd0e187d8ef237fd8337ef35b8f4eb22b4faf6cf6575187",
}
TOOLSET_SELECTION = "catalog"
# --- single MCP tool trial (capture/review --mcp-tool-trial) --------------------------------
# `--toolsets <server>` selects the alias Hermes registers for `mcp-<server>`, and
# `mcp_servers.<server>.tools.include` limits which server tools are registered; resources/prompts
# utilities are switched off. Verified in these installed sources (same commit); the plugin's
# tool_offer records then show what each API request actually offered.
MCP_SERVER = "tfg-mission-control"
TRIAL_TOOL = "get_mission_state"
TRIAL_REGISTRY_NAME = "mcp__tfg_mission_control__get_mission_state"  # Hermes mcp_prefixed_tool_name
TRIAL_RUN_ID = "00000000-0000-4000-8000-000000000000"  # canonical UUID, checked unused before the run
TRIAL_EXPECTED_STATUS = "NOT_FOUND"
TRIAL_PROMPT = (f"Llama una sola vez a la herramienta {TRIAL_REGISTRY_NAME} con run_id=\"{TRIAL_RUN_ID}\" "
                "y view=\"summary\". Después responde únicamente con el valor del campo status del resultado.")
TRIAL_CASE_ID = "mcp-get-mission-state"
TRIAL_TOOLS_FILTER = {"include": [TRIAL_TOOL], "resources": False, "prompts": False}


def registry_name(tool: str, server: str = MCP_SERVER) -> str:
    """Hermes mcp_prefixed_tool_name for a tool of one of this project's servers (default tfg-mission-control)."""
    return "mcp__" + server.replace("-", "_") + "__" + tool


def tools_filter(tools) -> dict:
    return {"include": list(tools), "resources": False, "prompts": False}


class _Absent:
    """Expectation marker: the JSON pointer must not exist (distinct from an expected null)."""

    def __repr__(self):
        return "ABSENT"


ABSENT = _Absent()
# Historical case: a real, finished preflight from 2026-10-18 (sequence member, request_key without a
# personal name). Its local files are pinned; the expectation lists ONLY these pointers of the
# tool's summary view and their recorded values (checked offline against the real tool).
HISTORICAL_RUN_ID = "467f7ec6-b2a6-4b68-9d97-766d85732f8e"
HISTORICAL_FILES = {
    "job.json": "5a7bb17f1acdeaf15936b0658208341c9690b3533a503ac899d2ba1ddc6a1b4c",
    "report.json": "d967bc138c2c9a9834ba0a845417139a491c01953bd9690b610a10ac7b155451",
    "mission.json": "b9fb6ce534e7704deabcefc4b493c978d7f633f437ab5e2aa894d8332e5e8c74",
    "input.json": "b9fb6ce534e7704deabcefc4b493c978d7f633f437ab5e2aa894d8332e5e8c74",
}
HISTORICAL_EXPECTED = (
    # What the tool says about the query itself: historical, nothing current checked or granted.
    ("/status", "KNOWN_WITH_WARNINGS"), ("/readiness_now", "UNKNOWN_NOT_CHECKED"),
    ("/consent", "NOT_GRANTED_BY_THIS_QUERY"), ("/hardware_authorized", False),
    # The recorded run (2026-10-18), exactly one preflight in the answer.
    ("/preflights/0/run_id", HISTORICAL_RUN_ID), ("/preflights/1", ABSENT),
    ("/preflights/0/job_state", "FINISHED"), ("/preflights/0/phase", "analyze"),
    ("/preflights/0/result_status", "PASSED"), ("/preflights/0/worker_alive", False),
    ("/preflights/0/mission_sha256", "b9fb6ce534e7704deabcefc4b493c978d7f633f437ab5e2aa894d8332e5e8c74"),
    ("/preflights/0/snapshot_integrity", "VERIFIED_LOCAL_HASH"),
    ("/preflights/0/readiness_now", "UNKNOWN_NOT_CHECKED"),
    ("/preflights/0/vehicle_selection/vehicle_id", "drone_01"),
    ("/preflights/0/vehicle_selection/simulated_vehicle", "v1"),
    ("/preflights/0/report/status", "PASSED"),
    ("/preflights/0/report/finished_at", "2026-10-18T21:18:42.180468+00:00"),
    ("/preflights/0/report/mission_identity/mission_id", "simulation_navigation_3waypoint_001"),
    ("/preflights/0/report/validation/mission_status", "FEASIBLE"),
    ("/preflights/0/report/executor_result/status", "COMPLETED"),
    ("/preflights/0/report/executor_result/waypoints_completed", 3),
    ("/preflights/0/report/executor_result/return_to_home", True),
    ("/preflights/0/report/analysis/passed", True),
)
TRIAL_CASES = {
    "not-found": {"run_id": TRIAL_RUN_ID, "case_id": TRIAL_CASE_ID, "prompt": TRIAL_PROMPT,
                  "expected_answer": TRIAL_EXPECTED_STATUS, "run_must_exist": False, "expected": None},
    "historical-passed": {
        "run_id": HISTORICAL_RUN_ID, "case_id": "mcp-get-mission-state-historical",
        "prompt": (f"Llama una sola vez a la herramienta {TRIAL_REGISTRY_NAME} con run_id=\"{HISTORICAL_RUN_ID}\" "
                   "y view=\"summary\". Después responde únicamente con el valor de result_status de la "
                   "ejecución consultada."),
        "expected_answer": "PASSED", "run_must_exist": True, "expected": HISTORICAL_EXPECTED},
}
# Multi-field case (PREPARED): the real FAILED run of 2026-10-17, read through view=external. Its report
# is byte-identical to the Git-tracked failed_wp3_report.json; the expected answer is derived from it by
# observability.mission_query_cases (a test recomputes it).
FAILED_RUN_ID = "d4519cab-ebd1-4359-b547-44be38294a6a"
FAILED_FILES = {"report.json": "f265cf77fef275c4f0cc600a546dc6a4e339b80116dc3ba97caf0e25c92777a2",
                "mission.json": "2366d5a2c38f092e7ce5b01220f49463001dbf8164db6706899ff26beb9d56d1"}
FAILED_EXPECTED = (
    ("/view", "external"), ("/external_schema_version", 1), ("/status", "KNOWN_WITH_WARNINGS"),
    ("/readiness_now", "UNKNOWN_NOT_CHECKED"), ("/queried/run_id", FAILED_RUN_ID), ("/rejected_fields/0", ABSENT),
    ("/preflights/0/run_id", FAILED_RUN_ID), ("/preflights/1", ABSENT),
    ("/preflights/0/result_status", "FAILED"), ("/preflights/0/report_stage", "analyze"),
    ("/preflights/0/execution_attempted", True), ("/preflights/0/mission_id", "prueba_hermes_001"),
    ("/preflights/0/vehicle_id", "drone_01"), ("/preflights/0/simulated_vehicle", "v1"),
    ("/preflights/0/planned_waypoint_ids/0", "WP1"), ("/preflights/0/planned_waypoint_ids/1", "WP2"),
    ("/preflights/0/planned_waypoint_ids/2", "WP3"), ("/preflights/0/planned_waypoint_ids/3", ABSENT),
    ("/preflights/0/reached_waypoint_ids/0", "WP1"), ("/preflights/0/reached_waypoint_ids/1", "WP2"),
    ("/preflights/0/reached_waypoint_ids/2", ABSENT),
    ("/preflights/0/waypoints_completed", None), ("/preflights/0/return_to_home", None),
    ("/preflights/0/landing_evidence_count", 0),
    ("/preflights/0/recovery_landing_completed", True), ("/preflights/0/recovery_landed", True),
)
FAILED_ANSWER = {
    "run_id": FAILED_RUN_ID, "historical_status": "FAILED", "mission_id": "prueba_hermes_001",
    "vehicle_id": "drone_01", "simulated_vehicle": "v1", "planned_waypoint_ids": ["WP1", "WP2", "WP3"],
    "reached_waypoint_ids": ["WP1", "WP2"], "return_to_home": "UNKNOWN", "mission_landed_event_recorded": False,
    "recovery_landing_completed": True, "current_availability": "UNKNOWN",
}
TRIAL_CASES["failed-structured"] = {
    "run_id": FAILED_RUN_ID, "case_id": "mcp-mission-failed-structured",
    "prompt": (f"Llama una sola vez a la herramienta {TRIAL_REGISTRY_NAME} con run_id=\"{FAILED_RUN_ID}\" y "
               "view=\"external\". Después responde únicamente con un objeto JSON, sin texto adicional, con "
               "exactamente estas claves: run_id (texto), historical_status (texto), mission_id (texto), "
               "vehicle_id (texto), simulated_vehicle (texto), planned_waypoint_ids (lista de textos), "
               "reached_waypoint_ids (lista de textos), return_to_home (booleano), "
               "mission_landed_event_recorded (booleano: true si landing_evidence contiene un evento LANDED con "
               "landed=true, false si landing_evidence es una lista vacía), recovery_landing_completed "
               "(booleano) y current_availability (texto). Escribe el texto \"UNKNOWN\" en cualquier clave cuyo "
               "dato sea null o no figure en el resultado; no lo deduzcas de otros campos. current_availability "
               "es la disponibilidad actual del simulador: \"UNKNOWN\" salvo que el resultado incluya una "
               "comprobación actual."),
    "expected_answer": None, "answer": FAILED_ANSWER, "run_must_exist": True, "files": FAILED_FILES,
    "recorded_status": "FAILED", "job_required": False, "expected": FAILED_EXPECTED,
    "arguments": (("run_id", FAILED_RUN_ID), ("view", "external")),
    # Executed 2026-10-22 17:40 against external schema 1 (FINAL_RESPONSE_NOT_AS_EXPECTED). Kept only to
    # re-review that evidence: its expectation bytes must not change. It no longer matches the view.
    "superseded_by": "failed-structured-v2",
}
# v2 (PREPARED): same real FAILED run, external schema 2 (executor facts / acceptance criteria /
# recovery as separate groups) and a prompt that names the exact source field of every key, from
# mission_query_cases.ANSWER_CONTRACT, without any expected value.
_KIND_ES = {"text": "texto", "list of text": "lista de textos", "boolean": "booleano"}
FAILED_V2_PROMPT = (
    f"Llama una sola vez a la herramienta {TRIAL_REGISTRY_NAME} con run_id=\"{FAILED_RUN_ID}\" y "
    "view=\"external\". Después responde únicamente con un objeto JSON, sin texto adicional, con exactamente "
    "estas 11 claves. Toma cada valor solo del campo indicado del resultado (preflights[0] es la ejecución "
    "consultada); si ese campo es null o no existe, escribe el texto \"UNKNOWN\". No uses acceptance_criteria "
    "ni ningún otro campo para rellenar una clave.\n"
    + "\n".join(
        f"- {key} ({_KIND_ES[kind]}): "
        + {"mission_landed_event_recorded": "preflights[0].executor_facts.mission_landing_events; true si algún "
                                            "evento tiene landed=true, false si la lista está vacía",
           "current_availability": "readiness_now; \"UNKNOWN\" si vale UNKNOWN_NOT_CHECKED"}.get(
            key, pointer.lstrip("/").replace("preflights/0/", "preflights[0].").replace("/", "."))
        for key, (pointer, kind, _) in mission_query_cases.ANSWER_CONTRACT.items()))
FAILED_V2_EXPECTED = (
    ("/view", "external"), ("/external_schema_version", 2), ("/status", "KNOWN_WITH_WARNINGS"),
    ("/readiness_now", "UNKNOWN_NOT_CHECKED"), ("/queried/run_id", FAILED_RUN_ID), ("/rejected_fields/0", ABSENT),
    ("/preflights/1", ABSENT),
    ("/preflights/0/identity/run_id", FAILED_RUN_ID), ("/preflights/0/identity/mission_id", "prueba_hermes_001"),
    ("/preflights/0/identity/vehicle_id", "drone_01"), ("/preflights/0/identity/simulated_vehicle", "v1"),
    ("/preflights/0/record/result_status", "FAILED"), ("/preflights/0/record/report_stage", "analyze"),
    ("/preflights/0/record/execution_attempted", True),
    ("/preflights/0/plan/planned_waypoint_ids/0", "WP1"), ("/preflights/0/plan/planned_waypoint_ids/1", "WP2"),
    ("/preflights/0/plan/planned_waypoint_ids/2", "WP3"), ("/preflights/0/plan/planned_waypoint_ids/3", ABSENT),
    ("/preflights/0/executor_facts/status", "FAILED"),
    ("/preflights/0/executor_facts/reached_waypoint_ids/0", "WP1"),
    ("/preflights/0/executor_facts/reached_waypoint_ids/1", "WP2"),
    ("/preflights/0/executor_facts/reached_waypoint_ids/2", ABSENT),
    ("/preflights/0/executor_facts/waypoints_completed", None),
    ("/preflights/0/executor_facts/return_to_home", None),
    ("/preflights/0/executor_facts/mission_landing_event_count", 0),
    # The trap of the v1 trial is still present, now under its own group.
    ("/preflights/0/acceptance_criteria/passed", False),
    ("/preflights/0/acceptance_criteria/checks/return_home_reached", False),
    ("/preflights/0/recovery_after_failure/landing_completed", True),
    ("/preflights/0/recovery_after_failure/landed", True),
)
TRIAL_CASES["failed-structured-v2"] = {
    "run_id": FAILED_RUN_ID, "case_id": "mcp-mission-failed-structured-v2", "prompt": FAILED_V2_PROMPT,
    "expected_answer": None, "answer": FAILED_ANSWER, "run_must_exist": True, "files": FAILED_FILES,
    "recorded_status": "FAILED", "job_required": False, "expected": FAILED_V2_EXPECTED,
    "arguments": (("run_id", FAILED_RUN_ID), ("view", "external")),
    # Executed 2026-10-23 08:42 (FINAL_RESPONSE_NOT_AS_EXPECTED: null instead of "UNKNOWN"). Kept to re-review.
    "superseded_by": "failed-structured-v3",
}
# v3 (PREPARED): same run, same view and result expectation as v2; answer contract v3, in which
# return_to_home is true, false or null (null = not recorded) and the key must be present.
FAILED_V3_PROMPT = FAILED_V2_PROMPT.replace(
    "escribe el texto \"UNKNOWN\". No uses",
    "escribe el texto \"UNKNOWN\", salvo en return_to_home (ver su línea). No uses").replace(
    "- return_to_home (booleano): preflights[0].executor_facts.return_to_home",
    "- return_to_home (true, false o null): preflights[0].executor_facts.return_to_home; copia true o false tal "
    "como figure y escribe null (no el texto \"UNKNOWN\") si es null o no existe. La clave debe aparecer siempre")
FAILED_ANSWER_V3 = {**FAILED_ANSWER, "return_to_home": None}
EXTERNAL_VIEW_SHA256 = "394d0c1978b80ba475b15204646f8d7c2aeb39c83a8d52ebd92111c7f7627335"  # view schema 2, as run 2026-10-23 08:42
TRIAL_CASES["failed-structured-v3"] = {
    "run_id": FAILED_RUN_ID, "case_id": "mcp-mission-failed-structured-v3", "prompt": FAILED_V3_PROMPT,
    "expected_answer": None, "answer": FAILED_ANSWER_V3, "answer_contract": "v3", "run_must_exist": True,
    "files": FAILED_FILES, "recorded_status": "FAILED", "job_required": False, "expected": FAILED_V2_EXPECTED,
    "arguments": (("run_id", FAILED_RUN_ID), ("view", "external")),
    "pinned_sources": {"tools/mission_external_view.py": EXTERNAL_VIEW_SHA256},
    # Executed 2026-10-23 08:53 (TOOL_NOT_REQUESTED: answered without calling the tool). Kept to re-review.
    "superseded_by": "failed-structured-v4",
}
# v4 (PREPARED): same run, view, result expectation and nullable contract v3; a short prompt whose first
# step is the call. Hermes d923a5eb48 offers no supported way to FORCE the call for this oneshot route
# (chat_completions never sets tool_choice; request_overrides only via custom_providers/delegation), so
# the call stays the model's choice and a missing call is rejected (TOOL_NOT_REQUESTED), never accepted.
def query_prompt(run_id: str) -> str:
    """Short historical-query prompt (v4 wording): the call first, then the contract-v3 JSON answer."""
    return (
        f"Paso 1: llama a {TRIAL_REGISTRY_NAME} con run_id=\"{run_id}\" y view=\"external\". "
        "No respondas antes de tener su resultado.\n"
        "Paso 2: responde solo un objeto JSON con estas 11 claves, leídas de preflights[0] del resultado:\n"
        "run_id, mission_id, vehicle_id, simulated_vehicle <- identity; historical_status <- record.result_status; "
        "planned_waypoint_ids <- plan.planned_waypoint_ids; reached_waypoint_ids, return_to_home <- executor_facts; "
        "mission_landed_event_recorded <- executor_facts.mission_landing_events (true si algún landed=true, false si "
        "está vacía); recovery_landing_completed <- recovery_after_failure.landing_completed; "
        "current_availability <- readiness_now (\"UNKNOWN\" si es UNKNOWN_NOT_CHECKED).\n"
        "return_to_home es true, false o null (null si no consta). En las demás claves, \"UNKNOWN\" si no consta. "
        "Nunca uses acceptance_criteria."
    )


FAILED_V4_PROMPT = query_prompt(FAILED_RUN_ID)
TRIAL_CASES["failed-structured-v4"] = {
    **{k: v for k, v in TRIAL_CASES["failed-structured-v3"].items() if k != "superseded_by"},
    "case_id": "mcp-mission-failed-structured-v4", "prompt": FAILED_V4_PROMPT, "tool_call_forced": False,
}
DEFAULT_TRIAL_CASE = "not-found"
QUERY_CASE_ID = "mcp-mission-query"
# H1 planning case (PREPARED, not run): Hermes builds the two agri_demo_001 missions from a request with
# H0's explicit data. update_mission_draft already generates the route from a complete geometry_intent
# (generate_draft_route only wraps it) and finalize_mission_draft returns mission_path, mission_sha256 and
# the validation, so these two tools suffice; get_mission_state is not needed. Everything operational,
# execution, reconciliation, revision and redundant validation stays unregistered. No result
# expectation: the artifacts are accepted afterwards by reporting.agri_scenario_summary.bind_scenario.
PLANNING_TOOLS = ("update_mission_draft", "finalize_mission_draft")
AGRI_PLANNING_PROMPT = (
    "Prepara dos misiones de planificación para el escenario agrícola de demostración agri_demo_001. Usa solo "
    "estos datos, que aporta el operador; no inventes, completes ni cambies ninguno. Los puntos de interés son "
    "datos declarados del escenario, no detecciones, y no se toman imágenes. Batería, consumo y viento son "
    "valores de referencia del escenario, no lecturas reales. No arranques simulaciones ni pidas ejecutar vuelos.\n"
    "Datos comunes: multirrotor ArduPilot; velocidad de crucero 35 km/h; batería 100 %; consumo 0.8 % por minuto; "
    "objective_type precision_agriculture; viento 0 km/h desde 0 grados; reserva mínima de batería 20 %; viento "
    "máximo 30 km/h; altitud máxima 120 m; low_battery_action, unsafe_wind_action y communication_loss_action "
    "RETURN_TO_HOME. Ruta en geometry_intent con mode offsets: home en latitud 41.275, longitud 1.987 y altitud 0; "
    "altitude_reference relative_to_home; altitude_m 5; return_to_home true; close_route false.\n"
    "Misión 1: mission_id agri_demo_001_h1_sector_a; name \"agri_demo_001 H1 sector A\"; vehicle_id drone_01; "
    "objective_target agri_demo_001_sector_a; offsets en este orden: POI_A1 north_m 8, east_m -4; POI_A2 north_m "
    "16, east_m -4.\n"
    "Misión 2: mission_id agri_demo_001_h1_sector_b; name \"agri_demo_001 H1 sector B\"; vehicle_id drone_02; "
    "objective_target agri_demo_001_sector_b; offsets en este orden: POI_B1 north_m 8, east_m 4; POI_B2 north_m "
    "16, east_m 4.\n"
    "Para cada misión, crea un borrador con update_mission_draft con todos sus datos y la ruta en geometry_intent, "
    "y después finalízalo con finalize_mission_draft usando su draft_id y su draft_revision. Al terminar, responde "
    "solo un objeto JSON con, para cada mission_id, su finalization_id, status y validation.execution_status."
)
TRIAL_CASES["agri-planning-h1"] = {
    "kind": "planning", "tools": PLANNING_TOOLS, "case_id": "mcp-agri-planning-h1", "prompt": AGRI_PLANNING_PROMPT,
    "run_id": None, "run_check": "none", "run_must_exist": False, "expected_answer": None, "answer": None,
    "expected": None,
    # The exact code that produces the responses the provider will receive; re-pin after reviewing a change.
    "pinned_sources": {
        "tools/hermes_mcp_server.py": "24068e725d9f104b5325ec166b081a4ba4e4c1bb849cf2913095d73b045a0491",
        "tools/hermes_mission_planning.py": "63f47b38a08e67f529ac6da6e49181c20cc1fced2bd7529e74c64e175f378a54",
        "planning/relative_routes.py": "d3847791d340a2abc31b49fae3f6bf3eda7012ae55b30b9d5edbf2e403673573",
        "planning/mission_plan_service.py": "11d8f1f03c3e2b589c568304b3aefe2bb50b3bfd4307a3af7695701373352a5e",
        "tools/hermes_mission_validation.py": "9e7ac22529abc0e05bd4e17e2b8b94d8c7b21774c59cf870394b12de9b22fdf8",
    },
    "writes": ("missions/generated/drafts/<draft_id>/: draft.json, draft_state.json, draft.lock; and per "
               "finalization <finalization_id>/: source_draft.json, source_draft_state.json, mission.json, "
               "<mission_id>.plan, finalization.json. No simulation, vehicle, reservation or preflight effect."),
}


# H3 scenario query (PREPARED): one isolated turn over the two REAL H2 children (sequence 6628bc51,
# key agri-demo-001-h2-r01), with the same read-only tool and external view as the historical queries.
# The view has no sequence order, scenario summary or rover task, so those facts are supplied as
# application context (from plan.json and scenario_summary.json); record.started_at in the view is the
# job's admission time, not the flight start. The answer is accepted afterwards by
# reporting.agri_scenario_summary accept-h3 against the session's real results and the saved summary.
H3_RUN_IDS = ("2f7db1f6-ef92-4302-b1ae-ec5566e24757", "febf7c4f-27c8-4486-bd3b-63ce0a5f261a")
AGRI_H3_PROMPT = (
    f"Paso 1: llama a {TRIAL_REGISTRY_NAME} con run_id=\"{H3_RUN_IDS[0]}\" y view=\"external\".\n"
    f"Paso 2: llama a {TRIAL_REGISTRY_NAME} con run_id=\"{H3_RUN_IDS[1]}\" y view=\"external\".\n"
    "No respondas antes de tener los dos resultados.\n"
    "Contexto aportado por la aplicación, no por la herramienta: esos run_id son los hijos 1 y 2, en ese orden, "
    "de la secuencia SITL 6628bc51-e232-45f5-901e-f5fdeb05c6f4 (clave agri-demo-001-h2-r01), con estado "
    "FINISHED y resultado PASSED; el coordinador solo inicia el hijo 2 tras verificar el PASSED del hijo 1. "
    "record.started_at de la herramienta es la hora de admisión del trabajo, no la del despegue. Resumen "
    "determinista del escenario agri_demo_001: status AERIAL_COMPLETED_GROUND_PENDING, scenario_complete false. "
    "Asociación de puntos de interés declarados por el operador (no son detecciones): drone_01 WP1=POI_A1, "
    "WP2=POI_A2; drone_02 WP1=POI_B1, WP2=POI_B2. Tarea terrestre R1 (rover_01 hacia POI_A1): status "
    "BLOCKED_PENDING, dependency MET, commands_sent false; barreras: identidad del rover no establecida, sin "
    "entrada pública con autorización y reservas, sin navegación hasta una posición. No hubo imágenes ni "
    "percepción agrícola; la velocidad no se comandó ni se midió; los hechos del ejecutor proceden de sus "
    "observaciones por AP_DDS.\n"
    "Paso 3: responde solo un objeto JSON con estas claves:\n"
    "sequence_order (lista de vehicle_id en orden de ejecución); runs (lista, una entrada por resultado, con "
    "run_id, vehicle_id, simulated_vehicle, mission_id <- identity; result_status <- record.result_status; "
    "reached_waypoint_ids, return_to_home <- executor_facts; mission_landed: true si "
    "executor_facts.mission_landing_events tiene algún landed=true, false si está vacía); reached_points (lista "
    "de POI alcanzados según la asociación y reached_waypoint_ids); scenario_complete (booleano); r1_status; "
    "r1_dependency; r1_commands_sent (booleano); r1_movement_authorized (booleano: si la dependencia satisfecha "
    "autoriza mover el rover); evidence_source (texto breve); explanation (texto en español: qué hicieron "
    "ambos drones y en qué orden, qué POI se alcanzaron, qué evidencia respalda regreso y aterrizaje, por qué el "
    "escenario sigue incompleto, qué significa que la dependencia de R1 esté MET y qué queda pendiente y qué "
    "limitaciones impiden afirmar más). No uses acceptance_criteria para rellenar runs."
)
TRIAL_CASES["agri-scenario-h3"] = {
    "kind": "scenario_query", "case_id": "mcp-agri-scenario-h3", "prompt": AGRI_H3_PROMPT, "run_id": None,
    "run_ids": H3_RUN_IDS, "run_check": "all_exist", "run_must_exist": True, "expected_answer": None,
    "answer": None, "expected": None,
    "pinned_sources": {"tools/mission_external_view.py": EXTERNAL_VIEW_SHA256,
                       "tools/mission_state.py": "e66dd901f37572bf0f174928398da919ea1d55d4290330c993e1d5551028d2be",
                       "tools/hermes_mcp_server.py": "24068e725d9f104b5325ec166b081a4ba4e4c1bb849cf2913095d73b045a0491"},
}


# Both executed once on 2026-10-24; their pins describe the sources of THOSE runs. tools/hermes_mcp_server.py
# changed afterwards (get_scenario_view), so they are kept only to re-review their evidence.
TRIAL_CASES["agri-planning-h1"]["superseded_by"] = "executed 2026-10-24 (evaluation/observability/agri_planning_h1_nous_2026_10_24)"
# Planning profile's first real turn (PREPARED 27/10/2026, not run): the SAME prompt and tools as H1, run inside
# the containerized planning profile (deploy/planner; procedure in docs/planning-first-real-test.md). Its pins are
# the server sources at preparation time; any change refuses the run until reviewed and re-pinned.
TRIAL_CASES["agri-planning-container"] = {
    **{k: v for k, v in TRIAL_CASES["agri-planning-h1"].items() if k != "superseded_by"},
    "case_id": "mcp-agri-planning-container",
    "pinned_sources": {
        "tools/hermes_mcp_server.py": "7083b65763f8279e6a9641ed83241685698745278e1af61fd5976f4817a9ad7e",
        "tools/hermes_mission_planning.py": "63f47b38a08e67f529ac6da6e49181c20cc1fced2bd7529e74c64e175f378a54",
        "planning/relative_routes.py": "d3847791d340a2abc31b49fae3f6bf3eda7012ae55b30b9d5edbf2e403673573",
        "planning/mission_plan_service.py": "11d8f1f03c3e2b589c568304b3aefe2bb50b3bfd4307a3af7695701373352a5e",
        "tools/hermes_mission_validation.py": "a4720d052aa3885fdcf23ed66e1f34aa3cb45bc7f07bc6d6d0439ba5d2298d26",
    },
}
TRIAL_CASES["agri-scenario-h3"]["superseded_by"] = "agri-scenario-h3b"
# H3b (PREPARED, not run): the same question, answered from ONE deterministic read-only scenario view
# instead of application context pasted into the prompt. The prompt names fields of the view, never values.
H3B_TOOL = "get_scenario_view"
H3B_REQUEST_KEY = "agri-demo-001-h2-r01"
AGRI_H3B_PROMPT = (
    f"Paso 1: llama a {registry_name(H3B_TOOL)} con scenario_id=\"agri_demo_001\" y request_key=\"{H3B_REQUEST_KEY}\". "
    "No respondas antes de tener su resultado.\n"
    "Paso 2: responde solo un objeto JSON. Toma cada valor únicamente del resultado de la herramienta; si un dato no "
    "figura, escribe null. Claves:\n"
    "scenario_status <- scenario.status (o status si scenario es null); scenario_complete <- scenario.scenario_complete; "
    "sequence_order <- scenario.order.vehicle_order (null si scenario.order.status no es "
    "ACCREDITED_BY_EXECUTION_TIMESTAMPS); order_basis: \"EXECUTION_TIMESTAMPS\" si scenario.order.status es "
    "ACCREDITED_BY_EXECUTION_TIMESTAMPS, si no \"NOT_ACCREDITED\"; runs: una entrada por scenario.runs con run_id, "
    "vehicle_id, simulated_vehicle, mission_id, status, result_status, reached_points (POI con valor REACHED en "
    "points), return_home, landing, executor_started_at y executor_finished_at (de timeline); r1_status, "
    "r1_dependency, r1_commands_sent, r1_movement_authorized <- scenario.ground_task (status, dependency, "
    "commands_sent, movement_authorized); claims: objeto con images_captured, detections_made, speed_commanded, "
    "speed_measured, simultaneous_flight, common_frame_validated y current_permissions_checked, cada uno true solo si "
    "el resultado lo registra (ver limitations y scope); evidence_source (texto breve); explanation (texto en español: "
    "qué hicieron los drones y en qué orden, qué lo acredita, qué POI se alcanzaron, qué respalda regreso y "
    "aterrizaje, por qué el escenario está o no completo, qué significa la dependencia de R1 y qué límites impiden "
    "afirmar más).\n"
    "timeline.job_admitted_at es la admisión del trabajo, no el despegue."
)
TRIAL_CASES["agri-scenario-h3b"] = {
    "kind": "scenario_query", "tools": (H3B_TOOL,), "case_id": "mcp-agri-scenario-h3b", "prompt": AGRI_H3B_PROMPT,
    "run_id": None, "request_key": H3B_REQUEST_KEY, "run_check": "sequence_exists", "run_must_exist": True,
    "expected_answer": None, "answer": None, "expected": None,
    "pinned_sources": {
        "tools/hermes_mcp_server.py": "1cf136c9da94a96367500d88182d6cf438cafaf6a5210d697756117b886e035e",
        "reporting/agri_scenario_summary.py": "eb9c5783b62f8adff85f50d2540bd460d094db8c9a117ed4f12c94668def4e32",
        "tools/preflight_sequences.py": "80aae52ed0e220d7d43222bb2151517e8ca7055cd321be90b0cb805fab33389b",
        "tools/virtual_preflight_jobs.py": "64ec1039eacd53d654ab1311e3b2003f7fb530dabfbfe205b646ad164485fd17",
    },
}


# Executed once on 2026-10-24 (evaluation/observability/agri_scenario_h3b_nous_2026_10_24); its pins describe
# that run. reporting/agri_scenario_summary.py changed afterwards (deterministic report), so it is closed.
TRIAL_CASES["agri-scenario-h3b"]["superseded_by"] = "executed 2026-10-24 (evaluation/observability/agri_scenario_h3b_nous_2026_10_24)"


# Evaluation pilot (PREPARED, not run): repetitions of the REAL H2 case with H3b's prompt, tool and contract,
# pinned to the current sources. Each repetition is one separately labelled capture run (--run-id), reviewed
# and accepted with accept-h3b. Synthetic pilot cases are code-level only (reporting pilot-dry-run).
TRIAL_CASES["agri-scenario-pilot-real"] = {
    **{k: v for k, v in TRIAL_CASES["agri-scenario-h3b"].items() if k not in ("superseded_by", "pinned_sources")},
    "case_id": "mcp-agri-scenario-pilot-real",
    "pinned_sources": {
        "tools/hermes_mcp_server.py": "1cf136c9da94a96367500d88182d6cf438cafaf6a5210d697756117b886e035e",
        "reporting/agri_scenario_summary.py": "24f01c77ed38aba1b53e87e0c2a5f8a26521f5606f2f1c102fe7d64f23ecd624",
        "tools/preflight_sequences.py": "80aae52ed0e220d7d43222bb2151517e8ca7055cd321be90b0cb805fab33389b",
        "tools/virtual_preflight_jobs.py": "64ec1039eacd53d654ab1311e3b2003f7fb530dabfbfe205b646ad164485fd17",
    },
}
# Executed on 2026-10-24 (pilot-real-r01..r10, evaluation/observability/agri_scenario_pilot_nous_2026_10_24);
# its pins describe those runs. reporting/agri_scenario_summary.py changed afterwards (reached_points fix).
TRIAL_CASES["agri-scenario-pilot-real"]["superseded_by"] = \
    "executed 2026-10-24 (evaluation/observability/agri_scenario_pilot_nous_2026_10_24)"


# Planning evaluation pilot v1 (PREPARED 31/10/2026, not run): twelve single-turn cases over the two planning tools,
# defined with their pins in evaluation/hermes_planning_pilot_v1/cases.json. Each repetition is one separately
# labelled capture run; its turn is accepted afterwards by reporting.hermes_planning_pilot (not by bind-h1).
PLANNING_PILOT_FILE = REPO_ROOT / "evaluation" / "hermes_planning_pilot_v1" / "cases.json"


def register_planning_pilot(path: Path = PLANNING_PILOT_FILE) -> list[str]:
    if not path.is_file():
        return []
    suite = json.loads(path.read_text(encoding="utf-8"))
    names = []
    for case in suite["cases"]:
        name = "planning-pilot-" + case["case_id"].lower()
        TRIAL_CASES[name] = {
            "kind": "planning", "tools": PLANNING_TOOLS, "case_id": "mcp-" + name, "prompt": case["operator_request"],
            "run_id": None, "run_check": "none", "run_must_exist": False, "expected_answer": None, "answer": None,
            "expected": None, "pinned_sources": dict(suite["pinned_sources"]),
            "writes": TRIAL_CASES["agri-planning-h1"]["writes"]}
        names.append(name)
    return names


PLANNING_PILOT_CASES = register_planning_pilot()


def case_tools(trial_case: str) -> tuple:
    return tuple(TRIAL_CASES[trial_case].get("tools", (TRIAL_TOOL,)))


def case_server(trial_case: str) -> str:
    return TRIAL_CASES[trial_case].get("server", MCP_SERVER)


# Local Hermes + Ollama planning demo (PREPARED 08/11/2026). Unlike the cases above it does NOT edit a
# habitual home temporarily: it runs in its own permanent profile (tfg-demo-local) whose config already
# offers only the planning-only server tfg-demo-planning (tools/hermes_demo_planning_server.py, which
# registers nothing else), Tool Search off and the capture plugin enabled. Two operator turns in ONE
# Hermes session: the first omits the three safety limits (Hermes must ask for them), the second supplies
# them and asks for finalization. Mission data: H1 sector A (agri_demo_001, FEASIBLE/APPROVED on 24/10).
# Run, review and view with observability.local_planning_demo; opik-dry-run below works on its evidence.
LOCAL_DEMO_CASE = "local-planning-demo"
LOCAL_DEMO_SERVER = "tfg-demo-planning"
LOCAL_DEMO_TURN_1 = (
    "Quiero planificar una misión para el escenario agrícola de demostración agri_demo_001. Usa solo estos "
    "datos, que aporta el operador; no inventes, completes ni cambies ninguno. Los puntos de interés son datos "
    "declarados del escenario, no detecciones, y no se toman imágenes. Batería, consumo y viento son valores de "
    "referencia del escenario, no lecturas reales. No arranques simulaciones ni pidas ejecutar vuelos.\n"
    "Datos: mission_id agri_demo_001_h1_sector_a; name \"agri_demo_001 H1 sector A\"; vehicle_id drone_01; "
    "multirrotor ArduPilot; velocidad de crucero 35 km/h; batería 100 %; consumo 0.8 % por minuto; "
    "objective_type precision_agriculture; objective_target agri_demo_001_sector_a; viento 0 km/h desde 0 "
    "grados; low_battery_action, unsafe_wind_action y communication_loss_action RETURN_TO_HOME. Ruta en "
    "geometry_intent con mode offsets: home en latitud 41.275, longitud 1.987 y altitud 0; altitude_reference "
    "relative_to_home; altitude_m 5; return_to_home true; close_route false; offsets en este orden: POI_A1 "
    "north_m 8, east_m -4; POI_A2 north_m 16, east_m -4.\n"
    "Guarda el borrador con update_mission_draft. Si falta algún dato para poder finalizar la misión, "
    "pregúntamelo; no lo supongas."
)
LOCAL_DEMO_TURN_2 = (
    "Estos son los datos que faltaban, para el mismo borrador: reserva mínima de batería 20 %; viento máximo "
    "30 km/h; altitud máxima 120 m. Guárdalos en ese borrador con update_mission_draft y, si ya no falta "
    "nada, finalízalo con finalize_mission_draft. Después resume el resultado: status, "
    "validation.mission_status, validation.execution_status y el estado de la exportación QGC. No arranques "
    "simulaciones ni ejecutes vuelos."
)
TRIAL_CASES[LOCAL_DEMO_CASE] = {
    "kind": "planning", "local_demo": True, "server": LOCAL_DEMO_SERVER, "tools": PLANNING_TOOLS,
    "case_id": "mcp-local-planning-demo", "prompts": (LOCAL_DEMO_TURN_1, LOCAL_DEMO_TURN_2),
    "prompt": LOCAL_DEMO_TURN_1 + "\n\n" + LOCAL_DEMO_TURN_2,  # the pair; only its hash is recorded
    "omitted_in_turn_1": ("minimum_battery_reserve_percent", "maximum_wind_speed_kmh", "maximum_altitude_m"),
    "mission_source": "evaluation/observability/agri_planning_h1_nous_2026_10_24 (drone_01, sector A)",
    "run_id": None, "run_check": "none", "run_must_exist": False, "expected_answer": None, "answer": None,
    "expected": None,
    "writes": ("TFG_DEMO_DRAFT_ROOT (private, outside the repository)/<draft_id>/: draft.json, "
               "draft_state.json, draft.lock; per finalization <finalization_id>/: source_draft.json, "
               "source_draft_state.json, mission.json, finalization.json (and <mission_id>.plan only with an "
               "AMSL home). No simulation, vehicle, reservation or preflight effect."),
}


def register_query_case(run_id: str) -> str:
    """A generic historical query for an explicit, canonical run_id, through the same isolation as the
    trials (only get_mission_state, Tool Search off, temporary config restored, one invocation).

    No fixed expectation: acceptance compares the answer with the REAL result of that same turn
    (tools.mission_report_query), so the plugin gets no result-expectation file. The run must exist."""
    try:
        canonical = isinstance(run_id, str) and str(UUID(run_id)) == run_id
    except ValueError:
        canonical = False
    if not canonical:
        raise CaptureError("run_id must be a canonical UUID")
    key = f"query-{run_id}"
    TRIAL_CASES[key] = {
        "run_id": run_id, "case_id": QUERY_CASE_ID, "prompt": query_prompt(run_id), "expected_answer": None,
        "answer": None, "answer_contract": "v3", "run_must_exist": True, "run_check": "exists",
        "expected": None, "pinned_sources": {"tools/mission_external_view.py": EXTERNAL_VIEW_SHA256},
    }
    return key


def expectation_bytes(case: str):
    """The plugin's expectation file for a trial case, or None. ``ABSENT`` = the pointer must not
    exist; ``None`` = the value must be JSON null. Arguments, when listed, check the executed call."""
    expected = TRIAL_CASES[case]["expected"]
    if expected is None:
        return None
    checks = [{"pointer": p, "absent": True} if v is ABSENT else {"pointer": p, "expected": v} for p, v in expected]
    spec = {"schema": capture.EXPECTATION_SCHEMA, "tool_name": TRIAL_REGISTRY_NAME, "checks": checks}
    if TRIAL_CASES[case].get("arguments"):
        spec["arguments"] = [{"key": k, "expected": v} for k, v in TRIAL_CASES[case]["arguments"]]
    return _json_bytes(spec)
TRIAL_SOURCES = {
    **VERIFIED_SOURCES,
    "tools/mcp_tool_registration.py": "7e73a415283c5255fedeb9318fceeb556eb31a19cea2e9bd3d9fdfc0f9297ade",
    "tools/mcp_tool_schema.py": "21ab2ef8b122add133af4ef387b32f6e8c6711f6e1b2f6f4744bcb279fa2135b",
    "tools/mcp_schema_cache.py": "a9ddf72a63bbacb527f6d50cbaac7f73e6e88f1236c0fd626e39a15e4b1152ad",
    "tools/registry.py": "4a05aae5b4dd40bf9a104d23582d4363326ad7ce3fdac1ac249e0af04334d909",
    "agent/turn_api_request.py": "fae43abf285e6f2b82d1820b7bd62ee10214676a48d6af552b8d62530e59dd15",
    "agent/conversation_loop.py": "926435d563ef1b7de1049f5c36897f1cda7376508b98164a68a0cb5192656270",
    "agent/display.py": "15348b9bca6cbe1eaf5daf294ad24018f92d719496c70c5dabce86092e4ca12e",
    # Tool Search: _tri_state("off") disables the bridge; load_config deep-merges over the defaults.
    "tools/tool_search.py": "b9ee4f80dba8e51cb78d287daaa94aa2193f38d73675637e0692e2c5ecbe0324",
    "hermes_cli/config.py": "a1667a958f52aa6201200bde354c3a380d79d49fd7635aeee3a3ebb23533a788",
    "hermes_cli/config_defaults.py": "3770f92378e37093720040de6d4813202a88edc7a196415dfc7be7b4e88064d7",
    # No supported forced tool call on this route (2026-10-24): chat_completions never sets tool_choice
    # and request_overrides come only from custom_providers / delegation. Re-check if these change.
    "agent/transports/chat_completions.py": "1a8f7fa6a60815013e2b3e6f2ea4f65b665e8686933381896bed898abe201072",
    "hermes_cli/runtime_provider_custom.py": "d52d70eb1c3d3f01ecd8b1f4a3565ec514214d20f821bd36f2b1032e552aceac",
    # untrusted_tool_result wrapper that tools/mission_report_query.unwrap_untrusted reads (2026-10-24).
    "agent/tool_dispatch_helpers.py": "fded1508e518f2f248dd1ced597b6222b54b2f8c901a6a736402a9572c9c2faa",
}
TRIAL_SERVER_ARGS = ["-m", "tools.hermes_mcp_server"]
# Recorded in every trial run.json: the server code the trial will run. mission_external_view.py was
# added on 2026-10-23 (earlier run.json files do not list it; they are not amended). A case may also
# PIN some of them ("pinned_sources"): the preflight then blocks if the file changed.
TRIAL_SERVER_SOURCES = ("tools/hermes_mcp_server.py", "tools/mission_state.py", "tools/virtual_preflight_jobs.py",
                        "tools/mission_response_views.py", "tools/mission_external_view.py")
_MCP_LINE = re.compile(rb"^mcp_servers:[ \t]*(#.*)?$")
_MCP_KEY = re.compile(rb"^mcp_servers[ \t]*:")
_SERVER_LINE = re.compile(rb"^  " + re.escape(MCP_SERVER.encode()) + rb":[ \t]*(#.*)?$")
# Tool Search is "auto" by default and activates for ANY MCP tool (tools/tool_search.py:
# should_activate), replacing it with bridge tools; the 22/10 16:40 trial showed exactly that.
TRIAL_TOOL_SEARCH = "off"
_TOOLS_LINE = re.compile(rb"^tools:[ \t]*(#.*)?$")
_TOOLS_KEY = re.compile(rb"^tools[ \t]*:")
_TOOL_SEARCH_LINE = re.compile(rb"^  tool_search:[ \t]*(#.*)?$")
_TOOL_SEARCH_KEY = re.compile(rb"^  tool_search[ \t]*:")
NATIVE_ALLOWED = ("estimated_cost_usd", "cost_status", "cost_source", "input_tokens", "output_tokens",
                  "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "total_tokens", "api_calls",
                  "model", "provider", "completed", "partial", "interrupted", "turn_exit_reason", "failed",
                  "service_tier")
NATIVE_COUNTERS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                   "reasoning_tokens", "estimated_cost_usd", "total_tokens", "api_calls")
COMPARED_COUNTERS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                     "reasoning_tokens", "total_tokens")
_PLUGINS_LINE = re.compile(rb"^plugins:[ \t]*(#.*)?$")
_PLUGINS_KEY = re.compile(rb"^plugins[ \t]*:")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


class CaptureError(Exception):
    """A refused or failed step; the message never contains credentials or captured content."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path):
    try:
        return _sha(path.read_bytes())
    except FileNotFoundError:
        return None


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: bytes, mode: int = 0o600):
    """Temp file beside ``path``, fsync, rename over it: readers see the old or the new file."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("write made no progress")
            view = view[written:]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        os.unlink(tmp)
        raise
    os.close(fd)
    os.replace(tmp, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _write_new(path: Path, data: bytes, mode: int = 0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _json_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


# --- config edit -------------------------------------------------------------------------

def enable_plugin_text(raw: bytes) -> bytes:
    """Add ``plugins.enabled: [tfg-observability-capture]`` and nothing else (validated by parsing).

    Only a config without ``plugins.enabled`` is supported: an existing allow-list would mean
    other user plugins are active, which this utility does not take responsibility for."""
    lines = raw.split(b"\n")
    hits = [i for i, line in enumerate(lines) if _PLUGINS_LINE.match(line)]
    keys = [i for i, line in enumerate(lines) if _PLUGINS_KEY.match(line)]
    if len(keys) > 1 or keys != hits:  # duplicate or inline `plugins:` parses differently per loader
        raise CaptureError("config has a duplicate or inline top-level 'plugins' key")
    block = [b"  enabled:", b"    - " + PLUGIN_NAME.encode()]
    if len(hits) == 1:
        new = b"\n".join(lines[:hits[0] + 1] + block + lines[hits[0] + 1:])
    elif not hits:
        new = raw + (b"" if raw.endswith(b"\n") or not raw else b"\n") + b"plugins:\n" + b"\n".join(block) + b"\n"
    else:
        raise CaptureError("config has several top-level 'plugins:' lines")
    try:
        before, after = yaml.safe_load(raw) or {}, yaml.safe_load(new) or {}
    except yaml.YAMLError:
        raise CaptureError("config edit does not parse as YAML") from None
    plugins = after.get("plugins") if isinstance(after, dict) else None
    if not isinstance(plugins, dict) or plugins.pop("enabled", None) != [PLUGIN_NAME]:
        raise CaptureError("config edit did not produce plugins.enabled as expected")
    if not hits and plugins == {}:
        after.pop("plugins")
    if before != after:
        raise CaptureError("config edit would change more than plugins.enabled")
    return new


def restrict_mcp_text(raw: bytes, tools=(TRIAL_TOOL,)) -> bytes:
    """Add ``mcp_servers.<server>.tools`` = ``tools_filter(tools)`` and nothing else (validated by parsing).

    Only a block-style server entry without its own ``tools`` key is supported."""
    if not tools or any(not isinstance(t, str) or not re.fullmatch(r"[a-z_]+", t) for t in tools):
        raise CaptureError("tools must be plain MCP tool names")
    lines = raw.split(b"\n")
    hits = [i for i, line in enumerate(lines) if _MCP_LINE.match(line)]
    if len(hits) != 1 or [i for i, line in enumerate(lines) if _MCP_KEY.match(line)] != hits:
        raise CaptureError("config needs exactly one block-style top-level 'mcp_servers:' line")
    end = next((i for i in range(hits[0] + 1, len(lines)) if lines[i][:1] not in (b"", b" ", b"#")), len(lines))
    servers = [i for i in range(hits[0] + 1, end) if _SERVER_LINE.match(lines[i])]
    if len(servers) != 1:
        raise CaptureError(f"config needs exactly one block-style '{MCP_SERVER}:' entry under mcp_servers")
    following = lines[servers[0] + 1] if servers[0] + 1 < end else b""
    if not following.startswith(b"    ") or following.startswith(b"     "):
        raise CaptureError("server entry is not a 4-space block mapping")
    block = [b"    tools:", b"      include:", *(b"        - " + t.encode() for t in tools),
             b"      resources: false", b"      prompts: false"]
    new = b"\n".join(lines[:servers[0] + 1] + block + lines[servers[0] + 1:])
    try:
        before, after = yaml.safe_load(raw) or {}, yaml.safe_load(new) or {}
    except yaml.YAMLError:
        raise CaptureError("config edit does not parse as YAML") from None
    server = ((after.get("mcp_servers") or {}).get(MCP_SERVER) if isinstance(after, dict) else None) or {}
    if (before.get("mcp_servers") or {}).get(MCP_SERVER, {}).get("tools") is not None:
        raise CaptureError("server entry already has a 'tools' filter")
    if server.pop("tools", None) != tools_filter(tools):
        raise CaptureError("config edit did not produce the expected tools filter")
    if before != after:
        raise CaptureError("config edit would change more than the server's tools filter")
    return new


def disable_tool_search_text(raw: bytes) -> bytes:
    """Add ``tools.tool_search.enabled: "off"`` and nothing else (validated by parsing).

    Hermes reads it with ``_tri_state(str(value))``; the value is quoted so YAML keeps a string
    (bare ``off`` is a YAML 1.1 boolean). Existing ``tools``/``tool_search`` keys are preserved;
    an existing ``enabled`` is the operator's setting and is refused, never overridden."""
    lines = raw.split(b"\n")
    hits = [i for i, line in enumerate(lines) if _TOOLS_LINE.match(line)]
    if [i for i, line in enumerate(lines) if _TOOLS_KEY.match(line)] != hits or len(hits) > 1:
        raise CaptureError("config has a duplicate or inline top-level 'tools' key")
    enabled = b'enabled: "' + TRIAL_TOOL_SEARCH.encode() + b'"'
    if not hits:
        new = raw + (b"" if raw.endswith(b"\n") or not raw else b"\n") + b"tools:\n  tool_search:\n    " + enabled + b"\n"
    else:
        end = next((i for i in range(hits[0] + 1, len(lines)) if lines[i][:1] not in (b"", b" ", b"#")), len(lines))
        children = [line for line in lines[hits[0] + 1:end] if line.strip() and not line.lstrip().startswith(b"#")]
        if any(not c.startswith(b"  ") or (c.startswith(b"   ") and not c.startswith(b"    ")) for c in children):
            raise CaptureError("top-level 'tools' is not a 2-space block mapping")
        search = [i for i in range(hits[0] + 1, end) if _TOOL_SEARCH_LINE.match(lines[i])]
        if [i for i in range(hits[0] + 1, end) if _TOOL_SEARCH_KEY.match(lines[i])] != search or len(search) > 1:
            raise CaptureError("config has a duplicate or inline 'tools.tool_search' key")
        if search:
            insert, block = search[0] + 1, [b"    " + enabled]
        else:
            insert, block = hits[0] + 1, [b"  tool_search:", b"    " + enabled]
        new = b"\n".join(lines[:insert] + block + lines[insert:])
    try:
        before, after = yaml.safe_load(raw) or {}, yaml.safe_load(new) or {}
    except yaml.YAMLError:
        raise CaptureError("config edit does not parse as YAML") from None
    previous = (before.get("tools") or {}).get("tool_search") if isinstance(before.get("tools"), dict) else None
    if previous is not None and (not isinstance(previous, dict) or "enabled" in previous):
        raise CaptureError("tools.tool_search is already set; refusing to override the operator's value")
    tools = after.get("tools") if isinstance(after, dict) else None
    search_cfg = tools.get("tool_search") if isinstance(tools, dict) else None
    if not isinstance(search_cfg, dict) or search_cfg.pop("enabled", None) != TRIAL_TOOL_SEARCH:
        raise CaptureError('config edit did not produce tools.tool_search.enabled == "off" (string)')
    if not search_cfg and previous is None:
        tools.pop("tool_search")
    if not tools and "tools" not in before:
        after.pop("tools")
    if before != after:
        raise CaptureError("config edit would change more than tools.tool_search.enabled")
    return new


def tool_trial_config_text(raw: bytes, tools=(TRIAL_TOOL,)) -> bytes:
    """All temporary edits for the MCP tool trial: the server's tools filter, Tool Search off
    (otherwise Hermes replaces MCP tools with its tool_search/describe/call bridge), then
    plugins.enabled. Each step validates that it changes only its own key."""
    return enable_plugin_text(disable_tool_search_text(restrict_mcp_text(raw, tools)))


# --- preflight ---------------------------------------------------------------------------

def list_hermes_processes(own_pid=None):
    """Visible processes running the Hermes launcher or its agent checkout (argv only)."""
    own_pid = own_pid or os.getpid()
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == own_pid:
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if any(a.endswith(b"/.local/bin/hermes") or b"/.hermes/hermes-agent/" in a for a in argv):
            found.append(int(entry.name))
    return found


def list_mcp_server_processes(own_pid=None):
    """Visible processes running this project's MCP server module (argv only)."""
    own_pid = own_pid or os.getpid()
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == own_pid:
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if b"tools.hermes_mcp_server" in argv:
            found.append(int(entry.name))
    return found


def _trial_run_id_unused(repo: Path = REPO_ROOT, run_id: str = TRIAL_RUN_ID):
    """The neutral run_id must not name any run the tool could find (job dir or legacy report)."""
    if (repo / "missions" / "generated" / "preflights" / run_id).exists():
        return False
    reports = (repo / "simulation" / "ros2_gazebo" / "results").glob("virtual_preflight_*/*_report.json")
    return not any(run_id.encode() in p.read_bytes() for p in reports)


def _historical_run_matches(repo: Path = REPO_ROOT, run_id: str = HISTORICAL_RUN_ID, files=None,
                            status: str = "PASSED", job_required: bool = True):
    """(ok, detail): the pinned files are unchanged and record a finished run with ``status``."""
    files = HISTORICAL_FILES if files is None else files
    directory = repo / "missions" / "generated" / "preflights" / run_id
    changed = sorted(n for n, digest in files.items() if _file_sha(directory / n) != digest)
    if changed:
        return False, f"{run_id}: changed or missing {changed}"
    report = json.loads((directory / "report.json").read_bytes())
    ok = report.get("run_id") == run_id and report.get("status") == status and bool(report.get("finished_at"))
    if job_required:
        job = json.loads((directory / "job.json").read_bytes())
        ok = ok and job.get("run_id") == run_id and job.get("job_state") == "FINISHED"
    return ok, (f"{run_id}: pinned files unchanged; recorded {'job FINISHED / ' if job_required else ''}"
                f"report {status} (historical, not current)")


def preflight(*, home: Path = DEFAULT_HOME, hermes_bin: Path = DEFAULT_BIN, verified_sources=None,
              process_lister=list_hermes_processes, trial: bool = False,
              mcp_process_lister=list_mcp_server_processes, repo: Path = REPO_ROOT,
              trial_case: str = DEFAULT_TRIAL_CASE):
    """Read-only checks; returns a report with ``ok`` and the exact config edit that would be made.

    ``trial`` prepares the single MCP tool trial instead of the zero-tool ``catalog`` turn."""
    if verified_sources is None:
        verified_sources = TRIAL_SOURCES if trial else VERIFIED_SOURCES
    checks, facts = [], {}

    def check(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("hermes_binary", hermes_bin.is_file() and os.access(hermes_bin, os.X_OK), str(hermes_bin))
    agent = home / "hermes-agent"
    mismatched = sorted(rel for rel, digest in verified_sources.items() if _file_sha(agent / rel) != digest)
    verified = (f"sources match the version where --toolsets {MCP_SERVER} offers only the included tool"
                if trial else "sources match the version where --toolsets catalog selects zero tools/MCP")
    check("tool_selection_sources_verified", not mismatched,
          verified if not mismatched else f"changed or missing: {mismatched}; re-verify the tool selection first")
    config_path = home / "config.yaml"
    raw = config_path.read_bytes() if config_path.is_file() else None
    check("config_present", raw is not None, str(config_path))
    config = {}
    if raw is not None:
        facts["config_sha256"] = _sha(raw)
        try:
            config = yaml.safe_load(raw) or {}
        except yaml.YAMLError:
            config = None
        check("config_parses", isinstance(config, dict), "YAML mapping")
        config = config if isinstance(config, dict) else {}
        plugins = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}
        check("no_plugins_allow_list", "enabled" not in plugins,
              "plugins.enabled absent (no other user plugin is active)")
        check("plugin_not_disabled", PLUGIN_NAME not in (plugins.get("disabled") or []), "plugins.disabled")
        servers = config.get("mcp_servers") or {}
        check("no_mcp_named_like_selection", TOOLSET_SELECTION not in servers,
              f"configured MCP keys: {len(servers)}; none may be '{TOOLSET_SELECTION}'")
        check("no_shell_hooks", not config.get("hooks"), "top-level 'hooks' absent or empty")
        try:
            edited = tool_trial_config_text(raw, case_tools(trial_case)) if trial else enable_plugin_text(raw)
            facts["edited_config_sha256"] = _sha(edited)
            check("config_edit_isolated", True,
                  f"only plugins.enabled, mcp_servers.{MCP_SERVER}.tools (include {list(case_tools(trial_case))}) "
                  f'and tools.tool_search.enabled "{TRIAL_TOOL_SEARCH}" would be added' if trial
                  else "only plugins.enabled would be added")
        except CaptureError as exc:
            check("config_edit_isolated", False, str(exc))
        if trial:
            servers = servers if isinstance(servers, dict) else {}
            entry = servers.get(MCP_SERVER) if isinstance(servers.get(MCP_SERVER), dict) else {}
            check("trial_server_configured",
                  entry.get("enabled", True) is True and entry.get("command") == str(repo / ".venv" / "bin" / "python")
                  and entry.get("args") == TRIAL_SERVER_ARGS and "url" not in entry,
                  f"mcp_servers.{MCP_SERVER}: enabled stdio server running this repository's tools.hermes_mcp_server")
            check("trial_server_not_lazy", not entry.get("lazy"), "lazy servers register from the schema cache")
            others = sorted(n for n, s in servers.items()
                            if n != MCP_SERVER and not (isinstance(s, dict) and s.get("enabled") is False))
            check("no_other_mcp_server_enabled", not others,
                  f"{len(others)} other enabled MCP server(s); discovery would start them")
        facts["model"] = (config.get("model") or {}).get("default") if isinstance(config.get("model"), dict) else None
        facts["provider"] = (config.get("model") or {}).get("provider") if isinstance(config.get("model"), dict) else None
    plugins_dir = home / "plugins"
    entries = sorted(p.name for p in plugins_dir.iterdir()) if plugins_dir.is_dir() else []
    check("user_plugins_dir_empty", not entries, f"{plugins_dir}: {len(entries)} entries")
    missing = [f for f in PLUGIN_FILES if not (PLUGIN_SOURCE / f).is_file()]
    check("plugin_source_present", not missing, f"{PLUGIN_SOURCE}" + (f" missing {missing}" if missing else ""))
    facts["plugin_source_sha256"] = {f: _file_sha(PLUGIN_SOURCE / f) for f in PLUGIN_FILES}
    others = process_lister()
    check("no_other_hermes_process", not others, f"{len(others)} visible Hermes process(es)")
    if trial:
        servers_running = mcp_process_lister()
        check("no_project_mcp_server_process", not servers_running,
              f"{len(servers_running)} visible tools.hermes_mcp_server process(es)")
        case = TRIAL_CASES[trial_case]
        check("trial_case_not_profile_demo", not case.get("local_demo"),
              "runs in its own profile through observability.local_planning_demo, never by editing this home"
              if case.get("local_demo") else f"{trial_case} uses the temporary-edit flow")
        check("trial_case_current", not case.get("superseded_by"),
              f"superseded by {case['superseded_by']}; kept only to re-review its evidence"
              if case.get("superseded_by") else f"{trial_case} is a current case")
        if case.get("pinned_sources"):
            changed = sorted(rel for rel, digest in case["pinned_sources"].items() if _file_sha(repo / rel) != digest)
            check("trial_server_sources_pinned", not changed,
                  f"changed or missing: {changed}; review and re-pin before running" if changed
                  else f"{len(case['pinned_sources'])} pinned server source(s) unchanged")
        if case.get("run_check") == "none":
            pass  # a planning case queries no run
        elif case.get("run_check") == "sequence_exists":
            index = (repo / "missions" / "generated" / "preflight_sequences" / "requests"
                     / (_sha(case["request_key"].encode()) + ".json"))
            check("trial_sequence_exists", index.is_file(), f"request_key {case['request_key']} names an admitted sequence")
        elif case.get("run_check") == "all_exist":
            missing = [r for r in case["run_ids"] if _trial_run_id_unused(repo, r)]
            check("trial_runs_exist", not missing,
                  f"missing runs: {missing}" if missing else f"{len(case['run_ids'])} queried runs have job directories")
        elif case.get("run_check") == "exists":
            check("trial_run_exists", not _trial_run_id_unused(repo, case["run_id"]),
                  f"{case['run_id']} names a preflight job directory or legacy report")
        elif case["run_must_exist"]:
            check("trial_historical_run_pinned", *_historical_run_matches(
                repo, case["run_id"], case.get("files"), case.get("recorded_status", "PASSED"),
                case.get("job_required", True)))
        else:
            check("trial_run_id_unused", _trial_run_id_unused(repo, case["run_id"]),
                  f"{case['run_id']} names no preflight job directory or legacy report")
        facts["trial_server_sources_sha256"] = {rel: _file_sha(repo / rel) for rel in TRIAL_SERVER_SOURCES}
        facts["mcp_schema_cache_sha256"] = _file_sha(home / "cache" / "mcp_schema_cache.json")
    return {"utility_version": UTILITY_VERSION, "mode": "preflight", "hermes_home": str(home),
            "ok": all(c["ok"] for c in checks), "checks": checks, "facts": facts,
            "verified_hermes_commit": VERIFIED_HERMES_COMMIT,
            "toolset_selection": MCP_SERVER if trial else TOOLSET_SELECTION,
            "mcp_tool_trial": trial_plan(trial_case) if trial else None}


def trial_plan(trial_case: str = DEFAULT_TRIAL_CASE):
    """What the single MCP tool trial does and how its outcome is read; no secrets, no paths."""
    case = TRIAL_CASES[trial_case]
    expectation = expectation_bytes(trial_case)
    tools = case_tools(trial_case)
    single = len(tools) == 1
    return {"server": MCP_SERVER, "tool": tools[0] if single else None,
            "registry_name": registry_name(tools[0]) if single else None,
            "tools": list(tools), "registry_names": [registry_name(t) for t in tools],
            "tools_filter": tools_filter(tools), "tool_search_enabled": TRIAL_TOOL_SEARCH,
            "toolsets_argument": MCP_SERVER, "trial_case": trial_case,
            "prompt": case["prompt"], "prompt_sha256": _sha(case["prompt"].encode("utf-8")),
            "queried_run_id": case["run_id"], "run_must_exist": case["run_must_exist"],
            "expected_final_answer": case["expected_answer"], "expected_structured_answer": case.get("answer"),
            "expected_arguments": dict(case.get("arguments") or ()),
            "result_expectation_sha256": _sha(expectation) if expectation else None,
            "result_expectation_pointers": [p for p, _ in case["expected"] or ()],
            "tool_classification": (
                "planning writes only: " + case["writes"] if case.get("kind") == "planning"
                else "read-only: run_id lookup reads job/report files only; verified offline "
                     "under an audit hook (no writes, mkdir, subprocess or socket)")}


# --- execution ---------------------------------------------------------------------------

def _install_plugin(plugin_dir: Path, installed: dict):
    """Fill ``installed`` file by file, so a partial install is still removable."""
    plugin_dir.mkdir(mode=0o700)
    for name in PLUGIN_FILES:
        data = (PLUGIN_SOURCE / name).read_bytes()
        _write_new(plugin_dir / name, data, 0o644)
        installed[name] = _sha(data)


def _remove_plugin(plugin_dir: Path, installed: dict):
    """Remove only what was installed (plus Python bytecode caches); anything else stays."""
    if not plugin_dir.exists():
        return "absent"
    names = {p.name for p in plugin_dir.iterdir()}
    caches_ok = all(p.suffix == ".pyc" for p in (plugin_dir / "__pycache__").glob("*")) \
        if (plugin_dir / "__pycache__").is_dir() else True
    if names - set(installed) - {"__pycache__"} or not caches_ok or \
            any(_file_sha(plugin_dir / n) != d for n, d in installed.items() if (plugin_dir / n).exists()):
        return "changed_not_removed"
    shutil.rmtree(plugin_dir)
    return "removed"


def restore(*, config_path: Path, backup: bytes, original_sha: str, edited_sha: str, plugin_dir: Path,
            installed: dict, created_plugins_dir: Path | None, writer=_atomic_write):
    """Compare-and-restore: write the backup only over the exact bytes this utility wrote."""
    result = {"config": None, "plugin": None, "error_type": None}
    try:
        current = _file_sha(config_path)
        if current == edited_sha:
            writer(config_path, backup, 0o600)
            result["config"] = "restored" if _file_sha(config_path) == original_sha else "restore_unverified"
        elif current == original_sha:
            result["config"] = "already_original"
        else:
            result["config"] = "concurrent_edit_not_overwritten"
    except Exception as exc:  # never escape: the report must say what is left behind
        result.update(config="restore_failed", error_type=type(exc).__name__)
    try:
        result["plugin"] = _remove_plugin(plugin_dir, installed)
        if created_plugins_dir is not None and result["plugin"] in ("removed", "absent"):
            try:
                created_plugins_dir.rmdir()
            except OSError:
                pass
    except Exception as exc:
        result.update(plugin="removal_failed", error_type=result["error_type"] or type(exc).__name__)
    result["ok"] = result["config"] in ("restored", "already_original") and result["plugin"] in ("removed", "absent")
    return result


def _run_hermes(argv, *, env, cwd, stdout_path, stderr_path, timeout):
    """One process group, one wait with a deadline, TERM then KILL on timeout; never re-run."""
    with open(stdout_path, "xb") as out, open(stderr_path, "xb") as err:
        os.fchmod(out.fileno(), 0o600)
        os.fchmod(err.fileno(), 0o600)
        proc = subprocess.Popen(argv, stdout=out, stderr=err, stdin=subprocess.DEVNULL, env=env, cwd=cwd,
                                start_new_session=True)
        try:
            return proc.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
                try:
                    os.killpg(proc.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    proc.wait(timeout=grace)
                    break
                except subprocess.TimeoutExpired:
                    continue
            return proc.returncode, True


def execute_capture(*, home: Path = DEFAULT_HOME, hermes_bin: Path = DEFAULT_BIN, private_root: Path = DEFAULT_PRIVATE_ROOT,
                    prompt: str = DEFAULT_PROMPT, timeout: float = DEFAULT_TIMEOUT_S, run_id: str, case_id: str,
                    verified_sources=None, process_lister=list_hermes_processes, base_env=None, writer=_atomic_write,
                    trial: bool = False, mcp_process_lister=list_mcp_server_processes, repo: Path = REPO_ROOT,
                    trial_case: str = DEFAULT_TRIAL_CASE):
    """ONE real Hermes turn with temporary plugin enablement. Returns the run report.

    ``trial``: the single MCP tool trial (fixed prompt per ``trial_case``, ``--toolsets
    tfg-mission-control`` and the server's temporary tools filter) instead of the zero-tool
    ``catalog`` turn. A case with expected fields also gets the plugin's result check."""
    if not (0 < timeout <= MAX_TIMEOUT_S):
        raise CaptureError(f"timeout must be in (0, {MAX_TIMEOUT_S}] seconds")
    for label in (run_id, case_id):
        if not _LABEL.fullmatch(label) or "synthetic" in label.lower():
            raise CaptureError("run_id/case_id must be short labels without 'synthetic'")
    if trial_case not in TRIAL_CASES:
        raise CaptureError(f"unknown trial case {trial_case!r}")
    if TRIAL_CASES[trial_case].get("local_demo"):
        raise CaptureError(f"{trial_case} runs in its own profile: use observability.local_planning_demo")
    case_prompt = TRIAL_CASES[trial_case]["prompt"]
    if trial and prompt != DEFAULT_PROMPT and prompt != case_prompt:
        raise CaptureError("the MCP tool trial uses its fixed neutral prompt")
    prompt = case_prompt if trial else prompt
    expectation = expectation_bytes(trial_case) if trial else None
    report = preflight(home=home, hermes_bin=hermes_bin, verified_sources=verified_sources,
                       process_lister=process_lister, trial=trial, mcp_process_lister=mcp_process_lister, repo=repo,
                       trial_case=trial_case)
    if not report["ok"]:
        raise CaptureError("preflight failed: " + ", ".join(c["check"] for c in report["checks"] if not c["ok"]))
    config_path, plugins_dir = home / "config.yaml", home / "plugins"
    plugin_dir = plugins_dir / PLUGIN_NAME
    private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    private = private_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    private.mkdir(mode=0o700)
    backup = config_path.read_bytes()
    original_sha = _sha(backup)
    if original_sha != report["facts"]["config_sha256"]:
        raise CaptureError("config changed during preflight")
    _write_new(private / "config.yaml.backup", backup)
    edited = tool_trial_config_text(backup, case_tools(trial_case)) if trial else enable_plugin_text(backup)
    edited_sha = _sha(edited)
    created_plugins_dir = None
    installed = {}
    selection = MCP_SERVER if trial else TOOLSET_SELECTION
    cache_path = home / "cache" / "mcp_schema_cache.json"
    run = {"utility_version": UTILITY_VERSION, "private_dir": str(private), "run_id": run_id, "case_id": case_id,
           "prompt_sha256": _sha(prompt.encode("utf-8")), "config_sha256_original": original_sha,
           "config_sha256_edited": edited_sha, "verified_hermes_commit": VERIFIED_HERMES_COMMIT,
           "toolset_selection": selection, "timeout_s": timeout, "hermes_invocations": 0,
           "automatic_retry": False, "model_configured": report["facts"].get("model"),
           "provider_configured": report["facts"].get("provider")}
    if trial:
        run["mcp_tool_trial"] = {**trial_plan(trial_case),
                                 "server_sources_sha256": report["facts"]["trial_server_sources_sha256"],
                                 "mcp_schema_cache_sha256_before": _file_sha(cache_path)}
    if expectation is not None:
        _write_new(private / "result-expectation.json", expectation)
    try:
        if not plugins_dir.exists():
            plugins_dir.mkdir(mode=0o755)
            created_plugins_dir = plugins_dir
        _install_plugin(plugin_dir, installed)
        run["plugin_installed_sha256"] = dict(installed)
        if _file_sha(config_path) != original_sha:
            raise CaptureError("config changed before the edit; nothing enabled")
        writer(config_path, edited, 0o600)
        env = dict(os.environ if base_env is None else base_env)
        # Hermes must read the home that was checked and edited, not an inherited HERMES_HOME (the planning image
        # sets HERMES_HOME=/hermes/planning; on 28/10/2026 that made Hermes ignore --hermes-home).
        env["HERMES_HOME"] = str(home)
        env.update({"HERMES_DISABLE_LAZY_INSTALLS": "1", "TFG_OBSERVABILITY_CAPTURE": "1",
                    "TFG_OBSERVABILITY_DIR": str(private / "capture"), "TFG_OBSERVABILITY_RUN_ID": run_id,
                    "TFG_OBSERVABILITY_CASE_ID": case_id})
        env.pop(capture.EXPECTATION_ENV, None)
        if expectation is not None:
            env[capture.EXPECTATION_ENV] = str(private / "result-expectation.json")
        argv = [str(hermes_bin), "-z", prompt, "--toolsets", selection,
                "--usage-file", str(private / "native-usage.json")]
        run["started_at_utc"] = _utc_now()
        started = time.monotonic()
        run["hermes_invocations"] = 1
        rc, timed_out = _run_hermes(argv, env=env, cwd=str(REPO_ROOT), stdout_path=private / "stdout.txt",
                                    stderr_path=private / "stderr.txt", timeout=timeout)
        run.update(finished_at_utc=_utc_now(), elapsed_wall_s=round(time.monotonic() - started, 3),
                   return_code=rc, timed_out=timed_out)
    except CaptureError as exc:
        run["aborted_before_hermes"] = str(exc)
    except Exception as exc:
        run["aborted_error_type"] = type(exc).__name__
    finally:
        run["restore"] = restore(config_path=config_path, backup=backup, original_sha=original_sha,
                                 edited_sha=edited_sha, plugin_dir=plugin_dir, installed=installed,
                                 created_plugins_dir=created_plugins_dir, writer=writer)
        if trial:
            # Hermes' own write-through cache gains an entry for the filtered fingerprint; it is
            # reported, not restored (lazy is off, so it is not read). Leftover servers are
            # reported, never signalled.
            run["mcp_tool_trial"]["mcp_schema_cache_sha256_after"] = _file_sha(cache_path)
            run["mcp_tool_trial"]["mcp_server_processes_after"] = len(mcp_process_lister())
        capture_dir = private / "capture"
        run["capture_files"] = sorted(p.name for p in capture_dir.iterdir()) if capture_dir.is_dir() else []
        _write_new(private / "run.json", _json_bytes(run))
    return run


# --- review ------------------------------------------------------------------------------

def _review_native(path: Path):
    raw = path.read_bytes()
    data = json.loads(raw)
    reviewed = {k: data[k] for k in NATIVE_ALLOWED if k in data}
    aux = data.get("auxiliary")
    if isinstance(aux, dict):
        reviewed["auxiliary"] = {k: aux[k] for k in NATIVE_COUNTERS if k in aux}
        tasks = aux.get("by_task") if isinstance(aux.get("by_task"), dict) else {}
        reviewed["auxiliary"]["by_task"] = {t: {k: v for k, v in (tasks[t] or {}).items() if k in NATIVE_COUNTERS}
                                            for t in tasks}
    total = data.get("total_including_auxiliary")
    if isinstance(total, dict):
        reviewed["total_including_auxiliary"] = {k: total[k] for k in ("estimated_cost_usd", "total_tokens", "api_calls")
                                                 if k in total}
    omitted = sorted(set(data) - set(reviewed))
    review = {"raw_native_report_sha256": _sha(raw), "raw_native_report_retained_in_evidence": False,
              "omitted_fields": omitted,
              "note": "Hermes --usage-file, allowlisted; normalized counters, not raw provider usage; "
                      "api_calls is not an HTTP request count; cost is an estimate, not a billed amount."}
    return reviewed, review


def correlate(events, native):
    """Main turn only: plugin llm_call events vs the native main-turn counters. The auxiliary
    title generation is reported separately and never matched against plugin events."""
    calls = [e for e in events if e["event_type"] == "llm_call"]
    errors = [e for e in events if e["event_type"] == "llm_error"]
    result = {"scope": "main_turn_only", "plugin_llm_calls": len(calls), "plugin_llm_errors": len(errors),
              "native_main_api_calls": native.get("api_calls"), "fields": {}}
    if len(calls) == 1 and not errors and native.get("api_calls") == 1:
        usage = calls[0].get("usage") or {}
        for name in COMPARED_COUNTERS:
            plugin = usage.get(name) or {"value": None, "status": "absent"}
            result["fields"][name] = {"plugin": plugin, "native": native.get(name),
                                      "values_equal": plugin["value"] is not None and plugin["value"] == native.get(name)}
        result["verdict"] = ("all_compared_values_equal" if all(f["values_equal"] for f in result["fields"].values())
                             else "differences_found")
    elif len(calls) > 1 and not errors:
        # Each llm_call carries ONE response's usage (incremental); the native report gives the
        # main-turn total. Only those counters are summed; api_call_count is a running index.
        result["scope"] = "main_turn_sum_of_llm_calls"
        for name in COMPARED_COUNTERS:
            parts = [(c.get("usage") or {}).get(name) or {"value": None, "status": "absent"} for c in calls]
            values = [p["value"] for p in parts]
            total = sum(values) if all(isinstance(v, int) for v in values) else None
            result["fields"][name] = {"plugin_sum": total, "plugin_statuses": [p["status"] for p in parts],
                                      "native": native.get(name),
                                      "values_equal": total is not None and total == native.get(name)}
        result["call_count"] = {"plugin_llm_calls": len(calls), "native_api_calls": native.get("api_calls"),
                                "values_equal": len(calls) == native.get("api_calls"),
                                "meaning": "model calls in Hermes' main turn on both sides; not HTTP requests"}
        result["not_comparable"] = {
            "api_call_count": "per-call running index in the plugin, never summed",
            "prompt_tokens": "derived per call; the allow-listed native report has no such field",
            "estimated_cost_usd": "native estimate only; the plugin computes no cost",
            "auxiliary": "title generation is in the native report only (auxiliary_native_only)"}
        compared = list(result["fields"].values()) + [result["call_count"]]
        result["verdict"] = ("not_computable_absent_values" if any(f.get("plugin_sum", 0) is None for f in compared)
                             else "all_compared_values_equal" if all(f["values_equal"] for f in compared)
                             else "differences_found")
    else:
        result["verdict"] = "not_compared_no_llm_call_or_llm_errors"
    aux = native.get("auxiliary") or {}
    result["auxiliary_native_only"] = {
        "by_task": aux.get("by_task"), "captured_by_plugin": False,
        "reason": "Hermes emits pre/post_auxiliary_call for auxiliary tasks, not post_api_request; "
                  "the plugin registers pre/post_api_request, api_request_error and post_tool_call only"}
    result["not_inferred"] = ["http_request_count", "internal_retries", "billed_cost"]
    return result


def load_tool_offers(paths, schema_file="tool-offer.schema.json"):
    """(records, errors) for hermes-tool-offers-*.jsonl (or another side file with ``schema_file``);
    every line must validate, nothing repaired."""
    from jsonschema import Draft202012Validator
    validator = Draft202012Validator(json.loads((PLUGIN_SOURCE / schema_file).read_text()))
    records, errors = [], []
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                errors.append(f"{path.name}:{number}: invalid JSON")
                continue
            if any(True for _ in validator.iter_errors(record)):
                errors.append(f"{path.name}:{number}: schema")
                continue
            records.append(record)
    return records, errors


def assess_result_checks(trial_case, result_checks):
    """Classify the plugin's in-process comparison of the REAL tool result (outcomes only)."""
    expected = TRIAL_CASES[trial_case]["expected"]
    if expected is None:
        return {"result_check": "NOT_APPLICABLE"}
    records = list(result_checks or [])
    arguments = TRIAL_CASES[trial_case].get("arguments") or ()
    sha = _sha(expectation_bytes(trial_case))
    if any(r["result_envelope"].startswith("expectation_") for r in records):
        status = "EXPECTATION_NOT_LOADED"
    elif not records:
        status = "NOT_RECORDED"
    elif any(r["expectation_sha256"] != sha or r["tool_name"] != TRIAL_REGISTRY_NAME for r in records):
        status = "EXPECTATION_OR_TOOL_MISMATCH"
    elif arguments and any(len(r.get("argument_checks") or []) != len(arguments) for r in records):
        status = "ARGUMENTS_NOT_RECORDED"
    elif any(c["outcome"] != "match" for r in records for c in r.get("argument_checks") or []):
        status = "EXECUTED_QUERY_DIFFERS"  # the call that ran was not the intended run_id/view
    elif any(r["counts"]["mismatch"] for r in records):
        status = "CONTRADICTS_EXPECTATION"
    elif any(r["counts"]["absent"] or len(r["checks"]) != len(expected) for r in records):
        status = "EXPECTED_FIELDS_ABSENT"
    else:
        status = "ALL_EXPECTED_FIELDS_MATCH"
    return {"result_check": status, "result_check_records": len(records), "expectation_sha256": sha,
            "result_envelopes": [r["result_envelope"] for r in records],
            "not_matching_pointers": sorted({c["pointer"] + ":" + c["outcome"] for r in records
                                             for c in r["checks"] if c["outcome"] != "match"}),
            "argument_checks": [c for r in records for c in r.get("argument_checks") or []]}


def assess_tool_trial(events, offers, final_text, trial_case=DEFAULT_TRIAL_CASE, result_checks=None):
    """Separate verdicts for offered / requested / executed / result / final response; never merged.

    ``final_text`` is the model's reply (private stdout); only its classification is kept. For a
    case with expected fields, the real tool result must match them: status=ok or a matching reply
    is never enough."""
    expected_answer = TRIAL_CASES[trial_case]["expected_answer"]
    result = assess_result_checks(trial_case, result_checks)
    result_ok = result["result_check"] in ("NOT_APPLICABLE", "ALL_EXPECTED_FIELDS_MATCH")
    # The labels keep their historical names; "trial tool" means the case's registered tool(s).
    expected = sorted(registry_name(t, case_server(trial_case)) for t in case_tools(trial_case))
    if not offers:
        offered = "NOT_OBSERVED"
    elif all(sorted(o["offered_tool_names"]) == expected and o["tool_count"] == len(expected) for o in offers):
        offered = "ONLY_TRIAL_TOOL_OFFERED"
    elif all(o["offered_tool_names"] == [] for o in offers):
        offered = "NO_TOOL_OFFERED"
    else:
        offered = "OTHER_OR_UNREADABLE_TOOLS_OFFERED"
    calls = [e for e in events if e["event_type"] == "llm_call"]
    requested_names = [n for e in calls for n in (e.get("requested_tool_names") or [])]
    if any(e.get("requested_tool_names") is None for e in calls) and not requested_names:
        requested = "UNKNOWN_NOT_CAPTURED"
    elif not requested_names:
        requested = "NOT_REQUESTED"
    elif all(n in expected for n in requested_names):
        requested = "TRIAL_TOOL_REQUESTED"
    else:
        requested = "OTHER_OR_UNREADABLE_TOOL_REQUESTED"
    tools = [e for e in events if e["event_type"] == "tool_call"]
    if not tools:
        executed = "NOT_EXECUTED"
    elif any(e.get("tool_name") not in expected for e in tools):
        executed = "OTHER_OR_UNREADABLE_TOOL_EXECUTED"
    elif all(e.get("status") == "ok" for e in tools):
        executed = "EXECUTED_NO_ERROR_DETECTED_BY_HERMES"
    else:
        executed = "EXECUTED_WITH_ERROR_OR_BLOCKED"
    text = (final_text or "").strip()
    structured = None
    llm_errors = sum(e["event_type"] == "llm_error" for e in events)
    kind = TRIAL_CASES[trial_case].get("kind")
    if kind in ("planning", "scenario_query"):
        # Only the isolation is judged here. The model's text is never accepted as the result: the
        # session is read afterwards (bind-h1 for finalized artifacts, accept-h3 for a scenario answer).
        # Never vacuous: offer records, at least one requested call, an observed execution for every
        # request and no model error are all required; offers=[] is NOT_OBSERVED, not compliance.
        within = (offered == "ONLY_TRIAL_TOOL_OFFERED" and requested == "TRIAL_TOOL_REQUESTED"
                  and executed == "EXECUTED_NO_ERROR_DETECTED_BY_HERMES" and len(requested_names) >= 1
                  and len(tools) == len(requested_names) and not llm_errors)
        prefix = "PLANNING" if kind == "planning" else "QUERY"
        verdict = (f"{prefix}_CALLS_WITHIN_ALLOWED_TOOLS" if within
                   else "ISOLATION_NOT_CONFIRMED" if offered != "ONLY_TRIAL_TOOL_OFFERED"
                   else "TOOL_NOT_REQUESTED" if requested == "NOT_REQUESTED"
                   else f"{prefix}_CALLS_NOT_AS_EXPECTED")
        judged = "ARTIFACTS_JUDGED_BY_BINDING" if kind == "planning" else "ANSWER_JUDGED_BY_ACCEPT_H3"
        return {"verdict": verdict, "trial_case": trial_case, "offered": offered, "requested": requested,
                "executed": executed, **result, "final_response": "NOT_EVALUATED_" + judged,
                "api_requests_with_offer_record": len(offers), "llm_calls": len(calls), "llm_errors": llm_errors,
                "requested_tool_names": requested_names,
                "tool_calls": [{k: e.get(k) for k in ("tool_name", "status", "error_type", "duration_ms_measured")}
                               for e in tools],
                "limits": ["offered = tool names in each request body (pre_api_request), not a provider-side check",
                           "status 'ok' means Hermes detected no error in a result, not that a mission is valid",
                           "acceptance = bind-h1 (missions) or accept-h3 (scenario answer) on this session's data"]}
    if TRIAL_CASES[trial_case].get("answer") is not None:
        structured = mission_query_cases.evaluate_answer(text, TRIAL_CASES[trial_case]["answer"],
                                                         TRIAL_CASES[trial_case].get("answer_contract", "v2"))
        response = "STRUCTURED_" + structured["verdict"]
    else:
        response = ("EMPTY" if not text else "EQUALS_EXPECTED_STATUS" if text == expected_answer
                    else "CONTAINS_EXPECTED_STATUS" if expected_answer in text else "DIFFERENT")
    observed =(offered == "ONLY_TRIAL_TOOL_OFFERED" and requested == "TRIAL_TOOL_REQUESTED"
                and executed == "EXECUTED_NO_ERROR_DETECTED_BY_HERMES" and len(tools) == 1
                and len(requested_names) == 1 and result_ok
                and response in ("EQUALS_EXPECTED_STATUS", "CONTAINS_EXPECTED_STATUS",
                                 "STRUCTURED_ALL_FIELDS_CORRECT"))
    if observed:
        verdict = "TOOL_CALL_OBSERVED_AS_EXPECTED"
    elif offered != "ONLY_TRIAL_TOOL_OFFERED":
        verdict = "ISOLATION_NOT_CONFIRMED"
    elif requested == "NOT_REQUESTED":
        verdict = "TOOL_NOT_REQUESTED"
    elif executed == "NOT_EXECUTED":
        verdict = "REQUESTED_BUT_NOT_EXECUTED"
    elif executed != "EXECUTED_NO_ERROR_DETECTED_BY_HERMES":
        verdict = "TOOL_EXECUTION_FAILED_OR_BLOCKED"
    elif len(tools) != 1 or len(requested_names) != 1:
        verdict = "MORE_THAN_ONE_TOOL_CALL"
    elif result["result_check"] in ("EXECUTED_QUERY_DIFFERS", "ARGUMENTS_NOT_RECORDED"):
        verdict = "EXECUTED_QUERY_NOT_VERIFIED_AS_INTENDED"
    elif result["result_check"] == "CONTRADICTS_EXPECTATION":
        verdict = "TOOL_RESULT_CONTRADICTS_EXPECTATION"
    elif not result_ok:
        verdict = "TOOL_RESULT_NOT_VERIFIED"
    else:
        verdict = "FINAL_RESPONSE_NOT_AS_EXPECTED"
    return {"verdict": verdict, "trial_case": trial_case, "offered": offered, "requested": requested,
            "executed": executed, **result, "final_response": response, "structured_answer": structured,
            "expected_final_answer": expected_answer, "api_requests_with_offer_record": len(offers),
            "llm_calls": len(calls), "llm_errors": llm_errors, "requested_tool_names": requested_names,
            "tool_calls": [{k: e.get(k) for k in ("tool_name", "status", "error_type", "duration_ms_measured")}
                           for e in tools],
            "limits": ["offered = tool names in each request body (pre_api_request), not a provider-side check",
                       "requested = tool_calls in the model's response (post_api_request)",
                       "executed = Hermes dispatched the call and emitted post_tool_call; status 'ok' means Hermes "
                       "detected no error in the result, the project result itself is not captured",
                       "result_check = the plugin compared allow-listed pointers of the real result inside "
                       "Hermes and kept only match/mismatch/absent; other fields of the result are unchecked",
                       "final response = model text; containing the expected value is consistent with, not proof "
                       "of, the tool result",
                       "one trial is not a reliability or performance measurement"]}


def review(*, private_dir: Path, evidence_dir: Path, prompt: str = DEFAULT_PROMPT, trial: bool = False,
           trial_case: str = DEFAULT_TRIAL_CASE):
    """Validate a private capture and write reviewed evidence to a NEW directory."""
    if trial_case not in TRIAL_CASES:
        raise CaptureError(f"unknown trial case {trial_case!r}")
    case = TRIAL_CASES[trial_case]
    prompt = case["prompt"] if trial else prompt
    run_path = private_dir / "run.json"
    run = json.loads(run_path.read_bytes()) if run_path.is_file() else {}
    if run and run.get("prompt_sha256") != _sha(prompt.encode("utf-8")):
        raise CaptureError("prompt does not match the run's prompt_sha256")
    captures = sorted((private_dir / "capture").glob("hermes-events-*.jsonl"))
    records = sorted((private_dir / "capture").glob("capture-provenance-*.json"))
    if not captures or not records:
        raise CaptureError("no capture JSONL or provenance record: nothing to review")
    if evidence_dir.exists():
        raise CaptureError("evidence directory already exists; it is never reused")
    events, errors = common.load_events(captures)
    if errors:
        raise CaptureError(f"capture does not validate: {len(errors)} error(s)")
    check = common.verify_capture_provenance(captures)
    if not check["ok"]:
        raise CaptureError("capture provenance records do not verify")
    offer_files = sorted((private_dir / "capture").glob("hermes-tool-offers-*.jsonl"))
    offers, offer_errors = load_tool_offers(offer_files)
    if offer_errors:
        raise CaptureError(f"tool offer records do not validate: {len(offer_errors)} error(s)")
    check_files = sorted((private_dir / "capture").glob("hermes-tool-result-checks-*.jsonl"))
    result_checks, check_errors = load_tool_offers(check_files, "tool-result-check.schema.json")
    if check_errors:
        raise CaptureError(f"tool result check records do not validate: {len(check_errors)} error(s)")
    if trial and run and run.get("toolset_selection") != MCP_SERVER:
        raise CaptureError("run.json is not an MCP tool trial run")
    if trial and run and (run.get("mcp_tool_trial") or {}).get("trial_case", DEFAULT_TRIAL_CASE) != trial_case:
        raise CaptureError("run.json belongs to another trial case")
    texts = [p.read_text(encoding="utf-8") for p in captures + offer_files + check_files]
    stdout = (private_dir / "stdout.txt").read_text(encoding="utf-8").strip() if (private_dir / "stdout.txt").is_file() else ""
    # The response is searched as a JSON string value: a short reply such as OK can occur inside words.
    needles = [("prompt", prompt), ("response", json.dumps(stdout, ensure_ascii=False) if stdout else ""),
               ("url", "://"), ("home_path", "/home/"), ("tool_argument", (case.get("run_id") or "") if trial else "")]
    # Distinctive expected values must never surface in capture files (only pointers may).
    needles += [("tool_result_value", v) for _, v in (case["expected"] or ()) if trial and isinstance(v, str) and len(v) >= 16]
    leaks = [label for label, needle in needles if needle and any(needle in t for t in texts)]
    if leaks:
        raise CaptureError(f"capture contains content it must not: {leaks}")
    native_path = private_dir / "native-usage.json"
    native, native_review = _review_native(native_path) if native_path.is_file() else (None, None)
    kinds = capture_summary.classify(events, "captured", check)
    summary = {"utility_version": UTILITY_VERSION, "summary": capture_summary.summarize(events, kinds),
               "provenance_check": check,
               "correlation_with_native": correlate(events, native) if native else None,
               "limits": ["covers Hermes' main turn only; auxiliary title generation is not captured",
                          "token counters are Hermes-normalized; zeros may be unconfirmed",
                          "first_chunk_offset_s is not a verified TTFT",
                          "billed cost unknown; no cost is computed",
                          "one capture is not a representative sample"]}
    summary["tool_offers"] = {"records": len(offers),
                              "offered_tool_names": [o["offered_tool_names"] for o in offers],
                              "tool_count": [o["tool_count"] for o in offers]}
    if trial:
        summary["mcp_tool_trial"] = assess_tool_trial(events, offers, stdout, trial_case, result_checks)
    expectation = (private_dir / "result-expectation.json") if trial else None
    if expectation is not None and expectation.is_file() and expectation.read_bytes() != expectation_bytes(trial_case):
        raise CaptureError("result-expectation.json differs from the trial case's expectation")
    evidence_dir.mkdir(parents=False)
    (evidence_dir / "capture").mkdir()
    for path in captures + records + offer_files + check_files:
        _write_new(evidence_dir / "capture" / path.name, path.read_bytes(), 0o644)
    if expectation is not None and expectation.is_file():
        # Public by construction: the allow-listed pointers and the values recorded in the run's files.
        _write_new(evidence_dir / "result-expectation.json", expectation.read_bytes(), 0o644)
    if native is not None:
        _write_new(evidence_dir / "native_usage_reviewed.json", _json_bytes(native), 0o644)
        _write_new(evidence_dir / "native_usage_review.json", _json_bytes(native_review), 0o644)
    if run:
        public_run = {k: v for k, v in run.items() if k not in ("private_dir",)}
        public_run["stdout_sha256"] = _file_sha(private_dir / "stdout.txt")
        public_run["stderr_bytes"] = (private_dir / "stderr.txt").stat().st_size if (private_dir / "stderr.txt").is_file() else None
        _write_new(evidence_dir / "run.json", _json_bytes(public_run), 0o644)
    _write_new(evidence_dir / "capture_summary.json", _json_bytes(summary), 0o644)
    write_manifest(evidence_dir)
    return {"evidence_dir": str(evidence_dir), "events": len(events), "provenance_ok": check["ok"],
            "correlation_verdict": (summary["correlation_with_native"] or {}).get("verdict"),
            "tool_offer_records": len(offers),
            "mcp_tool_trial_verdict": summary["mcp_tool_trial"]["verdict"] if trial else None,
            "manifest": "SHA256SUMS"}


def write_manifest(evidence_dir: Path):
    files = sorted(p for p in evidence_dir.rglob("*") if p.is_file() and p.name not in ("SHA256SUMS", "README.md"))
    lines = "".join(f"{_file_sha(p)}  {p.relative_to(evidence_dir).as_posix()}\n" for p in files)
    _atomic_write(evidence_dir / "SHA256SUMS", lines.encode(), 0o644)


def verify_manifest(evidence_dir: Path):
    manifest = evidence_dir / "SHA256SUMS"
    if not manifest.is_file():
        raise CaptureError("evidence has no SHA256SUMS")
    for line in manifest.read_text().splitlines():
        digest, name = line.split("  ", 1)
        if _file_sha(evidence_dir / name) != digest:
            raise CaptureError(f"evidence hash mismatch: {name}")


# --- opik dry-run ------------------------------------------------------------------------

def opik_dry_run(*, evidence_dir: Path, project: str, workspace: str):
    """Payload for an explicit destination; never sends, never reads a key."""
    verify_manifest(evidence_dir)
    captures = sorted((evidence_dir / "capture").glob("hermes-events-*.jsonl"))
    events, errors = common.load_events(captures)
    if errors:
        raise CaptureError("capture does not validate")
    check = common.verify_capture_provenance(captures)
    plan = opik_export.build_plan(events, project, workspace=workspace, provenance="captured", provenance_check=check)
    described = opik_export.describe(plan)
    target = evidence_dir / "opik_dry_run.json"
    if target.exists():
        raise CaptureError("opik_dry_run.json already exists; create a new evidence directory for another destination")
    # Insertion key order, NOT _json_bytes (sort_keys): loading this file and re-serialising each
    # body with opik_export.body_bytes must give the exact bytes --send would POST.
    saved = (json.dumps(described, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _write_new(target, saved, 0o644)
    write_manifest(evidence_dir)
    bodies = {key: [_sha(opik_export.body_bytes(b)) for b in batches]
              for key, batches in described["payload"].items()}
    capture_arg = " ".join(str(p) for p in captures)
    return {"mode": "dry-run", "sent": False, "destination": described["destination"],
            "traces": described["traces"], "spans": described["spans"],
            "trace_ids": [t["id"] for t in plan.traces], "span_ids": [s["id"] for s in plan.spans],
            "body_sha256": bodies, "blocked_for_future_send_by_default": described["blocked_for_future_send_by_default"],
            "prepared_send_command_NOT_EXECUTED": (
                f".venv/bin/python -m observability.opik_export {capture_arg} --project {project} "
                f"--workspace {workspace} --provenance captured --send --record <NEW_RECORD_PATH> "
                f"--timeout 30 --error-body-file <NEW_PRIVATE_DIR>/error-body.bin")}


# --- CLI ---------------------------------------------------------------------------------

def main(argv=None, *, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture", help="offline preflight; --execute runs ONE real Hermes turn")
    cap.add_argument("--execute", action="store_true", help="really run Hermes once (provider call)")
    cap.add_argument("--hermes-home", type=Path, default=DEFAULT_HOME)
    cap.add_argument("--hermes-bin", type=Path, default=DEFAULT_BIN)
    cap.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    cap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    cap.add_argument("--run-id", default="real-hermes-" + datetime.now(timezone.utc).strftime("%Y%m%d"))
    cap.add_argument("--case-id", default=None, help="default oneshot-ok, or the trial case's label with --mcp-tool-trial")
    cap.add_argument("--mcp-tool-trial", action="store_true",
                     help=f"offer ONLY the trial case's {MCP_SERVER} tool(s) (default {TRIAL_TOOL}) "
                          "and use the case's fixed prompt")
    cap.add_argument("--trial-case", choices=sorted(TRIAL_CASES), default=DEFAULT_TRIAL_CASE)
    rev = sub.add_parser("review", help="validate a private capture and write NEW reviewed evidence")
    rev.add_argument("--private-dir", type=Path, required=True)
    rev.add_argument("--evidence-dir", type=Path, required=True)
    rev.add_argument("--mcp-tool-trial", action="store_true", help="also assess the MCP tool trial")
    rev.add_argument("--trial-case", choices=sorted(TRIAL_CASES), default=DEFAULT_TRIAL_CASE)
    dry = sub.add_parser("opik-dry-run", help="Opik payload for an explicit destination; never sends")
    dry.add_argument("--evidence-dir", type=Path, required=True)
    dry.add_argument("--project", required=True)
    dry.add_argument("--workspace", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "capture" and not args.execute:
            result = preflight(home=args.hermes_home, hermes_bin=args.hermes_bin, trial=args.mcp_tool_trial,
                               trial_case=args.trial_case)
            result["note"] = "Offline preflight only: nothing was created and Hermes was not run."
            code = 0 if result["ok"] else 1
        elif args.command == "capture":
            case_id = args.case_id or (TRIAL_CASES[args.trial_case]["case_id"] if args.mcp_tool_trial else "oneshot-ok")
            result = execute_capture(home=args.hermes_home, hermes_bin=args.hermes_bin, private_root=args.private_root,
                                     timeout=args.timeout, run_id=args.run_id, case_id=case_id,
                                     trial=args.mcp_tool_trial, trial_case=args.trial_case)
            result["note"] = "One Hermes invocation at most; no retry. Raw material stays in private_dir."
            code = 0 if result.get("return_code") == 0 and result["restore"]["ok"] else 2
        elif args.command == "review":
            result = review(private_dir=args.private_dir, evidence_dir=args.evidence_dir, trial=args.mcp_tool_trial,
                            trial_case=args.trial_case)
            code = 0
        else:
            result = opik_dry_run(evidence_dir=args.evidence_dir, project=args.project, workspace=args.workspace)
            code = 0
    except (CaptureError, ExportError) as exc:
        print(f"hermes_capture_run: {exc}", file=sys.stderr)
        return 2
    json.dump(result, out, indent=2, ensure_ascii=False)
    out.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
