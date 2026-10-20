"""Registered SDK contracts with backend doubles only, never operational MCP."""
import asyncio
from unittest.mock import Mock

import pytest

from tools import execution_reconciliation as backend
from tools import hermes_mcp_server as server
from tests.test_mission_response_views import registered


def test_registered_inspection_and_application_forward_reviewed_bindings(monkeypatch):
    inspect=Mock(return_value={'status':'BLOCKED','reasons':['synthetic']})
    apply=Mock(return_value={'status':'APPLIED','flight_authorized':False})
    monkeypatch.setattr(backend,'inspect_execution_reconciliation',inspect)
    monkeypatch.setattr(backend,'apply_execution_reconciliation',apply)
    assert registered('inspect_execution_reconciliation',{'target_id':'retained-id'})['status']=='BLOCKED'
    ground=[{'vehicle':v,'source':'OPERATOR_VISUAL','on_ground':True,'statement':'Operator sees vehicle resting on ground','observed_at_utc':'2026-10-19T12:00:00+00:00'} for v in ('v1','v2')]
    result=registered('apply_execution_reconciliation',{'inspection_id':'retained-inspection','inspection_sha256':'a'*64,
                       'authorization_statement':'Reconcile only','ground_confirmations':ground})
    assert result['flight_authorized'] is False
    assert apply.call_args.args==('retained-inspection','a'*64,'Reconcile only',ground)
    inspect.assert_called_once_with('retained-id')


def test_registered_ground_schema_has_explicit_source_and_true_claim_before_backend(monkeypatch):
    tools={t.name:t for t in asyncio.run(server.mcp.list_tools())}
    schema=tools['apply_execution_reconciliation'].input_schema
    model=schema['$defs']['GroundConfirmation']
    assert model['properties']['source']['const']=='OPERATOR_VISUAL'
    assert model['properties']['on_ground']['const'] is True
    assert set(model['required'])=={'vehicle','source','on_ground','statement','observed_at_utc'}
    call=Mock();monkeypatch.setattr(backend,'apply_execution_reconciliation',call)
    with pytest.raises(Exception):
        registered('apply_execution_reconciliation',{'inspection_id':'id','inspection_sha256':'a'*64,
                    'authorization_statement':'yes','ground_confirmations':[{'vehicle':'v2','source':'ARMED_FALSE'}]})
    call.assert_not_called()


def test_registered_termination_application_can_omit_inapplicable_ground_claims(monkeypatch):
    tools={t.name:t for t in asyncio.run(server.mcp.list_tools())}
    assert 'ground_confirmations' not in tools['apply_execution_reconciliation'].input_schema['required']
    apply=Mock(return_value={'status':'BLOCKED','reconciliation_basis':'ENVIRONMENT_TERMINATED'})
    monkeypatch.setattr(backend,'apply_execution_reconciliation',apply)
    result=registered('apply_execution_reconciliation',{'inspection_id':'reviewed-inspection','inspection_sha256':'a'*64,
                       'authorization_statement':'Administrative closure only'})
    assert result['reconciliation_basis']=='ENVIRONMENT_TERMINATED'
    apply.assert_called_once_with('reviewed-inspection','a'*64,'Administrative closure only',None)


def test_registered_legacy_review_schema_and_dispatch_preserve_structured_declaration(monkeypatch):
    tools={t.name:t for t in asyncio.run(server.mcp.list_tools())}
    schema=tools['apply_execution_reconciliation'].input_schema
    model=schema['$defs']['LegacyEnvironmentConfirmation']
    assert model['additionalProperties'] is False
    assert model['properties']['continuous_project_environment']['const'] is True
    assert model['properties']['wall_clock_comparison_supported']['const'] is True
    call=Mock(return_value={'status':'BLOCKED'});monkeypatch.setattr(backend,'apply_execution_reconciliation',call)
    claim={'source':'OPERATOR_ENVIRONMENT_REVIEW','engine_id':'reviewed-engine','container_id':'a'*64,
           'continuous_project_environment':True,'wall_clock_comparison_supported':True,
           'statement':'Operator reviewed project Docker deployment/selector continuity and wall clock records'}
    registered('apply_execution_reconciliation',{'inspection_id':'reviewed-id','inspection_sha256':'b'*64,
               'authorization_statement':'Administrative closure only','legacy_environment_confirmation':claim})
    call.assert_called_once_with('reviewed-id','b'*64,'Administrative closure only',None,legacy_environment_confirmation=claim)
    call.reset_mock();claim['continuous_project_environment']=False
    with pytest.raises(Exception):
        registered('apply_execution_reconciliation',{'inspection_id':'reviewed-id','inspection_sha256':'b'*64,
                   'authorization_statement':'yes','legacy_environment_confirmation':claim})
    call.assert_not_called()


def test_registered_start_and_restart_expose_gui_without_changing_defaults(monkeypatch):
    tools={t.name:t for t in asyncio.run(server.mcp.list_tools())}
    for name in ('start_simulation','restart_simulation'):
        assert tools[name].input_schema['properties']['gui']['default'] is True
    start=Mock(return_value={'status':'BLOCKED'});restart=Mock(return_value={'status':'BLOCKED'})
    monkeypatch.setattr(server,'start_simulation_backend',start)
    monkeypatch.setattr(server,'restart_simulation_backend',restart)
    registered('start_simulation',{'gui':False});registered('restart_simulation',{'gui':True})
    start.assert_called_once_with(gui=False);restart.assert_called_once_with(gui=True)


def test_registered_audit_query_never_calls_inspection_or_application(monkeypatch):
    read=Mock(return_value={'status':'BLOCKED','application':None})
    inspect=Mock(side_effect=AssertionError('query must not collect'))
    apply=Mock(side_effect=AssertionError('query must not apply'))
    monkeypatch.setattr(backend,'get_execution_reconciliation',read)
    monkeypatch.setattr(backend,'inspect_execution_reconciliation',inspect)
    monkeypatch.setattr(backend,'apply_execution_reconciliation',apply)
    assert registered('get_execution_reconciliation',{'inspection_id':'retained-id'})['status']=='BLOCKED'
    read.assert_called_once_with('retained-id');inspect.assert_not_called();apply.assert_not_called()


def test_registered_preflight_summary_preserves_failed_read_endpoint_without_full_trace(monkeypatch):
    failed={'operation':'read_origin','endpoint':'/ap/v2/gps_global_origin/filtered','return_code':124,
            'confirmed':False,'error':[{'type':'FlightControlError','message':'read failed'}]}
    full={'run_id':'retained-run','job_state':'FINISHED','result_status':'FAILED',
          'report':{'status':'FAILED','executor_result':{'status':'FAILED','control_outcome':'NOT_ATTEMPTED',
                    'operation_diagnostics':{'initial':[failed],'recent':[],'total_operations':1,'omitted_operations':0}}}}
    monkeypatch.setattr(server,'get_preflight_backend',Mock(return_value=full))
    short=registered('get_virtual_preflight',{'run_id':'retained-run'})
    raw=short['report']['executor_result']
    assert raw['control_outcome']=='NOT_ATTEMPTED'
    assert raw['operation_diagnostics']['failed_operations']==[failed]
    assert 'initial' not in raw['operation_diagnostics']
    assert registered('get_virtual_preflight',{'run_id':'retained-run','view':'detail'})==full
