"""Offline conversational boundaries: persisted facts, not an evaluation of LLM fidelity."""
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from models.mission_plan_draft import MissionPlanDraft
from planning.draft_provenance import InputAttribution
from planning.mission_artifacts import load_finalization
from planning.relative_routes import RelativeRouteRequest
from planning.artifact_store import sha256
import tools.hermes_mission_planning as planning
import tools.mission_state as state
from tests.test_hermes_mission_planning import complete
from tests.test_relative_routes import rectangle

INCIDENT = "08de7c26-99fc-41b6-8e7f-65722e309152"


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(planning, "DRAFT_ROOT", tmp_path / "drafts")
    import planning.mission_revisions as revisions
    import tools.virtual_preflight_jobs as jobs
    import graph.virtual_preflight_graph as graph
    monkeypatch.setattr(revisions, "REVISION_ROOT", tmp_path / "revisions")
    monkeypatch.setattr(jobs, "RUN_ROOT", tmp_path / "runs")
    doubles = []
    for module, attribute in ((graph, "check_simulation_ready"), (graph, "execute_approved_mission"),
                              (jobs.subprocess, "Popen")):
        double = Mock(side_effect=AssertionError("No infrastructure or flight in draft planning"))
        monkeypatch.setattr(module, attribute, double)
        doubles.append(double)
    yield tmp_path
    for double in doubles:
        double.assert_not_called()


def tree():
    return {str(p): p.read_bytes() for p in planning.DRAFT_ROOT.rglob("*") if p.is_file()}


def partial(name="Parcela Norte"):
    result = planning.update_mission_draft(MissionPlanDraft(name=name,
        geometry_intent=dict(mode="rectangle", length_m=40, width_m=20)))
    assert result["status"] == "INCOMPLETE", result
    return result


def edit(previous, **values):
    return planning.update_mission_draft(MissionPlanDraft(**values), previous["draft_id"], previous["draft_revision"])


def intent(previous, replace_route=False, **values):
    return planning.generate_draft_route(previous["draft_id"], previous["draft_revision"],
                                         RelativeRouteRequest(**values), replace_route)


@pytest.mark.parametrize("name", ["Parcela Norte", "Circuito de prueba", "Rectangular test"])
def test_name_and_dimensions_do_not_imply_other_mission_facts(name):
    result = partial(name)
    assert result["draft_revision"] == result["geometry_revision"] == 1
    assert result["geometry_intent"]["length_m"] == 40
    assert result["geometry_intent"]["width_m"] == 20
    for field, value in result["draft"].items():
        if field not in {"geometry_intent", "name", "waypoints"}:
            assert value is None, (field, value)
    assert result["draft"]["waypoints"] == [] and result["route_provenance"] is None
    assert result["geometry"]["status"] == "INCOMPLETE"
    assert result["provenance_status"] == "UNVERIFIED_AGENT_INPUT"
    assert all(p["source"] == "UNKNOWN" and p["authenticated"] is False
               for p in result["field_provenance"].values())
    defaults = result["compatibility_defaults"]
    assert not any("maximum_altitude" in d["path"] or "objective" in d["path"] for d in defaults)
    assert next(d for d in defaults if d["path"] == "/route/return_to_home")["applies_on_finalization"] is False


def test_partial_recovers_after_reload_and_state_query_is_read_only(monkeypatch):
    saved = partial()
    root = planning.DRAFT_ROOT
    before = tree()
    importlib.reload(planning)
    monkeypatch.setattr(planning, "DRAFT_ROOT", root)
    recovered = state.get_mission_state(draft_id=saved["draft_id"])
    assert recovered["draft"]["geometry_intent"] == saved["geometry_intent"]
    assert recovered["draft"]["geometry_revision"] == 1
    assert recovered["draft"]["draft_revision"] == 1
    assert recovered["pending"]["route_generation"] == saved["geometry_missing_fields"]
    assert tree() == before
    invalid = state.get_mission_state()
    assert invalid["status"] == "ERROR" and invalid["error_code"] == "INVALID_ARGUMENTS"
    assert invalid["lookup_performed"] is False and invalid["inventory_status"] == "UNKNOWN"
    assert tree() == before


def test_home_alone_is_insufficient_and_joint_pending_blocks_finalization():
    first = partial()
    home = edit(first, home_latitude=41, home_longitude=2, home_altitude_m=0)
    assert home["geometry_intent"]["length_m"] == 40
    assert home["geometry_intent"]["width_m"] == 20
    assert set(home["geometry_missing_fields"]) == {
        "orientation_deg", "traversal", "altitude_m", "altitude_reference", "home_position",
        "close_route", "return_to_home"}
    assert home["draft"]["waypoints"] == []
    assert "maximum altitude" in home["mission_missing_fields"]
    assert "geometry.orientation_deg" in home["pending"]["mission_finalization"]
    before = tree()
    result = planning.finalize_mission_draft(home["draft_id"], home["draft_revision"])
    assert result["status"] == "INCOMPLETE" and result["pending"] == home["pending"]
    assert tree() == before and not list(planning.DRAFT_ROOT.rglob("mission.json"))


def test_multi_turn_completion_preserves_dimensions_and_exports_only_when_requested():
    first = partial("Circuito explícito")
    home = edit(first, home_latitude=41, home_longitude=2, home_altitude_m=0)
    shape = intent(home, orientation_deg=90, traversal="counterclockwise", altitude_m=12,
                   altitude_reference="relative_to_home", home_position="center", close_route=False,
                   return_to_home=False)
    assert shape["geometry"]["status"] == "GENERATED" and shape["status"] == "INCOMPLETE"
    assert len(shape["draft"]["waypoints"]) == 4
    assert shape["geometry_intent"]["length_m"] == 40 and shape["geometry_intent"]["width_m"] == 20
    assert shape["draft"]["maximum_altitude_m"] is None
    assert shape["draft"]["return_to_home"] is False
    assert shape["route_provenance"]["source"] == "DETERMINISTIC_GENERATION"
    assert shape["field_provenance"]["/waypoints/WP1/latitude"]["source"] == "DETERMINISTIC_GENERATION"
    assert not list(planning.DRAFT_ROOT.rglob("*.plan"))
    supplied = complete().model_dump(exclude_none=True)
    for key in ("name", "waypoints", "home_latitude", "home_longitude", "home_altitude_m"):
        supplied.pop(key)
    ready = edit(shape, **supplied)
    assert ready["status"] == "COMPLETE" and ready["geometry_revision"] == shape["geometry_revision"]
    assert ready["draft"]["waypoints"] == shape["draft"]["waypoints"]
    final = planning.finalize_mission_draft(ready["draft_id"], ready["draft_revision"])
    assert final["validation"]["execution_status"] == "APPROVED", final
    mission = json.loads(Path(final["mission_path"]).read_text())
    assert "geometry_intent" not in mission and mission["route"]["return_to_home"] is False
    assert Path(final["validation"]["qgc_plan_path"]).is_file()
    record = load_finalization(final["draft_id"], final["finalization_id"])
    assert record["draft_state_sha256"] and record["geometry_intent"]["length_m"] == 40
    assert record["flight_consent"] == "NOT_GRANTED"
    assert any(d["source"] == "COMPATIBILITY_DEFAULT" for d in final["compatibility_defaults"])
    before = tree()
    assert state.get_mission_state(draft_id=ready["draft_id"])["status"] == "KNOWN"
    assert tree() == before


@pytest.mark.parametrize("patch", [dict(width_m=.001), dict(length_m=2001), dict(length_m=1600, width_m=1600), dict(home_latitude=76),
    dict(home_altitude_m=1), dict(offsets=[dict(north_m=1, east_m=1)]),
    dict(mode="offsets", offsets=[]), dict(mode="offsets", offsets=[dict(north_m=1001, east_m=0)])])
def test_invalid_partial_patch_preserves_valid_state_and_versions(patch):
    first = partial()
    before = tree()
    result = intent(first, **patch)
    assert result["status"] == "ERROR", result
    assert tree() == before
    current = state.get_mission_state(draft_id=first["draft_id"])["draft"]
    assert current["geometry_revision"] == 1 and current["geometry_intent"]["width_m"] == 20


@pytest.mark.parametrize("bad", [dict(width_m=0), dict(orientation_deg=float("nan")),
    dict(altitude_m=float("inf")), dict(altitude_reference="AMSL"), dict(home_longitude=181)])
def test_invalid_schema_cannot_overwrite_partial_state(bad):
    partial()
    before = tree()
    with pytest.raises(ValidationError):
        MissionPlanDraft(geometry_intent=bad)
    assert tree() == before


def test_contradictory_shared_facts_are_errors_without_precedence_or_writes():
    first = partial()
    before = tree()
    result = edit(first, home_latitude=41, geometry_intent=dict(home_latitude=40))
    assert result["status"] == "ERROR" and tree() == before


def test_mode_change_discards_shape_fields_but_preserves_shared_decisions():
    first = partial()
    common = intent(first, altitude_m=10, altitude_reference="relative_to_home", close_route=False,
                    return_to_home=False)
    shifted = intent(common, mode="offsets", offsets=[dict(north_m=10, east_m=0)])
    parameters = shifted["geometry_intent"]
    assert parameters["length_m"] is None and parameters["width_m"] is None
    assert parameters["altitude_m"] == 10 and parameters["return_to_home"] is False
    assert parameters["offsets"] == [dict(north_m=10, east_m=0)]
    back = intent(shifted, mode="rectangle")
    assert back["geometry_intent"]["offsets"] is None
    assert {"length_m", "width_m", "orientation_deg", "home_position", "traversal"}.issubset(back["geometry_missing_fields"])
    assert not any(key.endswith("/width_m") for key in back["field_provenance"])


def test_selecting_previously_unknown_mode_preserves_compatible_known_dimensions():
    first = planning.update_mission_draft(MissionPlanDraft(name="Unknown shape",
        geometry_intent=dict(length_m=40, width_m=20)))
    assert first["geometry_intent"]["mode"] is None and "mode" in first["geometry_missing_fields"]
    selected = intent(first, mode="rectangle")
    assert selected["geometry_intent"]["length_m"] == 40
    assert selected["geometry_intent"]["width_m"] == 20


def test_shared_builder_refuses_incomplete_or_divergent_geometry_outside_mcp():
    from planning.mission_plan_service import build_mission_from_draft
    draft = complete().model_copy(update={"geometry_intent": RelativeRouteRequest(mode="rectangle", length_m=40, width_m=20)})
    with pytest.raises(ValueError, match="Geometry decisions remain pending"):
        build_mission_from_draft(draft)
    draft.geometry_intent = rectangle()
    with pytest.raises(ValueError, match="do not match"):
        build_mission_from_draft(draft)


def test_replacing_existing_route_with_incomplete_intent_clears_waypoints_not_other_fields():
    original = planning.update_mission_draft(complete())
    before = tree()
    blocked = intent(original, mode="rectangle", length_m=40, width_m=20)
    assert blocked["status"] == "CONFLICT" and tree() == before
    pending = intent(original, True, mode="rectangle", length_m=40, width_m=20)
    assert pending["draft"]["waypoints"] == [] and pending["route_provenance"] is None
    assert pending["draft"]["battery_percent"] == 95 and pending["draft"]["maximum_altitude_m"] == 50
    assert "return_to_home" in pending["geometry_missing_fields"]  # A compatibility default is not a decision.
    assert pending["geometry_intent"]["home_latitude"] == original["draft"]["home_latitude"]


def test_mode_replacement_requires_consent_and_never_accumulates_waypoints():
    initial = planning.update_mission_draft(MissionPlanDraft(name="Route"))
    generated = planning.generate_draft_route(initial["draft_id"], initial["draft_revision"], rectangle(close_route=True))
    before = tree()
    assert intent(generated, mode="offsets")["status"] == "CONFLICT"
    assert tree() == before
    pending = intent(generated, True, mode="offsets")
    assert pending["draft"]["waypoints"] == [] and pending["geometry_missing_fields"] == ["offsets"]
    two = intent(pending, offsets=[dict(north_m=10, east_m=0), dict(north_m=20, east_m=0)], close_route=False)
    assert len(two["draft"]["waypoints"]) == 2
    one = intent(two, True, offsets=[dict(north_m=30, east_m=0)])
    assert len(one["draft"]["waypoints"]) == 1
    assert one["draft"]["waypoints"][0]["waypoint_id"] == "WP1"
    assert one["geometry_intent"]["mode"] == "offsets"


def test_manual_replacement_detaches_intent_and_drops_leftovers():
    initial = planning.update_mission_draft(MissionPlanDraft(name="Route"))
    generated = planning.generate_draft_route(initial["draft_id"], initial["draft_revision"], rectangle())
    updates = MissionPlanDraft(waypoints=[dict(waypoint_id="MANUAL", latitude=41.01, longitude=2, altitude_m=10)])
    before = tree()
    assert planning.update_mission_draft(updates, initial["draft_id"], generated["draft_revision"])["status"] == "CONFLICT"
    assert tree() == before
    manual = planning.update_mission_draft(updates, initial["draft_id"], generated["draft_revision"], True)
    assert manual["geometry_intent"] is None and manual["route_provenance"] is None
    assert [w["waypoint_id"] for w in manual["draft"]["waypoints"]] == ["MANUAL"]


def test_stale_or_unversioned_geometry_cannot_overwrite_and_concurrent_patches_serialize():
    first = partial()
    before = tree()
    no_version = planning.update_mission_draft(MissionPlanDraft(geometry_intent=dict(width_m=30)), first["draft_id"])
    assert no_version["status"] == "ERROR" and tree() == before
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda width: intent(first, width_m=width), (25, 30)))
    assert {r["status"] for r in results} == {"INCOMPLETE", "CONFLICT"}
    current = state.get_mission_state(draft_id=first["draft_id"])["draft"]
    assert current["draft_revision"] == current["geometry_revision"] == 2
    assert current["geometry_intent"]["length_m"] == 40 and current["geometry_intent"]["width_m"] in {25, 30}
    before = tree()
    assert planning.finalize_mission_draft(first["draft_id"], first["draft_revision"])["status"] == "CONFLICT"
    assert tree() == before


def test_incoherent_geometry_metadata_does_not_get_repaired_on_read_or_edit():
    first = partial()
    path = planning.DRAFT_ROOT / first["draft_id"] / "draft_state.json"
    damaged = json.loads(path.read_text()); damaged["geometry_intent_sha256"] = "0" * 64
    path.write_text(json.dumps(damaged))
    before = tree()
    assert state.get_mission_state(draft_id=first["draft_id"])["status"] == "ERROR"
    assert edit(first, name="Attempt")["status"] == "ERROR"
    assert tree() == before


def test_agent_declarations_unknowns_and_defaults_are_distinct_not_authenticated():
    first = planning.update_mission_draft(MissionPlanDraft(name="Circuito",
        geometry_intent=dict(mode="rectangle", length_m=40, width_m=20)), attributions={
            "/name": InputAttribution(source="OPERATOR_DECLARED_VIA_AGENT", statement="El operador indica Circuito"),
            "/geometry_intent/length_m": InputAttribution(source="OPERATOR_DECLARED_VIA_AGENT", statement="Indica 40 metros de longitud")})
    sources = first["field_provenance"]
    assert sources["/name"]["source"] == "OPERATOR_DECLARED_VIA_AGENT"
    assert sources["/geometry_intent/width_m"]["source"] == "UNKNOWN"
    assert all(entry["authenticated"] is False for entry in sources.values())
    assert first["draft"]["vehicle_id"] is None
    assert next(d for d in first["compatibility_defaults"] if d["path"] == "/vehicle/vehicle_id")["source"] == "COMPATIBILITY_DEFAULT"
    assert "not proof of dialogue fidelity" in first["provenance_notice"]
    before = tree()
    result = planning.update_mission_draft(MissionPlanDraft(name="New"), first["draft_id"], first["draft_revision"],
        attributions={"/maximum_altitude_m": InputAttribution(source="OPERATOR_DECLARED_VIA_AGENT", statement="No such input")})
    assert result["status"] == "ERROR" and tree() == before
    with pytest.raises(ValidationError):
        InputAttribution(source="COMPATIBILITY_DEFAULT", statement="Invented limit")
    with pytest.raises(ValidationError):
        InputAttribution(source="OPERATOR_DECLARED_VIA_AGENT")


def test_legacy_metadata_has_unknown_sources_without_migration_or_geometry_inference():
    # Synthetic old-format fixture; no dependency on ignored local evidence.
    old = MissionPlanDraft(name="Legacy circuit", objective_type="survey",
        objective_target="Rectangle 40x20m", objective_description="Free text 40x20m",
        maximum_altitude_m=20, return_to_home=True).model_dump(mode="json")
    old.pop("geometry_intent")
    content = json.dumps(old, indent=2).encode()
    directory = planning.DRAFT_ROOT / INCIDENT
    directory.mkdir(parents=True)
    (directory / "draft.json").write_bytes(content)
    (directory / "draft_state.json").write_text(json.dumps({"draft_id": INCIDENT,
        "draft_revision": 2, "draft_sha256": sha256(content), "route_provenance": None,
        "provenance_status": "OPERATOR_INPUT"}))
    before = tree()
    recovered = state.get_mission_state(draft_id=INCIDENT)["draft"]
    assert recovered["draft_revision"] == 2
    assert recovered["draft_sha256"] == sha256(content)
    assert recovered["provenance_status"] == "UNKNOWN_LEGACY_INPUT"
    assert recovered["stored_provenance_status"] == "OPERATOR_INPUT"
    assert all(entry["source"] == "UNKNOWN" for entry in recovered["field_provenance"].values())
    assert recovered["geometry_intent"] is None and recovered["geometry_revision"] is None
    assert recovered["draft"]["objective_type"] == "survey"  # Preserved evidence, not endorsement.
    assert tree() == before
    renamed = planning.update_mission_draft(MissionPlanDraft(name="Explicitly renamed copy"), INCIDENT, 2,
        attributions={"/name": InputAttribution(source="OPERATOR_DECLARED_VIA_AGENT", statement="New name for this test copy")})
    assert renamed["field_provenance"]["/name"]["source"] == "OPERATOR_DECLARED_VIA_AGENT"
    assert renamed["field_provenance"]["/objective_type"]["source"] == "UNKNOWN"
    stored = json.loads((directory / "draft_state.json").read_text())
    assert "/objective_type" not in stored["field_provenance"]


def test_legacy_geometry_source_label_is_qualified_without_rewriting_record():
    first = planning.update_mission_draft(complete())
    path = planning.DRAFT_ROOT / first["draft_id"] / "draft_state.json"
    legacy = {"draft_id": first["draft_id"], "draft_revision": first["draft_revision"],
              "draft_sha256": first["draft_sha256"], "provenance_status": "OPERATOR_INPUT",
              "route_provenance": {"source": "explicit_operator_parameters", "method": "old_record"}}
    path.write_text(json.dumps(legacy))
    before = tree()
    result = state.get_mission_state(draft_id=first["draft_id"])["draft"]
    assert result["route_provenance"]["source"] == "LEGACY_GENERATION_METADATA"
    assert result["route_provenance"]["stored_source"] == "explicit_operator_parameters"
    assert result["provenance_status"] == "UNKNOWN_LEGACY_INPUT"
    assert tree() == before
