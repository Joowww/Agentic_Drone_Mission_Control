from types import SimpleNamespace
from tools.ardurover_contract_adapter import ArduRoverContractAdapter
from tools.jetracer_dry_run_adapter import JetRacerDryRunAdapter
from tools.rover_vehicle_contract import ExecutionAuthorization, NavigationPlan

def test_ardurover_adapter_only_maps_accredited_localization_and_refuses_command_path():
    adapter=ArduRoverContractAdapter(lambda: SimpleNamespace(pose_reference_validated=False,pose_frame='odom',
      position_m=(1,2,0),linear_mps=(.1,0,0),armed=False,mode=4,motion_source='/model/rover1/odometry',
      motion_received_monotonic_s=3,status_publisher_gid='a'*48,odometry_publisher_gid='b'*48,
      observation_provenance_sha256='c'*64,failsafe=()))
    state,health,localization,telemetry=adapter.observe()
    assert state.frame is None and state.x_m is None and localization.validated is False
    plan=NavigationPlan('p','odom',1,0,.1,10); auth=ExecutionAuthorization('d'*64,True)
    assert adapter.execute(plan,auth).physical_effect is False
    stopped=adapter.stop()
    assert stopped.physical_effect is False and stopped.stop_semantics.confirmed_by_observation

def test_jetracer_remains_actuator_free_and_does_not_claim_localization():
    adapter=JetRacerDryRunAdapter()
    state,health=adapter.observe()
    assert state.x_m is None and state.frame is None
    assert adapter.execute(NavigationPlan('p','map',1,0,.1,10),ExecutionAuthorization('e'*64,True)).physical_effect is False
    stopped=adapter.stop()
    assert stopped.physical_effect is False and not stopped.stop_semantics.confirmed_by_observation
