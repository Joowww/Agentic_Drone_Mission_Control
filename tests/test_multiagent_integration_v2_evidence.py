"""The integration evidence generator: provenance and the mission-input section (the heavy sections are the same
code the hand-off, battery and scenario tests already exercise)."""
from multiagent.benchmark import integration_v2_evidence as ev
from multiagent import rover_handoff as rh


def test_provenance_names_both_rover_snapshots_and_what_was_not_done():
    from tests.history_requirements import require_commits
    require_commits(rh.ROVER_CONTRACT_COMMIT, rh.REVIEWED["commit"])
    p = ev.provenance()
    assert p["rover_committed"]["commit"] == rh.ROVER_CONTRACT_COMMIT and p["rover_reviewed"]["patch_sha256"] == rh.REVIEWED[
        "patch_sha256"]
    assert len(p["multiagent_commit"]) == 40 and "no LLM call" in p["not_done"] and "no MAVLink" in p["not_done"]


def test_mission_inputs_section_round_trips_a_qgc_plan_and_rejects_a_foreign_site(tmp_path):
    r = ev.mission_inputs(tmp_path / "mi")
    assert r["as_expected"] and r["qgc_plan"]["poi"] == ["POI_1", "POI_3"] and r["foreign_finding"] == "OUTSIDE_SITE_GEOREFERENCE"
    assert (tmp_path / "mi/poi1_poi3.plan").is_file()


def test_the_demo_battery_passes_the_reviewed_snapshot_choice_through(monkeypatch, tmp_path):
    from multiagent import demo, integration_battery as ib
    seen = {}
    monkeypatch.setattr(ib, "run_all", lambda snapshot, reviewed=False: seen.update(reviewed=reviewed) or [])
    assert demo.main(["--battery", "--rover-snapshot", str(tmp_path), "--rover-reviewed"]) == 0
    assert seen == {"reviewed": True}
    assert demo.main(["--battery", "--rover-snapshot", str(tmp_path)]) == 0 and seen == {"reviewed": False}


def test_the_adapter_evidence_records_contracts_topics_and_git_relations(tmp_path):
    from multiagent.benchmark import rover_adapter_evidence as cae
    try:
        cmp = cae.contract_comparison(tmp_path)
    except Exception as exc:  # noqa: BLE001
        import pytest
        pytest.skip(f"rover snapshot unavailable: {exc}")
    assert cmp["committed"]["tag"] == rh.ROVER_CONTRACT_COMMIT and cmp["reviewed"]["tag"].startswith(rh.REVIEWED["commit"])
    assert "schemas/rover-mission-execution-v2.schema.json" in cmp["differing_files"]
    assert cmp["committed"]["adapter_present"] is False and cmp["reviewed"]["adapter_present"] is False
    topics = cae.sitl_topics()
    assert not any(t["status"] in topics["ingestible_statuses"] for t in topics["topics"].values())
    # The integration's genealogy is a fact of its development history (the archive tag once main is consolidated).
    from multiagent import historical_identifiers as hist
    from tests.history_requirements import require_commits
    require_commits(hist.DEVELOPMENT_HISTORY_TAG, *hist.INTEGRATED_BRANCH_TIPS.values())
    history = hist.DEVELOPMENT_HISTORY_TAG
    rel = cae.git_relations(history)
    assert rel[f"feature/hermes-integration ancestor of {history}"]
    assert rel[f"feature/natural-language-qgc-plan ancestor of {history}"]
    assert not rel[f"feature/ardupilot-ros2 ancestor of {history}"]
