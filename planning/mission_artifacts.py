"""Verify sidecars next to missions. No validation pipeline, registry or flight calls."""
import json
from pathlib import Path

from planning.artifact_store import child, identifier, sha256


def _inside(directory, filename):
    path = directory / filename
    if not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("Artifact file escapes its directory")
    return path


def checked_mission_record(directory, filename):
    record_path = _inside(directory, filename)
    record_bytes = record_path.read_bytes()
    record = json.loads(record_bytes)
    if not isinstance(record, dict):
        raise ValueError("Mission sidecar must be an object")
    mission_path = _inside(directory, "mission.json")
    if (Path(record["mission_path"]).resolve() != mission_path.resolve()
            or sha256(mission_path.read_bytes()) != record["mission_sha256"]):
        raise ValueError("Mission sidecar/path/hash does not match its snapshot")
    validation = record.get("validation")
    if not isinstance(validation, dict):
        raise ValueError("Invalid saved validation object")
    plan = validation.get("qgc_plan_path")
    if plan:
        plan_path = _inside(directory, Path(plan).name)
        if Path(plan).resolve() != plan_path.resolve():
            raise ValueError("Plan path escapes artifact directory")
        if sha256(plan_path.read_bytes()) != record.get("qgc_plan_sha256"):
            raise ValueError("Exported plan hash mismatch")
    return {**record, "record_path": str(record_path),
            "record_sha256": sha256(record_bytes), "integrity": "VERIFIED_LOCAL_HASHES"}


def load_finalization(draft_id, finalization_id):
    from tools import hermes_mission_planning as drafts
    directory = child(drafts._directory(draft_id), finalization_id)
    record = checked_mission_record(directory, "finalization.json")
    if (record.get("kind") != "finalization" or record["draft_id"] != draft_id
            or record["finalization_id"] != finalization_id):
        raise ValueError("Finalization identity mismatch")
    source = _inside(directory, "source_draft.json")
    if sha256(source.read_bytes()) != record["draft_sha256"]:
        raise ValueError("Finalized source draft hash mismatch")
    if record.get("draft_state_sha256") is not None:
        if sha256(_inside(directory, "source_draft_state.json").read_bytes()) != record["draft_state_sha256"]:
            raise ValueError("Finalized source draft metadata hash mismatch")
    return record


def load_revision(revision_id):
    from planning import mission_revisions as revisions
    directory = child(revisions.REVISION_ROOT / "missions", revision_id)
    record = checked_mission_record(directory, "revision.json")
    if record.get("kind") != "revision" or record["revision_id"] != revision_id:
        raise ValueError("Revision identity mismatch")
    proposal = revisions.get_revision_proposal(record["proposal_id"])
    if (proposal["status"] != "PROPOSED" or proposal["proposal_sha256"] != record["proposal_sha256"]
            or proposal["proposal"]["run_id"] != record["source_run_id"]
            or proposal["proposal"]["mission_sha256"] != record["source_mission_sha256"]
            or proposal["proposal"]["report_sha256"] != record["source_report_sha256"]):
        raise ValueError("Revision source/proposal link is invalid")
    return record


def artifact_for_input(mission_path, mission_sha256):
    """Capture explicit lineage at admission; a plain JSON has unknown lineage.

    Loading happens before reservation/spawn. Any known damaged sidecar is an
    error, never silently reclassified as an unrelated mission.
    """
    from tools import hermes_mission_planning as drafts
    from planning import mission_revisions as revisions
    path = Path(mission_path).resolve()
    record = None
    if path.is_relative_to(drafts.DRAFT_ROOT.resolve()) and path.name == "mission.json":
        if (path.parent / "finalization.json").exists():
            record = load_finalization(path.parent.parent.name, path.parent.name)
            kind, artifact_id = "finalization", record["finalization_id"]
    elif path.is_relative_to((revisions.REVISION_ROOT / "missions").resolve()) and path.name == "mission.json":
        if (path.parent / "revision.json").exists():
            record = load_revision(path.parent.name)
            kind, artifact_id = "revision", record["revision_id"]
    if record is None:
        return None
    if record["mission_sha256"] != mission_sha256:
        raise ValueError("Admission bytes differ from the linked mission artifact")
    return {"kind": kind, "artifact_id": artifact_id, "draft_id": record.get("draft_id"),
            "mission_sha256": mission_sha256, "record_sha256": record["record_sha256"]}


def load_link(link):
    if not isinstance(link, dict):
        raise ValueError("Missing mission artifact link")
    identifier(link["artifact_id"])
    if link["kind"] == "finalization":
        record = load_finalization(link["draft_id"], link["artifact_id"])
    elif link["kind"] == "revision":
        record = load_revision(link["artifact_id"])
    else:
        raise ValueError("Unknown mission artifact kind")
    if any(link[key] != record[key] for key in ("mission_sha256", "record_sha256")):
        raise ValueError("Mission artifact link hash mismatch")
    return record
