"""Offline faults at the actual executor boundary, no Docker/ROS/control subprocess."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import simulation_mission_executor as executor
from tools import ros2_flight_control as ros
from tools import execution_diagnostics as diagnostics
from tests.test_virtual_preflight import EXAMPLE


@pytest.fixture
def mission(tmp_path, monkeypatch):
    data = json.loads(EXAMPLE.read_text())
    data['vehicle']['vehicle_id'] = 'drone_02'
    path = tmp_path/'mission.json'
    path.write_text(json.dumps(data))
    monkeypatch.setattr(executor, 'check_mission_execution_ready', lambda p: {'execution_authorized': True})
    for name in ('switch_vehicle_mode','arm_vehicle','takeoff_vehicle','land_vehicle','send_global_position_target'):
        monkeypatch.setattr(executor, name, Mock(side_effect=AssertionError('Unexpected control')))
    return path


def test_origin_124_has_exact_endpoint_and_no_recovery(mission, monkeypatch):
    run = Mock(return_value=SimpleNamespace(returncode=124, stdout='', stderr=''))
    monkeypatch.setattr(ros.subprocess, 'run', run)
    raw = executor.execute_approved_mission(str(mission), progress=False)
    assert raw['status']=='FAILED' and raw['events']==[]
    assert raw['control_outcome']=='NOT_ATTEMPTED' and raw['control_attempts']==[]
    assert raw['simulation_origin'] is None and raw['launch_position'] is None
    assert raw['recovery']['landing_attempted'] is False
    evidence = raw['operation_diagnostics']['initial'][0]
    assert evidence['endpoint']=='/ap/v2/gps_global_origin/filtered'
    assert evidence['vehicle_id']=='drone_02' and evidence['vehicle']=='v2'
    assert evidence['return_code']==124 and evidence['confirmed'] is False
    assert evidence['timeout_seconds']==15 and evidence['inner_timeout_seconds']==10
    assert evidence['elapsed_wall_seconds']>=0 and evidence['transport']['command'].startswith('timeout 10')
    assert raw['error_evidence'][0]['type']=='FlightControlError'
    executor.land_vehicle.assert_not_called()
    executor.switch_vehicle_mode.assert_not_called()
    assert run.call_count==1


def test_position_failure_keeps_origin_without_inventing_position(mission, monkeypatch):
    origin={'latitude':-35.,'longitude':149.,'altitude_amsl_m':584.}
    monkeypatch.setattr(executor,'get_vehicle_global_origin',Mock(return_value=origin))
    error = ros.FlightControlError('position parse failed')
    monkeypatch.setattr(executor,'get_vehicle_geopose',Mock(side_effect=error))
    raw=executor.execute_approved_mission(str(mission),progress=False)
    assert raw['simulation_origin']==origin and raw['launch_position'] is None
    assert [d['operation'] for d in raw['operation_diagnostics']['initial']]==['read_origin','read_position']
    assert raw['operation_diagnostics']['initial'][0]['observation']==origin
    assert raw['error_evidence'][0]['message']==str(error)
    assert raw['control_attempts']==[] and not raw['recovery']['landing_attempted']


def test_arm_timeout_marks_attempt_before_call_and_recovers_on_v2(mission, monkeypatch):
    pose={'latitude':-35.,'longitude':149.,'altitude_amsl_m':584.}
    monkeypatch.setattr(executor,'get_vehicle_global_origin',Mock(return_value=pose))
    monkeypatch.setattr(executor,'get_vehicle_geopose',Mock(return_value=pose))
    monkeypatch.setattr(executor,'switch_vehicle_mode',Mock(return_value={'success':True}))
    monkeypatch.setattr(executor,'arm_vehicle',Mock(side_effect=ros.FlightControlError('timeout; effects unknown')))
    land=Mock(return_value={'success':True}); monkeypatch.setattr(executor,'land_vehicle',land)
    monkeypatch.setattr(executor,'_wait_for_landing',Mock(return_value={'landed':True,'armed':False,'flying':False}))
    raw=executor.execute_approved_mission(str(mission),progress=False)
    attempts=raw['control_attempts']
    assert [(a['operation'],a['confirmed']) for a in attempts]==[('guided',True),('arm',False),('recovery_land',True)]
    assert attempts[1]['effects']=='UNCONFIRMED'
    land.assert_called_once_with(vehicle='v2')
    assert raw['recovery']['landing_completed'] is True
    executor.takeoff_vehicle.assert_not_called()


def test_bounded_diagnostics_keep_initial_fault_context_and_latest_operations():
    trace=diagnostics.OperationTrace('v1');token=diagnostics.current_trace.set(trace)
    try:
        for index in range(200):
            diagnostics.operation('read_status',lambda: {'sample':index})
    finally:
        diagnostics.current_trace.reset(token)
    evidence=trace.evidence()
    assert evidence['initial'][0]['observation']=={'sample':0}
    assert evidence['recent'][-1]['observation']=={'sample':199}
    assert evidence['omitted_operations']==88


def test_original_timeout_cause_is_preserved(mission, monkeypatch):
    import subprocess
    monkeypatch.setattr(ros.subprocess,'run',Mock(side_effect=subprocess.TimeoutExpired('docker read',15)))
    raw=executor.execute_approved_mission(str(mission),progress=False)
    assert [e['type'] for e in raw['error_evidence']]==['FlightControlError','TimeoutExpired']
    assert raw['operation_diagnostics']['initial'][0]['transport']['return_code'] is None


def test_initial_failure_is_persisted_by_real_workflow_with_analysis(mission, monkeypatch, tmp_path):
    import graph.virtual_preflight_graph as graph
    from tools.virtual_preflight import run_preflight_in_directory
    from uuid import uuid4
    monkeypatch.setattr(graph, 'check_simulation_ready', lambda: {'ready': True})
    monkeypatch.setattr(executor, 'get_vehicle_global_origin', Mock(side_effect=ros.FlightControlError('read-only failure')))
    directory=tmp_path/'preflight';directory.mkdir()
    report=run_preflight_in_directory(str(mission),str(uuid4()),directory)
    assert report['status']=='FAILED' and report['analysis']['passed'] is False
    assert report['executor_result']['control_outcome']=='NOT_ATTEMPTED'
    assert report['executor_result']['operation_diagnostics']['initial'][0]['endpoint'].startswith('/ap/v2/')
    assert json.loads((directory/'report.json').read_text())==report
