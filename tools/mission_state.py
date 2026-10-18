"""Read-only explanation from artifact sidecars and explicit identity/hash links."""
from pathlib import Path

from planning.artifact_store import boundary, identifier, read_object, sha256
from planning.mission_artifacts import load_finalization, load_revision, load_link
from planning import mission_revisions as revisions
from tools import hermes_mission_planning as drafts
from tools import virtual_preflight_jobs as jobs
from tools.mission_response_views import ResponseView, summarize_mission_state


def _scan(root, pattern, warnings):
    for path in sorted(root.glob(pattern)):
        try:
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("Record escapes root")
            yield path, read_object(path)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            warnings.append({"path": str(path), "message": str(exc)})


def _run_view(run_id):
    view = jobs.get_virtual_preflight(run_id=run_id)
    if view["job_state"] == "ERROR":
        raise ValueError(str(view["errors"]))
    report = view.get("report")
    job = jobs.read_json(jobs.run_directory(run_id) / "job.json", jobs.RUN_ROOT) or {}
    view["source_artifact"] = (report or {}).get("source_artifact") or job.get("source_artifact")
    view["readiness_now"] = "UNKNOWN_NOT_CHECKED"
    view["readiness_scope"] = "Stored readiness is historical; no present infrastructure check performed"
    view["snapshot_integrity"] = "UNKNOWN"
    if report and report.get("mission_sha256"):
        path = Path(view["paths"]["report_path"])
        snapshot = path.with_name("mission.json" if path.name == "report.json"
                                  else path.name.replace("_report.json", "_mission.json"))
        if (not snapshot.resolve().is_relative_to(path.parent.resolve())
                or sha256(snapshot.read_bytes()) != report["mission_sha256"]):
            raise ValueError("Preflight snapshot hash mismatch; cannot associate evidence")
        view["snapshot_integrity"] = "VERIFIED_LOCAL_HASH"
    view["result_scope"] = "Historical result for this exact simulated v1 snapshot only; no new consent"
    return view


def _matching_runs(artifacts, warnings, entries):
    matches = {}
    for path, entry in entries:
        link = entry.get("source_artifact")
        if not isinstance(link, dict):
            continue  # No inference from filenames, mission name, dates or equal-looking routes.
        target = artifacts.get(link.get("artifact_id"))
        if not target:
            continue
        try:
            linked = load_link(link)
            if linked["record_sha256"] != target["record_sha256"]:
                raise ValueError("Linked record changed")
            admitted_hash = entry.get("input_sha256") or entry.get("mission_sha256")
            if admitted_hash != link["mission_sha256"]:
                raise ValueError("Run content does not match the recorded artifact link")
            run_id = identifier(entry["run_id"])
            view = _run_view(run_id)
            if view.get("mission_sha256") != link["mission_sha256"]:
                raise ValueError("Queried run snapshot does not match its artifact link")
            matches[run_id] = view
        except (ValueError, OSError, KeyError, TypeError) as exc:
            warnings.append({"path": str(path), "message": str(exc)})
    return list(matches.values())


@boundary
def _get_mission_state_detail(*, draft_id=None, finalization_id=None, revision_id=None, run_id=None):
    """Exactly one anchor; optional finalization_id selects one snapshot of a draft."""
    if sum(value is not None for value in (draft_id, revision_id, run_id)) != 1:
        return {"status": "ERROR", "error_code": "INVALID_ARGUMENTS", "lookup_performed": False,
                "inventory_status": "UNKNOWN", "errors": ["Supply exactly one of draft_id, revision_id or run_id; this is not an inventory query or evidence that no drafts exist"]}
    if finalization_id is not None and draft_id is None:
        return {"status": "ERROR", "error_code": "INVALID_ARGUMENTS", "lookup_performed": False,
                "inventory_status": "UNKNOWN", "errors": ["finalization_id requires draft_id"]}
    warnings, artifacts, runs, proposals, revision_records = [], {}, [], [], []
    current_draft = None
    if draft_id is not None:
        draft, state = drafts.read_draft_record(identifier(draft_id))
        current_draft = {**drafts.draft_result(draft_id, draft, state),
                         "path": str(drafts._directory(draft_id) / "draft.json")}
        paths = ([drafts._directory(draft_id) / identifier(finalization_id) / "finalization.json"]
                 if finalization_id else drafts._directory(draft_id).glob("*/finalization.json"))
        for path in paths:
            record = load_finalization(draft_id, path.parent.name)
            record["matches_current_draft"] = record["draft_sha256"] == state["draft_sha256"]
            artifacts[record["finalization_id"]] = record
    elif revision_id is not None:
        record = load_revision(identifier(revision_id))
        artifacts[revision_id] = record
        revision_records.append(record)
        runs.append(_run_view(record["source_run_id"]))
    else:
        view = _run_view(identifier(run_id))
        if view["job_state"] == "NOT_FOUND":
            return {"status": "NOT_FOUND", "run_id": run_id, "consent": "NOT_GRANTED_BY_THIS_QUERY"}
        runs.append(view)
        link = view["source_artifact"]
        if link:
            record = load_link(link)
            if view.get("mission_sha256") != link["mission_sha256"]:
                raise ValueError("Run snapshot differs from the linked mission artifact")
            artifacts[link["artifact_id"]] = record
        else:
            warnings.append({"message": "Mission/draft lineage UNKNOWN: historical run has no explicit artifact link"})
    known = {view["run_id"]: view for view in runs}
    proposal_entries = list(_scan(revisions.REVISION_ROOT / "proposals", "*/proposal.json", warnings))
    revision_entries = list(_scan(revisions.REVISION_ROOT / "missions", "*/revision.json", warnings))
    run_entries = [*list(_scan(jobs.RUN_ROOT, "*/job.json", warnings)),
                   *list(_scan(jobs.RUN_ROOT, "*/report.json", warnings))]
    proposal_map = {}
    revision_map = {r["revision_id"]: r for r in revision_records}
    # A proposal belongs to a run only when the exact source report AND mission
    # hashes agree. A revision additionally binds the reviewed proposal bytes.
    while True:
        count = len(known) + len(artifacts) + len(proposal_map) + len(revision_map)
        for view in _matching_runs(artifacts, warnings, run_entries):
            known[view["run_id"]] = view
        for view in list(known.values()):
            link = view.get("source_artifact")
            if link and link["artifact_id"] not in artifacts:
                record = load_link(link)
                if view.get("mission_sha256") != link["mission_sha256"]:
                    raise ValueError("Parent run content differs from its linked artifact")
                artifacts[link["artifact_id"]] = record
        for path, entry in proposal_entries:
            source = known.get(entry.get("run_id"))
            if not source or not source.get("report") or path.parent.name in proposal_map:
                continue
            try:
                source_report = Path(source["paths"]["report_path"]).read_bytes()
                if (entry["mission_sha256"] != source["report"].get("mission_sha256")
                        or entry["report_sha256"] != sha256(source_report)):
                    raise ValueError("Proposal/source run hash mismatch")
                proposal = revisions.get_revision_proposal(identifier(path.parent.name))
                if proposal["status"] != "PROPOSED":
                    raise ValueError(str(proposal))
                proposal_map[proposal["proposal_id"]] = proposal
            except (ValueError, OSError, KeyError, TypeError) as exc:
                warnings.append({"path": str(path), "message": str(exc)})
        for path, entry in revision_entries:
            if entry.get("proposal_id") not in proposal_map or path.parent.name in revision_map:
                continue
            try:
                record = load_revision(identifier(path.parent.name))
                revision_map[record["revision_id"]] = record
                artifacts[record["revision_id"]] = record
            except (ValueError, OSError, KeyError, TypeError) as exc:
                warnings.append({"path": str(path), "message": str(exc)})
        if len(known) + len(artifacts) + len(proposal_map) + len(revision_map) == count:
            break
    runs, proposals, revision_records = list(known.values()), list(proposal_map.values()), list(revision_map.values())
    linked_drafts = []
    for linked_id in sorted({r["draft_id"] for r in artifacts.values() if r.get("draft_id")} - {draft_id}):
        linked_draft, state = drafts.read_draft_record(identifier(linked_id))
        linked_drafts.append(drafts.draft_result(linked_id, linked_draft, state))
    missing = current_draft["missing_fields"] if current_draft else []
    next_actions = ["Ask the operator for missing fields"] if missing else []
    if current_draft and not missing and not any(r.get("matches_current_draft") for r in artifacts.values()):
        next_actions.append("Finalize the current draft version to validate and export once")
    if any(r["job_state"] in {"STARTING", "RUNNING", "ADMITTED"} for r in runs):
        next_actions.append("Query the SAME run_id every 15-30 seconds; never repeat start")
    if any(r["job_state"] in {"INTERRUPTED", "UNCONFIRMED"} for r in runs):
        next_actions.append("Reconcile unconfirmed vehicle/worker state with the operator; do not infer landing")
    if any(r.get("result_status") in {"BLOCKED", "FAILED", "ERROR"} for r in runs):
        next_actions.append("Review report and pending proposal conditions; no automatic fix/retry")
    if artifacts:
        next_actions.append("Any new rehearsal requires explicit consent for the reviewed snapshot; the worker does not start simulation")
    # Repeated traversal does not duplicate warnings in the response.
    warnings = list({str(w): w for w in warnings}.values())
    return {"status": "KNOWN_WITH_WARNINGS" if warnings else "KNOWN", "draft": current_draft,
            "linked_drafts": linked_drafts,
            "artifacts": list(artifacts.values()), "preflights": runs, "proposals": proposals,
            "revisions": revision_records, "missing_fields": missing, "warnings": warnings,
            "pending": current_draft["pending"] if current_draft else None,
            "next_actions": next_actions, "readiness_now": "UNKNOWN_NOT_CHECKED",
            "consent": "NOT_GRANTED_BY_THIS_QUERY", "hardware_authorized": False,
            "limits": ["Saved validation and PASSED apply only to their recorded hashes",
                       "Modified content needs new evaluation; historical readiness is not current availability",
                       "Missing explicit links remain unknown; hashes do not provide signatures or full TOCTOU protection"]}


@boundary
def get_mission_state(*, draft_id=None, finalization_id=None, revision_id=None, run_id=None,
                      view: ResponseView = "detail"):
    """Preserve the Python detail default; project only after all existing checks."""
    if view not in ("summary", "detail"):
        return {"status": "ERROR", "error_code": "INVALID_ARGUMENTS", "lookup_performed": False,
                "inventory_status": "UNKNOWN", "errors": ["view must be summary or detail"]}
    anchor = {key: value for key, value in {
        "draft_id": draft_id, "finalization_id": finalization_id,
        "revision_id": revision_id, "run_id": run_id,
    }.items() if value is not None}
    full = _get_mission_state_detail(**anchor)
    return summarize_mission_state(full, anchor) if view == "summary" else full
