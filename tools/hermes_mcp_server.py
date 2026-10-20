from __future__ import annotations

from typing import Annotated
from pydantic import Field

from mcp.server import MCPServer

from models.mission_plan_draft import MissionPlanDraft
from planning.relative_routes import RelativeRouteRequest
from planning.draft_provenance import InputAttribution
from tools.mission_state import get_mission_state as mission_state_backend
from tools.mission_response_views import ResponseView, summarize_preflight, summarize_proposal
from tools.virtual_preflight import run_virtual_preflight as preflight_backend
from tools.virtual_preflight_jobs import (
    start_virtual_preflight as start_preflight_backend,
    get_virtual_preflight as get_preflight_backend,
)
from tools.preflight_sequences import (
    start_preflight_sequence as start_sequence_backend,
    get_preflight_sequence as get_sequence_backend,
)
from tools.hermes_mission_planning import (
    update_mission_draft as update_draft_backend,
    finalize_mission_draft as finalize_draft_backend,
    generate_draft_route as generate_route_backend,
)

from tools.hermes_mission_validation import (
    validate_mission_file,
)
from tools.mission_execution_gate import (
    check_mission_execution_ready as check_execution_ready,
)
from tools.execution_reconciliation import GroundConfirmation, LegacyEnvironmentConfirmation
from tools.simulation_control import (
    restart_simulation as restart_simulation_backend,
    start_simulation as start_simulation_backend,
    stop_simulation as stop_simulation_backend,
)
from tools.simulation_mission_executor import (
    execute_approved_mission as execute_mission_backend,
)
from tools.simulation_status import (
    check_simulation_ready as check_simulation_backend,
)

from planning.mission_revisions import (
    RevisionChanges, propose_mission_revision as propose_revision_backend,
    get_revision_proposal as get_proposal_backend, build_mission_revision as build_revision_backend,
)


mcp = MCPServer(
    name="tfg-mission-control",
    title="TFG Mission Control",
    description=(
        "Deterministic mission validation and simulation-control "
        "tools for the Agentic Drone Mission Control TFG."
    ),
    instructions=(
        "Save ONLY facts/decisions actually supplied by the operator; leave all absent values null. "
        "A mission name or rectangular shape does not imply survey, agriculture, inspection, "
        "return-to-home, a safety limit or a flight height. Ask for purpose and missing decisions. "
        "Never copy facts from another mission unless the operator explicitly requests that copy. "
        "Use registered schemas for enums; do not inspect source code to guess valid labels. "
        "Never invent safety limits or present suggested heights as standards without a basis. "
        "Existing compatibility defaults are not operator decisions; expose them and provenance "
        "caveats before seeking explicit consent for a reviewed rehearsal. No new safety defaults. "
        "MCP data originates from YOU: an operator attribution is your unverified declaration, "
        "not authenticated evidence of dialogue fidelity. Use attributions only when supported "
        "by the operator's actual statements, otherwise retain UNKNOWN. "
        "Use update_mission_draft, retain draft_id across turns, ask for missing fields, "
        "and persist incomplete geometry_intent (mode/dimensions/known parameters) in that SAME "
        "draft instead of burying dimensions in objective text. Merge partial facts across turns; "
        "HOME alone cannot complete geometry. Read the joint mission/geometry pending lists. "
        "When finalization is requested, use finalize_mission_draft to build, validate and export. "
        "Choose tools according to requests and results without a fixed tool count. "
        "Retain draft_revision and supply expected_revision for edits/finalization; "
        "generate_draft_route persists partial parameters and generates only when complete; "
        "geometry changes to an existing route require explicit replacement and current version. "
        "Ask for missing geometry decisions; never assume orientation, traversal, home location, "
        "closure, altitude reference or return. Never equate travel direction with an edge orientation. Attribute only "
        "resolved supplied fields; OPERATOR_DECLARED_VIA_AGENT requires a supporting statement. "
        "Finalization/revision ALREADY validates and "
        "exports: explain its result without repeating validation/export. Saving and validating "
        "an already requested mission needs no additional authorization. "
        "A completed result satisfies the requested operations even when the user lists several verbs. "
        "Use get_mission_state with retained IDs after reload or to explain links and next steps; "
        "it requires an identifier and is NOT a list operation. INVALID_ARGUMENTS/ERROR does "
        "not establish that no drafts exist: inventory remains unknown. For a NEW mission, "
        "create its draft directly; for continuation recover a retained identifier or ask for it. "
        "When the project response already supplies draft, geometry, provenance and pending "
        "facts, use it without redundant resource discovery or direct file reads. "
        "Read-only state/proposal/preflight queries default to view=summary; use view=detail "
        "with the SAME retained identifiers when full fields/events/provenance are needed. "
        "Follow detail_access instead of inventing identifiers or paths. Neither view grants "
        "consent, starts a worker, or changes vehicle ownership. Invalid arguments are not "
        "an empty inventory. Never repeat writes to recover a lost response: query retained "
        "IDs or the preflight request_key; if unavailable, reconcile with the operator. "
        "SITL rehearsal consent does not require hardware authorization; recommendations are "
        "not new technical gates. PASSED does not explain the previous WP3 failure, and "
        "qgc_plan_path=null does not establish absence of earlier exports. "
        "Do not explore files to guess a latest mission. Saved readiness is historical. "
        "Workflow/executor elapsed times are not airborne duration without timed flight events. "
        "Propose revisions from final verified run_id, retain proposal_id/hash/request keys, "
        "and build only explicitly accepted changes in a NEW artifact. Physical changes require "
        "operator declarations; recommendations are not telemetry or interventions. "
        "Obtain explicit "
        "user authorization before starting simulation or executing the reviewed "
        "mission_path. APPROVED is not user consent or formal virtual preflight. "
        "After a requested GUI start, distinguish backend readiness from operator-confirmed "
        "visualization: ask whether Gazebo shows the world and drones correctly, is black, "
        "or did not open. READY, a GUI process or GUI: ON is not proof of a rendered image. "
        "For a black/missing window, offer one controlled restart, leaving recovery pending, "
        "or explicitly continuing without visualization. Get acceptance before restarting. "
        "Before any recovery stop/start, verify no active execution and no vehicle/global "
        "reservation through known project run IDs/keys; INTERRUPTED/UNCONFIRMED, a remaining "
        "reservation, ERROR/NOT_FOUND or missing evidence forbids GUI recovery. Do not invent "
        "IDs or treat a historical query as a global execution inventory. With verified idle "
        "state and consent, use restart_simulation ONCE for the atomic stop/start transaction "
        "and await its confirmed completion; "
        "check backend readiness and ask about the "
        "image again. No parallel lifecycle calls, automatic loops or retries on timeout/lost "
        "response. Start also cleans previous processes, so another start is a restart, not "
        "a visual probe. The updated lifecycle entry points atomically fence flight admissions; "
        "inspection queries alone do not. UNCONFIRMED requires inspect_execution_reconciliation, "
        "reviewed inspection ID/hash and separate explicit reconciliation authorization. In an ACTIVE "
        "environment require new telemetry and independent visual ON-GROUND confirmations for BOTH "
        "vehicles; do not infer ground from armed/flying. A verifiably STOPPED exact environment "
        "has a separate administrative-closure path with prior container identity, dead owners and "
        "matching reservation versions, without telemetry/ground claims. Posthoc identity references do not "
        "bind the original execution: review continuity and wall clocks with the operator and supply "
        "legacy_environment_confirmation explicitly, never infer it from host boot_id or matching IDs. "
        "Missing name or Docker "
        "exec failure alone is insufficient; never start/restart to prove an earlier flight ended. "
        "Black GUI blocks the active ground path, not verified environment-termination inspection. "
        "Continuing "
        "without visualization requires the operator's explicit choice and grants no flight "
        "consent or gate bypass. No automatic visual detection or unsupported cause claim. "
        "For an explicitly requested rehearsal prefer start_virtual_preflight with a "
        "request_key chosen and recorded BEFORE starting. Preserve run_id and request_key. "
        "Poll get_virtual_preflight on the SAME run about every 15-30 seconds; never "
        "restart a run on timeout, lost response or reconnection. Recover a lost ID by "
        "querying request_key. ACCEPTED/STARTING is admission, not validation or PASSED. "
        "INTERRUPTED/UNCONFIRMED requires operator reconciliation; do not infer landing, "
        "release a restriction or repeat flight. Synchronous tools can exceed MCP timeouts. "
        "Use run_virtual_preflight only when the user requests a synchronous rehearsal: "
        "it arms, takes off and moves the mission-selected simulated vehicle, never starts simulation. "
        "PASSED is not consent for another execution or permission for real hardware. "
        "Only navigate execution is supported; speed tracking is not verified. "
        "Use these tools to validate drone missions and interact "
        "with the ROS2, Gazebo and ArduPilot simulation stack. "
        "Only drone_01->v1 and drone_02->v2 are supported; never substitute another vehicle. At most one project flight may execute; no simultaneous flight or separation guarantee. Mission safety decisions are deterministic and must never "
        "be invented or overridden by the language model. "
        "A mission must pass the execution gate before flight "
        "commands can be issued. "
        "For an explicitly authorized ordered pair, use start_preflight_sequence with two mission paths "
        "in operator order and a recorded request_key/authorization_statement. It reserves the whole "
        "sequence, validates both before flight, and only proceeds after a verified PASSED/landed child. "
        "It may arm/take off/move both simulated vehicles strictly sequentially, never starts simulation. "
        "Query get_preflight_sequence by the SAME ID/key after lost response/reload; never repeat, "
        "resume or substitute a child. Admission is not PASSED; uncertainty requires reconciliation."
    ),
    version="0.3.0",
)


@mcp.tool(description=(
    "Quick persistent admission of exactly TWO SITL rehearsals, one drone_01/v1 and one drone_02/v2, "
    "in the operator-supplied order. Requires explicit consent to BOTH exact snapshots, recorded as "
    "authorization_statement (agent declaration, not authenticated conversation). Detached coordinator "
    "may ARM, TAKE OFF, MOVE and LAND each vehicle strictly sequentially; whole-sequence global "
    "reservation prevents intervening project flights. No separation guarantee, task allocation, "
    "simulation start/restart or automatic retry. ACCEPTED is not validation/PASSED. Record request_key "
    "before calling; recover via get_preflight_sequence after timeout/lost response, never another flight. "
    "Paths must be regular bounded mission files inside this project's missions root."
), structured_output=True)
def start_preflight_sequence(
    mission_paths: Annotated[list[str], Field(min_length=2, max_length=2)],
    request_key: str,
    authorization_statement: Annotated[str, Field(min_length=1)],
) -> dict[str, object]:
    return start_sequence_backend(mission_paths, request_key, authorization_statement)


@mcp.tool(description=(
    "Read-only persistent sequence lookup by exactly one sequence_id or request_key. Never creates, "
    "resumes or retries any work. Returns ordered snapshot hashes, declared consent, coordinator "
    "identity/liveness, individual child states/report links and whole-sequence/global restrictions. "
    "NOT_STARTED differs from FAILED. summary by default; detail includes existing child reports. "
    "UNCONFIRMED or integrity errors forbid continuation; no inference of landing/release. "
    "Historical PASSED grants no hardware or subsequent flight permission."
), structured_output=True)
def get_preflight_sequence(sequence_id: str | None = None, request_key: str | None = None,
                           view: ResponseView = "summary") -> dict[str, object]:
    return get_sequence_backend(sequence_id=sequence_id, request_key=request_key, detail=view == "detail")


@mcp.tool(description="Persist a proposal from a final verified preflight run_id and snapshot hash. Recommendations only; no source edits or simulation. Preserve request_key/proposal_id and review proposal_sha256 before accepting changes.", structured_output=True)
def propose_mission_revision(run_id: str, request_key: str) -> dict[str, object]:
    return propose_revision_backend(run_id, request_key)


@mcp.tool(description="Read a persistent proposal and its reviewed version/hash after reload. view=summary (default) keeps source IDs/hashes, reasons, conditions and consent; view=detail preserves the complete previous response including executor evidence. Both verify the same source-copy integrity. No mission edits, simulation, flight or release of vehicle/global restrictions.", structured_output=True)
def get_revision_proposal(proposal_id: str, view: ResponseView = "summary") -> dict[str, object]:
    full = get_proposal_backend(proposal_id)
    return summarize_proposal(full) if view == "summary" else full


@mcp.tool(description="Build a NEW mission revision from explicitly accepted/operator-supplied changes and the reviewed proposal hash. Physical battery/wind/performance updates require field declarations, labelled operator-declared, not telemetry. Revalidates and exports QGC once; may remain BLOCKED. Never flies or inherits flight consent. Same request_key is idempotent; different inputs conflict.", structured_output=True)
def build_mission_revision(proposal_id: str, expected_proposal_sha256: str, changes: RevisionChanges,
                           operator_statement: str, request_key: str,
                           declarations: dict[str, str] | None = None) -> dict[str, object]:
    return build_revision_backend(proposal_id, expected_proposal_sha256, changes, operator_statement,
                                  request_key, declarations)


@mcp.tool(
    description=(
        "Admit ONE asynchronous virtual preflight and quickly return run_id and paths. "
        "Requires an explicit user rehearsal request: the detached worker may ARM, TAKE OFF "
        "and MOVE only the mission-selected drone_01->v1 or drone_02->v2, then land; one global flight slot. Choose and record request_key before "
        "calling; it permanently identifies this admission. Validation/acceptance are pending. "
        "Never starts simulation. A lost response is recovered with get_virtual_preflight, "
        "not another start. PASSED grants neither hardware permission nor another flight."
    ), structured_output=True,
)
def start_virtual_preflight(mission_path: str, request_key: str) -> dict[str, object]:
    return start_preflight_backend(mission_path, request_key)


@mcp.tool(
    description=(
        "Read-only preflight lookup by exactly one of run_id or request_key, including "
        "historical reports. Use this to query an EXISTING rehearsal by its run_id; "
        "a run is not an MCP prompt or generic resource. Returns job state, current/last phase, final result if available, "
        "report and paths. Never spawns, resumes, clears vehicle/global ownership or commands flight. "
        "view=summary by default; view=detail returns the complete previous response and raw "
        "executor evidence. Both retain result/reasons, uncertainty and vehicle restriction. "
        "Saved readiness is historical, not current availability; workflow/executor times "
        "are operation durations, not airborne time. "
        "Poll the same run every 15-30 seconds. INTERRUPTED/UNCONFIRMED never implies landing."
    ), structured_output=True,
)
def get_virtual_preflight(run_id: str | None = None, request_key: str | None = None,
                          view: ResponseView = "summary") -> dict[str, object]:
    full = get_preflight_backend(run_id=run_id, request_key=request_key)
    return summarize_preflight(full) if view == "summary" else full


@mcp.tool(
    description=(
        "SYNCHRONOUS legacy operation: holds the request throughout the rehearsal and may "
        "exceed the MCP client timeout without cancelling the backend. Prefer "
        "start_virtual_preflight plus get_virtual_preflight for tracking. "
        "Run one explicitly requested virtual preflight in Gazebo/ArduPilot SITL. "
        "WARNING: this tool ARMS, TAKES OFF and MOVES only the mission-selected drone_01->v1 or drone_02->v2, "
        "then lands and waits for disarm via the existing executor. It snapshots and "
        "hashes the mission, validates safety, checks readiness and compatibility, "
        "and persists an evidence report. Never starts/restarts simulation or retries "
        "a flight. Use only when the user requests the rehearsal. PASSED does not "
        "authorize hardware or grant consent for any subsequent execution."
    ),
    structured_output=True,
)
def run_virtual_preflight(mission_path: str) -> dict[str, object]:
    return preflight_backend(mission_path)


@mcp.tool(
    description="Save only operator-supplied mission facts and partial geometry_intent together; no inferred purpose/agriculture, safety limits, height or return decision. Geometry patches merge non-null facts, preserving dimensions; an explicit mode change clears old shape-specific fields. Retain draft_id/draft_revision; geometry edits require current expected_revision, existing routes require replace_route=true. A partial intent saves without waypoints; invalid facts do not overwrite state. Empty updates retrieve. Returns mission/geometry pending fields, effective compatibility defaults and UNVERIFIED field attribution (optional JSON-pointer attributions for resolved supplied fields; OPERATOR_DECLARED_VIA_AGENT requires a nonblank supporting statement). Ordinary legacy waypoint updates merge; explicit manual replacement detaches geometry intent. No extra approval for requested saving, and no flight commands.",
    structured_output=True,
)
def update_mission_draft(
    updates: MissionPlanDraft, draft_id: str | None = None,
    expected_revision: int | None = None,
    replace_route: bool = False,
    attributions: dict[str, InputAttribution] | None = None,
) -> dict[str, object]:
    return update_draft_backend(updates, draft_id, expected_revision, replace_route, attributions)


@mcp.tool(description="Read-only mission explanation using exactly one retained draft_id, revision_id or run_id; query an EXISTING preflight run_id here to explain its mission/artifact links, or use get_virtual_preflight for its job/report. No prompt/resource search is needed. NOT a draft inventory. Missing identifier is INVALID_ARGUMENTS, lookup_performed=false, inventory UNKNOWN, never evidence of no drafts. view=summary by default keeps geometry intent/version/count, pending decisions, attribution caveats, defaults, validation and verified links without repeated trees. view=detail returns the complete previous response including route and field provenance. Both perform the same integrity checks. Use retained IDs/detail_access without redundant resource/file exploration. Optional finalization_id selects a draft snapshot. Historical readiness is not current; no consent, validation, writes or operational effects.", structured_output=True)
def get_mission_state(draft_id: str | None = None, finalization_id: str | None = None,
                      revision_id: str | None = None, run_id: str | None = None,
                      view: ResponseView = "summary") -> dict[str, object]:
    return mission_state_backend(draft_id=draft_id, finalization_id=finalization_id,
                                 revision_id=revision_id, run_id=run_id, view=view)


@mcp.tool(description="Save/complete structured geometry intent in an existing versioned draft, including incomplete parameters; null/omitted facts preserve earlier dimensions/decisions, explicit mode change resets old shape fields. Return joint geometry/mission pending fields; generate waypoints only when all geometry decisions are explicit. Travel direction alone does not select an edge/axis orientation: save other clear parameters and ask; a numeric value cannot prove dialogue fidelity. HOME alone is insufficient. Existing routes require replace_route=true for changed geometry; incomplete replacements invalidate old waypoints. Metres, length-edge heading clockwise from north. Deterministic generation is not operator attribution, agriculture or coverage. Optional JSON-pointer attributions only for resolved supplied fields; OPERATOR_DECLARED_VIA_AGENT requires a nonblank supporting statement, not authentication. Never flies.", structured_output=True)
def generate_draft_route(draft_id: str, expected_revision: int, request: RelativeRouteRequest,
                         replace_route: bool = False,
                         attributions: dict[str, InputAttribution] | None = None) -> dict[str, object]:
    return generate_route_backend(draft_id, expected_revision, request, replace_route, attributions)


@mcp.tool(
    description="On requested finalization, snapshot the complete draft, validate and export QGC .plan in ONE operation without another saving/validation approval. A successful result already satisfies construct/validate/export even when the user lists all three; do not issue extra validation/export for that unchanged version. Pending geometry also blocks finalization. Supply expected_revision; retain finalization_id/mission_path/hashes. Explain this result and show compatibility defaults and unverified provenance before seeking rehearsal consent. Unsafe plans remain BLOCKED candidates. Never starts simulation or grants flight consent.",
    structured_output=True,
)
def finalize_mission_draft(draft_id: str, expected_revision: int | None = None) -> dict[str, object]:
    return finalize_draft_backend(draft_id, expected_revision)


@mcp.tool(
    name="validate_mission",
    description=(
        "Validate a drone mission using the deterministic TFG "
        "mission-safety pipeline. No LLM is used for the safety "
        "decision."
    ),
    structured_output=True,
)
def validate_mission(
    mission_path: str,
) -> dict[str, object]:
    return validate_mission_file(
        mission_path
    )


@mcp.tool(
    name="validate_and_export_qgc",
    description=(
        "Validate a drone mission deterministically and export a "
        "QGroundControl .plan file. Unsafe missions remain blocked "
        "and are exported only as candidate plans. For standalone JSON or a new explicit "
        "revalidation/export request; not an extra step after finalize_mission_draft or "
        "build_mission_revision already returned validation and export for unchanged content."
    ),
    structured_output=True,
)
def validate_and_export_qgc(
    mission_path: str,
    output_directory: str | None = None,
) -> dict[str, object]:
    return validate_mission_file(
        mission_path,
        export_qgc=True,
        output_dir=output_directory,
    )


@mcp.tool(
    name="check_simulation_ready",
    description=(
        "Check whether the ROS2, Gazebo and ArduPilot simulation "
        "stack is healthy and ready. This is a read-only check and "
        "does not issue flight commands. Backend readiness does not verify GUI rendering, "
        "a visible window, operator visualization or absence of active flights/reservations."
    ),
    structured_output=True,
)
def check_simulation_ready() -> dict[str, object]:
    return check_simulation_backend()


@mcp.tool(
    name="start_simulation",
    description=(
        "Start the deterministic ROS2, Gazebo and ArduPilot "
        "simulation stack. This starts the simulation environment "
        "only and does not arm, take off or command a vehicle. It also stops previous "
        "project simulation processes: repeating start is a restart, never a read-only GUI probe. "
        "After a GUI start, check backend readiness and ask the operator whether the world "
        "and drones are visible, black or no window opened; success/READY/process existence "
        "cannot confirm the image. GUI recovery needs explicit restart acceptance and verified "
        "absence of active execution or any unresolved vehicle/global reservation. If unknown, "
        "do not restart. Use one sequential confirmed stop/start/readiness/visual question; "
        "never retry automatically. Explicitly choosing no visualization grants no flight consent."
    ),
    structured_output=True,
)
def start_simulation(gui: bool = True) -> dict[str, object]:
    return start_simulation_backend(gui=gui)


@mcp.tool(description="Explicitly authorized ONE simulator stop/start transaction. Atomically excludes all project flight admissions. Active/uncertain flight, sequence or lifecycle restrictions block it; never reconcile implicitly. gui=false selects headless, gui=true still requires operator visual confirmation. Does not grant flight consent or retry automatically.", structured_output=True)
def restart_simulation(gui: bool = True) -> dict[str, object]:
    return restart_simulation_backend(gui=gui)


@mcp.tool(description="Explicit read-only operational reconciliation INSPECTION of a known current reservation owner UUID (sequence/run/lifecycle). First reads bounded Docker metadata and known owners/versions/process identities under OS mutex. For ACTIVE environment collects new telemetry for BOTH interfaces. For verifiably STOPPED exact container uses retained identity evidence, with no telemetry or ground claim; Docker inaccessible/absent/replaced/unknown blocks. Persists only a separate audit, never controls, edits/releases restrictions or resumes work. Historical telemetry is insufficient. Return inspection_id/hash, basis, known/unknown fields, collection state, applicability and expiry (never-collected is not expired). Separate explicit authorization is always required. STOPPED with posthoc identity returns AWAITING_LEGACY_ENVIRONMENT_REVIEW, application_eligible=false until the separate operator continuity/clock declaration accompanies application; chronology is conditional evidence. Only the ACTIVE path requires independent recent visual on-ground confirmations. Absolute message generation age is unknown; armed=false/flying=false is not ground contact.", structured_output=True)
def inspect_execution_reconciliation(target_id: str) -> dict[str, object]:
    from tools.execution_reconciliation import inspect_execution_reconciliation as inspect_backend
    return inspect_backend(target_id)


@mcp.tool(description="Read a retained reconciliation inspection/application audit by inspection_id after reload or lost response. Fixed project root, no telemetry collection, reservation writes, application, resume or new consent. An APPLIED audit reconciles restrictions, never repairs historical mission results. Preserve inspection hash and original application arguments; do not repeat with invented fresh declarations.", structured_output=True)
def get_execution_reconciliation(inspection_id: str) -> dict[str, object]:
    from tools.execution_reconciliation import get_execution_reconciliation as get_backend
    return get_backend(inspection_id)


@mcp.tool(description="Apply ONLY an explicitly authorized reviewed reconciliation inspection_id + exact SHA-256, within expiry and same boot. For ACTIVE_TELEMETRY_AND_GROUND requires OPERATOR_VISUAL ground_confirmations for v1/v2 with vehicle, on_ground=true, statement and observed_at_utc after inspection, plus new telemetry. For ENVIRONMENT_TERMINATED omit ground_confirmations: administrative closure revalidates exact Docker engine/container/incarnation stopped state and retained identity reference, dead responsible processes and all versions under common exclusion. Never start the simulator to obtain evidence. Posthoc references require legacy_environment_confirmation: explicit operator review of deployment/selector continuity, no substitution/clone and comparable wall clocks, matching inspected engine_id/container_id with a supporting statement. Missing or contradicted review stays pending/blocked; original historical identity is still unknown. Host boot_id is not Docker engine identity/restart evidence. Administrative closure asserts neither landing nor mission success. Missing/changed/uncertain evidence stays blocked. Preserves original reservations in audit/history and never edits ERROR/PASSED reports, resumes, retries or authorizes flights. Identical repeated application is idempotent; no force unlock. Claims supplied through MCP are unverified agent declarations.", structured_output=True)
def apply_execution_reconciliation(inspection_id: str, inspection_sha256: str,
                                   authorization_statement: str,
                                   ground_confirmations: list[GroundConfirmation] | None = None,
                                   legacy_environment_confirmation: LegacyEnvironmentConfirmation | None = None) -> dict[str, object]:
    from tools.execution_reconciliation import apply_execution_reconciliation as apply_backend
    arguments = (inspection_id, inspection_sha256, authorization_statement,
                 [g.model_dump() for g in ground_confirmations] if ground_confirmations is not None else None)
    if legacy_environment_confirmation is not None:
        return apply_backend(*arguments, legacy_environment_confirmation=legacy_environment_confirmation.model_dump())
    return apply_backend(*arguments)


@mcp.tool(
    name="stop_simulation",
    description=(
        "Stop the ROS2, Gazebo and ArduPilot simulation processes. "
        "This tool is intended for simulation lifecycle management "
        "and does not represent a normal in-flight landing command. For GUI recovery require "
        "explicit restart acceptance and verify no active execution or vehicle/global reservation "
        "first; unknown outcome, lost worker or remaining reservation forbids stopping/restarting "
        "to fix the image. Await confirmed stop before start; no parallel calls or automatic retries. "
        "All updated project entry points share an atomic lifecycle/flight exclusion. A failed or interrupted lifecycle retains its own restriction. Explicit restart uses one transaction, not parallel stop/start calls."
    ),
    structured_output=True,
)
def stop_simulation() -> dict[str, object]:
    return stop_simulation_backend()


@mcp.tool(
    name="check_mission_execution_ready",
    description=(
        "Check whether a mission is authorized for execution. "
        "The deterministic mission-safety pipeline must approve "
        "the mission and the simulation must be healthy before "
        "execution is authorized."
    ),
    structured_output=True,
)
def check_mission_execution_ready(
    mission_path: str,
) -> dict[str, object]:
    return check_execution_ready(
        mission_path
    )


@mcp.tool(
    name="execute_approved_mission",
    description=(
        "SYNCHRONOUS: may exceed the MCP client timeout; timeout does not cancel flight. "
        "Shares global flight exclusion and per-vehicle reservations with asynchronous preflight. "
        "Resolve MissionDefinition.vehicle.vehicle_id (drone_01->v1, drone_02->v2), reject unknown IDs, and execute one approved waypoint mission in the "
        "Gazebo/ArduPilot simulation. The executor re-runs the "
        "deterministic execution gate internally before issuing "
        "any flight command. Unsupported or unsafe missions are "
        "blocked. The current executor supports ArduPilot "
        "multirotor missions with navigate actions."
    ),
    structured_output=True,
)
def execute_approved_mission(
    mission_path: str,
) -> dict[str, object]:
    return execute_mission_backend(
        mission_path,
        progress=False,
    )


if __name__ == "__main__":
    mcp.run(
        transport="stdio"
    )
