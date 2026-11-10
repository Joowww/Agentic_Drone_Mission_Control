"""Descriptive analysis of the pilot evidence (offline; reads saved files only)."""
import hashlib, json, math, sys
from collections import Counter
from pathlib import Path

E = Path("<repo>/evaluation/observability/agri_scenario_pilot_nous_2026_10_24")
VIEW_SHA = "062e774ac10298d329a2bab2f5920dbe60dd22828c83d756abb4f24c6cd2017c"
KEYS = [f"pilot-real-r{i:02d}" for i in range(1, 11)]


def load(p):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(max(0, c - h), 3), round(min(1, c + h), 3)]


def flatten(obj, prefix=""):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}{k}."))
        return out
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        out = {}
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}{i}."))
        return out
    return {prefix[:-1]: obj}


def main():
    log = {}
    if (E / "driver_log.jsonl").exists():
        for line in (E / "driver_log.jsonl").read_text().splitlines():
            r = json.loads(line)
            if "key" in r:
                log[r["key"]] = r
    rows, answers = [], {}
    for key in KEYS:
        d = E / key
        r = log.get(key)
        if not d.exists() and r is None:
            rows.append({"key": key, "attempted": False})
            continue
        run = load(d / "run.json") or {}
        original = load(d / "accept_h3b.json") or {}
        acc = load(d / "accept_h3b_post_fix.json") or original
        summ = (load(d / "capture_summary.json") or {}).get("mcp_tool_trial", {})
        usage = load(d / "native_usage_reviewed.json") or {}
        tools = load(d / "tool_result_as_received.json") or []
        received = [digest(t.get("result")) for t in tools]
        ans = acc.get("answer")
        answers[key] = ans
        rows.append({
            "key": key, "attempted": True,
            "evaluator_crash_original": bool(original.get("error")),
            "post_fix_identical_to_original": (load(d / "accept_h3b_post_fix.json") == original) if (d / "accept_h3b_post_fix.json").exists() else None,
            "started_at_utc": run.get("started_at_utc"), "elapsed_wall_s": run.get("elapsed_wall_s"),
            "return_code": run.get("return_code"), "timed_out": run.get("timed_out"),
            "restore_ok": (run.get("restore") or {}).get("ok"),
            "review_verdict": summ.get("verdict"), "offered": summ.get("offered"),
            "requested_tools": summ.get("requested_tool_names"), "executed": summ.get("executed"),
            "llm_calls": summ.get("llm_calls"), "llm_errors": summ.get("llm_errors"),
            "tool_calls_received": len(tools),
            "view_received_matches_frozen": bool(received) and all(x == VIEW_SHA for x in received),
            "format": (acc.get("factual") or {}).get("parse"),
            "tool_execution": (acc.get("tool_execution") or {}).get("status"),
            "factual_failed": sorted(k for k, v in (acc.get("factual") or {}).items() if k != "parse" and v != "match"),
            "critical_failed": sorted(k for k, v in (acc.get("critical") or {}).items() if v != "match"),
            "classifications": acc.get("classifications"),
            "status": acc.get("status"), "score": acc.get("score"),
            "heuristic_flags": (acc.get("explanation_review") or {}).get("heuristic_flags"),
            "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
            "cache_read_tokens": usage.get("cache_read_tokens"), "reasoning_tokens": usage.get("reasoning_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "total_including_auxiliary": (usage.get("total_including_auxiliary") or {}).get("total_tokens"),
            "api_calls": usage.get("api_calls"),
            "estimated_cost_usd": usage.get("estimated_cost_usd"), "cost_status": usage.get("cost_status"),
            "turn_exit_reason": usage.get("turn_exit_reason"),
            "answer_sha256": digest(ans) if ans is not None else None,
            "structured_sha256": digest({k: v for k, v in ans.items() if k != "explanation"}) if isinstance(ans, dict) else None,
            "explanation_sha256": digest(ans.get("explanation")) if isinstance(ans, dict) else None,
        })
    done = [r for r in rows if r.get("attempted")]
    completed = [r for r in done if r.get("status") is not None]
    flats = {k: flatten({kk: vv for kk, vv in a.items() if kk != "explanation"}) for k, a in answers.items() if isinstance(a, dict)}
    all_fields = sorted(set().union(*flats.values())) if flats else []
    varying = {f: Counter(json.dumps(flats[k].get(f), ensure_ascii=False) for k in flats) for f in all_fields}
    varying = {f: dict(c) for f, c in varying.items() if len(c) > 1}
    statuses = Counter(r.get("status") for r in done)
    critical_fail = [r["key"] for r in done if r.get("critical_failed")]
    n = len(completed)
    k_valid = sum(r["status"] == "STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED" for r in completed)
    tok = [r["total_tokens"] for r in done if r.get("total_tokens")]
    dur = [r["elapsed_wall_s"] for r in done if r.get("elapsed_wall_s") is not None]
    summary = {
        "planned": len(KEYS), "attempted": len(done), "completed_with_acceptance": n,
        "not_attempted": [r["key"] for r in rows if not r.get("attempted")],
        "status_counts": dict(statuses),
        "critical_failure_keys": critical_fail,
        "factual_failure_keys": [r["key"] for r in done if r.get("factual_failed")],
        "structured_validated": k_valid,
        "wilson95_structured_validated": wilson(k_valid, n),
        "interval_note": "Wilson 95% assumes independent, identically distributed invocations; NOT justified here (same prompt prefix, provider-side prompt cache observed, unknown sampling settings). Descriptive only.",
        "fields_varying_across_structured_answers": varying,
        "distinct_structured_answers": len({r["structured_sha256"] for r in completed}),
        "distinct_explanations": len({r["explanation_sha256"] for r in completed}),
        "identical_full_answers": [ks for ks in _groups(completed, "answer_sha256") if len(ks) > 1],
        "views_received_all_match_frozen": all(r.get("view_received_matches_frozen") for r in done),
        "tokens_total": {"min": min(tok), "max": max(tok), "sum": sum(tok)} if tok else None,
        "cache_read_tokens": [r.get("cache_read_tokens") for r in done],
        "elapsed_wall_s": {"min": min(dur), "max": max(dur), "sum": round(sum(dur), 3)} if dur else None,
        "estimated_cost_usd_sum": sum((r.get("estimated_cost_usd") or 0) for r in done),
        "cost_note": "Hermes estimate (cost_status 'estimated', ':free' model); billed cost and quota not accredited",
    }
    out = {"rows": rows, "summary": summary}
    print(json.dumps(out, indent=2, ensure_ascii=False))


def _groups(rows, key):
    g = {}
    for r in rows:
        g.setdefault(r.get(key), []).append(r["key"])
    return list(g.values())


if __name__ == "__main__":
    main()
