"""Offline evidence evaluator for a proposed first one-metre rover trial.

A positive result means only that supplied evidence meets the stated criteria;
it never authorizes or issues vehicle commands.
"""
import math


def evaluate(evidence, *, thresholds=None):
    t={"target_m":1.0,"distance_tolerance_m":0.05,"max_lateral_error_m":0.10,
       "max_speed_mps":0.15,"max_overshoot_m":0.05,"max_pose_age_s":1.0,
       "max_final_speed_mps":0.02}
    if thresholds: t.update(thresholds)
    reasons=[]
    if not isinstance(evidence,dict):
        return {"verdict":"UNCONFIRMED","reasons":["EVIDENCE_NOT_OBJECT"],"movement_authorized":False}
    required=("mission_id","plan_id","vehicle_id","lifecycle_id","host_boot_id","frame",
              "start_pose","final_pose","maximum_speed_mps","elapsed_host_monotonic_s",
              "maximum_pose_age_s","final_speed_mps","commands_sent","armed_at_end",
              "stationary_at_end","stop_confirmed","worker_closed","localization_validated")
    for k in required:
        if k not in evidence: reasons.append("MISSING:"+k)
    for k in ("start_pose","final_pose"):
        pose=evidence.get(k)
        if not isinstance(pose,dict) or any(not isinstance(pose.get(c),(int,float)) or isinstance(pose.get(c),bool) or not math.isfinite(pose[c]) for c in ("x_m","y_m")):
            reasons.append("POSE_INVALID:"+k)
    numeric=("maximum_speed_mps","elapsed_host_monotonic_s","maximum_pose_age_s","final_speed_mps")
    for k in numeric:
        v=evidence.get(k)
        if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<0: reasons.append("METRIC_INVALID:"+k)
    progress=lateral=overshoot=None
    if not any(r.startswith("POSE_INVALID") for r in reasons):
        a=evidence.get("start_pose") or {}; b=evidence.get("final_pose") or {}
        if all(isinstance((a.get(c)),(int,float)) and isinstance(b.get(c),(int,float)) for c in ("x_m","y_m")):
            dx=b["x_m"]-a["x_m"]; dy=b["y_m"]-a["y_m"]
            expected=evidence.get("heading_rad")
            if not isinstance(expected,(int,float)) or not math.isfinite(expected): reasons.append("START_HEADING_MISSING")
            else:
                progress=dx*math.cos(expected)+dy*math.sin(expected)
                lateral=abs(-dx*math.sin(expected)+dy*math.cos(expected))
                overshoot=max(0.0,progress-t["target_m"])
                if abs(progress-t["target_m"])>t["distance_tolerance_m"]: reasons.append("DISTANCE_OUT_OF_TOLERANCE")
                if lateral>t["max_lateral_error_m"]: reasons.append("LATERAL_ERROR_EXCEEDED")
                if overshoot>t["max_overshoot_m"]: reasons.append("OVERSHOOT_EXCEEDED")
        else: progress=lateral=overshoot=None
    else: progress=lateral=overshoot=None
    if evidence.get("maximum_speed_mps",float("inf"))>t["max_speed_mps"]: reasons.append("SPEED_LIMIT_EXCEEDED")
    if evidence.get("maximum_pose_age_s",float("inf"))>t["max_pose_age_s"]: reasons.append("POSE_STALE")
    if evidence.get("final_speed_mps",float("inf"))>t["max_final_speed_mps"]: reasons.append("FINAL_NOT_STATIONARY")
    if evidence.get("commands_sent") != 1: reasons.append("COMMAND_EVIDENCE_NOT_EXACTLY_ONE")
    if evidence.get("armed_at_end") is not False: reasons.append("ARMED_STATE_UNCONFIRMED")
    if evidence.get("stationary_at_end") is not True: reasons.append("STATIONARY_STATE_UNCONFIRMED")
    if evidence.get("stop_confirmed") is not True: reasons.append("STOP_UNCONFIRMED")
    if evidence.get("worker_closed") is not True: reasons.append("WORKER_CLOSE_UNCONFIRMED")
    if evidence.get("localization_validated") is not True: reasons.append("LOCALIZATION_UNCONFIRMED")
    return {"schema":"tfg.rover.first-meter-evaluation/1",
            "verdict":"EVIDENCE_MEETS_THRESHOLDS" if not reasons else "UNCONFIRMED",
            "reasons":reasons,"progress_m":progress,"lateral_error_m":lateral,
            "overshoot_m":overshoot,"thresholds":t,"movement_authorized":False}
