"""Read-only check, against the REAL project state, that the change opened nothing.

No container, simulator, ROS, reservation, lease, disposition or job is started,
written, applied or released. Run from the repository root.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from tools import rover_ground_executor as ground  # noqa: E402
from tools import vehicle_execution_lock as locks  # noqa: E402
from tools.rover_xrce_trace import historical_disposition as d  # noqa: E402
from tools.rover_xrce_trace.present_recovery import reader_hashes  # noqa: E402

OWNER = '891dab60-75f4-4008-b63d-2623ca5221a4'
GENERATED = locks.LOCK_ROOT.parent


def tree():
    return {str(p.relative_to(GENERATED)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(GENERATED.rglob('*')) if p.is_file() and not p.is_symlink()}


before = tree()
checks = {
    'git_head': subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(),
    'host_boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    'operational_rover_enabled': ground.OPERATIONAL_ROVER_ENABLED,
    'reservations': {v: locks.restriction(v) for v in locks.RESERVATION_INTERFACES},
    'infrastructure_restriction': locks.infrastructure_restriction(),
    'current_reader_pin': reader_hashes()[d.SUCCESSOR_PIN],
    'precheck': {k: v for k, v in d.current_diagnostic_precheck().items()
                 if k in ('status', 'precheck_satisfied', 'reason', 'disposition_consumed',
                          'opening_authorized', 'movement_authorized')},
    'successor_dry_run': {k: v for k, v in d.real_dry_run(present=True, successor_owner=OWNER).items()
                          if k in ('status', 'reason', 'scope_sha256', 'opening_authorized')},
}
stores = {}
for folder in sorted((GENERATED/'historical_dispositions').iterdir()):
    result = d.ProjectDisposition(folder.name).query()
    stored = json.loads((folder/'intent.json').read_bytes())
    stores[folder.name] = {'status': result.get('status'), 'stored_status': stored.get('status'),
                           'scope_sha256': result.get('scope_sha256'),
                           'revisions_present': (folder/'revisions').exists(),
                           'chain_fields_added': 'consumer_chain' in result or 'consumer_successor' in result}
checks['historical_stores'] = stores
checks['generated_state_unchanged'] = tree() == before
print(json.dumps(checks, indent=2, default=str))
