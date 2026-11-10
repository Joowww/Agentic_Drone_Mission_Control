"""Controller progress policies; synthetic coordinates, no ROS/operations."""
from dataclasses import asdict,replace
import math
import pytest
from tools.rover_control import GoalController, NavigationGoal, RoverControlError
from tests.test_rover_navigation import LIMITS
from tests.test_rover_ground_executor import setup  # temporary project, TEST-ONLY policy

GOAL=NavigationGoal(.8,.4,.2,'odom','m','IDENTITY_SAME_ACCREDITED_FRAME',.05,math.pi,5.,10.,120.,10.,.5,.01,256)

def arrived(goal=GOAL):
    c=GoalController(goal,LIMITS)
    c.step(0.,0.,.2,0.)
    c.step(.8,.4,.2,2.)
    return c


def test_slow_recovery_uses_new_spatial_watermarks_without_changing_parameters():
    before=asdict(GOAL);c=arrived()
    for now in (3.,6.,9.,12.5):
        d=c.step(.5+(now-3)*.02,.4,.2,now)
        assert d['phase']=='RECOVERY' and d['progress_quantum_m']==.05
    assert not c.step(.8,.4,.2,16.)['reached']
    assert c.step(.8,.4,.2,21.)['reached']
    assert asdict(GOAL)==before and GOAL.progress_m==.5


def test_recovery_below_meaningful_resolution_can_still_fail_by_policy():
    c=arrived();c.step(.5,.4,.2,3.)
    with pytest.raises(RoverControlError,match='NO_PROGRESS'):
        c.step(.501,.4,.2,13.)  # positive slope alone is not sufficient


def test_approach_retains_authorized_progress_m():
    c=GoalController(GOAL,LIMITS);yaw=math.atan2(.4,.8)
    assert c.step(0.,0.,yaw,0.)['progress_quantum_m']==.5
    with pytest.raises(RoverControlError,match='NO_PROGRESS'):
        c.step(.1,.05,yaw,11.)


def test_oscillation_does_not_recount_recovered_distance():
    c=arrived()
    for now,x in ((3.,.5),(5.,.56),(7.,.5),(9.,.56),(11.,.5),(13.,.56)):
        c.step(x,.4,.2,now)
    # First 6 cm improvement counts; revisiting that same minimum does not.
    with pytest.raises(RoverControlError,match='NO_PROGRESS'):c.step(.5,.4,.2,15.)

@pytest.mark.parametrize('recovery',[False,True])
def test_stationary_outside_goal_times_out(recovery):
    c=arrived() if recovery else GoalController(GOAL,LIMITS)
    start=3. if recovery else 0.
    c.step(.5,.4,.2,start)
    with pytest.raises(RoverControlError,match='NO_PROGRESS'):c.step(.5,.4,.2,start+10.)


def test_boundary_flicker_does_not_renew_progress_clock():
    c=arrived()
    with pytest.raises(RoverControlError,match='NO_PROGRESS'):
        for n in range(1,30):
            c.step(.8-(.051 if n%2 else .049),.4,.2,2.+n*.5)


def test_repeated_genuine_recoveries_cannot_extend_global_timeout():
    goal=replace(GOAL,timeout_s=30.)
    c=GoalController(goal,LIMITS);c.step(.8,.4,.2,0.)
    with pytest.raises(RoverControlError,match='GOAL_TIMEOUT'):
        for n in range(1,40):
            c.step(.5 if n%4 in (1,2) else .8,.4,.2,float(n))
    assert c.started==0.


def test_valid_dwell_is_not_stuck_approach_even_when_longer_than_progress_window():
    goal=replace(GOAL,dwell_s=12.,timeout_s=30.)
    c=GoalController(goal,LIMITS)
    c.step(.8,.4,.2,0.)
    assert not c.step(.8,.4,.2,11.)['reached']
    assert c.step(.8,.4,.2,12.)['reached']


def test_inside_but_moving_does_not_pause_stagnation_budget():
    c=GoalController(GOAL,LIMITS);c.step(.8,.4,.2,0.,linear_speed=.1)
    with pytest.raises(RoverControlError,match='NO_PROGRESS'):c.step(.8,.4,.2,11.,linear_speed=.1)


def test_inside_but_moving_keeps_existing_zero_command_and_can_recover():
    c=GoalController(GOAL,LIMITS)
    decision=c.step(.8,.4,.1,0.,linear_speed=.1)
    assert decision['forward_mps']==decision['yaw_rate_rad_s']==0.
    c.step(.5,.4,.2,1.)
    for now in (4.,7.,10.,12.):
        assert c.step(.5+(now-1)*.02,.4,.2,now)['phase']=='RECOVERY'


def test_dwell_does_not_pause_global_deadline():
    c=GoalController(replace(GOAL,dwell_s=40.,timeout_s=30.),LIMITS)
    c.step(.8,.4,.2,0.)
    with pytest.raises(RoverControlError,match='GOAL_TIMEOUT'):c.step(.8,.4,.2,30.)


def test_slow_recovery_crosses_worker_adapter_and_authorized_closure(setup,monkeypatch):
    """Real protected workflow; only observations/kinematics are synthetic."""
    from tests import test_rover_navigation as nav
    from tools import rover_ground_executor as ground, vehicle_execution_lock as locks

    class SlowRecovery(nav.Session):
        def observe(self,**kw):
            if self.reads==40:
                self.x-=.3
                self.displaced=True
            return super().observe(**kw)

        def exchange(self,command,**kw):
            reply=super().exchange(command,**kw)
            if getattr(self,'displaced',False):self.v=min(self.v,.02)
            return reply

    monkeypatch.setattr(nav,'Session',SlowRecovery)
    report,session,admission=nav.execute(setup,pose=(.8,.4,.2),goal=GOAL,
        limits=replace(LIMITS,max_duration_s=130.),
        finalization={'kind':'DISARM_AFTER_OBSERVED_STOP_V1','timeout_s':3.})
    decisions=report['result']['decisions']
    recovery=[d for d in decisions if d['phase']=='RECOVERY']
    assert recovery[-1]['received_monotonic_s']-recovery[0]['received_monotonic_s']>GOAL.no_progress_s
    assert report['result']['goal_outcome']=='GOAL_REACHED'
    assert report['result']['goal']['progress_m']==.5
    assert len(report['r1']['samples'])<=GOAL.max_samples
    assert report['r1_ground_result']['origin']=='SYNTHETIC_TEST_DOUBLE'
    query=ground.query_ground_trial(admission['run_id'])
    assert query['status']=='FINISHED' and query['job_closure_confirmed']
    assert locks.restriction('v3') is None and session.closed
