from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tools import simulation_lifecycle as lifecycle
from tools import simulation_control as control
from tools import vehicle_execution_lock as locks


@pytest.mark.parametrize('action',['start','stop','restart'])
def test_lifecycle_atomically_excludes_all_admissions_and_logs_without_stdio(monkeypatch,action):
    entered=Event();finish=Event();order=[]
    def backend(step,gui,fd,process,log):
        assert (locks.LOCK_ROOT/'lifecycle.json').exists()
        assert fd>=0 and process['start_ticks']>0
        order.append(step)
        entered.set();assert finish.wait(10)
        return 0
    monkeypatch.setattr(lifecycle,'_backend',backend)
    with ThreadPoolExecutor() as pool:
        future=pool.submit(lifecycle.run_lifecycle,action,gui=False)
        assert entered.wait(10)
        try:
            for v in ('v1','v2'):
                with pytest.raises(locks.VehicleBusy):locks.reserve(str(uuid4()),'other',v)
            with pytest.raises(locks.VehicleBusy):locks.reserve_sequence(str(uuid4()),'x',[])
            assert lifecycle.run_lifecycle('stop')['status']=='BLOCKED'
        finally:finish.set()
        assert future.result()['success'] is True
    assert order==(['stop','start'] if action=='restart' else [action])
    assert locks.restriction() is None


def test_any_flight_or_uncertain_reservation_prevents_lifecycle(monkeypatch):
    backend=Mock();monkeypatch.setattr(lifecycle,'_backend',backend)
    owner=str(uuid4());locks.reserve(owner,'fixture','v2');locks.mark_uncertain(owner,'v2')
    for action in ('start','stop','restart'):
        assert lifecycle.run_lifecycle(action)['status']=='BLOCKED'
    backend.assert_not_called()


def test_backend_timeout_keeps_durable_barrier_and_never_restarts(monkeypatch):
    backend=Mock(side_effect=subprocess.TimeoutExpired('fake backend',180))
    monkeypatch.setattr(lifecycle,'_backend',backend)
    result=lifecycle.run_lifecycle('restart')
    assert result['status']=='UNCONFIRMED' and backend.call_count==1
    with pytest.raises(locks.VehicleBusy):locks.reserve(str(uuid4()),'other','v1')
    assert lifecycle.run_lifecycle('start')['status']=='BLOCKED'


def test_all_python_wrappers_use_shared_lifecycle(monkeypatch):
    backend=Mock(return_value={'success':True});monkeypatch.setattr(lifecycle,'run_lifecycle',backend)
    control.start_simulation(gui=False);control.stop_simulation();control.restart_simulation(gui=True)
    assert [c.args[0] for c in backend.call_args_list]==['start','stop','restart']


def test_private_backend_requires_real_inherited_descriptor(monkeypatch):
    monkeypatch.delenv('TFG_LIFECYCLE_PROCESS',raising=False)
    with pytest.raises((KeyError,FileNotFoundError,locks.VehicleBusy)):
        lifecycle.verify_backend()


def test_live_executor_mutex_without_record_still_blocks_lifecycle(monkeypatch):
    backend=Mock();monkeypatch.setattr(lifecycle,'_backend',backend)
    assert locks.restriction() is None
    with locks.file_mutex(locks.LOCK_ROOT/'v1.execution.lock'):
        assert lifecycle.run_lifecycle('stop')['status']=='BLOCKED'
    backend.assert_not_called()
