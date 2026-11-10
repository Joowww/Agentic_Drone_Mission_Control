"""Planning-only MCP server for the local Hermes demo (tfg-demo-planning).

It registers exactly two tools, ``update_mission_draft`` and ``finalize_mission_draft``, with the same
names, descriptions and argument schemas as ``tools.hermes_mcp_server``, and calls the same backend
functions of ``tools.hermes_mission_planning``. There is no second planner: drafts are merged, routes
generated, missions built, validated (LangGraph ``waypoint_mission_graph``) and exported exactly as in
the full server.

Isolation is enforced by the server itself, not only by Hermes' include filter: this module does not
import the simulation, preflight, sequence, reservation, reconciliation or execution modules, so those
operations cannot be registered or reached through it (tests/test_hermes_demo_planning_server.py
checks the imported modules in a fresh interpreter).

Drafts and finalizations go to a private directory given by ``TFG_DEMO_DRAFT_ROOT`` (an absolute path
outside the repository). Without it the server refuses to start, so a demo never writes into
``missions/generated`` of a checkout.

Run (Hermes starts it through stdio; by hand it waits for JSON-RPC on stdin):

    TFG_DEMO_DRAFT_ROOT=/abs/private/dir .venv/bin/python -m tools.hermes_demo_planning_server
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp.server import MCPServer

from models.mission_plan_draft import MissionPlanDraft
from planning.draft_provenance import InputAttribution
import tools.hermes_mission_planning as planning

SERVER_NAME = "tfg-demo-planning"
DRAFT_ROOT_ENV = "TFG_DEMO_DRAFT_ROOT"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_TOOLS = ("update_mission_draft", "finalize_mission_draft")

# Descriptions start with the full server's text, verbatim (tests compare it), so the model sees the same
# contract; the demo appends guidance for small local models. Added after pilot r01 (08/11/2026), where Qwen3 4B
# put the current wind (0 km/h) into maximum_wind_speed_kmh and invented draft_id "draft-001". Argument schemas
# and backend are unchanged.
FULL_UPDATE_DESCRIPTION = "Save only operator-supplied mission facts and partial geometry_intent together; no inferred purpose/agriculture, safety limits, height or return decision. Geometry patches merge non-null facts, preserving dimensions; an explicit mode change clears old shape-specific fields. Retain draft_id/draft_revision; geometry edits require current expected_revision, existing routes require replace_route=true. A partial intent saves without waypoints; invalid facts do not overwrite state. Empty updates retrieve. Returns mission/geometry pending fields, effective compatibility defaults and UNVERIFIED field attribution (optional JSON-pointer attributions for resolved supplied fields; OPERATOR_DECLARED_VIA_AGENT requires a nonblank supporting statement). Ordinary legacy waypoint updates merge; explicit manual replacement detaches geometry intent. No extra approval for requested saving, and no flight commands."
FULL_FINALIZE_DESCRIPTION = "On requested finalization, snapshot the complete draft, validate it and attempt the strict QGC .plan export in ONE operation without another saving/validation approval. The export writes a file only when its data are present (including a real AMSL for the planned home, which drafts do not carry); otherwise validation.qgc_export.status is REFUSED with its reasons and qgc_plan_path is null: report that refusal as such, not as a failure to retry. A result already covers construct/validate/export-attempt even when the user lists all three; do not issue extra validation/export for that unchanged version. Pending geometry also blocks finalization. Supply expected_revision; retain finalization_id/mission_path/hashes. Explain this result and show compatibility defaults and unverified provenance before seeking rehearsal consent. Unsafe plans remain BLOCKED candidates. Never starts simulation or grants flight consent."

UPDATE_GUIDANCE = (
    " Demo guidance: for a NEW mission omit draft_id and expected_revision; the tool creates the draft and "
    "returns draft_id and draft_revision. Afterwards pass exactly the returned draft_id and draft_revision, "
    "never an invented identifier. wind_speed_kmh and wind_direction_from_deg hold the current reference wind "
    "the operator states, even when it is 0. minimum_battery_reserve_percent, maximum_wind_speed_kmh and "
    "maximum_altitude_m are safety LIMITS: set them only when the operator states those limits, otherwise omit "
    "them and ask for them. A current wind of 0 km/h is never a maximum wind."
)
FINALIZE_GUIDANCE = (
    " Demo guidance: pass the draft_id and draft_revision returned by the last successful update_mission_draft; "
    "call it only when that result has no missing fields."
)
UPDATE_DESCRIPTION = FULL_UPDATE_DESCRIPTION + UPDATE_GUIDANCE
FINALIZE_DESCRIPTION = FULL_FINALIZE_DESCRIPTION + FINALIZE_GUIDANCE

INSTRUCTIONS = (
    "Planning-only server for a local demonstration: it can save a mission draft and finalize it "
    "(build, deterministic validation and an attempted QGroundControl export). It has no simulation, "
    "preflight, reservation or vehicle operations, and nothing here grants flight consent. "
    "Save ONLY facts and decisions actually supplied by the operator; leave absent values null. "
    "Never invent safety limits (battery reserve, maximum wind, maximum altitude), flight heights or a "
    "return decision, and never copy facts from another mission. Use registered schemas for enums. "
    "Use update_mission_draft for a new mission, keep its draft_id and draft_revision across turns, read "
    "the pending fields it returns and ask the operator for them. Merge later facts into the SAME draft "
    "with expected_revision. When the draft is complete and the operator asks to finalize, call "
    "finalize_mission_draft with draft_id and expected_revision once: it already validates and exports, "
    "so do not repeat it. Report its validation result as returned (mission_status, execution_status, "
    "failure reasons) and a qgc_export status REFUSED as a reported refusal, not as an error to retry. "
    "Mission safety decisions are deterministic and must never be invented or overridden by the "
    "language model."
)

mcp = MCPServer(
    name=SERVER_NAME,
    title="TFG Demo Planning",
    description="Planning-only subset of the TFG mission tools for the local Hermes demo.",
    instructions=INSTRUCTIONS,
    version="0.2.0",
)


@mcp.tool(description=UPDATE_DESCRIPTION, structured_output=True)
def update_mission_draft(
    updates: MissionPlanDraft, draft_id: str | None = None,
    expected_revision: int | None = None,
    replace_route: bool = False,
    attributions: dict[str, InputAttribution] | None = None,
) -> dict[str, object]:
    return planning.update_mission_draft(updates, draft_id, expected_revision, replace_route, attributions)


@mcp.tool(description=FINALIZE_DESCRIPTION, structured_output=True)
def finalize_mission_draft(draft_id: str, expected_revision: int | None = None) -> dict[str, object]:
    return planning.finalize_mission_draft(draft_id, expected_revision)


def configure_draft_root(environ=os.environ) -> Path:
    """Point the planning backend at the private draft directory; refuse anything unsafe."""
    raw = environ.get(DRAFT_ROOT_ENV, "")
    if not raw:
        raise SystemExit(f"{DRAFT_ROOT_ENV} is required (absolute private directory outside the repository)")
    root = Path(raw)
    if not root.is_absolute():
        raise SystemExit(f"{DRAFT_ROOT_ENV} must be an absolute path")
    resolved = root.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise SystemExit(f"{DRAFT_ROOT_ENV} must be outside the repository ({REPO_ROOT})")
    resolved.mkdir(mode=0o700, parents=True, exist_ok=True)
    if resolved.stat().st_mode & 0o077:
        raise SystemExit(f"{DRAFT_ROOT_ENV} must not be accessible by group or others (chmod 700)")
    planning.DRAFT_ROOT = resolved
    return resolved


def main() -> None:
    configure_draft_root()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    sys.exit(main())
