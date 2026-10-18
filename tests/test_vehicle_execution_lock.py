from unittest.mock import Mock

import pytest

import tools.vehicle_execution_lock as vehicle
import tools.guarded_demo as demo


def test_actual_os_mutex_prevents_second_scope_for_same_reservation():
    vehicle.reserve("owner", "test")
    with vehicle.execution_scope("owner"):
        with pytest.raises(vehicle.VehicleBusy, match="OS mutex"):
            with vehicle.execution_scope("owner"):
                pytest.fail("second execution scope entered")
    assert vehicle.restriction() is not None  # releasing flock alone is insufficient


def test_sync_unknown_result_retains_durable_restriction():
    wrapped = vehicle.serialized_v1(lambda *a, **k: {"status": "FAILED", "success": False})
    assert wrapped("mission.json")["status"] == "FAILED"
    assert vehicle.restriction()["state"] == "UNCONFIRMED"
    assert wrapped("mission.json")["stage"] == "VEHICLE_EXCLUSION"


def test_sync_exception_retains_restriction():
    wrapped = vehicle.serialized_v1(Mock(side_effect=RuntimeError("unknown outcome")))
    with pytest.raises(RuntimeError):
        wrapped("mission.json")
    assert vehicle.restriction()["state"] == "UNCONFIRMED"


@pytest.mark.parametrize("raw, safe", [
    ({"status": "COMPLETED", "success": True}, False),
    ({"status": "FAILED", "success": False, "recovery": {"landing_completed": True}}, False),
    ({"status": "FAILED", "success": False, "recovery": {"landing_completed": True,
      "landing": {"landed": True, "armed": False, "flying": False}}}, True),
    ({"status": "COMPLETED", "success": True, "events": [
      {"event": "LANDED", "landed": True, "armed": False, "flying": False}]}, True),
])
def test_restriction_release_needs_positive_no_flight_or_landing_evidence(raw, safe):
    assert vehicle.safe_executor_exit(raw) is safe


@pytest.mark.parametrize("busy", [False, True])
def test_legacy_parallel_demo_is_disabled_even_without_a_reservation(monkeypatch, busy):
    if busy:
        vehicle.reserve("async-run", "asynchronous_preflight", "v2")
    call = Mock(side_effect=AssertionError("legacy parallel demo must not start"))
    monkeypatch.setattr("subprocess.run", call)
    before = vehicle.restriction()
    assert demo.run_demo() == 1
    assert demo.verify_child() is False
    assert vehicle.restriction() == before
    call.assert_not_called()


def test_copied_context_cannot_reuse_an_expired_execution_scope():
    from contextvars import copy_context
    vehicle.reserve("old", "test")
    with vehicle.execution_scope("old"):
        expired = copy_context()
    vehicle.release("old")
    vehicle.reserve("current", "test")
    commands = Mock(return_value={"status": "COMPLETED"})
    with vehicle.execution_scope("current"):
        result = expired.run(vehicle.serialized_v1(commands), "mission.json")
    assert result["status"] == "BLOCKED"
    commands.assert_not_called()
    assert vehicle.restriction()["owner_id"] == "current"


def test_copied_context_cannot_execute_two_flights_concurrently_for_one_owner():
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from threading import Event
    entered, finish = Event(), Event()
    def commands(*args, **kwargs):
        entered.set()
        assert finish.wait(3)
        return {"status": "FAILED", "success": False}
    wrapped = vehicle.serialized_v1(commands)
    vehicle.reserve("one", "test")
    with vehicle.execution_scope("one"):
        first_context, second_context = copy_context(), copy_context()
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(first_context.run, wrapped, "mission.json")
            assert entered.wait(3)
            try:
                # This must return immediately instead of issuing another flight.
                second_commands = Mock(return_value={"status": "UNEXPECTED_FLIGHT"})
                duplicate = second_context.run(vehicle.serialized_v1(second_commands), "mission.json")
                assert duplicate["status"] == "BLOCKED"
                second_commands.assert_not_called()
            finally:
                finish.set()
            assert first.result(timeout=3)["status"] == "FAILED"
