from tools.rover_failsafe_metrics import analyze


def fixture():
    ident={'lifecycle_id':'life','host_boot_id':'boot','status_gid':'a'*48,'odometry_gid':'b'*48,'frame_id':'odom','child_frame_id':'base_link'}
    rows=[]
    # Known synthetic trace: 0.20 m/s, 0.5 s delay, then 0.10 m/s² deceleration.
    for i in range(7):
        t=i*0.5
        if t<=0.5: x=0.2*t; v=0.2
        else:
            dt=min(t-0.5,1.7); x=0.1+0.2*dt-0.05*dt*dt; v=max(0.0,0.2-0.1*dt)
        rows.append({**ident,'host_monotonic_s':t,'position_m':[x,0,0],'linear_velocity_mps':[v,0,0],
          'angular_velocity_rad_s':[0,0,0],'position_unit':'m','linear_velocity_unit':'m/s','angular_velocity_unit':'rad/s',
          'telemetry_age_s':{'status':0.05,'odometry':0.05},'status':{'armed':True,'failsafe':[]},
          'status_age':0.05,'odometry_age':0.05})
    return {'schema':'tfg.rover.failsafe-trace/1','source_class':'SYNTHETIC','capture_complete':True,
      'identity':ident,'loss_event':{'monotonic_s':0.5,'event_id':'loss-1'},'records':rows}


def test_synthetic_known_loss_and_stop_metrics_are_computed_without_claiming_hardware():
    out=analyze(fixture())
    assert out['verdict']=='OBSERVED_TRACE_METRICS'
    assert out['metrics']['initial_speed_mps']==0.2
    assert out['metrics']['loss_to_reaction_s']==0.5
    assert out['metrics']['stop_observed_and_held_through_capture']
    assert out['source_class']=='SYNTHETIC' and out['movement_authorized'] is False
    assert 'does not establish hardware behavior' in out['interpretation']


def test_identity_staleness_and_incomplete_trace_fail_closed():
    trace=fixture(); trace['records'][2]['odometry_gid']='c'*48
    assert 'SAMPLE_INVALID_OR_STALE' in analyze(trace)['reasons']
    trace=fixture(); trace['records'][1]['telemetry_age_s']['status']=1.0
    assert 'SAMPLE_INVALID_OR_STALE' in analyze(trace)['reasons']
    trace=fixture(); trace['capture_complete']=False
    assert analyze(trace)['verdict']=='UNCONFIRMED'
