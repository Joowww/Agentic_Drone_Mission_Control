"""Metadata-only Docker probe, fully doubled; no actual Docker executable."""
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import reconciliation_environment as probe
from tests.test_execution_reconciliation import environment


def outputs(value=None):
    value = value or environment(False)
    metadata = {k:value[k] for k in ('container_id','name','created_at','image_id','state')}
    return [json.dumps(value['engine_id']),value['container_id'],json.dumps(metadata),value['container_id'],json.dumps(value['engine_id'])]


def mock_cli(monkeypatch, values):
    def run(*args, **kwargs):
        item = next(values)
        if isinstance(item, Exception): raise item
        if isinstance(item, tuple): return SimpleNamespace(returncode=item[0], stdout='', stderr=item[1])
        return SimpleNamespace(returncode=0, stdout=item, stderr='')
    call = Mock(side_effect=run)
    monkeypatch.setattr(probe.subprocess,'run',call)
    return call


@pytest.mark.parametrize('active',[True,False])
def test_exact_metadata_classifies_active_and_stopped_without_exec_or_secrets(monkeypatch,active):
    call = mock_cli(monkeypatch, iter(outputs(environment(active))))
    value = probe.inspect_environment()
    assert value['status'] == ('ACTIVE' if active else 'STOPPED')
    assert value['unknown_fields']==[]
    assert len(value['operations'])==5
    assert {c.args[0][1] for c in call.call_args_list}=={'info','ps','inspect'}
    assert all(c.kwargs['timeout']==3 and c.kwargs['check'] is False for c in call.call_args_list)
    assert all('Config.Env' not in str(c.args) for c in call.call_args_list)


@pytest.mark.parametrize('failure',[FileNotFoundError('docker missing'), subprocess.TimeoutExpired(['docker','info'],3), (1,'daemon unavailable')])
def test_inaccessible_docker_is_not_stopped_and_preserves_precise_failure(monkeypatch,failure):
    call=mock_cli(monkeypatch,iter([failure]))
    value=probe.inspect_environment()
    assert value['status']=='DOCKER_UNAVAILABLE'
    assert 'container_id' in value['unknown_fields'] and value['reasons']
    assert len(value['operations'])==1 and call.call_count==1


def test_missing_name_with_accessible_daemon_is_absent_not_stopped(monkeypatch):
    mock_cli(monkeypatch,iter(['"engine"','']))
    value=probe.inspect_environment()
    assert value['status']=='CONTAINER_ABSENT' and value['engine_id']=='engine'
    assert 'state' in value['unknown_fields']


def test_partial_metadata_keeps_engine_container_identity_and_explicit_missing_state_fields(monkeypatch):
    value=environment(False);value['state']={}
    mock_cli(monkeypatch,iter(outputs(value)))
    result=probe.inspect_environment()
    assert result['status']=='UNKNOWN'
    assert result['container_id']=='a'*64 and result['engine_id']=='synthetic-engine'
    assert 'state.StartedAt' in result['unknown_fields'] and 'state.Running' in result['unknown_fields']
    assert result['reasons']


@pytest.mark.parametrize('change',['pid','running','restarting','paused','dead','created','finish','timestamp_type','wrong_name','id_changed','engine_changed','inspect_failed'])
def test_contradictory_or_changed_metadata_never_proves_termination(monkeypatch,change):
    value=environment(False)
    if change=='pid':value['state']['Pid']=12
    elif change=='running':value['state']['Running']=True
    elif change in ('restarting','paused','dead'):value['state'][change.capitalize()]=True
    elif change=='created':value['state']['Status']='created'
    elif change=='finish':value['state']['FinishedAt']='0001-01-01T00:00:00Z'
    elif change=='timestamp_type':value['created_at']=None
    elif change=='wrong_name':value['name']='/unrelated-container'
    values=outputs(value)
    if change=='id_changed': values[3]='f'*64
    if change=='engine_changed':values[4]='"another-engine"'
    if change=='inspect_failed':values[2]=(1,'no such object')
    mock_cli(monkeypatch,iter(values))
    result=probe.inspect_environment()
    assert result['status']=='UNKNOWN' and result['reasons']
    assert result['engine_id']=='synthetic-engine'
