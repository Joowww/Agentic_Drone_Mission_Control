"""Local summary of Hermes capture JSONL (tfg.hermes.capture/3) to compare models. Offline only.

Groups by experiment (``run_id``), ``case_id`` and model (``provider/model``) from metadata only;
no prompt or response is needed or read. Validation and provenance are the exporters' rules
(``observability.langsmith_export``): only traces declared captured with verified sink records
enter the comparative results by default; synthetic and unknown-provenance data are counted as
excluded and, on request, shown in a separate non-comparative section.

Token rules: per field, normalized provider counters (``nonzero_normalized``), received zeros
that Hermes cannot confirm (``zero_unconfirmed``), absent and redacted values are counted
separately; an absent value is never a zero. Derived sums (``prompt_tokens``, ``total_tokens``)
are reported on their own and never added to the component counters. Latency uses only
Hermes-measured intervals (both epochs, end >= start, consistent with ``api_duration_s``).
No cost is computed: no tariffs are declared.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import statistics
import sys

from observability import langsmith_export as common
from observability.hermes_capture import capture
from observability.langsmith_export import ExportError

SUMMARY_VERSION = "1"
COMPARATIVE_KINDS = ("captured_hermes_metadata",)


def _trace_key(event):
    if event["turn_ref"] is None:
        return ("event", event["event_id"])
    return ("turn", event["run_id"], event["session_ref"], event["turn_ref"])


def classify(events, provenance=None, provenance_check=None):
    """Attach each event to its trace's provenance kind, exactly as the exporters decide it."""
    if provenance not in (None, "synthetic", "captured"):
        raise ExportError("provenance must be 'synthetic' or 'captured'")
    if provenance == "captured" and not (provenance_check and provenance_check["ok"]):
        raise ExportError("declared captured, but the capture provenance records do not verify")
    groups = {}
    for event in events:
        groups.setdefault(_trace_key(event), []).append(event)
    kinds = {}
    for members in groups.values():
        origin = common._trace_provenance(members, provenance, provenance_check)
        for event in members:
            kinds[event["event_id"]] = origin["kind"]
    return kinds


def _stats(values):
    if not values:
        return None
    ordered = sorted(values)
    return {"n": len(ordered), "min": ordered[0], "median": statistics.median(ordered),
            "mean": statistics.fmean(ordered), "max": ordered[-1], "sum": sum(ordered)}


def _measured_latency(event):
    """Hermes wall-clock interval of one API call (including retries), or a reason it is unusable."""
    start, end, duration = event.get("started_at_epoch_s"), event.get("ended_at_epoch_s"), event.get("api_duration_s")
    if start is None or end is None:
        return None, "epochs_absent"
    if end < start:
        return None, "end_before_start"
    if duration is not None and abs((end - start) - duration) > common.DURATION_TOLERANCE_S:
        return None, "inconsistent_with_api_duration"
    return end - start, None


def _token_field_summary(records, field, derived):
    statuses, values = Counter(), {"nonzero": [], "received_including_unconfirmed_zeros": []}
    for usage in records:
        entry = usage.get(field) if usage else None
        status = entry["status"] if entry else "usage_absent"
        statuses[status] += 1
        if status in ("nonzero_normalized", "derived_nonzero"):
            values["nonzero"].append(entry["value"])
            values["received_including_unconfirmed_zeros"].append(entry["value"])
        elif status in ("zero_unconfirmed", "derived_zero"):
            values["received_including_unconfirmed_zeros"].append(0)
    return {
        "kind": "derived_sum_computed_by_hermes" if derived else "hermes_normalized_provider_counter",
        "status_counts": dict(sorted(statuses.items())),
        "nonzero_values": _stats(values["nonzero"]),
        # Zeros are received but unconfirmed; this view is a bound, not a measurement of zero.
        "received_values_including_unconfirmed_zeros": _stats(values["received_including_unconfirmed_zeros"]),
        "absent_or_redacted": statuses["absent"] + statuses["redacted"] + statuses["usage_absent"],
    }


def _summarize_group(events):
    calls = [e for e in events if e["event_type"] == "llm_call"]
    errors = [e for e in events if e["event_type"] == "llm_error"]
    usages = [e.get("usage") for e in calls]
    latencies, latency_issues = [], Counter()
    for event in calls:
        value, issue = _measured_latency(event)
        if value is None:
            latency_issues[issue] += 1
        else:
            latencies.append(value)
    first_chunk = [e["first_chunk_offset_s"] for e in calls if e.get("first_chunk_offset_s") is not None]
    error_requests = {e["api_request_ref"] for e in errors if e.get("api_request_ref")}
    return {
        "sample_size": {"llm_calls": len(calls), "llm_errors": len(errors),
                        "calls_with_usage": sum(u is not None for u in usages),
                        "calls_without_usage": sum(u is None for u in usages),
                        "calls_with_measured_latency": len(latencies),
                        "calls_without_measured_latency": sum(latency_issues.values())},
        "failures": {"llm_error_count": len(errors),
                     "error_types": dict(sorted(Counter(e.get("error_type") or "unknown" for e in errors).items())),
                     "status_codes": dict(sorted(Counter(str(e.get("status_code")) for e in errors).items())),
                     "calls_sharing_api_request_with_an_error": sum(e.get("api_request_ref") in error_requests
                                                                     for e in calls if e.get("api_request_ref"))},
        "tokens": {
            "normalized_counters": {f: _token_field_summary(usages, f, False) for f in capture.NORMALIZED_USAGE_FIELDS},
            "derived_sums_not_additive_with_counters": {f: _token_field_summary(usages, f, True)
                                                        for f in capture.DERIVED_USAGE_FIELDS},
            "semantics": "Hermes-normalised summaries, not raw provider usage",
        },
        "latency_s": {"stats": _stats(latencies), "excluded": dict(sorted(latency_issues.items())),
                      "basis": "hermes_hook_wall_clock", "scope": "api_call_from_first_attempt (includes retries)"},
        "first_chunk_offset_s": {"stats": _stats(first_chunk),
                                 "caveat": "equals time-to-first-chunk only when the call had no retry"},
        "cost": {"computed": False, "reason": "no declared tariffs"},
    }


def _summarize_tools(events):
    measured = [e["duration_ms_measured"] for e in events if e.get("duration_ms_measured") is not None]
    return {"tool_calls": len(events),
            "status_counts": dict(sorted(Counter(e.get("status") or "absent" for e in events).items())),
            "duration_source_counts": dict(sorted(Counter(e.get("duration_source") for e in events).items())),
            "measured_duration_ms": _stats(measured),
            "note": "only duration_source=hermes_reported_ms counts as measured; 0 and timeout values are not"}


def summarize(events, kinds, *, include_noncomparative=False):
    sections = {"comparative": [e for e in events if kinds[e["event_id"]] in COMPARATIVE_KINDS]}
    excluded = Counter(kinds[e["event_id"]] for e in events if kinds[e["event_id"]] not in COMPARATIVE_KINDS)
    if include_noncomparative:
        sections["non_comparative_synthetic_or_unknown"] = [e for e in events
                                                            if kinds[e["event_id"]] not in COMPARATIVE_KINDS]
    report = {"summary_version": SUMMARY_VERSION, "events_read": len(events),
              "excluded_from_comparison": dict(sorted(excluded.items())),
              "comparative_kinds": list(COMPARATIVE_KINDS)}
    for name, subset in sections.items():
        models, tools = {}, {}
        for event in subset:
            experiment, case = event.get("run_id") or "(none)", event.get("case_id") or "(none)"
            if event["event_type"] == "tool_call":
                tools.setdefault((experiment, case), []).append(event)
                continue
            model = f"{event.get('provider') or '(absent)'}/{event.get('model') or '(absent)'}"
            models.setdefault((experiment, case, model), []).append(event)
        report[name] = {
            "data_kinds": dict(sorted(Counter(kinds[e["event_id"]] for e in subset).items())),
            "groups": [{"experiment": k[0], "case_id": k[1], "model": k[2], **_summarize_group(v)}
                       for k, v in sorted(models.items())],
            "tools": [{"experiment": k[0], "case_id": k[1], **_summarize_tools(v)} for k, v in sorted(tools.items())],
        }
        if name != "comparative":
            report[name]["warning"] = "NOT PERFORMANCE RESULTS: synthetic or unknown-provenance data"
    if not sections["comparative"]:
        report["comparative"]["warning"] = "no captured data with verified provenance: nothing to compare"
    return report


def main(argv=None, *, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", help="capture JSONL files (tfg.hermes.capture/3)")
    parser.add_argument("--provenance", choices=("synthetic", "captured"),
                        help="declare the input's origin; 'captured' also needs verified sink provenance records")
    parser.add_argument("--include-noncomparative", action="store_true",
                        help="also summarise synthetic/unknown data in a separate, clearly labelled section")
    args = parser.parse_args(argv)
    events, errors = common.load_events(args.files)
    check = common.verify_capture_provenance(args.files) if args.provenance == "captured" else None
    kinds = classify(events, args.provenance, check)
    report = summarize(events, kinds, include_noncomparative=args.include_noncomparative)
    report.update(errors=errors, provenance_check=check)
    json.dump(report, out, indent=2, ensure_ascii=False)
    out.write("\n")
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ExportError as exc:
        print(f"capture_summary: {exc}", file=sys.stderr)
        sys.exit(2)
