"""Offline fake clients only; never invokes Docker, ROS or prearm services."""
import json
import subprocess
import sys
from unittest.mock import Mock

import pytest

from tools import prearm_diagnostics as diag
from tools import simulation_status as status
from tools.simulation_profiles import TWO_DRONES_ROVER


def response(success=True, message='Vehicle is Armable'):
    return f'response:\nstd_srvs.srv.Trigger_Response(success={success!r}, message={message!r})\n'


@pytest.mark.parametrize('code,out,err,deadline,expected',[
    (0,response(),'',False,'ACCEPTED'),
    (0,response(False,'Vehicle is Not Armable'),'',False,'NEGATIVE_RESPONSE'),
    (1,'','Service not available',False,'SERVICE_UNAVAILABLE'),
    (1,'Service unavailable','',False,'SERVICE_UNAVAILABLE'),
    (0,response(),'previous service not available',False,'ACCEPTED'),
    (124,'waiting for service to become available...','timeout: sending signal TERM to command ros2',False,'TIMEOUT'),
    (124,'','',False,'EXECUTION_ERROR'),
    (127,'','ros2: command not found',False,'EXECUTION_ERROR'),
    (1,response(),'',False,'EXECUTION_ERROR'),
    (0,'success=True','',False,'UNINTERPRETABLE_RESPONSE'),
    (0,response(),'',True,'TIMEOUT'),
    (0,'waiting for service to become available...','',False,'UNINTERPRETABLE_RESPONSE'),
])
def test_outcomes_do_not_invent_autopilot_reasons(code,out,err,deadline,expected):
    r=diag.classify(code,out,err,timed_out=deadline)
    assert r['outcome']==expected
    assert r['response'] is None or r['response']['message'] in ('Vehicle is Armable','Vehicle is Not Armable')


@pytest.mark.parametrize('text',[
    'request: success=True',
    'response:\nstd_srvs.srv.Trigger_Response(success="True", message="x")',
    'response:\nstd_srvs.srv.Trigger_Response(success=True)',
    'response:\nstd_srvs.srv.Trigger_Response(success=True, message="x", other=2)',
    'response:\n__import__("os").system("never execute")',
    'response:\nstd_srvs.srv.Trigger_Response(success=True, message="x")\nunrelated output',
])
def test_uninterpretable_response_fails_closed(text):
    assert diag.parse_response(text) is None


def test_valid_escaped_message_and_real_generated_type():
    message="Not armable: 'quote', commas, (parentheses)\nsecond line"
    text=response(False,message).replace('std_srvs.srv.Trigger_Response','std_srvs.srv._trigger.Trigger_Response')
    assert diag.parse_response(text)=={'success':False,'message':message}


def test_streamed_partial_output_survives_real_local_client_timeout():
    events=[]
    command=[sys.executable,'-u','-c',
             'import sys,signal; print("waiting for service to become available..."); '
             'print("client stderr before deadline",file=sys.stderr,flush=True); signal.pause()']
    result=diag.run_attempt('/ap/v3/prearm_check',2,events.append,command=command,timeout_s=.5)
    assert events[0]['event']=='started' and events[-1]['event']=='completed'
    assert any(e['event']=='output' and e['stream']=='stdout' for e in events)
    assert any(e['event']=='output' and e['stream']=='stderr' for e in events)
    assert result['outcome']=='TIMEOUT' and result['timed_out']
    assert result['return_code'] is not None
    assert result['service_type']=='std_srvs/srv/Trigger' and result['attempt']==2
    assert result['timeout_s']==.5 and result['duration_wall_s']>=.5
    assert 'waiting for service' in result['stdout']
    assert result['stderr']=='client stderr before deadline\n'
    assert result['response'] is None
    # An exterior readiness timeout may capture only start + output, not completion.
    partial='\n'.join(diag.EVENT_PREFIX+json.dumps(e) for e in events[:-1])
    record=status._prearm_attempts(TWO_DRONES_ROVER,partial)[0]
    assert record['outcome']=='INCOMPLETE_AT_CAPTURE' and record['return_code'] is None
    assert record['duration_wall_s'] is None and record['timed_out'] is None
    assert record['stdout']==result['stdout'] and record['stderr']==result['stderr']


def test_execution_spawn_error_is_persisted(monkeypatch):
    monkeypatch.setattr(diag.subprocess,'Popen',Mock(side_effect=FileNotFoundError('missing fake client')))
    events=[]
    result=diag.run_attempt('/ap/v1/prearm_check',1,events.append)
    assert result['outcome']=='EXECUTION_ERROR' and result['return_code'] is None
    assert result['execution_error'].startswith('FileNotFoundError:')
    assert result['command'][-1]=='/ap/v1/prearm_check'
    assert result['timeout_s']==30


def test_progress_prefix_and_attempt_journal_in_readiness_timeout(monkeypatch):
    events=[]
    result=diag.run_attempt('/ap/v1/prearm_check',1,events.append,
        command=[sys.executable,'-u','-c',f'print({response(False)!r})'])
    assert result['outcome']=='NEGATIVE_RESPONSE'
    stdout='...TFG_READINESS_VEHICLE /ap/v1 status PASS\n.TFG_READINESS_VEHICLE /ap/v1 prearm FAIL\n'
    stdout+='\n'.join('.'+diag.EVENT_PREFIX+json.dumps(e) for e in events)
    # A later explicit observation replaces FAIL, even with the old dot prefix.
    stdout+='\n.TFG_READINESS_VEHICLE /ap/v1 prearm PASS\n'
    run=Mock(side_effect=subprocess.TimeoutExpired('fake',180,output=stdout.encode(),stderr=b''))
    monkeypatch.setattr(status.subprocess,'run',run)
    r=status.check_simulation_ready('two_drones_rover')
    assert r['ready'] is False and r['timed_out']
    v=r['vehicles'][0]
    assert v['status_last_observed']==v['prearm_last_observed']=='PASS'
    assert v['prearm_attempts'][0]['response']['success'] is False
    assert v['prearm_attempts'][0]['stdout']==result['stdout']
    assert v['prearm_attempts'][0]['completed']
    assert r['vehicles'][2]['prearm_attempts']==[]
    assert run.call_args.kwargs['timeout']==180
