"""Facts of the closed rover identity session 1cb9d86a (REAL, the rover's evidence, read-only): manifest-verified,
reported per fact with scope, never a gate, never joined with another session."""
import json
from pathlib import Path
import shutil

import pytest

from reporting import agri_scenario_summary as summary
from reporting.rover_identity_facts import BOTH, POI_ONLY, identity_facts

ROOT = Path(__file__).resolve().parents[1]
TRIAL = ROOT / "simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f"
MANIFEST_SHA = "4d9558a2e31b9ea2ec42eca6d8b18cc007ce2cf4049bab011fa561ad59e34faf"
VIEW = ROOT / "evaluation/observability/agri_scenario_view_h2_2026_10_24/scenario_view.json"
pytestmark = pytest.mark.skipif(not TRIAL.is_dir(), reason="the rover's identity trial is not present here")


@pytest.fixture(scope="module")
def facts():
    return identity_facts(TRIAL)


def test_real_session_is_manifest_verified_and_reports_each_fact_separately(facts):
    assert facts["status"] == "OBSERVED" and facts["manifest_sha256"] == MANIFEST_SHA
    assert facts["files_verified"] == 164 and facts["identity_complete"] is False
    states = {f["id"]: f["state"] for f in facts["facts"]}
    assert states == {"odometry_to_bridge": "OBSERVED", "plugin_to_entity": "OBSERVED",
                      "parameters": "RECEIVED_ATTRIBUTION_PENDING", "fdm_receiver": "NOT_ACCREDITED",
                      "odometry_to_model": "UNKNOWN", "frames": "NOT_ACCREDITED",
                      "reception": "CLOSED_PARTIAL_COVERAGE", "monitor": "INCOMPLETE", "lifecycle_stop": "SUCCESS"}
    by_id = {f["id"]: f for f in facts["facts"]}
    assert "entidad 67 («rover1»" in by_id["plugin_to_entity"]["detail"]
    assert "127.0.0.1:60575" in by_id["fdm_receiver"]["detail"]
    assert "14 muestras retenidas de 20; 6/9 streams" in by_id["reception"]["detail"]
    assert "rc 1" in by_id["monitor"]["detail"] and by_id["lifecycle_stop"]["state"] == "SUCCESS"


def test_only_the_target_transform_is_exclusive_to_poi_a1(facts):
    scopes = {f["id"]: f["scope"] for f in facts["facts"]}
    assert scopes.pop("frames") == POI_ONLY and set(scopes.values()) == {BOTH}


def test_unverifiable_sessions_are_not_available(tmp_path):
    assert identity_facts(tmp_path / "absent")["status"] == "NOT_AVAILABLE"
    copy = tmp_path / "trial"
    shutil.copytree(TRIAL, copy)
    receipt = copy / "reader/journal.jsonl.receipt.json"
    receipt.write_text(receipt.read_text().replace("true", "false"))
    result = identity_facts(copy)
    assert result["status"] == "NOT_AVAILABLE" and "reader/journal.jsonl.receipt.json" in result["reason"]


def test_identity_facts_never_change_the_candidate_its_hash_stages_or_blockers(facts):
    view = json.loads(VIEW.read_text())
    from tests.test_agri_scenario import DOUBLE_INPUTS
    for inputs in (None, DOUBLE_INPUTS):
        kwargs = dict(inputs=inputs, executor_facts={"kind": "TEST", "policy_enabled": False,
                                                     "navigation_request_supported": True})
        without, with_facts = summary.prepare_ground_task(view, **kwargs), summary.prepare_ground_task(
            view, identity=facts, **kwargs)
        for key in ("candidate", "candidate_sha256", "stages", "blockers", "eligibility", "missing_data"):
            assert with_facts[key] == without[key], key
        assert with_facts["identity_facts"]["status"] == "OBSERVED"
        assert without["identity_facts"] == {"status": "NOT_PROVIDED"}


def test_report_keeps_identity_session_apart_from_the_3_capture_session(facts):
    from tools.rover_passive_journal import analyze_capture
    capture_root = ROOT / "simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-8fad-457e-918e-253483a2d728"
    if not capture_root.is_dir():
        pytest.skip("optional /3 capture not present")
    capture = {"value": analyze_capture(capture_root, "container-copies/tmp/tfg_rover_xrce_capture/"
                                        "4ac58516-8fad-457e-918e-253483a2d728"), "source": "test"}
    view = json.loads(VIEW.read_text())
    prepared = summary.prepare_ground_task(view, capture=capture, identity=facts,
                                           executor_facts={"kind": "TEST", "policy_enabled": False})
    capture_gids = {g["source"]["message_publisher_gid"] for g in prepared["measured_facts"]["groups"]}
    assert capture_gids.isdisjoint(facts["odometry_gids"])  # different sessions, different publishers
    text = summary.render_ground_report(view, prepared)
    assert text.index("#### Hechos medidos") < text.index("#### Hechos de identidad del rover")
    assert "No son contemporáneos de otras sesiones" in text and "| solo POI_A1 |" in text
