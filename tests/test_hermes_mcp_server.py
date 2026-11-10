from __future__ import annotations

import asyncio

import tools.hermes_mcp_server as server


EXPECTED_TOOLS = {
    "start_virtual_preflight",
    "get_virtual_preflight",
    "run_virtual_preflight",
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


def test_execute_approved_mission_defers_vehicle_resolution_and_disables_progress(
    monkeypatch,
):
    captured = {}

    def fake_execute(
        mission_path: str,
        *,
        vehicle: str | None = None,
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

    assert captured["vehicle"] is None
    assert captured["progress"] is False

def test_virtual_preflight_wrapper_forwards_only_mission_path(monkeypatch):
    calls = []
    def fake_preflight(path):
        calls.append(path)
        return {"status": "BLOCKED", "reasons": ["simulation stopped"]}
    monkeypatch.setattr(server, "preflight_backend", fake_preflight)
    assert server.run_virtual_preflight("mission.json")["status"] == "BLOCKED"
    assert calls == ["mission.json"]


def test_async_wrappers_forward_request_identity_without_operational_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "start_preflight_backend",
                        lambda path, key: calls.append((path, key)) or {"job_state": "STARTING"})
    monkeypatch.setattr(server, "get_preflight_backend",
                        lambda **kwargs: calls.append(kwargs) or {"job_state": "RUNNING"})
    assert server.start_virtual_preflight("mission.json", "key-one")["job_state"] == "STARTING"
    assert server.get_virtual_preflight(request_key="key-one")["job_state"] == "RUNNING"
    assert calls == [("mission.json", "key-one"), {"run_id": None, "request_key": "key-one"}]
