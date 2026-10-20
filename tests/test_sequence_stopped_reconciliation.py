"""Real project sequence records/workflow with doubled flight and Docker metadata."""
import json
from unittest.mock import Mock
from uuid import uuid4

from tests.test_preflight_sequences import system, start, run
from tests.test_execution_reconciliation import environment
from tests.test_stopped_environment_reconciliation import confirmation
from tools import execution_reconciliation as reconcile
from tools import preflight_sequences as sequences
from tools import vehicle_execution_lock as locks
from tools import virtual_preflight_jobs as jobs


def test_stopped_environment_closes_both_sequence_guards_without_repairing_either_child(system, tmp_path, monkeypatch):
    import graph.virtual_preflight_graph as graph
    from tools import virtual_preflight_worker as worker
    for module in (jobs,sequences,worker,graph):
        monkeypatch.setattr(module,'utc_now',lambda:'2026-10-18T21:18:50+00:00')
    original=system.flight.side_effect
    def execute(*args, **kwargs):
        if kwargs['vehicle']=='v2':
            raise RuntimeError('synthetic initial read failed, code 124; no inferred cause')
        return original(*args, **kwargs)
    system.flight.side_effect=execute
    admitted=start(system)
    assert run(system,admitted) is False
    sequence_id=admitted['sequence_id']
    children=admitted['plan']['children']
    paths=[sequences.directory(sequence_id)/'operation.json']
    paths.extend(jobs.run_directory(c['run_id'])/'report.json' for c in children)
    originals={p:p.read_bytes() for p in paths}
    assert json.loads(originals[paths[1]])['status']=='PASSED'
    assert json.loads(originals[paths[2]])['status']=='ERROR'
    guards={name:(locks.LOCK_ROOT/name).read_bytes() for name in ('sequence.json','v2.json')}
    assert all(json.loads(v)['state']=='UNCONFIRMED' for v in guards.values())
    # Responsible identities are now absent. This is a double, never killing real processes.
    monkeypatch.setattr(locks,'process_identity',lambda pid=None:None if pid else {'pid':123,'start_ticks':1,'boot_id':'test-boot'})
    monkeypatch.setattr(reconcile,'INSPECTION_ROOT',tmp_path/'inspections')
    monkeypatch.setattr(reconcile,'inspect_environment',Mock(return_value=environment(False)))
    telemetry=Mock(side_effect=AssertionError('No telemetry for terminated container'))
    monkeypatch.setattr(reconcile,'collect_observations',telemetry)
    ref=reconcile.INSPECTION_ROOT/str(uuid4());ref.mkdir(parents=True)
    locks.atomic_json(ref/'inspection.json',{'inspection_id':ref.name,'target_id':sequence_id,
        'status':'BLOCKED','reservations_changed':False,'exception_type':'RuntimeError',
        'created_at':'2026-10-19T18:38:58+00:00',
        'reasons':['RuntimeError: Read-only collector returned 1: Error response from daemon: container '+'a'*64+' is not running\n']})
    inspected=reconcile.inspect_execution_reconciliation(sequence_id)
    assert inspected['status']=='AWAITING_LEGACY_ENVIRONMENT_REVIEW'
    assert set(inspected['summary']['reservations'])=={'sequence.json','v2.json'}
    result=reconcile.apply_execution_reconciliation(inspected['inspection_id'],inspected['inspection_sha256'],
                                                    'Explicit administrative closure of this exact terminated SITL environment, no flight',
                                                    legacy_environment_confirmation=confirmation(inspected))
    assert result['status']=='APPLIED' and locks.restriction() is None
    for name,raw in guards.items():
        assert (locks.LOCK_ROOT/'history'/inspected['inspection_id']/name).read_bytes()==raw
    assert originals=={p:p.read_bytes() for p in paths}
    status=sequences.get_preflight_sequence(sequence_id=sequence_id)
    assert status['job_state']=='UNCONFIRMED' and status['result_status'] is None
    assert status['children'][0]['result_status']=='PASSED'
    assert status['children'][1]['observed_result_status']=='ERROR'
    assert status['global_flight_restriction'] is None
    telemetry.assert_not_called()
