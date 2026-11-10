"""Produce a passive stationarity report from an already saved capture (offline only)."""
from tools.rover_stationarity import analyze, StationarityThresholds


def analyze_capture(capture, *, lifecycle_id, host_boot_id, status_gid, odometry_gid,
                    worker_closed, thresholds=StationarityThresholds()):
    """Bind the existing analyzer to explicit session identities and closure evidence."""
    if not all(isinstance(v,str) and v for v in (lifecycle_id,host_boot_id,status_gid,odometry_gid)):
        return {"schema":"tfg.rover.stationarity-analysis/1","verdict":"UNCONFIRMED",
                "reasons":["EXPECTED_SESSION_IDENTITY_MISSING"],"movement_authorized":False}
    return analyze(capture,expected_lifecycle=lifecycle_id,expected_boot_id=host_boot_id,
                   expected_status_gid=status_gid,expected_odometry_gid=odometry_gid,
                   thresholds=thresholds,worker_closed=worker_closed)
