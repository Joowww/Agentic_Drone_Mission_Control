from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json

import pytest

from tools.rover_local_authorization import (
    AuthorizationError, FIXTURE, LocalAuthorizationProvider, Principal,
)


class Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.value


@pytest.fixture
def setup(tmp_path):
    clock = Clock()
    path = tmp_path / "ledger.json"
    provider = LocalAuthorizationProvider(path, fixture_mode=True, clock=clock)
    principal = Principal("fixture-reviewer", 2001, 44, 9911, FIXTURE)
    binding = {"scope_sha256": "a" * 64, "session_id": "session-1", "owner_id": "owner-1",
        "vehicle_id": "rover_01", "profile": "rover_only", "operations": ["START_ROVER_ONLY", "STOP_SAME_SESSION"],
        "host_boot_id": "host-boot-1", "container_boot_id": "container-boot-1", "environment_sha256": "b" * 64}
    return provider, principal, binding, clock, path


def test_valid_fixture_binds_exact_request_and_is_consumed_once(setup):
    provider, principal, binding, _, path = setup
    token = provider.issue_fixture(principal, binding)
    consumed = provider.consume(token, principal, binding)
    assert consumed["state"] == "CONSUMED"
    assert consumed["principal_status"] == "TEST_FIXTURE"
    assert consumed["binding"] == binding
    assert json.loads(path.read_text())["revision"] == 2
    with pytest.raises(AuthorizationError, match="NOT_ACTIVE|NOT_IN_LEDGER"):
        provider.consume(token, principal, binding)


@pytest.mark.parametrize("mutation", [
    lambda b: b.update(scope_sha256="c" * 64),
    lambda b: b.update(session_id="session-2"),
    lambda b: b.update(vehicle_id="rover_02"),
    lambda b: b.update(profile="other"),
    lambda b: b.update(host_boot_id="other-boot"),
    lambda b: b.update(container_boot_id="other-container"),
    lambda b: b.update(operations=["MOVE"]),
])
def test_binding_mismatch_fails_closed(setup, mutation):
    provider, principal, binding, _, _ = setup
    token = provider.issue_fixture(principal, binding)
    changed = dict(binding)
    mutation(changed)
    with pytest.raises(AuthorizationError, match="BINDING_MISMATCH"):
        provider.consume(token, principal, changed)


def test_wrong_principal_and_unverifiable_identity_fail_closed(setup):
    provider, principal, binding, _, _ = setup
    token = provider.issue_fixture(principal, binding)
    stranger = Principal("other", 2002, 45, 9912, FIXTURE)
    with pytest.raises(AuthorizationError, match="PRINCIPAL_MISMATCH"):
        provider.consume(token, stranger, binding)
    invalid = Principal("", -1, 0, 0, "CALLER_CLAIM")
    with pytest.raises(AuthorizationError, match="PRINCIPAL_UNVERIFIED"):
        provider.consume(token, invalid, binding)


def test_expired_revoked_and_restarted_ledger(setup):
    provider, principal, binding, clock, path = setup
    expired = provider.issue_fixture(principal, binding, valid_for_s=1)
    clock.value += timedelta(seconds=2)
    with pytest.raises(AuthorizationError, match="EXPIRED"):
        provider.consume(expired, principal, binding)
    active = provider.issue_fixture(principal, binding)
    restarted = LocalAuthorizationProvider(path, fixture_mode=True, clock=clock)
    assert restarted.revoke(active["authorization_id"], principal) == "REVOKED"
    with pytest.raises(AuthorizationError, match="NOT_ACTIVE"):
        restarted.consume(active, principal, binding)
    assert len(json.loads(path.read_text())["records"]) == 3


def test_replay_and_concurrent_double_consumption_are_atomic(setup):
    provider, principal, binding, _, _ = setup
    token = provider.issue_fixture(principal, binding)
    def consume():
        try:
            return provider.consume(token, principal, binding)["state"]
        except AuthorizationError:
            return "REJECTED"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: consume(), range(2)))
    assert sorted(outcomes) == ["CONSUMED", "REJECTED"]
    assert json.loads(provider.ledger.path.read_text())["revision"] == 2


def test_tampered_or_lost_ledger_and_fixture_in_production_fail_closed(setup):
    provider, principal, binding, _, path = setup
    token = provider.issue_fixture(principal, binding)
    data = json.loads(path.read_text())
    data["records"][0]["event"]["record"]["binding"]["scope_sha256"] = "f" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(AuthorizationError, match="CHAIN_INVALID"):
        provider.consume(token, principal, binding)
    production = LocalAuthorizationProvider(path, fixture_mode=False)
    with pytest.raises(AuthorizationError, match="FORBIDDEN_IN_PRODUCTION"):
        production.issue_fixture(principal, binding)
    path.unlink()
    with pytest.raises(AuthorizationError, match="NOT_IN_LEDGER"):
        provider.consume(token, principal, binding)


def test_identity_channel_must_be_helper_or_explicit_test_fixture(setup):
    provider, _, binding, _, _ = setup
    caller_claim = Principal("joel", 1000, 99, 1234, "CALLER_SUPPLIED_OPERATOR_ID")
    with pytest.raises(AuthorizationError, match="FIXTURE_PRINCIPAL_INVALID"):
        provider.issue_fixture(caller_claim, binding)
    helper_principal = Principal("approver-uid-2001", 2001, 44, 9911, "LOCAL_HELPER_PEERCRED")
    with pytest.raises(AuthorizationError, match="FIXTURE_PRINCIPAL_INVALID"):
        provider.issue_fixture(helper_principal, binding)


def test_backend_rejects_caller_claimed_helper_identity_and_all_production_use(setup):
    provider, principal, binding, _, path = setup
    token = provider.issue_fixture(principal, binding)
    caller_forged_peercred = Principal("approver", 2001, 44, 9911, "LOCAL_HELPER_PEERCRED")
    with pytest.raises(AuthorizationError, match="FIXTURE_PRINCIPAL_REQUIRED"):
        provider.consume(token, caller_forged_peercred, binding)
    with pytest.raises(AuthorizationError, match="FIXTURE_PRINCIPAL_REQUIRED"):
        provider.revoke(token["authorization_id"], caller_forged_peercred)

    production = LocalAuthorizationProvider(path, fixture_mode=False)
    with pytest.raises(AuthorizationError, match="OFFLINE_BACKEND_FORBIDDEN_IN_PRODUCTION"):
        production.consume(token, caller_forged_peercred, binding)
    with pytest.raises(AuthorizationError, match="OFFLINE_BACKEND_FORBIDDEN_IN_PRODUCTION"):
        production.revoke(token["authorization_id"], caller_forged_peercred)
