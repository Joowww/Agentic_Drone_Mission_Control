"""Read-only mapping from the existing protected ArduRover adapter contract.

This class accepts an injected observation provider and refuses to execute.
Movement remains exclusively in rover_ground_executor/RoverControlCore.
"""
from tools.rover_vehicle_contract import (ExecutionFeedback, SteeringModel, VehicleCapabilities,
    FailureSemantics, StopSemantics, VehicleHealth, VehicleIdentity, VehicleLocalization, VehicleState, VehicleTelemetry)

class ArduRoverContractAdapter:
    def __init__(self, observation_provider=None):
        self._observation_provider=observation_provider

    def identity(self):
        return VehicleIdentity(vehicle_id='rover_01',platform='ArduRover SITL',firmware=None,hardware_revision=None)

    def capabilities(self):
        return VehicleCapabilities(steering_model=SteeringModel.UNKNOWN,max_speed_mps=None,
                                   sensors=('AP_DDS_STATUS','SIMULATOR_ODOMETRY'),
                                   position_sources=('ROS2_ODOMETRY_REQUIRES_CURRENT_MOTION_BINDING',))

    def observe(self):
        if self._observation_provider is None:
            return (VehicleState(),VehicleHealth(healthy=None,detail='No observation source injected'),
                    VehicleLocalization(None,None,None,None,None,None,None,False),
                    VehicleTelemetry(None,None,None,None,None,None))
        obs=self._observation_provider()
        validated=(getattr(obs,'pose_reference_validated',False) is True and bool(getattr(obs,'pose_frame',None))
                   and bool(getattr(obs,'status_publisher_gid',None)) and bool(getattr(obs,'odometry_publisher_gid',None)))
        pos=getattr(obs,'position_m',None) if validated else None
        state=VehicleState(x_m=pos[0] if pos else None,y_m=pos[1] if pos else None,z_m=pos[2] if pos else None,
                           frame=getattr(obs,'pose_frame',None) if validated else None,
                           speed_mps=(sum(v*v for v in obs.linear_mps)**0.5 if getattr(obs,'linear_mps',None) else None),
                           heading_rad=None,armed=getattr(obs,'armed',None),mode=str(getattr(obs,'mode',None)))
        loc=VehicleLocalization(state.x_m,state.y_m,state.z_m,state.frame,
              getattr(obs,'motion_received_monotonic_s',None),getattr(obs,'motion_source',None),
              getattr(obs,'observation_provenance_sha256',None),validated)
        telemetry=VehicleTelemetry(None,None,getattr(obs,'status_publisher_gid',None),
              getattr(obs,'odometry_publisher_gid',None),None,None)
        failsafe=tuple(str(v) for v in (getattr(obs,'failsafe',None) or ()))
        health=VehicleHealth(healthy=False if failsafe else None,failsafes=failsafe,
              detail='Localization is unverified' if not validated else 'Read-only observation')
        return state,health,loc,telemetry

    def localization(self):
        return self.observe()[2]

    def telemetry(self):
        return self.observe()[3]

    def execute(self, plan, authorization):
        return ExecutionFeedback(status='REFUSED_USE_PROTECTED_EXECUTOR',state=None,
            error='Submit proposals only through rover_ground_executor; this adapter has no command path',physical_effect=False,
            failure_semantics=FailureSemantics(status='PROPOSAL_ONLY',retry_allowed=False,state_known=False))

    def stop(self):
        return ExecutionFeedback(status='REFUSED_USE_PROTECTED_EXECUTOR',state=None,
            error='Stop semantics are owned by the protected rover executor',physical_effect=False,
            stop_semantics=StopSemantics(method='PROTECTED_ROVER_EXECUTOR',acknowledgement_required=True,
                confirmed_by_observation=True,residual_risk='Stop is not issued by contract adapter'),
            failure_semantics=FailureSemantics(status='PROPOSAL_ONLY',retry_allowed=False,state_known=False))
