"""Read-only check of the conditions that block the first rover SITL motion.

No simulator, Docker, ROS, reservation, lease or job is started, written or
released. The executor calls below return BLOCKED before any filesystem write.
Run from the repository root: .venv/bin/python <this file>
"""
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from tools import rover_ground_executor as ground  # noqa: E402
from tools import vehicle_execution_lock as locks  # noqa: E402
from tools.rover_control import RoverControlCore  # noqa: E402
from tools.rover_environment_identity import RoverEnvironmentGuard  # noqa: E402
from tools import rover_ros2_adapter as ros  # noqa: E402
from tools.simulation_profiles import ACTIVE_PROFILE, get_profile  # noqa: E402


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def tree(path):
    return sorted(str(p.relative_to(path)) for p in path.rglob('*')) if path.exists() else None


checks = {}

checks['git'] = {'branch': git('rev-parse', '--abbrev-ref', 'HEAD'), 'head': git('rev-parse', 'HEAD'),
                 'status_porcelain': git('status', '--porcelain')}

rover = get_profile('two_drones_rover')
checks['profile'] = {'active_default': ACTIVE_PROFILE.name,
                     'rover_vehicles': [v.__dict__ for v in rover.vehicles if v.vehicle_id == 'rover_01'],
                     'launch_file': rover.launch_file, 'ports': rover.sitl_ports_awaited_before_start}

checks['executor_facts'] = ground.executor_facts()

before = tree(ground.RUN_ROOT)
checks['admit_ground_trial'] = ground.admit_ground_trial('does-not-exist.json', 'probe', {}, {})
checks['start_ground_trial'] = ground.start_ground_trial('00000000-0000-4000-8000-000000000000', {})
checks['run_root_unchanged'] = tree(ground.RUN_ROOT) == before

try:
    ground._request({'kind': 'ROVER_NAVIGATE_V1', 'limits': {}, 'goal': {}, 'preparation': {}})
    checks['navigation_preparation_rejected'] = False
except ValueError as exc:
    checks['navigation_preparation_rejected'] = str(exc)

navigate = inspect.getsource(RoverControlCore.navigate)
preparation = inspect.getsource(ros._assert_preparation_scope)
checks['navigation_requires_preexisting_arm'] = (
    'Navigation requires already armed GUIDED/external-control status' in navigate)
checks['arm_and_guided_only_for_pulse_preparation'] = (
    "request.get('kind')!='ROVER_PULSE_V1'" in preparation and 'GUIDED_ARM_AFTER_STATIONARY_V1' in preparation)

try:
    RoverEnvironmentGuard({}, lambda: {}).require_motion_source()
    checks['legacy_identity_guard'] = 'NOT_BLOCKED'
except RuntimeError as exc:
    checks['legacy_identity_guard'] = str(exc)

producers = []
for relative in git('ls-files', '*.py').splitlines():
    path = ROOT / relative
    if relative.startswith('tests/') or not path.is_file():
        continue
    lines = [n for n, line in enumerate(path.read_text(errors='replace').splitlines(), 1)
             if 'MotionBinding(' in line and 'class MotionBinding' not in line]
    if lines:
        producers.append({'file': relative, 'lines': lines})
checks['motion_binding_producers_outside_tests'] = producers
checks['host_rclpy_available'] = importlib.util.find_spec('rclpy') is not None

checks['lock_root_files'] = tree(locks.LOCK_ROOT)
checks['reservations'] = {v: locks.restriction(v) for v in locks.RESERVATION_INTERFACES}
session = locks.LOCK_ROOT.parent / 'diagnostic_agent_session.json'
target = json.loads(session.read_text()) if session.exists() else None
checks['diagnostic_session'] = None if target is None else {
    'state': target.get('state'), 'lifecycle_id': target.get('descriptor', {}).get('lifecycle_id'),
    'closed_by': target.get('closed_by')}

print(json.dumps(checks, indent=2, default=str))
