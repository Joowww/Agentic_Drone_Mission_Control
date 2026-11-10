"""Public confirmation boundary: no installed human verifier, so no mutations.

Temporary stores only. The inherited persistence fixture initially provides an
explicit offline verifier double; secure_system restores the production barrier.
"""
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tools import legacy_administrative_retirement as retirement
from tools import vehicle_execution_lock as locks
from tests.test_legacy_administrative_retirement import (
    system, prepare, arguments, tree, PRODUCTION_CONFIRMATION_GATE,
)
from tests.test_mission_response_views import registered


@pytest.fixture
def secure_system(system, monkeypatch):
    monkeypatch.setattr(retirement, '_require_operator_confirmation', PRODUCTION_CONFIRMATION_GATE)
    return system


def unchanged(prepared, system, callback):
    before = tree(system.root) | tree(locks.LOCK_ROOT)
    system.environment.reset_mock()
    result = callback()
    assert (tree(system.root) | tree(locks.LOCK_ROOT)) == before
    system.environment.assert_not_called()
    system.spawn.assert_not_called()
    return result


def test_fresh_exact_bound_declaration_cannot_substitute_for_human_confirmation(secure_system, monkeypatch):
    prepared = prepare()
    enter = Mock(side_effect=AssertionError('No mutation mutex without verified confirmation'))
    monkeypatch.setattr(retirement, '_exclusive', enter)
    result = unchanged(prepared, secure_system,
        lambda: retirement.apply_legacy_sequence_retirement(**arguments(prepared)))
    assert result['status'] == 'BLOCKED'
    assert result['error_code'] == 'OPERATOR_CONFIRMATION_UNAVAILABLE'
    assert result['operator_confirmation_verified'] is False
    assert result['automatic_retry_allowed'] is False
    assert result['new_preparation_authorized'] is False
    enter.assert_not_called()


@pytest.mark.parametrize('field', ['preparation_id', 'preparation_sha256'])
def test_confirmation_for_another_exact_id_or_hash_is_rejected(secure_system, field):
    prepared = prepare(); args = arguments(prepared)
    args['authorization'][field] = str(uuid4()) if field == 'preparation_id' else '0' * 64
    result = unchanged(prepared, secure_system,
        lambda: retirement.apply_legacy_sequence_retirement(**args))
    assert result['error_code'] == 'CONFIRMATION_BINDING_MISMATCH'


def test_expired_scope_then_new_preparation_cannot_inherit_old_confirmation(secure_system, monkeypatch):
    old = prepare(); old_args = arguments(old)
    now = retirement.time.monotonic()
    with monkeypatch.context() as clock:
        clock.setattr(retirement.time, 'monotonic', lambda: now + 121)
        expired = unchanged(old, secure_system,
            lambda: retirement.apply_legacy_sequence_retirement(**old_args))
    assert expired['error_code'] == 'PREPARATION_EXPIRED_OR_BOOT_CHANGED'
    new = prepare()  # explicit test action, never an application fallback
    new_args = arguments(new); new_args['authorization'] = old_args['authorization']
    prepare_again = Mock(side_effect=AssertionError('No automatic preparation'))
    monkeypatch.setattr(retirement, 'prepare_legacy_sequence_retirement', prepare_again)
    result = unchanged(new, secure_system,
        lambda: retirement.apply_legacy_sequence_retirement(**new_args))
    assert result['error_code'] == 'CONFIRMATION_BINDING_MISMATCH'
    # Rewriting the declaration's IDs still cannot manufacture a human response.
    rewritten = unchanged(new, secure_system,
        lambda: retirement.apply_legacy_sequence_retirement(**arguments(new)))
    assert rewritten['error_code'] == 'OPERATOR_CONFIRMATION_UNAVAILABLE'
    prepare_again.assert_not_called()


@pytest.mark.parametrize('field', ['preparation_id', 'preparation_sha256'])
def test_registered_schema_requires_explicit_bound_scope(secure_system, field):
    prepared = prepare(); args = arguments(prepared)
    del args['authorization'][field]
    before = tree(secure_system.root) | tree(locks.LOCK_ROOT)
    secure_system.environment.reset_mock()
    with pytest.raises(Exception):
        registered('apply_legacy_sequence_retirement', args)
    assert (tree(secure_system.root) | tree(locks.LOCK_ROOT)) == before
    secure_system.environment.assert_not_called()


def test_registered_tool_enforces_production_barrier_and_query_does_not_confirm(secure_system):
    prepared = prepare()
    result = unchanged(prepared, secure_system,
        lambda: registered('apply_legacy_sequence_retirement', arguments(prepared)))
    assert result['error_code'] == 'OPERATOR_CONFIRMATION_UNAVAILABLE'
    result = unchanged(prepared, secure_system,
        lambda: registered('get_legacy_sequence_retirement', {'preparation_id': prepared['preparation_id']}))
    assert result['application_enabled'] is False
    assert result['operator_confirmation_verified'] is False
    assert result['authorization_recorded'] is False


@pytest.mark.parametrize('error', [TimeoutError('no human response'), RuntimeError('confirmation transport failed')])
def test_confirmation_timeout_or_error_has_no_writes_or_fallback(secure_system, monkeypatch, error):
    prepared = prepare()
    verifier = Mock(side_effect=error)
    monkeypatch.setattr(retirement, '_require_operator_confirmation', verifier)
    prepare_again = Mock(side_effect=AssertionError('Must not renew the scope'))
    monkeypatch.setattr(retirement, 'prepare_legacy_sequence_retirement', prepare_again)
    result = unchanged(prepared, secure_system,
        lambda: retirement.apply_legacy_sequence_retirement(**arguments(prepared)))
    assert result['status'] == 'BLOCKED'
    assert result['automatic_retry_allowed'] is False
    assert not (secure_system.root / 'intent.json').exists()
    prepare_again.assert_not_called()


def reloaded(system):
    spec = importlib.util.spec_from_file_location('confirmation_reload', retirement.__file__)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.ROOT = system.root
    module.inspect_environment = system.environment
    return module


def test_lost_blocked_response_reload_and_reconnection_do_not_grant_confirmation(secure_system):
    prepared = prepare()
    # Ignore the first response to model loss at the caller; no durable grant exists.
    retirement.apply_legacy_sequence_retirement(**arguments(prepared))
    module = reloaded(secure_system)
    before = tree(secure_system.root) | tree(locks.LOCK_ROOT)
    secure_system.environment.reset_mock()
    state = module.get_legacy_sequence_retirement()
    assert state['operator_confirmation_verified'] is False
    assert state['authorization_recorded'] is False
    for callback in (module.apply_legacy_sequence_retirement,
                     retirement.apply_legacy_sequence_retirement):
        assert callback(**arguments(prepared))['error_code'] == 'OPERATOR_CONFIRMATION_UNAVAILABLE'
    assert (tree(secure_system.root) | tree(locks.LOCK_ROOT)) == before
    secure_system.environment.assert_not_called()


def test_partial_old_intent_cannot_be_resumed_with_agent_text(system, monkeypatch):
    prepared = prepare(); write = retirement._write_once
    def cut(path, raw):
        if path == system.root / 'result.json':
            raise OSError('interruption before final result; test double verifier only')
        return write(path, raw)
    with monkeypatch.context() as local:
        local.setattr(retirement, '_write_once', cut)
        assert retirement.apply_legacy_sequence_retirement(**arguments(prepared))['status'] == 'BLOCKED'
    monkeypatch.setattr(retirement, '_require_operator_confirmation', PRODUCTION_CONFIRMATION_GATE)
    result = unchanged(prepared, system,
        lambda: retirement.apply_legacy_sequence_retirement(**arguments(prepared)))
    assert result['error_code'] == 'OPERATOR_CONFIRMATION_UNAVAILABLE'
    assert (locks.LOCK_ROOT / 'reconciliation.json').exists()
    assert retirement.get_legacy_sequence_retirement()['status'] == 'RECOVERY_REQUIRED'


def test_completed_legacy_shape_survives_lost_response_and_reload_without_repeating(system, monkeypatch):
    prepared = prepare()
    assert retirement.apply_legacy_sequence_retirement(**arguments(prepared))['status'] == retirement.RESULT
    # Legacy-shaped records in TEMPORARIES: never migrate an actual incident file.
    intent_path = system.root / 'intent.json'
    intent = json.loads(intent_path.read_bytes())
    for key in ('preparation_id', 'preparation_sha256'):
        intent['request']['authorization'].pop(key)
    locks.atomic_json(intent_path, intent)
    result_path = system.root / 'result.json'
    result = json.loads(result_path.read_bytes())
    result['intent_sha256'] = retirement._hash(intent_path.read_bytes())
    locks.atomic_json(result_path, result)
    monkeypatch.setattr(retirement, '_require_operator_confirmation', PRODUCTION_CONFIRMATION_GATE)
    module = reloaded(system)
    existing = unchanged(prepared, system, lambda: module.get_legacy_sequence_retirement())
    assert existing['status'] == retirement.RESULT
    assert existing['operator_confirmation_verified'] is False
    replay = unchanged(prepared, system,
        lambda: module.apply_legacy_sequence_retirement(**intent['request']))
    assert replay['status'] == retirement.RESULT and replay['application_performed'] is False
    assert replay['replayed'] is True
    assert replay['authorization_provenance'] == 'UNVERIFIED_AGENT_DECLARATION'
    assert not (locks.LOCK_ROOT / 'reconciliation.json').exists()
