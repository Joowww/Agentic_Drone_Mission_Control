from __future__ import annotations

import asyncio

import tools.hermes_mcp_server as server


EXPECTED_TOOLS = {
    "validate_mission",
    "validate_and_export_qgc",
    "check_simulation_ready",
    "start_simulation",
    "stop_simulation",
    "check_mission_execution_ready",
    "execute_approved_mission",
}


def test_expected_mcp_tools_are_registered():
    tools = asyncio.run(
        server.mcp.list_tools()
    )

    tool_names = {
        tool.name
        for tool in tools
    }

    assert EXPECTED_TOOLS <= tool_names


def test_execute_approved_mission_uses_drone1_and_disables_progress(
    monkeypatch,
):
    captured = {}

    def fake_execute(
        mission_path: str,
        *,
        vehicle: str,
        progress: bool,
    ):
        captured[
            "mission_path"
        ] = mission_path

        captured[
            "vehicle"
        ] = vehicle

        captured[
            "progress"
        ] = progress

        return {
            "success": True,
            "status": "COMPLETED",
        }

    monkeypatch.setattr(
        server,
        "execute_mission_backend",
        fake_execute,
    )

    result = (
        server.execute_approved_mission(
            "/tmp/mission.json"
        )
    )

    assert result == {
        "success": True,
        "status": "COMPLETED",
    }

    assert (
        captured["mission_path"]
        == "/tmp/mission.json"
    )

    assert captured["vehicle"] == "v1"
    assert captured["progress"] is False