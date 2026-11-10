import copy
import pytest

from tools.rover_stationarity import StationarityThresholds, analyze

LIFE='life-1'; BOOT='boot-1'; SGID='a'*48; OGID='b'*48
TH=StationarityThresholds(minimum_observations=6, minimum_duration_s=4, maximum_gap_s=2)


def capture(n=6):
    rows=[]
    for i in range(n):
        stamp=(i+1)*1_000_000_000
        rows.append({'lifecycle_id':LIFE,'host_boot_id':BOOT,'host_received_monotonic_s':float(i),
          'host_clock':'HOST_MONOTONIC_S','sample_metadata':{
            'status':{'stamp_ns':stamp,'received_monotonic_s':float(i)+.01,'stamp_clock':'SIMULATED_STAMP_NS','receipt_clock':'WORKER_MONOTONIC_S','clock':'WORKER_MONOTONIC_S'},
            'odometry':{'stamp_ns':stamp,'received_monotonic_s':float(i)+.01,'stamp_clock':'SIMULATED_STAMP_NS','receipt_clock':'WORKER_MONOTONIC_S','clock':'WORKER_MONOTONIC_S'}},
          'worker_telemetry_age_s':{'status':.05,'odometry':.05},'status':{'armed':False,'flying':False,'failsafe':[]},
          'status_publisher_gid':SGID,'odometry_publisher_gid':OGID,'frame_id':'odom','child_frame_id':'base_link','driving':False,
          'measurement_units':{'position':'m','linear_velocity':'m/s','angular_velocity':'rad/s','orientation':'quaternion_xyzw'},
          'position':{'x':0.,'y':0.,'z':0.},'orientation':{'x':0.,'y':0.,'z':0.,'w':1.},
          'linear_velocity':{'x':0.,'y':0.,'z':0.},'angular_velocity':{'x':0.,'y':0.,'z':0.}})
    return {'capture_complete':True,'records':rows,'movement_authorized':False,'commands_sent':0}


def run(c, **kw):
    return analyze(c,expected_lifecycle=LIFE,expected_boot_id=BOOT,expected_status_gid=SGID,
                   expected_odometry_gid=OGID,thresholds=TH,**kw)


def test_constant_position_and_small_bounded_noise_are_stationary():
    c=capture()
    for i,r in enumerate(c['records']): r['position']['x']=.002*(i%2)
    assert run(c)['verdict']=='STATIONARY_OBSERVED'

@pytest.mark.parametrize('mutator, reason', [
 (lambda c: [r['position'].__setitem__('x',i*.02) for i,r in enumerate(c['records'])], 'POSITION_DRIFT_EXCEEDED'),
 (lambda c: c['records'][3]['position'].__setitem__('x',.2), 'POSITION_DRIFT_EXCEEDED'),
 (lambda c: c['records'][2]['linear_velocity'].__setitem__('x',.2), 'LINEAR_SPEED_EXCEEDED'),
 (lambda c: c['records'][2].__setitem__('odometry_publisher_gid','c'*48), 'INVALID_OR_UNATTRIBUTED_OBSERVATIONS'),
 (lambda c: c['records'][2].__setitem__('lifecycle_id','other'), 'INVALID_OR_UNATTRIBUTED_OBSERVATIONS'),
 (lambda c: c['records'][2]['sample_metadata']['odometry'].__setitem__('stamp_ns',c['records'][1]['sample_metadata']['odometry']['stamp_ns']), 'SOURCE_STAMPS_NOT_STRICTLY_INCREASING'),
 (lambda c: c['records'][2]['sample_metadata']['status'].__setitem__('stamp_ns',99), 'SOURCE_STAMPS_NOT_STRICTLY_INCREASING'),
 (lambda c: c['records'][2]['worker_telemetry_age_s'].__setitem__('odometry',9), 'INVALID_OR_UNATTRIBUTED_OBSERVATIONS'),
 (lambda c: c['records'][2].__setitem__('position',None), 'INVALID_OR_UNATTRIBUTED_OBSERVATIONS'),
 (lambda c: c['records'][2].__setitem__('linear_velocity',None), 'INVALID_OR_UNATTRIBUTED_OBSERVATIONS'),
 (lambda c: c['records'][2].__setitem__('frame_id','map'), 'INVALID_OR_UNATTRIBUTED_OBSERVATIONS'),
 (lambda c: c['records'][2].__setitem__('host_boot_id','other'), 'INVALID_OR_UNATTRIBUTED_OBSERVATIONS'),
 (lambda c: c['records'][2]['status'].update(armed=True), 'INVALID_OR_UNATTRIBUTED_OBSERVATIONS'),
])
def test_fail_closed_cases(mutator, reason):
    c=capture(); mutator(c); report=run(c)
    assert report['verdict']=='UNCONFIRMED' and reason in report['reasons']
    assert report['movement_authorized'] is False


def test_status_and_odometry_source_timestamps_must_both_progress():
    c=capture(); c['records'][3]['sample_metadata']['status']['stamp_ns']=c['records'][2]['sample_metadata']['status']['stamp_ns']
    assert 'SOURCE_STAMPS_NOT_STRICTLY_INCREASING' in run(c)['reasons']


def test_large_gap_is_not_covered():
    c=capture(); c['records'][3]['host_received_monotonic_s']=10
    out=run(c); assert out['verdict']=='UNCONFIRMED' and 'TELEMETRY_GAP_EXCEEDED' in out['reasons']


def test_incomplete_capture_or_worker_close_is_unconfirmed():
    c=capture(); c['capture_complete']=False
    assert 'CAPTURE_INCOMPLETE' in run(c)['reasons']
    assert 'WORKER_CLOSE_UNCONFIRMED' in run(c,worker_closed=False)['reasons']


def test_report_contains_coverage_freshness_and_no_command_claim():
    out=run(capture())
    assert out['metrics']['coverage_s']==5 and out['metrics']['valid_percent']==100
    assert out['commands_sent']==0 and out['movement_authorized'] is False


def test_residual_angular_speed_and_orientation_change_are_rejected():
    c=capture(); c['records'][1]['angular_velocity']['z']=.1
    assert 'ANGULAR_SPEED_EXCEEDED' in run(c)['reasons']
    c=capture(); c['records'][1]['orientation']={'x':0.,'y':0.,'z':.2,'w':.98}
    assert 'ORIENTATION_CHANGE_EXCEEDED_OR_UNKNOWN' in run(c)['reasons']


def test_worker_receive_time_regression_and_missing_sample_metadata_are_rejected():
    c=capture(); c['records'][3]['sample_metadata']['odometry']['received_monotonic_s']=.02
    assert 'RECEIPT_TIMESTAMPS_NOT_STRICTLY_INCREASING' in run(c)['reasons']
    c=capture(); c['records'][2]['sample_metadata']['status']['stamp_ns']=None
    assert run(c)['verdict']=='UNCONFIRMED'


def test_pose_endpoints_yaw_drift_and_passive_provenance_are_reported():
    c=capture(); c['movement_authorized']=False; c['commands_sent']=0
    out=run(c); assert out['metrics']['pose_initial']['position_m']==[0.,0.,0.]
    assert out['metrics']['pose_final']['position_m']==[0.,0.,0.]
    assert out['metrics']['yaw_drift_max_rad']==pytest.approx(0)
    c['records'][2]['orientation']={'x':0.,'y':0.,'z':.2,'w':.98}
    assert 'YAW_DRIFT_EXCEEDED_OR_UNKNOWN' in run(c)['reasons']


def test_capture_with_commands_or_movement_authority_is_not_a_passive_proof():
    c=capture(); c['commands_sent']=1
    assert 'CAPTURE_NOT_PASSIVE_OR_COMMANDS_PRESENT' in run(c)['reasons']



def test_default_requires_at_least_100_observations():
    c=capture(99)
    out=analyze(c,expected_lifecycle=LIFE,expected_boot_id=BOOT,expected_status_gid=SGID,
                expected_odometry_gid=OGID,thresholds=StationarityThresholds(minimum_duration_s=4))
    assert 'OBSERVATION_COUNT_BELOW_MINIMUM' in out['reasons']
    assert out['verdict']=='UNCONFIRMED'


def test_rover_driving_and_units_are_required_per_observation():
    c=capture()
    c['records'][2]['driving']=True
    out=run(c)
    assert out['verdict']=='UNCONFIRMED'
    assert 'INVALID_OR_UNATTRIBUTED_OBSERVATIONS' in out['reasons']
    c=capture(); c['records'][1]['measurement_units']['linear_velocity']='km/h'
    assert 'INVALID_OR_UNATTRIBUTED_OBSERVATIONS' in run(c)['reasons']


def test_malformed_capture_is_fail_closed():
    out=analyze(None,expected_lifecycle=LIFE,expected_boot_id=BOOT,expected_status_gid=SGID,
                expected_odometry_gid=OGID)
    assert out['verdict']=='UNCONFIRMED'
    assert 'CAPTURE_INCOMPLETE' in out['reasons']



def test_full_procedure_default_thresholds_accept_only_100_valid_stationary_rows():
    c=capture(100)
    out=analyze(c,expected_lifecycle=LIFE,expected_boot_id=BOOT,expected_status_gid=SGID,
                expected_odometry_gid=OGID)
    assert out['verdict']=='STATIONARY_OBSERVED'
    assert out['observations_total']==out['observations_valid']==100
    assert out['metrics']['coverage_s']==99
    assert out['metrics']['valid_percent']==100
    assert out['movement_authorized'] is False


def test_report_wrapper_requires_expected_owner_identity_and_worker_close():
    from tools.rover_passive_report import analyze_capture
    assert analyze_capture({},lifecycle_id="",host_boot_id="h",status_gid="s",odometry_gid="o",
                           worker_closed=True)["reasons"]==["EXPECTED_SESSION_IDENTITY_MISSING"]
    # Empty capture remains fail closed even with identity labels.
    result=analyze_capture({},lifecycle_id="l",host_boot_id="h",status_gid="s",odometry_gid="o",
                           worker_closed=False)
    assert result["verdict"]=="UNCONFIRMED"
    assert "WORKER_CLOSE_UNCONFIRMED" in result["reasons"]
