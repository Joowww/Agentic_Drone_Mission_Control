"""Read-only, ROS-free analysis of passive collector JSONL. Never credits identity."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

TOPICS = {"/ap/v3/status": "ardupilot_msgs/msg/Status",
          "/rover1/odometry": "nav_msgs/msg/Odometry"}
SCHEMA = "tfg.rover.passive-capture/1"
RESERVED_SCHEMA = "tfg.rover.passive-capture/2"
# /3 = /1 or /2 sampling (sampling_policy) plus odometry_fields on every odometry sample.
FIELDS_SCHEMA = "tfg.rover.passive-capture/3"
ODOMETRY_SOURCE = "nav_msgs/msg/Odometry fields as received; units and frames NOT validated"
NONFINITE = ("NaN", "Infinity", "-Infinity")
# Measured, PROPOSED only, never enforced here: see COLLECTOR.md ("Formato /3").
PROPOSED_MAX_RECORD_BYTES = 16384


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _receipt(value):
    return (isinstance(value, dict) and all(_integer(value.get(k))
            for k in ("system_unix_ns", "steady_ns"))
            and value["steady_ns"] >= 0)


def _gid(value):
    return (isinstance(value, str) and len(value) == 48
            and all(c in "0123456789abcdef" for c in value) and int(value, 16) != 0)


def _candidate(value):
    if not isinstance(value, dict):
        return False
    gid = value.get("endpoint_gid")
    if (not isinstance(gid, str) or len(gid) != 48
            or not all(c in "0123456789abcdef" for c in gid)
            or not isinstance(value.get("node_name"), str)
            or not isinstance(value.get("node_namespace"), str)):
        return False
    topic_type, qos = value.get("topic_type"), value.get("offered_qos")
    if topic_type is not None and not isinstance(topic_type, str):
        return False
    return qos is None or (isinstance(qos, dict)
        and qos.get("source") == "TopicEndpointInfo.qos_profile.get_rmw_qos_profile"
        and all(_integer(qos.get(k)) and qos[k] >= 0
                for k in ("reliability_rmw", "durability_rmw", "history_rmw", "depth"))
        and qos.get("other_policies") == "NOT_CAPTURED")


def _reserved(start):
    return bool(start) and (start.get("schema") == RESERVED_SCHEMA or (
        start.get("schema") == FIELDS_SCHEMA and start.get("sampling_policy") == "RESERVE_BOTH_STREAMS"))


def _odometry_fields(value):
    """(structurally valid, non-finite paths). Leaves are finite numbers or null listed in nonfinite."""
    if not isinstance(value, dict) or set(value) != {"source", "validity_flag", "pose", "twist", "nonfinite"}:
        return False, []
    if value["source"] != ODOMETRY_SOURCE or value["validity_flag"] != "NOT_PROVIDED_BY_MESSAGE":
        return False, []
    pose, twist, nonfinite = value["pose"], value["twist"], value["nonfinite"]
    if (not isinstance(pose, dict) or set(pose) != {"position", "orientation", "covariance"}
            or not isinstance(twist, dict) or set(twist) != {"linear", "angular", "covariance"}
            or not isinstance(nonfinite, dict) or any(v not in NONFINITE for v in nonfinite.values())):
        return False, []
    leaves = {}
    for name, keys, node in (("pose.position", "xyz", pose["position"]), ("pose.orientation", "xyzw", pose["orientation"]),
                             ("twist.linear", "xyz", twist["linear"]), ("twist.angular", "xyz", twist["angular"])):
        if not isinstance(node, dict) or set(node) != set(keys):
            return False, []
        leaves.update({f"{name}.{k}": node[k] for k in keys})
    for name, values in (("pose.covariance", pose["covariance"]), ("twist.covariance", twist["covariance"])):
        if not isinstance(values, list) or len(values) != 36:
            return False, []
        leaves.update({f"{name}[{i}]": v for i, v in enumerate(values)})
    nulls = sorted(k for k, v in leaves.items() if v is None)
    numbers_ok = all(v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)) for v in leaves.values())
    return numbers_ok and nulls == sorted(nonfinite), nulls


def analyze_bytes(data: bytes, *, receipt=None, returncode=None):
    """Analyze immutable bytes; optional final stdout receipt and process rc are external facts.

    Neither a footer nor a receipt alone confirms successful process completion.
    Timestamps stay in their own clock domains. No wall/source-age inference.
    """
    issues, events = [], []
    record_bytes = [len(line) for line in data.splitlines(keepends=True)]
    for number, line in enumerate(data.splitlines(keepends=True), 1):
        if not line.endswith(b"\n"):
            issues.append({"line": number, "reason": "unterminated_record"})
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate key")
                    result[key] = value
                return result
            value = json.loads(line, object_pairs_hook=unique,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(value, dict):
                raise ValueError()
            events.append((number, value))
        except (ValueError, UnicodeDecodeError):
            issues.append({"line": number, "reason": "invalid_json_record"})
    def issue(line, reason):
        issues.append({"line": line, "reason": reason})
    summaries = {t: {"samples": [], "gid_changes": [], "header_regressions": [], "header_repeats": [],
                     "frame_changes": [], "receipt_regressions": []} for t in TOPICS}
    discoveries = []
    start = end = None
    count = incomplete = 0
    previous_global = None
    for line, event in events:
        if (event.get("status") != "BLOCKED"
                or event.get("source_association_verified") is not False
                or event.get("movement_authorized") is not False):
            issue(line, "contradictory_safety_fields")
        kind = event.get("event")
        if kind == "start":
            if start is not None or count or end is not None or events[0][0] != line:
                issue(line, "start_out_of_order")
            start = event
            duration = event.get("duration_s")
            if (event.get("schema") not in (SCHEMA, RESERVED_SCHEMA, FIELDS_SCHEMA) or event.get("string_encoding") != "byte_escape_u00"
                    or not _integer(event.get("max_samples")) or not 2 <= event["max_samples"] <= 10000
                    or isinstance(duration, bool) or not isinstance(duration, (float, int))
                    or not 0 < duration <= 300):
                issue(line, "invalid_start_contract")
            if event.get("schema") == RESERVED_SCHEMA and (event.get("sampling_policy") != "RESERVE_BOTH_STREAMS"
                    or not _integer(event.get("max_samples")) or event["max_samples"] > 20):
                issue(line, "invalid_sampling_policy")
            if event.get("schema") == FIELDS_SCHEMA and (
                    event.get("sampling_policy") not in ("RESERVE_BOTH_STREAMS", "GLOBAL_CAP")
                    or (event.get("sampling_policy") == "RESERVE_BOTH_STREAMS"
                        and (not _integer(event.get("max_samples")) or event["max_samples"] > 20))):
                issue(line, "invalid_sampling_policy")
        elif kind == "sample":
            count += 1
            if start is None or end is not None:
                issue(line, "sample_out_of_order")
            topic = event.get("topic")
            if not isinstance(topic, str) or topic not in TOPICS:
                issue(line, "unknown_topic")
                incomplete += 1
                continue
            if _reserved(start) and _integer(start.get("max_samples")):
                other = next(t for t in TOPICS if t != topic)
                if not summaries[other]["samples"] and len(summaries[topic]["samples"]) >= start["max_samples"] - 1:
                    issue(line, "reserved_capacity_violated")
            valid = event.get("message_type") == TOPICS[topic]
            received = event.get("receipt")
            valid = valid and _receipt(received)
            header = event.get("header")
            stamp = header.get("stamp") if isinstance(header, dict) else None
            stamp_ok = (isinstance(stamp, dict) and _integer(stamp.get("sec"))
                        and _integer(stamp.get("nanosec")) and 0 <= stamp["nanosec"] < 10**9)
            valid = valid and stamp_ok and isinstance(header.get("frame_id"), str)
            gid = event.get("message_publisher_gid")
            valid = (valid and _gid(gid) and event.get("message_gid_state") == "OBSERVED_NOT_ACCREDITED"
                     and event.get("message_gid_source") == "rclcpp callback MessageInfo.rmw_message_info.publisher_gid"
                     and event.get("from_intra_process") is False
                     and isinstance(event.get("rmw_implementation_identifier"), str)
                     and bool(event["rmw_implementation_identifier"]))
            graph = event.get("graph")
            graph_ok = (isinstance(graph, dict) and graph.get("state") == "OBSERVED"
                        and _receipt(graph.get("receipt")) and isinstance(graph.get("candidates"), list)
                        and graph.get("source") == "Node.get_publishers_info_by_topic"
                        and all(_candidate(c) for c in graph["candidates"]))
            valid = valid and graph_ok
            if topic == "/ap/v3/status":
                fields = event.get("status_fields")
                valid = (valid and isinstance(fields, dict) and _integer(fields.get("vehicle_type"))
                         and fields["vehicle_type"] == 1 and isinstance(fields.get("armed"), bool)
                         and isinstance(fields.get("flying"), bool))
            else:
                valid = (valid and isinstance(event.get("child_frame_id"), str)
                         and bool(event["child_frame_id"]) and bool(header.get("frame_id")))
                fields = event.get("odometry_fields", "absent")
                if start and start.get("schema") == FIELDS_SCHEMA:
                    structural, nulls = _odometry_fields(fields)
                    if not structural:
                        issue(line, "invalid_odometry_fields")
                    valid = valid and structural and not nulls  # non-finite values are kept, never usable
                elif fields != "absent":
                    issue(line, "odometry_fields_outside_schema_3")
            if not isinstance(event.get("incomplete"), bool):
                valid = False
            if not valid or event.get("incomplete") is not False:
                incomplete += 1
                issue(line, "incomplete_sample")
            summary = summaries[topic]
            sample = {"line": line, "receipt": received, "header": header,
                      "child_frame_id": event.get("child_frame_id"),
                      "incomplete": event.get("incomplete"),
                      "odometry_fields": event.get("odometry_fields"),
                      "message_publisher_gid": gid,
                      "message_gid_state": event.get("message_gid_state"),
                      "message_gid_source": event.get("message_gid_source"),
                      "rmw_implementation_identifier": event.get("rmw_implementation_identifier"),
                      "from_intra_process": event.get("from_intra_process"),
                      "graph_candidates_separate": graph}
            if summary["samples"]:
                prior = summary["samples"][-1]
                # Scope GID comparisons by implementation; report changes, not their cause.
                if (gid, sample["rmw_implementation_identifier"]) != (prior["message_publisher_gid"], prior["rmw_implementation_identifier"]):
                    summary["gid_changes"].append(line)
                old = prior.get("header")
                oldstamp = old.get("stamp") if isinstance(old, dict) else None
                if stamp_ok and isinstance(oldstamp, dict) and all(_integer(oldstamp.get(k)) for k in ("sec", "nanosec")):
                    if (stamp["sec"], stamp["nanosec"]) < (oldstamp["sec"], oldstamp["nanosec"]):
                        summary["header_regressions"].append(line)
                    elif (stamp["sec"], stamp["nanosec"]) == (oldstamp["sec"], oldstamp["nanosec"]):
                        summary["header_repeats"].append(line)
                # Reported, never explained or normalized: a frame change is not a frame validation.
                if ((old or {}).get("frame_id") if isinstance(old, dict) else None,
                        prior.get("child_frame_id")) != (header.get("frame_id") if isinstance(header, dict) else None,
                                                         event.get("child_frame_id")):
                    summary["frame_changes"].append(line)
            if _receipt(received):
                if previous_global is not None and received["steady_ns"] < previous_global:
                    summary["receipt_regressions"].append(line)
                    issue(line, "monotonic_receipt_regression")
                previous_global = received["steady_ns"]
            summary["samples"].append(sample)
        elif kind == "discovery":
            if not _reserved(start) or end is not None:
                issue(line, "discovery_out_of_order")
            if (event.get("topic") not in tuple(TOPICS)
                    or event.get("state") not in ("OBSERVED", "UNKNOWN")
                    or event.get("source") != "Node.get_publishers_info_by_topic"
                    or not isinstance(event.get("candidates"), list)
                    or not all(_candidate(c) for c in event.get("candidates", []))
                    or (event.get("state") == "OBSERVED" and not _receipt(event.get("receipt")))):
                issue(line, "invalid_discovery")
            discoveries.append({"line": line, "observation": event})
        elif kind == "end":
            if start is None or end is not None:
                issue(line, "end_out_of_order")
            end = event
            if events[-1][0] != line:
                issue(line, "records_after_end")
        else:
            issue(line, "unknown_event")
    if start is None:
        issue(None, "missing_start")
    if end is None:
        issue(None, "missing_end")
    both = all(v["samples"] for v in summaries.values())
    if start and _integer(start.get("max_samples")) and count > start["max_samples"]:
        issue(None, "sample_limit_exceeded")
    if end:
        if (not _integer(end.get("samples")) or end["samples"] != count
                or not _integer(end.get("incomplete_samples")) or end["incomplete_samples"] != incomplete
                or end.get("data_present_both_streams") is not bool(both)
                or end.get("capture_complete", "missing") is not None
                or end.get("termination") not in ("SAMPLE_LIMIT", "DURATION_LIMIT", "INTERRUPTED")):
            issue(None, "contradictory_footer")
        if end.get("termination") == "SAMPLE_LIMIT" and start and count != start.get("max_samples"):
            issue(None, "contradictory_sample_limit")
    quota = {"status": None, "odometry": None}
    if _reserved(start) and end:
        for key in quota:
            value = end.get("omitted_" + key + "_quota")
            if not _integer(value) or value < 0:
                issue(None, "invalid_quota_counter")
            else:
                quota[key] = value
                if receipt is not None and (not isinstance(receipt, dict)
                        or not _integer(receipt.get("omitted_" + key + "_quota"))
                        or receipt["omitted_" + key + "_quota"] != value):
                    issue(None, "quota_receipt_mismatch")
    for summary in summaries.values():
        samples = summary["samples"]
        receipts = [s["receipt"]["steady_ns"] for s in samples if _receipt(s["receipt"])]
        summary.update(count=len(samples),
                       first_receipt_steady_ns=receipts[0] if receipts else None,
                       last_receipt_steady_ns=receipts[-1] if receipts else None,
                       receipt_span_ns=receipts[-1] - receipts[0] if receipts else None)
    complete_data = bool(end and end.get("termination") != "INTERRUPTED" and both and not incomplete)
    confirmed = False
    if receipt is not None:
        confirmed = (isinstance(receipt, dict) and receipt.get("status") == "BLOCKED"
                     and receipt.get("source_association_verified") is False
                     and receipt.get("movement_authorized") is False
                     and receipt.get("capture_state") == "DATA_RECORDED"
                     and receipt.get("capture_complete") is True
                     and _integer(receipt.get("samples")) and receipt["samples"] == count
                     and end is not None and receipt.get("termination") == end.get("termination")
                     and _integer(returncode) and returncode == 0 and complete_data and not issues)
        if not confirmed:
            issue(None, "completion_not_confirmed")
    return {"schema": "tfg.rover.passive-analysis/1", "status": "BLOCKED",
            "source_association_verified": False, "movement_authorized": False,
            "journal_sha256": hashlib.sha256(data).hexdigest(), "samples": count,
            "start": start, "end": end, "string_encoding": "byte_escape_u00",
            "incomplete_samples": incomplete, "discoveries_separate": discoveries, "omitted_by_quota": quota, "topics": summaries, "issues": issues,
            "journal_structure_valid": not issues, "footer_present": end is not None,
            "record_bytes": {"journal": len(data), "max_record": max(record_bytes, default=0),
                             "proposed_max_record_not_enforced": PROPOSED_MAX_RECORD_BYTES},
            "completion": "DATA_RECORDED" if confirmed else "UNCERTAIN",
            "note": "Receipt and rc must be captured from this same invocation externally; no identity accreditation."}


def _describe(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {"n": len(values), "min": min(values), "max": max(values), "mean": statistics.fmean(values),
            "pstdev": statistics.pstdev(values) if len(values) > 1 else None}


def _intervals(values):
    gaps = [b - a for a, b in zip(values, values[1:])]
    return None if not gaps else {"n": len(gaps), "min": min(gaps), "max": max(gaps),
                                  "median": statistics.median(gaps)}


def _rpy_deg(q):
    """Roll, pitch, yaw (degrees) of a quaternion AS RECEIVED; a change of representation, not a frame check."""
    x, y, z, w = (q[k] for k in "xyzw")
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return tuple(math.degrees(a) for a in (roll, pitch, yaw))


def odometry_summary(report: dict) -> dict:
    """Descriptive statistics of RETAINED /rover1/odometry samples, one group per (GID, rmw, frame_id,
    child_frame_id): sources are never merged. Header stamps (message clock) and receipts (steady clock) are
    summarized separately. Covariances are reported as declared; zero is NOT certainty. Nothing here accredits
    identity, a model, a frame transformation, stopping or arrival, and a limited/selected capture says nothing
    about the complete stream's rate, loss or jitter."""
    start, end = report.get("start") or {}, report.get("end") or {}
    samples = report["topics"]["/rover1/odometry"]["samples"]
    quota = report.get("omitted_by_quota") or {}
    # The collector is ALWAYS selective: best-effort KeepLast(5) subscription, one callback per spin and a graph
    # query per sample, with uncounted drops. Limits and quotas add further selection.
    selection = ["best_effort KeepLast(5) subscription; dropped messages are not counted",
                 "one callback handled per spin, with a graph query per sample"]
    if end.get("termination") in ("SAMPLE_LIMIT", "INTERRUPTED"):
        selection.append(f"termination {end.get('termination')}")
    if quota.get("odometry"):
        selection.append(f"{quota['odometry']} odometry samples omitted by quota")
    groups = {}
    for sample in samples:
        header = sample.get("header") or {}
        key = (sample.get("message_publisher_gid"), sample.get("rmw_implementation_identifier"),
               header.get("frame_id"), sample.get("child_frame_id"))
        groups.setdefault(key, []).append(sample)
    out = []
    for (gid, rmw, frame, child), members in groups.items():
        usable = [s for s in members if s.get("incomplete") is False and isinstance(s.get("odometry_fields"), dict)]
        fields = [s["odometry_fields"] for s in usable]
        stamps = [s["header"]["stamp"]["sec"] * 10**9 + s["header"]["stamp"]["nanosec"] for s in members
                  if isinstance((s.get("header") or {}).get("stamp"), dict)]
        receipts = [s["receipt"]["steady_ns"] for s in members if isinstance(s.get("receipt"), dict)]
        diagonals = [[f[part]["covariance"][i] for i in (0, 7, 14, 21, 28, 35)]
                     for f in fields for part in ("pose", "twist")]
        group = {"message_publisher_gid": gid, "rmw_implementation_identifier": rmw, "frame_id": frame,
                 "child_frame_id": child, "retained_samples": len(members), "complete_with_fields": len(usable),
                 "incomplete": sum(s.get("incomplete") is not False for s in members),
                 "with_nonfinite": sum(bool((s.get("odometry_fields") or {}).get("nonfinite")) for s in members),
                 "header_stamp_interval_ns": _intervals(stamps),
                 "covered_header_span_ns": stamps[-1] - stamps[0] if len(stamps) > 1 else None,
                 "covered_receipt_span_ns": receipts[-1] - receipts[0] if len(receipts) > 1 else None,
                 "header_stamp_repeats_or_regressions": sum(b <= a for a, b in zip(stamps, stamps[1:])),
                 "receipt_interval_steady_ns": _intervals(receipts)}
        if fields:
            group["position_m_as_received"] = {axis: _describe([f["pose"]["position"][axis] for f in fields])
                                               for axis in "xyz"}
            group["orientation_quaternion_as_received"] = {k: _describe([f["pose"]["orientation"][k] for f in fields])
                                                          for k in "xyzw"}
            group["orientation_rpy_deg_from_quaternion"] = {k: _describe([_rpy_deg(f["pose"]["orientation"])[i]
                                                                       for f in fields])
                                                            for i, k in enumerate(("roll", "pitch", "yaw"))}
            group["linear_speed_norm"] = _describe([math.sqrt(sum(f["twist"]["linear"][a] ** 2 for a in "xyz"))
                                                    for f in fields])
            group["angular_rate_norm"] = _describe([math.sqrt(sum(f["twist"]["angular"][a] ** 2 for a in "xyz"))
                                                    for f in fields])
            group["declared_covariance_diagonal"] = _describe([v for d in diagonals for v in d])
            group["all_zero_declared_covariances"] = sum(all(v == 0 for v in f[part]["covariance"])
                                                         for f in fields for part in ("pose", "twist"))
        else:
            group["fields"] = "NOT_RECORDED (schema " + str(start.get("schema")) + ")" if start.get(
                "schema") != FIELDS_SCHEMA else "NO_COMPLETE_SAMPLE"
        out.append(group)
    return {"schema": "tfg.rover.odometry-summary/1", "status": "BLOCKED", "movement_authorized": False,
            "source_association_verified": False, "capture_schema": start.get("schema"),
            "sampling_policy": start.get("sampling_policy"), "max_samples": start.get("max_samples"),
            "termination": end.get("termination"), "omitted_odometry_by_quota": quota.get("odometry"),
            "capture_selection": selection, "groups": out, "sources_merged": False,
            "limits": ["retained samples only; the complete stream's rate, loss and jitter are NOT inferable",
                       "header-stamp and receipt intervals differ in meaning (message clock vs steady receipt); "
                       "their difference is not attributed to any cause and yields no real-time factor",
                       "positions/velocities in the message's own frames; frames and units NOT validated",
                       "declared covariance zero is not certainty",
                       "small reported speeds come from the same source and are not independent proof of physical rest",
                       "no identity, model, transformation, stop or arrival"],
            "r1_reportable": ["rest dispersion of position/orientation per group", "residual linear/angular speed",
                              "header-stamp and receipt intervals (separately)", "frame-name stability",
                              "declared covariances"],
            "r1_pending": ["approval of arrival tolerance and stop thresholds", "verified frame transformation",
                           "publisher/model/SYSID association", "complete-stream rate and loss",
                           "arrival, dwell and progress (need a movement trial)"]}


# R1 parameters a finished /3 capture at rest can CONTRAST (never approve), and what needs a wider design.
R1_CONTRASTABLE = {
    "arrival_tolerance_m": "position dispersion at rest per group (compare with the proposed tolerance)",
    "stopped_linear_mps / stopped_angular_rad_s": "residual speeds at rest (compare with the stop thresholds)",
    "max_sample_gap_s": "receipt intervals of RETAINED samples (a lower bound on gaps, not the stream's loss)",
}
R1_NEEDS_WIDER_DESIGN = [
    "complete-stream rate, loss and jitter (the collector is selective and capped at 20 samples in reserve mode)",
    "dispersion during motion and at the target, progress and dwell (need a movement trial)",
    "frame transformation and physical identity (need the three-vehicle check and the identity chain)",
    "any threshold approval: 20 samples of one session are not a basis for approving R1 parameters",
]


def analyze_capture(trial_root: Path, capture_dir: str) -> dict:
    """Entry for a FINISHED capture: verify the trial manifest (every listed file's size and SHA-256), require the
    capture files (journal, receipt, rc, stderr) to be listed, then receipt + rc + journal through analyze_bytes, and
    only then metrics.
    Refuses rather than analysing anything unverified, still being written, or incomplete."""
    refused = {"status": "REFUSED", "movement_authorized": False, "source_association_verified": False}
    trial_root = Path(trial_root)
    try:
        manifest = json.loads((trial_root / "manifest.json").read_text(encoding="utf-8"))
        listed = {entry["path"]: entry for entry in manifest["files"]}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {**refused, "reasons": [f"MANIFEST_UNREADABLE: {type(exc).__name__}"]}
    reasons = []
    for rel, entry in listed.items():
        path = trial_root / rel
        if (not path.is_file() or path.is_symlink() or path.stat().st_size != entry["size_bytes"]
                or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]):
            reasons.append(f"MANIFEST_MISMATCH: {rel}")
    names = {name: f"{capture_dir.rstrip('/')}/{name}" for name in ("journal.jsonl", "receipt.json", "stderr.txt")}
    # The rc is recorded either as plain text or as {"rc": int, ...}; exactly one listed form is accepted.
    rc_files = [f"{capture_dir.rstrip('/')}/{n}" for n in ("return_code.txt", "return_code.json")]
    listed_rc = [rel for rel in rc_files if rel in listed]
    reasons += [f"NOT_IN_MANIFEST: {rel}" for rel in names.values() if rel not in listed]
    if len(listed_rc) != 1:
        reasons.append("NOT_IN_MANIFEST: exactly one of " + ", ".join(rc_files))
    if reasons:
        return {**refused, "reasons": reasons}
    try:
        receipt = json.loads((trial_root / names["receipt.json"]).read_text(encoding="utf-8"))
        raw_rc = (trial_root / listed_rc[0]).read_text(encoding="utf-8").strip()
        if listed_rc[0].endswith(".json"):
            rc_record = json.loads(raw_rc)
            if not isinstance(rc_record, dict) or not _integer(rc_record.get("rc")) or rc_record.get("timeout_uncertain"):
                raise ValueError("rc record")
            returncode = rc_record["rc"]
        else:
            returncode = int(raw_rc)
    except (OSError, ValueError) as exc:
        return {**refused, "reasons": [f"RECEIPT_OR_RC_UNREADABLE: {type(exc).__name__}"]}
    report = analyze_bytes((trial_root / names["journal.jsonl"]).read_bytes(), receipt=receipt, returncode=returncode)
    if report["completion"] != "DATA_RECORDED" or report["issues"]:
        return {**refused, "reasons": ["CAPTURE_NOT_CONFIRMED_COMPLETE"], "issues": report["issues"],
                "journal_sha256": report["journal_sha256"]}
    summary = odometry_summary(report)
    stderr = (trial_root / names["stderr.txt"]).read_bytes()
    # Completion rests on separate evidences: the collector's footer never self-certifies (null), the external
    # receipt of the same invocation says complete, the process rc is 0, and both streams carried data.
    completion_evidence = {"footer_capture_complete": report["end"]["capture_complete"],
                           "receipt_capture_complete": receipt["capture_complete"], "returncode": returncode,
                           "data_present_both_streams": report["end"]["data_present_both_streams"],
                           "termination": report["end"]["termination"],
                           "stderr_bytes": len(stderr), "stderr_sha256": hashlib.sha256(stderr).hexdigest()}
    return {"status": "ANALYZED", "movement_authorized": False, "source_association_verified": False,
            "trial_manifest_sha256": hashlib.sha256((trial_root / "manifest.json").read_bytes()).hexdigest(),
            "completion_evidence": completion_evidence,
            "samples_per_topic": {topic: data["count"] for topic, data in report["topics"].items()},
            "journal_sha256": report["journal_sha256"], "capture_schema": summary["capture_schema"],
            "pose_fields_present": summary["capture_schema"] == FIELDS_SCHEMA, "odometry": summary,
            "r1_contrastable": R1_CONTRASTABLE if summary["capture_schema"] == FIELDS_SCHEMA else {},
            "r1_needs_wider_design": R1_NEEDS_WIDER_DESIGN,
            "note": "Metrics describe retained samples of one session; no identity, transformation or approval."}


def _fmt(stat, unit="", scale=1.0, digits=7):
    if not stat:
        return "—"
    spread = "" if stat["pstdev"] is None else f"; desv. típ. {stat['pstdev'] * scale:.{digits}g}{unit}"
    return (f"{stat['min'] * scale:.{digits}g}{unit} a {stat['max'] * scale:.{digits}g}{unit} "
            f"(media {stat['mean'] * scale:.{digits}g}{unit}{spread}; n={stat['n']})")


def render_capture_markdown(result: dict) -> str:
    """Deterministic report of an analyze_capture result. Observations of retained samples only; it accredits no
    identity, transformation, stop, arrival or threshold."""
    if result.get("status") != "ANALYZED":
        return "# Captura pasiva: REFUSED\n\n" + "\n".join(f"- {r}" for r in result.get("reasons", [])) + "\n"
    odometry, evidence = result["odometry"], result["completion_evidence"]
    lines = ["# Captura pasiva: observaciones descriptivas", "",
             "Estado: `ANALYZED` (`movement_authorized: false`, `source_association_verified: false`).", "",
             "## Verificación", "",
             f"- Manifiesto del ensayo: `{result['trial_manifest_sha256']}` (todos los archivos listados: tamaño y SHA-256)",
             f"- Diario: `{result['journal_sha256']}`, esquema `{result['capture_schema']}`",
             f"- Footer del colector `capture_complete`: `{json.dumps(evidence['footer_capture_complete'])}` "
             "(el colector nunca se autocertifica)",
             f"- Recibo externo `capture_complete`: `{json.dumps(evidence['receipt_capture_complete'])}`",
             f"- Retorno: `{evidence['returncode']}`; datos en ambos streams: "
             f"`{json.dumps(evidence['data_present_both_streams'])}`; terminación `{evidence['termination']}`",
             f"- stderr: {evidence['stderr_bytes']} bytes (`{evidence['stderr_sha256']}`)", "",
             "- Muestras por topic: " + ", ".join(f"`{k}` {v}" for k, v in result["samples_per_topic"].items()),
             "", "## Selección", ""]
    lines += [f"- {item}" for item in odometry["capture_selection"]]
    lines += [f"- máximo de muestras {odometry['max_samples']}, política `{odometry['sampling_policy']}`", ""]
    for n, g in enumerate(odometry["groups"], 1):
        hdr, rcv = g["header_stamp_interval_ns"] or {}, g["receipt_interval_steady_ns"] or {}
        lines += [f"## Fuente {n}", "",
                  f"- GID `{g['message_publisher_gid']}`, rmw `{g['rmw_implementation_identifier']}`",
                  f"- Marcos: `{g['frame_id']}` → `{g['child_frame_id']}`",
                  f"- Muestras retenidas {g['retained_samples']}; completas con campos {g['complete_with_fields']}; "
                  f"incompletas {g['incomplete']}; con no finitos {g['with_nonfinite']}"]
        if "position_m_as_received" in g:
            lines += [f"- Posición {axis} (m): {_fmt(g['position_m_as_received'][axis], digits=8)}" for axis in "xyz"]
            lines += [f"- Cuaternión {k}: {_fmt(g['orientation_quaternion_as_received'][k], digits=6)}" for k in "xyzw"]
            lines += [f"- {k} (°, conversión del cuaternión recibido): "
                      f"{_fmt(g['orientation_rpy_deg_from_quaternion'][k], digits=5)}" for k in ("roll", "pitch", "yaw")]
            lines += [f"- Norma de velocidad lineal (m/s): {_fmt(g['linear_speed_norm'], digits=4)}",
                      f"- Norma de velocidad angular (rad/s): {_fmt(g['angular_rate_norm'], digits=4)}",
                      f"- Covarianzas declaradas todas cero: {g['all_zero_declared_covariances']} matrices; diagonal "
                      f"{_fmt(g['declared_covariance_diagonal'], digits=4)} (cero declarado **no** es certeza)"]
        else:
            lines.append(f"- Campos: {g.get('fields')}")
        lines += [f"- Sellos de cabecera (reloj del mensaje): intervalo mediano {hdr.get('median', 0) / 1e6:g} ms, "
                  f"cubren {(g['covered_header_span_ns'] or 0) / 1e9:g} s; repeticiones o regresiones "
                  f"{g['header_stamp_repeats_or_regressions']}",
                  f"- Recepción (reloj monotónico): intervalo mediano {rcv.get('median', 0) / 1e6:.4g} ms, máximo "
                  f"{rcv.get('max', 0) / 1e6:.5g} ms, cubre {(g['covered_receipt_span_ns'] or 0) / 1e9:.4g} s", ""]
    lines += ["## Límites", ""] + [f"- {item}" for item in odometry["limits"]]
    lines += ["", "## Contrastable con la propuesta de R1 (no aprueba nada)", ""]
    lines += [f"- `{k}`: {v}" for k, v in result["r1_contrastable"].items()]
    lines += ["", "## Requiere un diseño más amplio", ""] + [f"- {item}" for item in result["r1_needs_wider_design"]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("journal", type=Path, nargs="?")
    parser.add_argument("--correlate-capture", type=Path,
                        help="offline manifested archive -> historical source-chain matrix (no ROS)")
    parser.add_argument("--receipt", type=Path, help="final stdout JSON from the same invocation")
    parser.add_argument("--returncode", type=int)
    parser.add_argument("--odometry", action="store_true", help="print the descriptive odometry summary instead")
    parser.add_argument("--trial-root", type=Path, help="finished trial with manifest.json (use with --capture-dir)")
    parser.add_argument("--capture-dir", help="capture directory relative to --trial-root")
    parser.add_argument("--markdown", action="store_true", help="with --trial-root: deterministic markdown report")
    args = parser.parse_args(argv)
    if args.correlate_capture:
        if args.journal or args.receipt or args.returncode is not None:
            parser.error("--correlate-capture is exclusive with journal/receipt/returncode")
        from tools.rover_identity_inventory import correlate_capture
        report = correlate_capture(args.correlate_capture)
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return 2 if report["evidence_valid"] else 1  # partial historical chain never a permit
    if args.trial_root is not None:
        result = analyze_capture(args.trial_root, args.capture_dir or "")
        print(render_capture_markdown(result) if args.markdown else json.dumps(result, indent=2, ensure_ascii=True),
              end="" if args.markdown else "\n")
        return 0 if result["status"] == "ANALYZED" else 2
    if args.journal is None:
        parser.error("journal or --correlate-capture is required")
    report = analyze_bytes(args.journal.read_bytes(),
                           receipt=json.loads(args.receipt.read_bytes()) if args.receipt else None,
                           returncode=args.returncode)
    if args.odometry:
        print(json.dumps(odometry_summary(report), indent=2, ensure_ascii=True))
        return 0
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0 if report["completion"] == "DATA_RECORDED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
