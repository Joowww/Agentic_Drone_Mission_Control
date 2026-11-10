from copy import deepcopy
from datetime import datetime, timezone

import pytest

from tools.rover_mission_payload import (SCHEMA, authorization_scope_sha256,
                                         plan_sha256, validate)

NOW = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)


def payload():
    value = {'schema': SCHEMA,
      'mission': {'id': 'mission-1', 'sha256': 'a'*64},
      'plan_id': 'plan-1',
      'rover': {'vehicle_id': 'rover_01', 'platform': 'ArduRover SITL'},
      'goal': {'objective': 'reach_declared_point', 'frame': 'odom', 'x_m': 1.0, 'y_m': 0.0, 'conditional': False},
      'localization': {'frame': 'odom', 'x_m': 0.0, 'y_m': 0.0, 'uncertainty_m': 0.02,
        'source': 'motion-binding', 'source_sha256': 'b'*64, 'validated': True,
        'observed_at_utc': '2026-11-06T11:59:59Z', 'transform': None},
      'dependencies': ['ready-check'],
      'constraints': {'max_distance_m': 1.2, 'max_lateral_error_m': 0.2},
      'operator_limits': {'max_speed_mps': 0.1, 'timeout_s': 20.0, 'max_distance_m': 1.2,
        'localization_max_uncertainty_m': 0.1, 'localization_max_age_s': 2.0},
      'provenance': {'source': 'mission-agent', 'source_sha256': 'c'*64},
      'authorization': {'scope_sha256': '', 'human_authorized': True, 'operator_id': 'operator-1',
        'operator_status': 'AUTHENTICATED', 'revocation_status': 'ACTIVE', 'authorization_receipt_sha256': 'e'*64},
      'validity': {'not_before_utc': '2026-11-06T00:00:00Z', 'expires_at_utc': '2026-11-07T00:00:00Z'},
      'executor': {'id': 'rover_ground_executor', 'version': '1'},
      'stop_conditions': ['stale odometry', 'distance bound']}
    value['plan_sha256'] = plan_sha256(value)
    value['authorization']['scope_sha256'] = authorization_scope_sha256(value)
    return value


def test_valid_payload_is_plan_bound_but_never_execution_authority():
    p = payload()
    out = validate(p, now=NOW)
    assert out['decision'] == 'READY_TO_SUBMIT' and out['reasons'] == []
    assert out['plan_sha256'] == p['plan_sha256']
    assert out['authorization_scope_sha256'] == p['authorization']['scope_sha256']
    assert out['commands'] == [] and out['movement_authorized'] is False
    assert out['execution_requires_protected_executor']
    assert out['operator_identity_authenticated'] is False
    assert out['authorization_receipt_verified'] is False
    assert out['execution_authorized'] is False


def test_hash_is_recomputed_over_exact_plan_and_modified_plan_is_rejected():
    p = payload(); p['goal']['x_m'] += 0.1
    out = validate(p, now=NOW)
    assert out['decision'] == 'REJECTED'
    assert 'PLAN_HASH_MISMATCH' in out['reasons']


def test_authorization_for_another_plan_is_rejected_even_with_valid_hash_format():
    p = payload(); p['authorization']['scope_sha256'] = 'd'*64
    out = validate(p, now=NOW)
    assert 'AUTHORIZATION_PLAN_SCOPE_MISMATCH' in out['reasons']


def test_authorization_scope_changes_when_plan_or_vehicle_changes():
    p = payload(); before = authorization_scope_sha256(p)
    p['plan_id'] = 'plan-2'; p['plan_sha256'] = plan_sha256(p)
    assert authorization_scope_sha256(p) != before
    p['authorization']['scope_sha256'] = before
    assert 'AUTHORIZATION_PLAN_SCOPE_MISMATCH' in validate(p, now=NOW)['reasons']


def test_optional_bridge_scope_is_bound_without_changing_legacy_v2_scope_digest():
    import hashlib
    import json

    p = payload()
    legacy_body = {'schema': p['schema'], 'mission_id': p['mission']['id'],
        'plan_id': p['plan_id'], 'vehicle_id': p['rover']['vehicle_id'],
        'plan_sha256': p['plan_sha256']}
    legacy = hashlib.sha256(json.dumps(legacy_body, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    assert authorization_scope_sha256(p) == legacy

    p['authorization']['bridge_scope_sha256'] = 'f' * 64
    bound = authorization_scope_sha256(p)
    assert bound != legacy
    p['authorization']['scope_sha256'] = legacy
    assert 'AUTHORIZATION_PLAN_SCOPE_MISMATCH' in validate(p, now=NOW)['reasons']
    p['authorization']['scope_sha256'] = bound
    assert validate(p, now=NOW)['decision'] == 'READY_TO_SUBMIT'


def test_operator_declaration_without_authentication_is_not_accepted():
    p = payload(); p['authorization']['operator_status'] = 'DECLARED'
    out = validate(p, now=NOW)
    assert 'OPERATOR_NOT_AUTHENTICATED' in out['reasons']
    assert out['movement_authorized'] is False


def test_revoked_or_unknown_authorization_fails_closed():
    p = payload(); p['authorization']['revocation_status'] = 'REVOKED'
    assert 'AUTHORIZATION_REVOKED' in validate(p, now=NOW)['reasons']
    p = payload(); p['authorization']['revocation_status'] = 'UNKNOWN'
    assert 'AUTHORIZATION_REVOCATION_UNCONFIRMED' in validate(p, now=NOW)['reasons']


def test_conditional_proposal_can_wait_for_localization_and_authorization():
    p = payload(); p['goal']['conditional'] = True; p['localization'] = None; p['authorization'] = {}
    p['plan_sha256'] = plan_sha256(p)
    out = validate(p, now=NOW)
    assert out['decision'] == 'WAITING'
    assert 'LOCALIZATION_PENDING_FOR_CONDITIONAL_PLAN' in out['reasons']
    assert out['commands'] == [] and out['movement_authorized'] is False


def test_nonconditional_plan_without_localization_is_rejected():
    p = payload(); p['localization'] = None; p['plan_sha256'] = plan_sha256(p)
    out = validate(p, now=NOW)
    assert out['decision'] == 'REJECTED'
    assert 'LOCALIZATION_MISSING_OR_UNVALIDATED' in out['reasons']


def test_transform_must_be_rigid_provenanced_and_current():
    p = payload(); p['goal']['frame'] = 'map'
    p['localization']['transform'] = {'source_frame': 'odom', 'target_frame': 'map',
      'matrix': [[1.0, 0.0, 1.0], [0.0, 1.0, 2.0], [0.0, 0.0, 1.0]],
      'uncertainty_m': 0.01, 'uncertainty_rad': 0.01, 'source': 'survey', 'source_sha256': 'f'*64,
      'validated': True, 'not_before_utc': '2026-11-06T11:00:00Z', 'expires_at_utc': '2026-11-06T13:00:00Z'}
    p['plan_sha256'] = plan_sha256(p); p['authorization']['scope_sha256'] = authorization_scope_sha256(p)
    assert validate(p, now=NOW)['decision'] == 'READY_TO_SUBMIT'
    p['localization']['transform']['matrix'][0][0] = 2.0
    p['plan_sha256'] = plan_sha256(p)
    assert 'FRAME_TRANSFORM_NOT_RIGID_2D' in validate(p, now=NOW)['reasons']


def test_incompatible_frames_without_transform_are_rejected():
    p = payload(); p['goal']['frame'] = 'map'
    p['plan_sha256'] = plan_sha256(p); p['authorization']['scope_sha256'] = authorization_scope_sha256(p)
    assert 'FRAME_TRANSFORM_REQUIRED' in validate(p, now=NOW)['reasons']


def test_stale_localization_and_expired_transform_are_rejected():
    p = payload(); p['localization']['observed_at_utc'] = '2026-11-06T11:00:00Z'
    assert 'LOCALIZATION_STALE' in validate(p, now=NOW)['reasons']
    p = payload(); p['goal']['frame'] = 'map'
    p['localization']['transform'] = {'source_frame': 'odom', 'target_frame': 'map',
      'matrix': [[1.0,0.0,0.0],[0.0,1.0,0.0],[0.0,0.0,1.0]], 'uncertainty_m': 0.0,
      'uncertainty_rad': 0.0, 'source': 'survey', 'source_sha256': 'f'*64, 'validated': True,
      'not_before_utc': '2026-11-06T10:00:00Z', 'expires_at_utc': '2026-11-06T11:00:00Z'}
    p['plan_sha256'] = plan_sha256(p); p['authorization']['scope_sha256'] = authorization_scope_sha256(p)
    assert 'FRAME_TRANSFORM_EXPIRED_OR_NOT_YET_VALID' in validate(p, now=NOW)['reasons']


def test_payload_expiry_and_nonfinite_plan_values_are_rejected():
    p = payload(); p['validity']['expires_at_utc'] = '2026-11-06T11:00:00Z'
    assert 'PAYLOAD_EXPIRED' in validate(p, now=NOW)['reasons']
    p = payload(); p['goal']['x_m'] = float('nan')
    assert 'PLAN_HASH_UNCANONICAL' in validate(p, now=NOW)['reasons']


def test_v2_schema_accepts_a_complete_plan_and_conditional_proposal():
    import json
    from pathlib import Path
    from jsonschema import Draft202012Validator, FormatChecker

    schema = json.loads(Path('schemas/rover-mission-execution-v2.schema.json').read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    valid = payload()
    validator.validate(valid)
    conditional = deepcopy(valid)
    conditional['goal']['conditional'] = True
    conditional['localization'] = None
    conditional['authorization'] = None
    conditional['plan_sha256'] = plan_sha256(conditional)
    validator.validate(conditional)


def test_v2_schema_rejects_malformed_frame_transform_and_authorization():
    import json
    from pathlib import Path
    from jsonschema import Draft202012Validator, ValidationError

    schema = json.loads(Path('schemas/rover-mission-execution-v2.schema.json').read_text())
    validator = Draft202012Validator(schema)
    broken = payload()
    broken['authorization']['scope_sha256'] = 'not-a-digest'
    with pytest.raises(ValidationError):
        validator.validate(broken)


def test_bridge_scope_schema_change_is_optional_and_preserves_committed_v2_contract():
    from tests.history_requirements import require_commits
    require_commits("2e206f1fa4c0c6db056adac4a3fcaaa0835e47f1")
    import hashlib
    import json
    import subprocess
    from pathlib import Path
    from jsonschema import Draft202012Validator, ValidationError

    base = '2e206f1fa4c0c6db056adac4a3fcaaa0835e47f1'
    raw_head = subprocess.run(['git', 'show', f'{base}:schemas/rover-mission-execution-v2.schema.json'],
        check=True, capture_output=True).stdout
    assert hashlib.sha256(raw_head).hexdigest() == '39c2a5f232f8ca3b7fc95f5216bb7bc7ec323829e4be251586f7f4ab37089d89'
    head_schema = json.loads(raw_head)
    worktree_schema = json.loads(Path('schemas/rover-mission-execution-v2.schema.json').read_text())
    candidate = payload()
    candidate['authorization']['bridge_scope_sha256'] = 'f'*64
    candidate['authorization']['scope_sha256'] = authorization_scope_sha256(candidate)
    Draft202012Validator(worktree_schema).validate(candidate)
    with pytest.raises(ValidationError):
        Draft202012Validator(head_schema).validate(candidate)
    # Older /2 payloads without this optional field remain valid under both schemas.
    older = payload()
    Draft202012Validator(head_schema).validate(older)
    Draft202012Validator(worktree_schema).validate(older)


def test_malformed_nested_json_objects_fail_closed_without_crashing():
    for key in ("mission", "rover", "goal", "operator_limits", "authorization"):
        out = validate({"schema": SCHEMA, key: ["wrong-shape"]}, now=NOW)
        assert out["decision"] == "REJECTED"
        assert out["movement_authorized"] is False
