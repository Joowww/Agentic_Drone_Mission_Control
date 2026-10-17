"""MCP-facing entry point for an explicitly requested simulated rehearsal."""
from pathlib import Path
from uuid import uuid4

from graph.virtual_preflight_graph import utc_now, virtual_preflight_graph

PREFLIGHT_ROOT = Path(__file__).resolve().parents[1] / "missions/generated/preflights"


def run_virtual_preflight(mission_path: str) -> dict[str, object]:
    """Arms, takes off and moves only simulated v1 when all checks pass.

    Never starts/restarts simulation. Never authorizes another flight or hardware.
    """
    run_id = str(uuid4())
    directory = PREFLIGHT_ROOT / run_id
    started = utc_now()
    try:
        directory.mkdir(parents=True)
    except OSError as exc:
        return {"status": "ERROR", "run_id": run_id, "started_at": started,
                "finished_at": utc_now(), "report_path": None, "report_persisted": False,
                "reasons": [f"Cannot create preflight directory: {exc}"]}
    return run_preflight_in_directory(mission_path, run_id, directory, started_at=started)


def run_preflight_in_directory(mission_path, run_id, directory, *, started_at=None, expected_sha256=None,
                              persist_progress=False):
    """Shared workflow invocation for synchronous callers and detached workers."""
    started = started_at or utc_now()
    final = virtual_preflight_graph.invoke({
        "run_id": run_id, "run_directory": str(directory),
        "expected_sha256": expected_sha256, "persist_progress": persist_progress,
        "source_path": str(Path(mission_path).resolve()),
        "snapshot_path": str(directory / "mission.json"),
        "report_path": str(directory / "report.json"),
        "mission_sha256": None, "mission_identity": None,
        "status": "RUNNING", "stage": "initializing", "reasons": [],
        "validation": None, "readiness": None, "compatibility_errors": [],
        "executor_result": None, "analysis": None, "execution_attempted": False,
        "started_at": started, "transitions": [],
    })
    return final["report"]
