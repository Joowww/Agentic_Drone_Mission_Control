"""SITL-only trial policy for one rover navigation; INACTIVE, checked by the executor.

OPERATIONAL_ROVER_ENABLED stays False and is not touched here. This module only
defines what a future, separately reviewed integration would require before one
SITL trial: the exact container execution, host boot, lifecycle start, profile,
vehicle, mission, goal and session-bound motion binding, plus an exact operator
declaration over that scope. The executor rejects legacy scopes without a complete
control contract. It grants nothing while SITL_TRIAL_POLICY_ENABLED is
False, and no caller, environment variable or argument can change that.
"""
from planning.artifact_store import fingerprint

SITL_TRIAL_POLICY_ENABLED = False
AUTHORIZATION_PREFIX = 'AUTHORIZE_ROVER_SITL_TRIAL'
PROFILES = ('rover_only', 'two_drones_rover')


def trial_scope(*, environment_execution, host_boot_id, lifecycle_id, profile, mission_sha256,
                goal_sha256, binding_evidence_sha256, request=None, control_context=None):
    scope = {'schema': 'tfg.rover.sitl-trial-scope/1', 'vehicle_id': 'rover_01', 'interface': 'v3',
            'environment_execution': environment_execution, 'host_boot_id': host_boot_id,
            'lifecycle_id': lifecycle_id, 'profile': profile, 'mission_sha256': mission_sha256,
            'goal_sha256': goal_sha256, 'binding_evidence_sha256': binding_evidence_sha256,
            'simulation_only': True, 'max_trials': 1}
    if request is not None:
        scope.update(schema='tfg.rover.sitl-trial-scope/2', request_contract_sha256=request_contract(request),
                     control_context=control_context)
    return scope


def request_contract(request):
    """All control parameters, excluding only the scope/declaration which would hash itself."""
    return fingerprint({k: v for k, v in request.items() if k != 'sitl_trial'})


def expected_authorization(scope):
    return f'{AUTHORIZATION_PREFIX} {fingerprint(scope)}'


def evaluate(scope, authorization, current):
    """BLOCKED unless enabled AND every bound fact matches the current observation."""
    reasons = []
    if not SITL_TRIAL_POLICY_ENABLED:
        reasons.append('SITL_TRIAL_POLICY_DISABLED')
    if scope.get('max_trials') != 1 or type(scope.get('max_trials')) is not int:
        reasons.append('EXACTLY_ONE_TRIAL_REQUIRED')
    if scope.get('profile') not in PROFILES:
        reasons.append('PROFILE_NOT_SITL_ROVER')
    if (scope.get('vehicle_id'), scope.get('interface'), scope.get('simulation_only')) != ('rover_01', 'v3', True):
        reasons.append('VEHICLE_OR_SCOPE_NOT_SITL_ROVER')
    if authorization != expected_authorization(scope):
        reasons.append('EXACT_OPERATOR_AUTHORIZATION_ABSENT')
    for key in ('environment_execution', 'host_boot_id', 'lifecycle_id', 'profile', 'binding_evidence_sha256'):
        if current.get(key) != scope.get(key):
            reasons.append('CURRENT_' + key.upper() + '_DIFFERS')
    if current.get('trials_consumed', 0) >= scope.get('max_trials', 0):
        reasons.append('TRIAL_ALREADY_CONSUMED')
    return {'status': 'BLOCKED' if reasons else 'AUTHORIZED_FOR_THIS_SCOPE', 'reasons': reasons,
            'scope_sha256': fingerprint(scope), 'movement_authorized': not reasons,
            'authorization_basis': 'EXACT_DECLARATION_NOT_AUTHENTICATED_IDENTITY'}
