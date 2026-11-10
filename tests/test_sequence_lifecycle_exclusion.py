from unittest.mock import Mock
from uuid import uuid4

import pytest

from tests.test_preflight_sequences import system, start, run
from tools import vehicle_execution_lock as locks
from tools import simulation_lifecycle as lifecycle
from tools import preflight_sequence_worker as coordinator
from tools import virtual_preflight_jobs as jobs


def test_lifecycle_and_both_admissions_cannot_interleave_in_gap_between_children(system,monkeypatch):
    original=coordinator.complete_sequence_child
    backend=Mock();monkeypatch.setattr(lifecycle,'_backend',backend)
    seen=[]
    def complete(owner,sha,index):
        original(owner,sha,index)
        if index==0:
            assert locks.restriction()==locks.sequence_restriction()
            assert locks.sequence_restriction()['active_child'] is None
            for action in ('start','stop','restart'):
                assert lifecycle.run_lifecycle(action)['status']=='BLOCKED'
            for vehicle in ('v1','v2'):
                with pytest.raises(locks.VehicleBusy):locks.reserve(str(uuid4()),'interloper',vehicle)
            assert jobs.start_virtual_preflight(system.paths[0],'gap-other-admission')['admission_status']=='VEHICLE_BUSY'
            seen.append('gap protected')
    monkeypatch.setattr(coordinator,'complete_sequence_child',complete)
    admitted=start(system)
    assert run(system,admitted) is True
    assert seen==['gap protected'] and system.order==['v1','v2']
    backend.assert_not_called()


def test_first_initial_read_failure_without_landing_evidence_stops_second_child(system):
    system.flight.side_effect=lambda path,**kw:{'status':'FAILED','success':False,'stage':'MISSION_EXECUTION',
        'mission_id':'drone_01_sequence','vehicle':'v1','vehicle_id':'drone_01','error':'initial read timed out',
        'events':[],'recovery':{'landing_attempted':False,'landing_completed':False},
        'control_outcome':'NOT_ATTEMPTED','control_attempts':[],'operation_diagnostics':{'initial':[{'operation':'read_origin','return_code':124}]}}
    admitted=start(system)
    assert run(system,admitted) is False
    assert system.flight.call_count==1
    assert locks.sequence_restriction()['state']=='UNCONFIRMED'
    second=admitted['plan']['children'][1]['run_id']
    assert jobs.get_virtual_preflight(run_id=second)['job_state']=='QUEUED'
