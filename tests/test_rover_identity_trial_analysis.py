"""Immutable real passive input; no Docker, nodes, queries, movement or rewrites."""
import copy
import json
from pathlib import Path
import pytest
from tools import rover_passive_validation as v

TRIAL=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f'


def closure():
    def read(name):return json.loads((TRIAL/name).read_bytes())
    return dict(start_operation=read('start-operation/operation.json'),stop_operation=read('stop-operation/operation.json'),
        target=read('post-host-state.json')['target'],active_observation=read('known-process-observation.stdout'),
        cleanup=json.loads((TRIAL/'stop-operation/backend.log').read_text().splitlines()[0]))


def analyze(evidence):
    return v.analyze_reader(TRIAL/'reader/journal.jsonl',TRIAL/'reader/journal.jsonl.receipt.json',
        TRIAL/'container-capture/trace.log',TRIAL/'container-capture/monitor.json',closure_evidence=evidence)


def test_real_prefix_is_usable_but_never_complete_or_current():
    with pytest.raises(ValueError):analyze(None)
    r=analyze(closure())
    assert r['analysis_scope']=='SUPERVISED_PREFIX_WITH_UNOBSERVED_TERMINAL_MODEL_EXIT'
    assert not r['capture_complete'] and not r['monitor_channels']['core_capture_complete']
    assert sum(r['counts'].values())==14 and len(r['counts'])==6
    assert r['parameters']['state']=='UNKNOWN' and 'GUID unavailable' in r['parameters']['reason']
    assert r['odometry']['state']=='SAMPLE_TO_BRIDGE_PROCESS_OBSERVED'
    assert len(r['odometry_samples'])==3
    assert r['model_source']['state']=='MODEL_SOURCE_CONTEXT_OBSERVED_ONLY'
    assert r['model_entities']['state']=='EXACT_RUNTIME_ENTITY_CONTEXT_OBSERVED'
    assert {(e['model_entity'],e['catalog_label']) for e in r['model_entities']['entities']}=={(11,'drone1'),(67,'rover1'),(181,'drone2')}
    assert all(e['pose_observations']==4 for e in r['model_entities']['entities'])
    assert r['state']=='BLOCKED' and not r['movement_authorized'] and r['frame_transform']['state']=='UNKNOWN'


@pytest.mark.parametrize('change',['unknown_failure','different_session','cleanup_error','live_target','model_pid','library_changed'])
def test_incomplete_reader_analysis_requires_independent_same_context(change):
    e=closure()
    if change=='unknown_failure':e['active_observation']['monitor']['errors']=['PermissionError']
    elif change=='different_session':e['active_observation']['lifecycle_id']='other'
    elif change=='cleanup_error':e['cleanup']['remaining']=[{'pid':1}]
    elif change=='live_target':e['target']['state']='STARTED'
    elif change=='model_pid':e['cleanup']['signals']=[]
    else:e['active_observation']['monitor']['model_source']['library_sha256']='0'*64
    with pytest.raises(ValueError):analyze(e)


@pytest.mark.parametrize('change',['duplicate','label','missing'])
def test_entity_relationship_cannot_be_inferred_from_name_or_spawn(change):
    r=analyze(closure());data=v.read_journal(TRIAL/'reader/journal.jsonl',TRIAL/'reader/journal.jsonl.receipt.json')['records']
    catalog=next(e for e in data if e['kind']=='scene_catalog')
    if change=='duplicate':catalog['body'].append(copy.deepcopy(catalog['body'][1]))
    elif change=='label':catalog['body'][1]['name']='different'
    else:catalog['body']=[]
    result=v.correlate_model_entities(r['model_source'],data)
    assert result['state']=='UNKNOWN' and not result['entities'] and not result['identity_verified']


def test_zero_requester_guid_never_credits_even_a_matching_zero_native_field():
    from tests.test_rover_passive_validation import events
    rows=events();writer={**rows[0],'domain':0}
    for event in rows:
        if 'request_writer_guid' in event:event['request_writer_guid']='0'*32
    reply=dict(endpoint='/ap/v3/get_parameters',request_writer_guid='0'*32,request_sequence=8,values={'MAV_SYSID':3})
    assert v.correlate_parameter(reply,rows,writer)['state']=='UNKNOWN'
