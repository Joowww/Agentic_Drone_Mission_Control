"""The M4c-r1 milestone record: read-only verification of the sealed evidence and the plan-quality checks."""
import json

from multiagent.benchmark import milestone as ms
from multiagent.benchmark import run as bench
from multiagent.historical_identifiers import PILOT_MANIFEST_REGISTRATIONS
from tests.history_requirements import require_commits

R = bench.ROOT / "multiagent/benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9"
RECORD = bench.ROOT / "docs/milestones/m4c_r1_2026-11-07/milestone.json"


def test_the_sealed_evidence_verifies():
    require_commits(PILOT_MANIFEST_REGISTRATIONS["m4c_r1_integrated_v1"])
    v = ms.verify(R)
    assert v["ok"] and set(v["seals"].values()) == {"OK"}
    assert v["manifest_registration_commit"] == "ac92b087f" and v["manifest_equals_registered"]
    assert all(d["prompt_sha256_ok"] and d["reply_sha256_ok"] for d in v["exchange_digests"])


def test_every_plan_quality_check_holds_and_the_validator_not_qwen_resolved_the_conflict():
    checks = {q["check"]: q for q in ms.plan_quality(R)}
    assert all(q["ok"] for q in checks.values()), [k for k, q in checks.items() if not q["ok"]]
    replay = ms.deconfliction_replay(R)
    assert replay["routes_equal_sealed"] and replay["schedule_reproduced"]
    assert replay["conflicts_at_each_smaller_delay"][40.0] > 0 and replay["delayed_vehicle"] == "drone_01"


def test_the_record_has_the_20_items_and_states_what_was_not_recorded():
    rec = ms.record(R)
    assert sum(1 for k in rec if k[:2].isdigit()) == 20
    assert rec["09_tools_invoked"]["rover_agent_phase_a"]["tool_log"].startswith("NOT_RECORDED")
    assert rec["10_tool_results"]["rover_agent_phase_a"]["labelled_replay"]["kind"].startswith("REPLAY")
    assert rec["20_zero_commands"]["result.commands_sent"] == 0 and rec["20_zero_commands"]["physical_effect"] is False
    assert set(rec["18_fallbacks"]["role_outcomes"].values()) == {"MODEL_SUCCESS_FIRST_ROUND"}


def test_the_committed_record_regenerates_identically():
    require_commits(PILOT_MANIFEST_REGISTRATIONS["m4c_r1_integrated_v1"])
    assert json.loads(json.dumps(ms.record(R), sort_keys=True, ensure_ascii=False)) == json.loads(RECORD.read_text())
