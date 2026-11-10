"""Offline cross-source parameter attribution; never contacts ROS, MAVLink or a vehicle."""

import math

REQUIRED = ('MAV_SYSID','DDS_USE_NS','GUID_TIMEOUT','ATC_ACCEL_MAX','ATC_DECEL_MAX','FS_GCS_ENABLE','FS_ACTION','FS_TIMEOUT',
            'FS_THR_ENABLE','FS_THR_VALUE','FS_EKF_ACTION','FS_EKF_THRESH','FS_OPTIONS','FS_GCS_TIMEOUT')


def verify(ros_capture, mavlink_capture, *, required=REQUIRED):
    """Require one lifecycle/process incarnation and independent live protocol provenance."""
    reasons=[]
    def identity(obj):
        return (obj.get('host_boot_id'),obj.get('lifecycle_id'),obj.get('target_process',{}).get('pid'),
                obj.get('target_process',{}).get('start_ticks'),obj.get('target_process',{}).get('exe_sha256'))
    try:
        ri=identity(ros_capture); mi=identity(mavlink_capture)
        if not all(ri) or not all(mi): reasons.append('PROCESS_OR_LIFECYCLE_IDENTITY_INCOMPLETE')
        if ri!=mi: reasons.append('SOURCE_PROCESS_OR_LIFECYCLE_MISMATCH')
        if ros_capture.get('source_association')!='NATIVE_RESPONSE_SAMPLEINFO_TO_TARGET_PROCESS': reasons.append('ROS_RESPONSE_NOT_ATTRIBUTED')
        if mavlink_capture.get('source_association')!='SOCKET_OWNER_AND_MAVLINK_TARGET_CORRELATED': reasons.append('MAVLINK_SOURCE_NOT_ATTRIBUTED')
        if ros_capture.get('live_read') is not True or mavlink_capture.get('live_read') is not True: reasons.append('NOT_BOTH_LIVE_READS')
        if ros_capture.get('capture_complete') is not True or mavlink_capture.get('capture_complete') is not True:
            reasons.append('CAPTURE_INCOMPLETE')
        if ros_capture.get('status')!='COMPLETE' or mavlink_capture.get('status')!='COMPLETE':
            reasons.append('SOURCE_CAPTURE_STATUS_NOT_COMPLETE')
        if mavlink_capture.get('firmware_report_status')!='OBSERVED': reasons.append('FIRMWARE_REPORT_UNKNOWN')
        if ros_capture.get('firmware_sha256')!=mavlink_capture.get('firmware_sha256') or not ros_capture.get('firmware_sha256'):
            reasons.append('FIRMWARE_IDENTITY_MISMATCH_OR_MISSING')
        if ros_capture.get('sysid')!=mavlink_capture.get('target_system') or ros_capture.get('component_id')!=mavlink_capture.get('target_component'):
            reasons.append('MAVLINK_SYSTEM_ID_MISMATCH')
        rv=ros_capture.get('values'); mv=mavlink_capture.get('values')
        if isinstance(rv,dict) and (type(ros_capture.get('sysid')) is not int or type(ros_capture.get('component_id')) is not int
                or type(rv.get('MAV_SYSID')) not in (int,float) or isinstance(rv.get('MAV_SYSID'),bool)
                or rv.get('MAV_SYSID')!=ros_capture.get('sysid') or rv.get('DDS_USE_NS')!=1):
            reasons.append('ROS_PARAMETER_IDENTITY_MISMATCH')
        if isinstance(mv,dict) and (type(mavlink_capture.get('target_system')) is not int
                or type(mavlink_capture.get('target_component')) is not int
                or type(mv.get('MAV_SYSID')) not in (int,float) or isinstance(mv.get('MAV_SYSID'),bool)
                or mv.get('MAV_SYSID')!=mavlink_capture.get('target_system') or mv.get('DDS_USE_NS')!=1):
            reasons.append('MAVLINK_PARAMETER_IDENTITY_MISMATCH')
        if not isinstance(rv,dict) or not isinstance(mv,dict): reasons.append('VALUE_SET_MISSING')
        else:
            for source,values in (('ROS',rv),('MAVLINK',mv)):
                for name,value in values.items():
                    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
                        reasons.append('PARAMETER_VALUE_TYPE_INVALID:'+source+':'+str(name))
            for name in required:
                if name not in rv or name not in mv: reasons.append('PARAMETER_MISSING:'+name)
                elif rv[name]!=mv[name]: reasons.append('PARAMETER_VALUE_MISMATCH:'+name)
    except (AttributeError,TypeError): reasons.append('MALFORMED_CAPTURE')
    return {'schema':'tfg.rover.parameter-correlation/1','verdict':'CROSS_SOURCE_ATTRIBUTED' if not reasons else 'UNVERIFIED',
            'reasons':reasons,'movement_authorized':False,
            'limitation':'Cross-source agreement is only as strong as native response identity, socket ownership and firmware provenance.'}
