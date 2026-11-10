"""M4/M4b Opik plans are DRY-RUN only: no send path, no credential, separate traces, nothing leaves."""
import json
from pathlib import Path

from multiagent import opik_bridge as ob, opik_pilots as op


def test_the_module_has_no_send_path():
    src = Path(op.__file__).read_text()
    for forbidden in ("send_import", "urlopen", "urllib", "_api_key", "OPIK_API_KEY", "transport", "requests."):
        assert forbidden not in src, forbidden


def test_m4_and_m4b_are_separate_traces_built_from_the_sealed_records(monkeypatch):
    monkeypatch.delenv("OPIK_API_KEY", raising=False)
    p4, p4b = op.plan("m4"), op.plan("m4b")
    assert p4.traces[0]["id"] != p4b.traces[0]["id"]
    assert p4.traces[0]["metadata"]["tfg_pilot"] == "m4_integrated_v1"
    assert p4b.traces[0]["metadata"]["tfg_pilot"] == "m4b_integrated_v1"
    assert p4b.traces[0]["metadata"]["tfg_prompt_ids"]["mission_orchestrator"] == "interpret_brief/3"
    assert [s["metadata"]["tfg_role"] for s in p4.spans] == ["mission_orchestrator", "rover_agent"]
    assert [s["metadata"]["tfg_role"] for s in p4b.spans] == ["mission_orchestrator"]
    assert "DRY_RUN_PREPARED_NOT_AUTHORIZED" in p4b.traces[0]["tags"]
    assert ob.egress_findings(p4) == [] and ob.egress_findings(p4b) == []


def test_the_ledger_keeps_e07_and_has_no_pilot_trace():
    ledger = ob.load_ledger()
    statuses = {v.get("status") for v in ledger["traces"].values()}
    assert "VERIFIED_PRESENT" in statuses
    for pilot in ("m4", "m4b"):
        assert op.plan(pilot).traces[0]["id"] not in ledger["traces"]


def test_m4c_r1_has_one_llm_span_per_real_call_and_its_own_trace():
    p = op.plan("m4c_r1")
    assert [s["metadata"]["tfg_role"] for s in p.spans] == ["mission_orchestrator", "drone_swarm_agent",
                                                            "rover_agent", "rover_agent"]
    assert p.traces[0]["metadata"]["tfg_pilot"] == "m4c_r1_integrated_v1" and ob.egress_findings(p) == []
    assert p.traces[0]["id"] not in {op.plan(x).traces[0]["id"] for x in ("m4", "m4b")}
