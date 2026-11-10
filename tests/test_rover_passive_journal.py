"""Synthetic journals only; no ROS imports, node execution or connections."""
import copy
import json
import pytest
from tools.rover_passive_journal import analyze_bytes, main, TOPICS

BLOCKED = dict(status="BLOCKED", source_association_verified=False, movement_authorized=False)


def sample(topic, tick=1):
    s = dict(BLOCKED, event="sample", topic=topic, message_type=TOPICS[topic],
             receipt=dict(system_unix_ns=100 + tick, steady_ns=tick),
             message_gid_state="OBSERVED_NOT_ACCREDITED",
             message_gid_source="rclcpp callback MessageInfo.rmw_message_info.publisher_gid",
             message_publisher_gid="01" * 24, rmw_implementation_identifier="synthetic",
             from_intra_process=False, header=dict(stamp=dict(sec=tick, nanosec=0), frame_id="odom"),
             graph=dict(state="OBSERVED", source="Node.get_publishers_info_by_topic",
                        receipt=dict(system_unix_ns=101 + tick, steady_ns=tick + 1),
                        candidates=[dict(endpoint_gid="02" * 24, node_name="candidate", node_namespace="/rover1")]),
             incomplete=False)
    if topic == "/ap/v3/status":
        s["status_fields"] = dict(vehicle_type=1, armed=False, flying=False)
    else:
        s["child_frame_id"] = "base_link"
    return s


def journal():
    return [dict(BLOCKED, event="start", schema="tfg.rover.passive-capture/1",
                 string_encoding="byte_escape_u00", max_samples=2, duration_s=10),
            sample("/ap/v3/status"), sample("/rover1/odometry", 2),
            dict(BLOCKED, event="end", termination="SAMPLE_LIMIT", samples=2,
                 incomplete_samples=0, data_present_both_streams=True, capture_complete=None)]


def receipt():
    return dict(BLOCKED, capture_state="DATA_RECORDED", capture_complete=True,
                samples=2, termination="SAMPLE_LIMIT")


def encode(events):
    return b"".join((json.dumps(e) + "\n").encode() for e in events)


def test_complete_requires_external_receipt_and_rc():
    data = encode(journal())
    assert analyze_bytes(data)["completion"] == "UNCERTAIN"
    report = analyze_bytes(data, receipt=receipt(), returncode=0)
    assert report["completion"] == "DATA_RECORDED"
    assert report["status"] == "BLOCKED" and not report["movement_authorized"]
    s = report["topics"]["/ap/v3/status"]["samples"][0]
    assert s["message_publisher_gid"] != s["graph_candidates_separate"]["candidates"][0]["endpoint_gid"]
    assert analyze_bytes(data, receipt=receipt(), returncode=2)["completion"] == "UNCERTAIN"


@pytest.mark.parametrize("tail", [b'', b'{"event":', b'null\n', b'{}', b'{"event":"end","event":"end"}\n'])
def test_truncated_invalid_and_duplicate_records(tail):
    report = analyze_bytes(encode(journal()[:-1]) + tail, receipt=receipt(), returncode=0)
    assert report["issues"] and report["completion"] == "UNCERTAIN"


@pytest.mark.parametrize("change", [
    lambda e: e[0].update(schema="future"),
    lambda e: e[0].update(max_samples=True),
    lambda e: e[1].update(movement_authorized=True),
    lambda e: e[1].update(message_publisher_gid=None),
    lambda e: e[1].update(message_publisher_gid="00" * 24),
    lambda e: e[1].update(from_intra_process=True),
    lambda e: e[1].update(receipt=None),
    lambda e: e[1].update(header=None),
    lambda e: e[1].update(graph={}),
    lambda e: e[1]["graph"].update(candidates=[{}]),
    lambda e: e[1].update(topic=[]),
    lambda e: e[1]["status_fields"].update(vehicle_type=2),
    lambda e: e[2].update(child_frame_id=""),
    lambda e: e[-1].update(samples=3),
    lambda e: e[-1].update(capture_complete=True),
    lambda e: e.append(copy.deepcopy(e[1])),
    lambda e: e.insert(1, copy.deepcopy(e[0])),
    lambda e: e[1]["header"]["stamp"].update(nanosec=10**9),
])
def test_contradictions_fail_closed(change):
    events = journal()
    change(events)
    report = analyze_bytes(encode(events), receipt=receipt(), returncode=0)
    assert report["issues"] and report["completion"] == "UNCERTAIN"
    assert report["status"] == "BLOCKED"


def test_changes_and_clock_regressions_have_no_cause_attribution():
    events = journal()
    extra = sample("/ap/v3/status", 0)
    extra["message_publisher_gid"] = "03" * 24
    events.insert(3, extra)
    events[0]["max_samples"] = 3
    events[-1]["samples"] = 3
    report = analyze_bytes(encode(events))
    summary = report["topics"]["/ap/v3/status"]
    assert summary["gid_changes"] == [4]
    assert summary["header_regressions"] == [4]
    assert summary["receipt_regressions"] == [4]
    assert report["completion"] == "UNCERTAIN"


def test_matching_graph_never_attributes_identity():
    events = journal()
    events[1]["graph"]["candidates"][0]["endpoint_gid"] = events[1]["message_publisher_gid"]
    report = analyze_bytes(encode(events), receipt=receipt(), returncode=0)
    assert report["completion"] == "DATA_RECORDED"
    assert report["source_association_verified"] is False


def test_readonly_cli(tmp_path, capsys):
    path = tmp_path / "journal.jsonl"
    data = encode(journal())
    path.write_bytes(data)
    assert main([str(path)]) == 2
    assert json.loads(capsys.readouterr().out)["samples"] == 2
    assert path.read_bytes() == data and list(tmp_path.iterdir()) == [path]


# This fixture runs only a fake-ROS stdlib helper, never collector.cpp / a ROS node.
from tests.test_rover_passive_collector import compiled  # noqa: E402,F401


@pytest.mark.parametrize("mode", ["normal", "incomplete", "duration", "sample_failure", "close_failure"])
def test_actual_cpp_serializer_contract(compiled, mode):
    import subprocess
    run = subprocess.run([str(compiled), mode], capture_output=True, check=True, timeout=5)
    lines = run.stdout.splitlines(keepends=True)
    # The harness has a test-only completion assertion before the journal, not collector stdout.
    data = b"".join(line for line in lines if b'"complete":' not in line)
    report = analyze_bytes(data)
    if mode == "normal":
        assert not report["issues"]
        assert report["samples"] == 2
    else:
        assert report["completion"] == "UNCERTAIN"
    assert report["status"] == "BLOCKED"


@pytest.mark.parametrize("field,value", [("samples", 3), ("termination", "DURATION_LIMIT"),
                                        ("source_association_verified", True), ("capture_complete", False)])
def test_contradictory_external_receipt(field, value):
    external = receipt()
    external[field] = value
    result = analyze_bytes(encode(journal()), receipt=external, returncode=0)
    assert result["completion"] == "UNCERTAIN" and result["issues"]


def test_summaries_and_unknown_bytes():
    report = analyze_bytes(encode(journal()))
    summary = report["topics"]["/ap/v3/status"]
    assert summary["count"] == 1 and summary["receipt_span_ns"] == 0
    assert summary["first_receipt_steady_ns"] == 1
    assert analyze_bytes(b'\xff\n')["issues"]


def test_v2_counters_and_receipt_are_bound():
    events=journal();events[0].update(schema='tfg.rover.passive-capture/2',sampling_policy='RESERVE_BOTH_STREAMS')
    events[-1].update(omitted_status_quota=0,omitted_odometry_quota=12)
    external=receipt();external.update(omitted_status_quota=0,omitted_odometry_quota=12)
    assert analyze_bytes(encode(events),receipt=external,returncode=0)['completion']=='DATA_RECORDED'
    external['omitted_odometry_quota']=13
    assert analyze_bytes(encode(events),receipt=external,returncode=0)['completion']=='UNCERTAIN'
    del events[-1]['omitted_status_quota']
    assert analyze_bytes(encode(events))['issues']


def test_v2_rejects_stolen_reserved_slot():
    events=journal();events[0].update(schema='tfg.rover.passive-capture/2',sampling_policy='RESERVE_BOTH_STREAMS')
    events[2]=sample('/ap/v3/status',2)
    events[-1].update(omitted_status_quota=0,omitted_odometry_quota=0,data_present_both_streams=False)
    assert any(i['reason']=='reserved_capacity_violated' for i in analyze_bytes(encode(events))['issues'])


def test_discovery_without_status_sample_never_supplies_coverage():
    events=journal();events[0].update(schema='tfg.rover.passive-capture/2',sampling_policy='RESERVE_BOTH_STREAMS',max_samples=20)
    events=events[:1]+[events[2]]+events[-1:]
    events[-1].update(samples=1,termination='DURATION_LIMIT',data_present_both_streams=False,omitted_status_quota=0,omitted_odometry_quota=0)
    events.insert(-1,dict(BLOCKED,event='discovery',topic='/ap/v3/status',source='Node.get_publishers_info_by_topic',state='OBSERVED',receipt=dict(system_unix_ns=1,steady_ns=1),candidates=[]))
    report=analyze_bytes(encode(events))
    assert not report['issues'] and report['topics']['/ap/v3/status']['count']==0
    assert len(report['discoveries_separate'])==1 and report['completion']=='UNCERTAIN'
