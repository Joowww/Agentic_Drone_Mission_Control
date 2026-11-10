from tools.rover_agent_adapter import REQUEST_SCHEMA, _bridge_scope, adapt_request, validate_bridge_request


def request():
    value={"schema":REQUEST_SCHEMA,"task_id":"task-1","vehicle_id":"rover_01",
      "proposal_sha256":"a"*64,"frame":"odom","target":{"point_id":"dock-1"},
      "dependencies":["localization"],"navigation_plan":{"plan_id":"plan-1","frame":"odom",
       "target_x_m":1.0,"target_y_m":0.0,"max_speed_mps":0.1,"timeout_s":20.0}}
    value["expected_scope_sha256"]=_bridge_scope(value["navigation_plan"],value["vehicle_id"],value["proposal_sha256"])
    return value


def adapt(value, verification=None):
    return adapt_request(value,mission={"id":"m1","sha256":"b"*64},
      rover={"vehicle_id":"rover_01","platform":"ArduRover SITL"},
      localization={"frame":"odom","x_m":0.0,"y_m":0.0,"uncertainty_m":0.01,
        "source":"binding","source_sha256":"c"*64,"validated":True,
        "observed_at_utc":"2026-11-06T10:00:00Z","transform":None},
      dependencies=["localization"],constraints={"max_distance_m":1.1},
      operator_limits={"max_distance_m":1.1,"localization_max_uncertainty_m":0.1,
        "localization_max_age_s":2.0},provenance={"source_sha256":"d"*64},
      validity={"not_before_utc":"2026-11-06T00:00:00Z","expires_at_utc":"2026-11-07T00:00:00Z"},
      executor={"id":"protected-executor","version":"1"},stop_conditions=["stale pose"],
      operator_verification=verification)


def test_bridge_scope_hash_and_plan_frame_are_recomputed():
    value=request()
    assert validate_bridge_request(value)==[]
    value["navigation_plan"]["target_x_m"]+=0.1
    assert "BRIDGE_SCOPE_HASH_MISMATCH" in validate_bridge_request(value)


def test_unknown_or_pending_bridge_data_waits_without_coordinates_or_commands():
    value=request(); value["navigation_plan"]=None
    result=adapt(value)
    assert result["decision"]=="WAITING"
    assert result["proposal"]["coordinates"] is None
    assert result["proposal"]["commands"] == []


def test_missing_authentication_receipt_waits_and_unbound_scope_rejects():
    value=request()
    result=adapt(value)
    assert result["decision"]=="WAITING"
    assert result["movement_authorized"] is False
    result=adapt(value,{"bridge_scope_sha256":value["expected_scope_sha256"],"scope_sha256":"e"*64})
    assert result["decision"]=="REJECTED"
    assert result["movement_authorized"] is False
