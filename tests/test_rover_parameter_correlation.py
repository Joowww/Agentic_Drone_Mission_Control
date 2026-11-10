import copy
import pytest
from tools.rover_parameter_correlation import verify, REQUIRED


def pair():
    target={'pid':41,'start_ticks':77,'exe_sha256':'e'*64}
    ident={'host_boot_id':'boot','lifecycle_id':'life','target_process':target,'firmware_sha256':'f'*64}
    vals={name:1.0 for name in REQUIRED}; vals.update(MAV_SYSID=3,DDS_USE_NS=1)
    return ({**ident,'status':'COMPLETE','capture_complete':True,'source_association':'NATIVE_RESPONSE_SAMPLEINFO_TO_TARGET_PROCESS','live_read':True,
             'sysid':3,'component_id':1,'values':dict(vals)},
            {**ident,'status':'COMPLETE','capture_complete':True,'firmware_report_status':'OBSERVED','source_association':'SOCKET_OWNER_AND_MAVLINK_TARGET_CORRELATED','live_read':True,
             'target_system':3,'target_component':1,'values':dict(vals)})


def test_complete_independent_matching_live_capture_can_be_attributed():
    r,m=pair(); assert verify(r,m)['verdict']=='CROSS_SOURCE_ATTRIBUTED'


def test_legacy_ros_parameter_result_stays_unverified():
    r,m=pair(); r['source_association']='LEGACY_RMW_REQUEST_ID'; out=verify(r,m)
    assert out['verdict']=='UNVERIFIED' and 'ROS_RESPONSE_NOT_ATTRIBUTED' in out['reasons']


def test_mismatched_process_firmware_or_values_fail_closed():
    r,m=pair(); m=copy.deepcopy(m); m['target_process']['pid']=42
    assert 'SOURCE_PROCESS_OR_LIFECYCLE_MISMATCH' in verify(r,m)['reasons']
    r,m=pair(); m['values']['GUID_TIMEOUT']=4
    assert 'PARAMETER_VALUE_MISMATCH:GUID_TIMEOUT' in verify(r,m)['reasons']
    r,m=pair(); m['firmware_sha256']='0'*64
    assert 'FIRMWARE_IDENTITY_MISMATCH_OR_MISSING' in verify(r,m)['reasons']


def test_no_live_reads_or_mavlink_identity_are_not_attributed():
    r,m=pair(); m['live_read']=False; m['target_system']=9
    out=verify(r,m)
    assert out['verdict']=='UNVERIFIED' and 'NOT_BOTH_LIVE_READS' in out['reasons']
    assert 'MAVLINK_SYSTEM_ID_MISMATCH' in out['reasons'] and out['movement_authorized'] is False


@pytest.mark.parametrize('field,value,reason',[('host_boot_id','other','SOURCE_PROCESS_OR_LIFECYCLE_MISMATCH'),
    ('lifecycle_id','other','SOURCE_PROCESS_OR_LIFECYCLE_MISMATCH')])
def test_boot_and_lifecycle_mismatch_are_explicit(field,value,reason):
    r,m=pair(); m[field]=value
    assert reason in verify(r,m)['reasons']


def test_missing_required_parameter_or_unknown_firmware_stays_unverified():
    r,m=pair(); del m['values']['FS_TIMEOUT']
    assert 'PARAMETER_MISSING:FS_TIMEOUT' in verify(r,m)['reasons']
    r,m=pair(); m['firmware_report_status']='NOT_OBSERVED'
    assert 'FIRMWARE_REPORT_UNKNOWN' in verify(r,m)['reasons']


def test_incomplete_capture_and_component_mismatch_are_rejected():
    r,m=pair(); m['capture_complete']=False
    assert 'CAPTURE_INCOMPLETE' in verify(r,m)['reasons']
    r,m=pair(); m['target_component']=2
    assert 'MAVLINK_SYSTEM_ID_MISMATCH' in verify(r,m)['reasons']



def test_boolean_or_nonfinite_parameter_values_are_not_normalized_as_numbers():
    r,m=pair(); m['values']['FS_TIMEOUT']=True
    assert 'PARAMETER_VALUE_TYPE_INVALID:MAVLINK:FS_TIMEOUT' in verify(r,m)['reasons']
    r,m=pair(); r['values']['GUID_TIMEOUT']=float('nan')
    assert 'PARAMETER_VALUE_TYPE_INVALID:ROS:GUID_TIMEOUT' in verify(r,m)['reasons']
