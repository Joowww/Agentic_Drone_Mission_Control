"""Registered schema/runtime agreement, not a test of conversational obedience."""
import asyncio
from copy import deepcopy

from jsonschema import Draft202012Validator, ValidationError
from mcp.server.mcpserver.exceptions import ToolError
import pytest

from tests.test_partial_geometry_planning import storage, tree
from tests.test_mission_response_views import registered
from tools.hermes_mcp_server import mcp


def arguments(name, attribution):
    body = {"attributions": {"/geometry_intent/orientation_deg": attribution}}
    if name == "update_mission_draft":
        return {**body, "updates": {"geometry_intent": {"orientation_deg": 90}}}
    return {**body, "draft_id": "fixture-id", "expected_revision": 1,
            "request": {"orientation_deg": 90}}


@pytest.mark.parametrize("name", ["update_mission_draft", "generate_draft_route"])
@pytest.mark.parametrize("statement", [None, "", " \t\n", "OMITTED"])
def test_registered_schema_and_dispatch_reject_unsupported_attribution_before_writes(storage, name, statement):
    attribution = {"source": "OPERATOR_DECLARED_VIA_AGENT"}
    if statement != "OMITTED":
        attribution["statement"] = statement
    schema = next(tool.input_schema for tool in asyncio.run(mcp.list_tools()) if tool.name == name)
    payload = arguments(name, attribution)
    before = tree()
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)
    with pytest.raises(ToolError):
        registered(name, payload)
    assert tree() == before


@pytest.mark.parametrize("angle", [0, 90, 180, 270, 359.9])
def test_numeric_headings_remain_valid_without_claiming_semantic_fidelity(storage, angle):
    first = registered("update_mission_draft", {"updates": {"name": "Temporary fixture",
        "geometry_intent": {"mode": "rectangle", "length_m": 40, "width_m": 20}}})
    attribution = {"source": "OPERATOR_DECLARED_VIA_AGENT",
                   "statement": f"Synthetic operator explicitly chooses length edge {angle} degrees"}
    payload = {"draft_id": first["draft_id"], "expected_revision": first["draft_revision"],
               "request": {"orientation_deg": angle},
               "attributions": {"/geometry_intent/orientation_deg": attribution}}
    schema = next(tool.input_schema for tool in asyncio.run(mcp.list_tools()) if tool.name == "generate_draft_route")
    Draft202012Validator(schema).validate(payload)
    result = registered("generate_draft_route", payload)
    assert result["geometry_intent"]["orientation_deg"] == angle
    assert result["geometry_intent"]["length_m"] == 40
    assert result["draft"]["waypoints"] == []
    source = result["field_provenance"]["/geometry_intent/orientation_deg"]
    assert source["statement"] == attribution["statement"] and source["authenticated"] is False


def test_unknown_attribution_and_resolved_height_do_not_resolve_orientation(storage):
    payload = {"updates": {"geometry_intent": {"mode": "rectangle", "length_m": 40,
        "width_m": 20, "altitude_m": 8, "altitude_reference": "relative_to_home"}},
        "attributions": {"/geometry_intent/altitude_m": {"source": "UNKNOWN"}}}
    schema = next(tool.input_schema for tool in asyncio.run(mcp.list_tools()) if tool.name == "update_mission_draft")
    Draft202012Validator(schema).validate(payload)
    result = registered("update_mission_draft", payload)
    assert result["geometry_intent"]["orientation_deg"] is None
    assert "orientation_deg" in result["pending"]["route_generation"]
    assert "altitude_reference" not in result["pending"]["route_generation"]
    assert result["draft"]["waypoints"] == []
    before = tree()
    invalid = deepcopy(payload)
    invalid.update(draft_id=result["draft_id"], expected_revision=result["draft_revision"])
    invalid["attributions"]["/geometry_intent/altitude_m"] = {"source": "OPERATOR_DECLARED_VIA_AGENT"}
    with pytest.raises(ToolError):
        registered("update_mission_draft", invalid)
    assert tree() == before
