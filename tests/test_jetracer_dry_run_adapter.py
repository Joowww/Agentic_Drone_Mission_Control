from tools.jetracer_dry_run_adapter import JetRacerDryRunAdapter
from tools.rover_vehicle_contract import NavigationPlan, ExecutionAuthorization, SteeringModel


def test_jetracer_adapter_declares_car_like_steering_without_inventing_sensors():
    a=JetRacerDryRunAdapter(); caps=a.capabilities(); state,health=a.observe()
    assert caps.steering_model is SteeringModel.ACKERMANN
    assert caps.position_sources==() and caps.max_speed_mps is None
    assert state.x_m is None and state.armed is None and health.healthy is None


def test_execution_and_stop_have_no_physical_effect():
    a=JetRacerDryRunAdapter(); plan=NavigationPlan('p','odom',1,0,.1,30)
    result=a.execute(plan,ExecutionAuthorization('a'*64,True)); stopped=a.stop()
    assert result.status=='REFUSED_DRY_RUN_ONLY' and not result.physical_effect
    assert stopped.status=='NO_PHYSICAL_OUTPUT' and not stopped.physical_effect
