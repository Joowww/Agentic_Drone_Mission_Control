"""Runs with the PROJECT .venv: writes dry-run payloads for the SDK harness. Offline, no SDK."""
import json
from pathlib import Path
import sys
import tempfile

repo, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(repo))
from observability import langsmith_export as ls  # noqa: E402
from observability import opik_export as export  # noqa: E402
from tests import test_opik_export as t  # noqa: E402  (fixture helpers only)

out_dir.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    cases = {}
    path = t.capture_with(tmp / "a", t.hermes_like_context(), error=True)
    cases["captured_llm_tool_error"] = t.plan_from(path, provenance="captured")
    cases["unknown_provenance"] = t.plan_from(t.capture_with(tmp / "b", t.hermes_like_context()))
    sink_dir = tmp / "c" / "capture"
    sink = t.capture.register(t.hermes_like_context(), environ={t.capture.ENABLE_ENV: "1",
                                                                t.capture.DIR_ENV: str(sink_dir)})
    sink.on_post_tool_call(**t.tool_kwargs(turn_id="", session_id="", api_request_id="", tool_call_id=""))
    (untimed,) = sink_dir.glob("hermes-events-*.jsonl")
    cases["untimed_included"] = t.plan_from(untimed, provenance="captured", include_untimed=True)
    events, errors = ls.load_events([t.SYNTHETIC_EVIDENCE])  # read-only
    assert errors == []
    cases["synthetic_evidence"] = export.build_plan(events, "tfg-opik")
    for name, plan in cases.items():
        (out_dir / f"{name}.json").write_text(json.dumps(export.describe(plan), indent=1), encoding="utf-8")
        print(name, len(plan.traces), "traces", len(plan.spans), "spans")
