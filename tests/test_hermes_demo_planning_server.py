"""Planning-only MCP server of the local Hermes demo: names, contracts, imports and isolation."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import tools.hermes_demo_planning_server as demo
import tools.hermes_mission_planning as planning

ROOT = Path(__file__).resolve().parents[1]
OPERATIONAL_MODULES = (
    "tools.simulation_control", "tools.simulation_lifecycle", "tools.simulation_mission_executor",
    "tools.simulation_status", "tools.virtual_preflight", "tools.virtual_preflight_jobs",
    "tools.preflight_sequences", "tools.execution_reconciliation", "tools.legacy_administrative_retirement",
    "tools.mission_execution_gate", "tools.mission_state", "planning.mission_revisions",
    "reporting.agri_scenario_summary", "tools.hermes_mcp_server",
)
OPERATIONAL_TOOLS = {
    "start_simulation", "restart_simulation", "stop_simulation", "check_simulation_ready",
    "start_virtual_preflight", "get_virtual_preflight", "run_virtual_preflight", "start_preflight_sequence",
    "get_preflight_sequence", "execute_approved_mission", "check_mission_execution_ready",
    "inspect_execution_reconciliation", "get_execution_reconciliation", "apply_execution_reconciliation",
    "prepare_legacy_sequence_retirement", "get_legacy_sequence_retirement", "apply_legacy_sequence_retirement",
    "propose_mission_revision", "get_revision_proposal", "build_mission_revision", "get_mission_state",
    "get_scenario_view", "generate_draft_route", "validate_mission", "validate_and_export_qgc",
}


def _tools():
    return {t.name: t for t in asyncio.run(demo.mcp.list_tools())}


def test_registers_exactly_the_two_planning_tools():
    assert set(_tools()) == {"update_mission_draft", "finalize_mission_draft"} == set(demo.DEMO_TOOLS)
    assert not OPERATIONAL_TOOLS & set(_tools())


def test_no_resources_or_prompts_are_announced():
    assert asyncio.run(demo.mcp.list_resources()) == []
    assert asyncio.run(demo.mcp.list_prompts()) == []


def test_contract_is_identical_to_the_full_server():
    full = pytest.importorskip("tools.hermes_mcp_server")
    full_tools = {t.name: t for t in asyncio.run(full.mcp.list_tools())}
    for name, tool in _tools().items():
        assert tool.input_schema == full_tools[name].input_schema
        assert tool.output_schema == full_tools[name].output_schema
        # Same contract text first; the demo only appends its guidance for small local models.
        assert tool.description.startswith(full_tools[name].description)
        guidance = tool.description[len(full_tools[name].description):]
        assert guidance == {"update_mission_draft": demo.UPDATE_GUIDANCE,
                            "finalize_mission_draft": demo.FINALIZE_GUIDANCE}[name]
        assert guidance.startswith(" Demo guidance:")


def test_wrappers_forward_to_the_same_backend(monkeypatch):
    seen = {}
    monkeypatch.setattr(planning, "update_mission_draft", lambda *a: seen.setdefault("update", a) and {"ok": 1})
    monkeypatch.setattr(planning, "finalize_mission_draft", lambda *a: seen.setdefault("finalize", a) and {"ok": 2})
    draft = demo.MissionPlanDraft(name="x")
    demo.update_mission_draft(draft, "d", 3, True, None)
    demo.finalize_mission_draft("d", 4)
    assert seen == {"update": (draft, "d", 3, True, None), "finalize": ("d", 4)}


def test_import_loads_no_operational_module_in_a_fresh_interpreter():
    code = ("import json, sys, tools.hermes_demo_planning_server; "
            "print(json.dumps(sorted(sys.modules)))")
    out = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, capture_output=True, text=True,
                         check=True, env={**os.environ, "PYTHONPATH": str(ROOT)})
    loaded = set(json.loads(out.stdout))
    assert not loaded & set(OPERATIONAL_MODULES)
    assert not any(m.startswith("tools.rover_") or m.startswith("multiagent") for m in loaded)


def test_source_imports_only_the_planning_backend():
    import ast
    tree = ast.parse(Path(demo.__file__).read_text(encoding="utf-8"))
    modules = [n.module if isinstance(n, ast.ImportFrom) else a.name
               for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
               for a in (n.names if isinstance(n, ast.Import) else [None])]
    assert modules == ["__future__", "os", "sys", "pathlib", "mcp.server", "models.mission_plan_draft",
                       "planning.draft_provenance", "tools.hermes_mission_planning"]


def test_draft_root_is_required_absolute_private_and_outside_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(planning, "DRAFT_ROOT", planning.DRAFT_ROOT)
    with pytest.raises(SystemExit, match="required"):
        demo.configure_draft_root({})
    with pytest.raises(SystemExit, match="absolute"):
        demo.configure_draft_root({demo.DRAFT_ROOT_ENV: "relative/dir"})
    with pytest.raises(SystemExit, match="outside the repository"):
        demo.configure_draft_root({demo.DRAFT_ROOT_ENV: str(ROOT / "missions/generated/demo")})
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    with pytest.raises(SystemExit, match="chmod 700"):
        demo.configure_draft_root({demo.DRAFT_ROOT_ENV: str(shared)})
    private = tmp_path / "private" / "drafts"
    assert demo.configure_draft_root({demo.DRAFT_ROOT_ENV: str(private)}) == private.resolve()
    assert planning.DRAFT_ROOT == private.resolve()
    assert private.stat().st_mode & 0o777 == 0o700


def test_planning_round_trip_writes_only_inside_the_private_root(tmp_path, monkeypatch):
    """Real backend, no model: an incomplete draft asks for fields; nothing is written in the repo."""
    monkeypatch.setattr(planning, "DRAFT_ROOT", planning.DRAFT_ROOT)
    root = demo.configure_draft_root({demo.DRAFT_ROOT_ENV: str(tmp_path / "drafts")})
    before = sorted(p for p in (ROOT / "missions").rglob("*")) if (ROOT / "missions").exists() else []
    result = demo.update_mission_draft(demo.MissionPlanDraft(name="demo", mission_id="demo_mission"))
    assert result["status"] == "INCOMPLETE" and result["missing_fields"]
    assert (root / result["draft_id"] / "draft.json").is_file()
    finalized = demo.finalize_mission_draft(result["draft_id"], result["draft_revision"])
    assert finalized["status"] == "INCOMPLETE" and "finalization_id" not in finalized
    after = sorted(p for p in (ROOT / "missions").rglob("*")) if (ROOT / "missions").exists() else []
    assert after == before


def test_server_script_refuses_to_start_without_private_root():
    env = {k: v for k, v in os.environ.items() if k != demo.DRAFT_ROOT_ENV}
    out = subprocess.run([sys.executable, "-B", "-m", "tools.hermes_demo_planning_server"], cwd=ROOT,
                         capture_output=True, text=True, env={**env, "PYTHONPATH": str(ROOT)},
                         stdin=subprocess.DEVNULL, timeout=60)
    assert out.returncode != 0 and demo.DRAFT_ROOT_ENV in out.stderr
