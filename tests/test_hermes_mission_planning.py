import asyncio
import json

import pytest
from pydantic import ValidationError
from mcp.server.mcpserver.exceptions import ToolError

from models.mission_plan_draft import MissionPlanDraft
import tools.hermes_mission_planning as planning
import tools.hermes_mcp_server as server


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(planning, "DRAFT_ROOT", tmp_path)


def complete():
    return MissionPlanDraft(
        name="Hermes test", vehicle_type="multirotor", autopilot="ArduPilot",
        cruise_speed_kmh=20, battery_percent=95,
        battery_consumption_percent_per_minute=0.8,
        objective_type="transit", objective_target="field",
        home_latitude=41, home_longitude=2, home_altitude_m=0,
        waypoints=[dict(waypoint_id="WP1", latitude=41.0001,
                        longitude=2, altitude_m=10, action="navigate")],
        wind_speed_kmh=0, wind_direction_from="north",
        minimum_battery_reserve_percent=20, maximum_wind_speed_kmh=30,
        maximum_altitude_m=50,
    )


def test_incomplete_continuation_and_retrieval():
    first = server.update_mission_draft(MissionPlanDraft(
        name="Test", waypoints=[dict(waypoint_id="WP1", latitude=41)]))
    draft_id = first["draft_id"]
    assert first["status"] == "INCOMPLETE"
    assert "WP1 longitude" in first["missing_fields"]
    updated = server.update_mission_draft(MissionPlanDraft(
        waypoints=[dict(waypoint_id="wp1", longitude=2)]), draft_id)
    assert len(updated["draft"]["waypoints"]) == 1
    assert updated["draft"]["waypoints"][0]["latitude"] == 41
    assert server.update_mission_draft(MissionPlanDraft(), draft_id) == updated
    assert server.finalize_mission_draft(draft_id)["status"] == "INCOMPLETE"
    assert not list(planning.DRAFT_ROOT.rglob("*.plan"))


@pytest.mark.parametrize("updates", [
    {"battery_percent": 101}, {"home_latitude": 91},
    {"cruise_speed_kmh": 0}, {"wind_speed_kmh": float("nan")},
    {"unknown": 1}, {"waypoints": [{"waypoint_id": "WP1", "altitude_m": -1}]},
])
def test_invalid_partial_values(updates):
    with pytest.raises(ValidationError):
        MissionPlanDraft.model_validate(updates)
    assert not list(planning.DRAFT_ROOT.iterdir())


def test_invalid_id_does_not_create_draft():
    assert server.update_mission_draft(MissionPlanDraft(), "../bad")["status"] == "ERROR"


def test_finalize_real_validation_export_and_snapshot():
    created = server.update_mission_draft(complete())
    result = server.finalize_mission_draft(created["draft_id"])
    assert result["status"] == "VALIDATED"
    assert result["validation"]["mission_status"] == "FEASIBLE"
    assert result["validation"]["execution_status"] == "APPROVED"
    path = result["mission_path"]
    assert json.loads(open(path).read())["source"] == "natural_language"
    assert json.loads(open(result["validation"]["qgc_plan_path"]).read())["fileType"] == "Plan"
    assert result["user_execution_authorization_required"] is True
    # Export wrapper accepts the public output_directory parameter.
    exported = server.validate_and_export_qgc(path, str(planning.DRAFT_ROOT))
    assert exported["mission_status"] == "FEASIBLE"
    server.update_mission_draft(MissionPlanDraft(name="Changed"), created["draft_id"])
    assert json.loads(open(path).read())["name"] == "Hermes test"


def test_unsafe_mission_exports_blocked_candidate():
    draft = complete()
    draft.wind_speed_kmh = 80
    created = server.update_mission_draft(draft)
    result = server.finalize_mission_draft(created["draft_id"])
    assert result["validation"]["execution_status"] == "BLOCKED"
    assert result["validation"]["qgc_plan_path"].endswith("_candidate.plan")


def test_wind_update_changes_representation():
    draft = complete()
    draft.wind_direction_from_deg = 90
    created = server.update_mission_draft(draft)
    updated = server.update_mission_draft(
        MissionPlanDraft(wind_direction_from="west"), created["draft_id"])
    assert updated["draft"]["wind_direction_from_deg"] is None


def test_tools_expose_structured_draft_schema():
    tools = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}
    assert "finalize_mission_draft" in tools
    schema = tools["update_mission_draft"].input_schema
    assert "updates" in schema["properties"]


def test_invalid_mcp_update_preserves_saved_draft():
    created = server.update_mission_draft(MissionPlanDraft(name="Keep"))
    async def invalid_update():
        with pytest.raises(ToolError, match="battery_percent"):
            await server.mcp.call_tool("update_mission_draft", {
                "updates": {"battery_percent": 200},
                "draft_id": created["draft_id"],
            })
    asyncio.run(invalid_update())
    assert server.update_mission_draft(
        MissionPlanDraft(), created["draft_id"]) == created


def test_mission_id_cannot_escape_export_directory():
    draft = complete()
    draft.mission_id = "../../escape"
    created = server.update_mission_draft(draft)
    assert server.finalize_mission_draft(created["draft_id"])["status"] == "ERROR"
    assert not list(planning.DRAFT_ROOT.rglob("mission.json"))
