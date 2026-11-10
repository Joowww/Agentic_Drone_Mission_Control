"""JetRacer interface stub. It is intentionally incapable of physical actuation."""
from tools.rover_vehicle_contract import (ExecutionAuthorization, ExecutionFeedback, FailureSemantics,
    NavigationPlan, SteeringModel, StopSemantics, VehicleCapabilities, VehicleHealth, VehicleIdentity,
    VehicleLocalization, VehicleState, VehicleTelemetry)


class JetRacerDryRunAdapter:
    def identity(self):
        return VehicleIdentity(vehicle_id='jetracer-unconfigured',platform='Waveshare JetRacer Pro AI Kit',
                               firmware=None,hardware_revision=None)

    def capabilities(self):
        # Camera/Jetson/chassis are reported from the project description. Sensors requiring
        # runtime drivers, GPS, ROS, SLAM, encoders and actuator mappings remain unconfirmed.
        return VehicleCapabilities(steering_model=SteeringModel.ACKERMANN,max_speed_mps=None,
                                   sensors=('IMX219_CAMERA_UNVERIFIED_MODIFICATIONS',),position_sources=())

    def observe(self):
        return VehicleState(),VehicleHealth(healthy=None,detail='No hardware driver or sensor source configured')

    def localization(self):
        return VehicleLocalization(None,None,None,None,None,None,None,False)

    def telemetry(self):
        return VehicleTelemetry(None,None,None,None,None,None)

    def execute(self, plan: NavigationPlan, authorization: ExecutionAuthorization):
        return ExecutionFeedback(status='REFUSED_DRY_RUN_ONLY',state=None,
                                 error='No physical adapter is implemented; plan is not sent',physical_effect=False,
            failure_semantics=FailureSemantics(status='REFUSED',retry_allowed=False,state_known=False))

    def stop(self):
        return ExecutionFeedback(status='NO_PHYSICAL_OUTPUT',state=None,
                                 error='No actuator interface exists in this adapter',physical_effect=False,
            stop_semantics=StopSemantics(method='NO_PHYSICAL_OUTPUT',acknowledgement_required=False,
                confirmed_by_observation=False,residual_risk='No actuator interface is configured'),
            failure_semantics=FailureSemantics(status='NO_PHYSICAL_OUTPUT',retry_allowed=False,state_known=False))
