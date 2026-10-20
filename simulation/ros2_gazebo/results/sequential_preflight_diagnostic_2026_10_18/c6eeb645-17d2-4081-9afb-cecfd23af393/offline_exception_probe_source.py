import hashlib,json,tempfile
from pathlib import Path
from unittest.mock import patch,Mock
from models.mission_definition import MissionDefinition
import tools.simulation_mission_executor as executor
import graph.virtual_preflight_graph as graph
from tools.ros2_flight_control import FlightControlError
archive=Path(Path('/tmp/tfg_sequence_diagnostic_archive.txt').read_text())
content=(archive/'artifacts/missions/generated/preflights/1b69dfc7-0707-4b68-a009-062610418fe4/mission.json').read_bytes()
mission=MissionDefinition.model_validate_json(content)
results=[]
for failed in ['get_vehicle_global_origin','get_vehicle_geopose','switch_vehicle_mode']:
    with tempfile.TemporaryDirectory(prefix='tfg_readonly_diagnosis_') as temp:
        root=Path(temp);snapshot=root/'mission.json';snapshot.write_bytes(content)
        origin=Mock(return_value={'latitude':-35.36,'longitude':149.16,'altitude_amsl_m':584.})
        position=Mock(return_value={'latitude':-35.36,'longitude':149.16,'altitude_amsl_m':584.19})
        mode=Mock(side_effect=AssertionError('No live mode calls'))
        mocks={'get_vehicle_global_origin':origin,'get_vehicle_geopose':position,'switch_vehicle_mode':mode,
               'arm_vehicle':Mock(side_effect=AssertionError('No arm')),'takeoff_vehicle':Mock(side_effect=AssertionError('No takeoff')),
               'send_global_position_target':Mock(side_effect=AssertionError('No navigate')),'land_vehicle':Mock(side_effect=AssertionError('No LAND'))}
        mocks[failed].side_effect=FlightControlError('ROS2 command failed with return code 124:\n')
        state={'run_id':'offline-diagnostic-probe','source_path':str(snapshot),'snapshot_path':str(snapshot),'report_path':str(root/'report.json'),
               'mission_sha256':hashlib.sha256(content).hexdigest(),'mission':mission,'vehicle_selection':{'vehicle_id':'drone_02','simulated_vehicle':'v2'},
               'status':'RUNNING','stage':'execute','executor_result':None,'analysis':None,'reasons':[]}
        with patch.object(executor,'check_mission_execution_ready',return_value={'execution_authorized':True}),patch.multiple(executor,**mocks),patch.object(graph,'execute_approved_mission',executor._execute_resolved_mission.__wrapped__):
            update=graph.execute_node.__wrapped__(state)
        assert not any(mocks[name].called for name in ['arm_vehicle','takeoff_vehicle','send_global_position_target','land_vehicle'])
        if failed!='switch_vehicle_mode':
            assert update['status']=='ERROR' and update.get('executor_result') is None and not mode.called
        else:
            assert update['executor_result']['status']=='FAILED'
        results.append({'injected_failure':failed,'graph_update':update,'mock_calls':{k:m.call_count for k,m in mocks.items()},'flight_commands_emitted':False,'note':'Offline doubles and temporary files; does not identify which read failed historically'})
with (archive/'offline_exception_probes.json').open('x',encoding='utf8') as f:json.dump(results,f,indent=2);f.write('\n')
print('3 offline exception boundary probes passed; both initial reads propagate to ERROR/null, mode error returns structured FAILED. No real control calls.')
