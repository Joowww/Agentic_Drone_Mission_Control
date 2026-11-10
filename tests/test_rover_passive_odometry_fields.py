"""Schema /3 (opt-in odometry fields) with fake ROS headers; never runs collector.cpp or ROS/DDS.

Synthetic samples only: no pose here comes from a Gazebo model, no frame is validated, and no
sample says anything about stopping, arrival, identity or authorization.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.test_rover_passive_rclcpp import STUB, ROOT
from tools.rover_passive_journal import FIELDS_SCHEMA, PROPOSED_MAX_RECORD_BYTES, analyze_bytes

HARNESS = r'''
#include "tools/rover_passive_rclcpp/collector_core.hpp"
#include <cassert>
#include <iostream>
#include <limits>
using namespace tfg::rover_passive;
struct Writer {
  std::vector<std::string> lines; bool finished=false;
  void append(const std::string &s){lines.push_back(s);} void finish(){finished=true;}
};
Sample base(bool status, int sec, unsigned nanosec) {
  Sample s; s.receipt={1000+sec, 2000+sec}; s.graph_received=Receipt{3000+sec, 4000+sec}; s.graph_state="OBSERVED";
  s.topic=status?"/ap/v3/status":"/rover1/odometry";
  s.message_type=status?"ardupilot_msgs/msg/Status":"nav_msgs/msg/Odometry";
  GidBytes gid{}; gid[0]=status?3:7; s.message_publisher_gid=gid;
  s.message_gid_state="OBSERVED_NOT_ACCREDITED"; s.rmw_implementation_identifier="synthetic-rmw";
  Candidate c{gid,"synthetic-bridge","/rover1"}; c.topic_type=s.message_type; c.offered_qos=OfferedQos{1,2,1,5};
  s.graph_candidates.push_back(c);
  if(status){ Status st; st.header.stamp.sec=sec; st.header.stamp.nanosec=nanosec; s.message=st; }
  else {
    Odometry od; od.header.stamp.sec=sec; od.header.stamp.nanosec=nanosec; od.header.frame_id="odom";
    od.child_frame_id="base_link";
    od.pose.pose.position={1.25,-3.5,0.1}; od.pose.pose.orientation={0,0,0.70710678118654757,0.70710678118654757};
    od.twist.twist.linear={0.1,0,0}; od.twist.twist.angular={0,0,0.01};
    for(int i=0;i<36;++i){ od.pose.covariance[i]=(i%7==0)?1e-3:0; od.twist.covariance[i]=(i%7==0)?2e-4:0; }
    s.message=od;
  }
  return s;
}
int main(int argc,char **argv) {
  assert(argc==2); const std::string mode=argv[1];
  const double nan=std::numeric_limits<double>::quiet_NaN(), inf=std::numeric_limits<double>::infinity();
  std::vector<Sample> feed;
  for(int i=0;i<3;++i){ feed.push_back(base(true,10+i,0)); feed.push_back(base(false,10+i,500000000)); }
  auto &odom=std::get<Odometry>(feed[1].message);
  if(mode=="nonfinite"){ odom.pose.pose.position.x=nan; odom.twist.twist.linear.x=inf; odom.pose.covariance[0]=-inf; }
  if(mode=="defaults"){ odom=Odometry{}; odom.header.frame_id="odom"; odom.child_frame_id="base_link"; }
  if(mode=="empty_frame") std::get<Odometry>(feed[3].message).header.frame_id="";
  if(mode=="other_frame") std::get<Odometry>(feed[3].message).child_frame_id="chassis";
  if(mode=="repeated_stamp") std::get<Odometry>(feed[3].message).header.stamp=odom.header.stamp;
  if(mode=="inverted_stamp") std::get<Odometry>(feed[3].message).header.stamp.sec=1;
  if(mode=="no_gid"){ feed[3].message_publisher_gid=GidBytes{}; feed[3].message_gid_state="UNKNOWN"; }
  if(mode=="oversize") std::get<Odometry>(feed[3].message).child_frame_id=std::string(20000,'f');
  const bool fields = mode.rfind("legacy",0)!=0;
  const bool reserve = mode!="legacy_global";
  Writer w; std::size_t i=0; double time=0;
  Limits limits{reserve?std::size_t{6}:std::size_t{6}, 10, reserve, fields};
  auto result=collect(w,limits,[&]{return time;},[&](auto &sink,double){
    time+=0.5; if(i<feed.size()) sink(feed[i++]); return true; });
  assert(w.finished && result.samples==6);
  for(const auto &line:w.lines) std::cout<<line<<'\n';
}
'''


@pytest.fixture(scope="module")
def fields_binary(tmp_path_factory):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("No C++ compiler")
    root = tmp_path_factory.mktemp("odometry_fields")
    (root / "contract.hpp").write_text(STUB.replace("bool armed=false;", "bool armed=false; bool flying=false;"))
    for name in ("ardupilot_msgs/msg/status.hpp", "nav_msgs/msg/odometry.hpp", "rclcpp/rclcpp.hpp",
                 "rclcpp/message_info.hpp", "rmw/types.h"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#include "contract.hpp"\n')
    (root / "fields.cpp").write_text(HARNESS)
    built = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic", "-I", str(root),
                            "-I", str(ROOT), str(root / "fields.cpp"), "-o", str(root / "fields")],
                           capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stderr
    return root / "fields"


def _run(binary, mode):
    return subprocess.run([str(binary), mode], capture_output=True, check=True, timeout=5).stdout


def _events(data):
    return [json.loads(line) for line in data.splitlines()]


def test_valid_pose_and_velocities_are_kept_exactly_with_their_frames(fields_binary):
    data = _run(fields_binary, "valid")
    events = _events(data)
    assert events[0]["schema"] == FIELDS_SCHEMA and events[0]["sampling_policy"] == "RESERVE_BOTH_STREAMS"
    odom = [e for e in events if e.get("topic") == "/rover1/odometry"]
    fields = odom[0]["odometry_fields"]
    assert fields["pose"]["position"] == {"x": 1.25, "y": -3.5, "z": 0.1}  # exact round trip, no rounding
    assert fields["pose"]["orientation"]["w"] == 0.70710678118654757
    assert fields["twist"]["angular"]["z"] == 0.01 and len(fields["twist"]["covariance"]) == 36
    assert fields["nonfinite"] == {} and fields["validity_flag"] == "NOT_PROVIDED_BY_MESSAGE"
    assert odom[0]["header"]["frame_id"] == "odom" and odom[0]["child_frame_id"] == "base_link"
    assert odom[0]["message_publisher_gid"].startswith("07")  # the callback's own GID, not a graph candidate
    assert all("odometry_fields" not in e for e in events if e.get("topic") == "/ap/v3/status")
    report = analyze_bytes(data)
    assert not report["issues"] and report["incomplete_samples"] == 0
    assert report["status"] == "BLOCKED" and report["movement_authorized"] is False
    assert report["source_association_verified"] is False
    assert report["topics"]["/rover1/odometry"]["samples"][0]["odometry_fields"]["pose"]["position"]["x"] == 1.25


def test_nonfinite_values_are_null_listed_and_make_the_sample_incomplete_never_zero(fields_binary):
    data = _run(fields_binary, "nonfinite")
    odom = [e for e in _events(data) if e.get("topic") == "/rover1/odometry"][0]
    fields = odom["odometry_fields"]
    assert fields["pose"]["position"]["x"] is None and fields["twist"]["linear"]["x"] is None
    assert fields["pose"]["covariance"][0] is None
    assert fields["nonfinite"] == {"pose.position.x": "NaN", "pose.covariance[0]": "-Infinity",
                                   "twist.linear.x": "Infinity"}
    assert odom["incomplete"] is True
    report = analyze_bytes(data)
    assert report["incomplete_samples"] == 1 and {"line": 3, "reason": "incomplete_sample"} in report["issues"]


def test_default_message_values_are_recorded_as_received_not_as_absence_or_rest(fields_binary):
    # A typed ROS message cannot mark a field absent: unset numbers are 0 (and w=1 in this stub).
    # They are kept as received; nothing here is read as "stopped" or "at origin".
    fields = [e for e in _events(_run(fields_binary, "defaults")) if e.get("topic") == "/rover1/odometry"][0]
    assert fields["odometry_fields"]["pose"]["position"] == {"x": 0, "y": 0, "z": 0}
    assert "stopped" not in json.dumps(fields) and "arrival" not in json.dumps(fields)


@pytest.mark.parametrize("mode,check", [
    ("empty_frame", lambda r: {"line": 5, "reason": "incomplete_sample"} in r["issues"]),
    ("other_frame", lambda r: r["topics"]["/rover1/odometry"]["frame_changes"] == [5, 7]),
    ("repeated_stamp", lambda r: r["topics"]["/rover1/odometry"]["header_repeats"] == [5]),
    ("inverted_stamp", lambda r: r["topics"]["/rover1/odometry"]["header_regressions"] == [5]),
    ("no_gid", lambda r: {"line": 5, "reason": "incomplete_sample"} in r["issues"]),
])
def test_frames_stamps_and_gid_problems_are_reported_without_explanation(fields_binary, mode, check):
    report = analyze_bytes(_run(fields_binary, mode))
    assert check(report)
    assert report["movement_authorized"] is False and report["source_association_verified"] is False


def test_reader_rejects_missing_or_altered_fields_and_fields_outside_schema_3(fields_binary):
    lines = _run(fields_binary, "valid").splitlines(keepends=True)
    odom_index = 2  # start, status, odometry
    event = json.loads(lines[odom_index])
    for mutate in (lambda f: f.pop("twist"), lambda f: f["pose"]["covariance"].pop(),
                   lambda f: f["pose"]["position"].update(x=None),  # null not listed in nonfinite
                   lambda f: f["pose"]["position"].update(x=True),
                   lambda f: f.update(source="Gazebo model rover1 pose")):  # no invented provenance
        changed = json.loads(json.dumps(event))
        mutate(changed["odometry_fields"])
        data = b"".join(lines[:odom_index] + [json.dumps(changed).encode() + b"\n"] + lines[odom_index + 1:])
        assert {"line": 3, "reason": "invalid_odometry_fields"} in analyze_bytes(data)["issues"]
    legacy = _run(fields_binary, "legacy_reserve").splitlines(keepends=True)
    injected = json.loads(legacy[2])
    injected["odometry_fields"] = event["odometry_fields"]
    data = b"".join(legacy[:2] + [json.dumps(injected).encode() + b"\n"] + legacy[3:])
    assert {"line": 3, "reason": "odometry_fields_outside_schema_3"} in analyze_bytes(data)["issues"]


def test_truncated_record_and_oversize_record_are_visible(fields_binary):
    data = _run(fields_binary, "valid")
    truncated = data[: data.index(b"\n", data.index(b"/rover1/odometry")) - 40]
    reasons = {i["reason"] for i in analyze_bytes(truncated)["issues"]}
    assert {"unterminated_record", "invalid_json_record", "missing_end"} <= reasons
    big = analyze_bytes(_run(fields_binary, "oversize"))
    # Measured and reported, NOT enforced: no byte limit exists in the collector or the reader.
    assert big["record_bytes"]["max_record"] > PROPOSED_MAX_RECORD_BYTES
    assert not any(i["reason"].startswith("record") for i in big["issues"])


# Captured from the PRE-CHANGE collector_core.hpp (same harness, flags off): legacy output must not change.
LEGACY_SHA256 = {"legacy_reserve": "4d22d190e9e6f1d713c89be29f7b3b65f7f3a86cd8f7d4853e1745e37d9b9d56", "legacy_global": "c314cbeb68d36b293f13d3f5b13ee8b52ded158cf74ad9ad520d79254c32b3e0"}


@pytest.mark.parametrize("mode", sorted(LEGACY_SHA256))
def test_without_the_option_output_is_byte_identical_to_the_previous_collector(fields_binary, mode):
    data = _run(fields_binary, mode)
    assert hashlib.sha256(data).hexdigest() == LEGACY_SHA256[mode]
    assert _events(data)[0]["schema"] in ("tfg.rover.passive-capture/1", "tfg.rover.passive-capture/2")
    assert not analyze_bytes(data)["issues"]


def _pre_3_journals():
    """Captures recorded BEFORE schema /3 existed (any /3 capture is covered by its own test)."""
    paths = sorted((ROOT / "simulation/ros2_gazebo/results").rglob("journal.jsonl"))
    selected=[]
    for path in paths:
        try:
            first=json.loads(path.read_bytes().split(b"\n",1)[0])
        except (ValueError,UnicodeDecodeError):
            continue
        if first.get("schema") in ("tfg.rover.passive-capture/1","tfg.rover.passive-capture/2"):
            selected.append(path)
    return selected


@pytest.mark.parametrize("journal", sorted(str(p.relative_to(ROOT)) for p in _pre_3_journals()))
def test_historical_captures_remain_readable_and_carry_no_odometry_fields(journal):
    report = analyze_bytes((ROOT / journal).read_bytes())
    assert report["start"]["schema"] in ("tfg.rover.passive-capture/1", "tfg.rover.passive-capture/2")
    assert all(s["odometry_fields"] is None for t in report["topics"].values() for s in t["samples"])
    assert report["movement_authorized"] is False


def test_record_size_growth_is_measured(fields_binary):
    legacy = max(len(l) for l in _run(fields_binary, "legacy_reserve").splitlines(keepends=True))
    fields = max(len(l) for l in _run(fields_binary, "valid").splitlines(keepends=True))
    assert legacy < fields < PROPOSED_MAX_RECORD_BYTES


# --- Descriptive odometry summary over the /3 reader (SYNTHETIC serializer output; no real capture exists) --

from tools.rover_passive_journal import odometry_summary  # noqa: E402


def test_summary_describes_retained_samples_per_source_with_clocks_apart(fields_binary):
    summary = odometry_summary(analyze_bytes(_run(fields_binary, "valid")))
    (group,) = summary["groups"]
    assert group["frame_id"] == "odom" and group["child_frame_id"] == "base_link"
    assert group["retained_samples"] == group["complete_with_fields"] == 3
    assert group["position_m_as_received"]["x"] == {"n": 3, "min": 1.25, "max": 1.25, "mean": 1.25, "pstdev": 0.0}
    assert group["linear_speed_norm"]["max"] == 0.1 and group["angular_rate_norm"]["max"] == 0.01
    assert group["header_stamp_interval_ns"]["min"] == 10**9  # message clock
    assert group["receipt_interval_steady_ns"]["min"] == 1  # steady receipt clock, reported apart
    assert summary["sources_merged"] is False and summary["movement_authorized"] is False
    assert any("NOT inferable" in limit for limit in summary["limits"]) and summary["capture_selection"]


def test_summary_never_merges_frames_or_uses_incomplete_samples(fields_binary):
    groups = odometry_summary(analyze_bytes(_run(fields_binary, "other_frame")))["groups"]
    assert sorted(g["child_frame_id"] for g in groups) == ["base_link", "chassis"]
    nonfinite = odometry_summary(analyze_bytes(_run(fields_binary, "nonfinite")))["groups"][0]
    assert nonfinite["with_nonfinite"] == 1 and nonfinite["incomplete"] == 1 and nonfinite["complete_with_fields"] == 2


def test_zero_declared_covariance_is_counted_not_read_as_certainty(fields_binary):
    summary = odometry_summary(analyze_bytes(_run(fields_binary, "defaults")))
    assert summary["groups"][0]["all_zero_declared_covariances"] == 2  # pose and twist of the default message
    assert "declared covariance zero is not certainty" in summary["limits"]


def test_historical_captures_have_no_fields_and_are_always_selected():
    paths = _pre_3_journals()
    assert len(paths) == 5  # the five pre-/3 captures, unchanged
    for path in paths:
        summary = odometry_summary(analyze_bytes(path.read_bytes()))
        assert all(g["fields"].startswith("NOT_RECORDED") for g in summary["groups"])
        assert summary["capture_selection"][0].startswith("best_effort")


# --- Finished-capture entry (SYNTHETIC trial fixtures + one REAL historical /2 capture) ---------------------

from tools.rover_passive_journal import analyze_capture  # noqa: E402

EB113 = "simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/eb113b19-4923-4983-bed4-2e99db1aa512"
EB113_CAPTURE = "container_after/container_copies/tmp/tfg_rover_xrce_capture/eb113b19-4923-4983-bed4-2e99db1aa512"


def _trial(tmp_path, journal, *, rc=0, list_capture=True):
    """A SYNTHETIC finished trial: journal from the real serializer, the receipt the collector would print, rc,
    and a manifest in the rover's format (path, size_bytes, sha256)."""
    capture = tmp_path / "capture"
    capture.mkdir()
    events = _events(journal)
    end = events[-1]
    receipt = {"status": "BLOCKED", "source_association_verified": False, "movement_authorized": False,
               "capture_state": "DATA_RECORDED", "capture_complete": True, "samples": end["samples"],
               "omitted_status_quota": end.get("omitted_status_quota", 0),
               "omitted_odometry_quota": end.get("omitted_odometry_quota", 0), "termination": end["termination"]}
    (capture / "journal.jsonl").write_bytes(journal)
    (capture / "receipt.json").write_text(json.dumps(receipt))
    (capture / "return_code.txt").write_text(f"{rc}\n")
    (capture / "stderr.txt").write_bytes(b"")
    files = [p for p in sorted(capture.iterdir()) if list_capture or p.name != "journal.jsonl"]
    manifest = {"schema": "SYNTHETIC_FIXTURE", "files": [{"path": f"capture/{p.name}", "size_bytes": p.stat().st_size,
                                                          "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                                         for p in files]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def test_finished_synthetic_capture_is_verified_before_metrics(fields_binary, tmp_path):
    result = analyze_capture(_trial(tmp_path, _run(fields_binary, "valid")), "capture")
    assert result["status"] == "ANALYZED" and result["pose_fields_present"] is True
    assert set(result["r1_contrastable"]) and any("not a basis" in item for item in result["r1_needs_wider_design"])
    group = result["odometry"]["groups"][0]
    assert group["covered_header_span_ns"] == 2 * 10**9 and group["covered_receipt_span_ns"] == 2
    assert result["movement_authorized"] is False and result["source_association_verified"] is False


def _relist(root):
    capture = root / "capture"
    (root / "manifest.json").write_text(json.dumps({"files": [
        {"path": f"capture/{p.name}", "size_bytes": p.stat().st_size,
         "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(capture.iterdir())]}))


def _rewrite_footer(root, **fields):
    journal = root / "capture/journal.jsonl"
    lines = journal.read_bytes().splitlines(keepends=True)
    end = json.loads(lines[-1])
    end.update(fields)
    journal.write_bytes(b"".join(lines[:-1]) + json.dumps(end, separators=(",", ":")).encode() + b"\n")


@pytest.mark.parametrize("missing", ["footer_self_certifies", "receipt_not_complete", "receipt_without_flag",
                                     "rc_nonzero", "one_stream_only", "stderr_unlisted"])
def test_completion_needs_every_separate_evidence_not_a_capture_specific_exception(fields_binary, tmp_path, missing):
    """The accepted combination (footer null, receipt true, rc 0, both streams, stderr manifested) holds only while
    EACH evidence holds; removing any one refuses. Mutations are SYNTHETIC; manifests are re-listed so only the
    evidence differs."""
    root = _trial(tmp_path, _run(fields_binary, "valid"))
    accepted = analyze_capture(root, "capture")
    assert accepted["status"] == "ANALYZED"
    assert {k: accepted["completion_evidence"][k] for k in ("footer_capture_complete", "receipt_capture_complete",
            "returncode", "data_present_both_streams")} == {"footer_capture_complete": None,
            "receipt_capture_complete": True, "returncode": 0, "data_present_both_streams": True}
    capture = root / "capture"
    receipt = json.loads((capture / "receipt.json").read_text())
    if missing == "footer_self_certifies":
        _rewrite_footer(root, capture_complete=True)
    elif missing == "receipt_not_complete":
        receipt["capture_complete"] = False
    elif missing == "receipt_without_flag":
        del receipt["capture_complete"]
    elif missing == "rc_nonzero":
        (capture / "return_code.txt").write_text("1\n")
    elif missing == "one_stream_only":
        _rewrite_footer(root, data_present_both_streams=False)
    (capture / "receipt.json").write_text(json.dumps(receipt))
    _relist(root)
    if missing == "stderr_unlisted":
        manifest = json.loads((root / "manifest.json").read_text())
        manifest["files"] = [f for f in manifest["files"] if not f["path"].endswith("stderr.txt")]
        (root / "manifest.json").write_text(json.dumps(manifest))
    result = analyze_capture(root, "capture")
    assert result["status"] == "REFUSED" and "odometry" not in result


@pytest.mark.parametrize("damage,reason", [("tamper", "MANIFEST_MISMATCH"), ("unlisted", "NOT_IN_MANIFEST"),
                                           ("rc", "CAPTURE_NOT_CONFIRMED_COMPLETE")])
def test_unverified_or_unconfirmed_capture_is_refused(fields_binary, tmp_path, damage, reason):
    root = _trial(tmp_path, _run(fields_binary, "valid"), rc=2 if damage == "rc" else 0,
                  list_capture=damage != "unlisted")
    if damage == "tamper":
        with (root / "capture/journal.jsonl").open("ab") as journal:
            journal.write(b"\n")
    result = analyze_capture(root, "capture")
    assert result["status"] == "REFUSED" and any(r.startswith(reason) for r in result["reasons"])
    assert "odometry" not in result


def test_real_historical_capture_is_analyzed_without_pose_metrics():
    result = analyze_capture(ROOT / EB113, EB113_CAPTURE)  # REAL capture (schema /2), manifest-verified
    assert result["status"] == "ANALYZED" and result["capture_schema"] == "tfg.rover.passive-capture/2"
    assert result["pose_fields_present"] is False and result["r1_contrastable"] == {}
    (group,) = result["odometry"]["groups"]
    assert group["frame_id"] == "odom" and group["child_frame_id"] == "base_link" and group["retained_samples"] == 19
    assert group["covered_header_span_ns"] == 360_000_000 and group["covered_receipt_span_ns"] > 22 * 10**9


REAL_3 = "simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-8fad-457e-918e-253483a2d728"
REAL_3_CAPTURE = "container-copies/tmp/tfg_rover_xrce_capture/4ac58516-8fad-457e-918e-253483a2d728"


def test_rc_json_form_is_accepted_and_an_uncertain_timeout_is_refused(fields_binary, tmp_path):
    root = _trial(tmp_path, _run(fields_binary, "valid"))
    capture = root / "capture"
    for record, status in (({"rc": 0, "timeout_uncertain": False}, "ANALYZED"),
                           ({"rc": 0, "timeout_uncertain": True}, "REFUSED")):
        (capture / "return_code.txt").unlink(missing_ok=True)
        (capture / "return_code.json").write_text(json.dumps(record))
        files = [p for p in sorted(capture.iterdir())]
        (root / "manifest.json").write_text(json.dumps({"files": [
            {"path": f"capture/{p.name}", "size_bytes": p.stat().st_size,
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}))
        assert analyze_capture(root, "capture")["status"] == status


def test_real_closed_3_capture_metrics_are_observations_only():
    """REAL headless /3 capture closed by the rover subsystem (manifest-verified). Descriptive retained samples only."""
    result = analyze_capture(ROOT / REAL_3, REAL_3_CAPTURE)
    assert result["status"] == "ANALYZED" and result["capture_schema"] == FIELDS_SCHEMA
    assert result["trial_manifest_sha256"] == "a88a09f9cfcce654709a6524eb30da3867408e8c48b8e7631dd7b8c7d9bdf8a5"
    assert result["journal_sha256"] == "13811afdfe8b20b71e3b5f1ff595c546ebdc5ff5c4919ef77424216d679a3f18"
    evidence = result["completion_evidence"]
    assert (evidence["footer_capture_complete"], evidence["receipt_capture_complete"], evidence["returncode"],
            evidence["data_present_both_streams"], evidence["stderr_bytes"]) == (None, True, 0, True, 0)
    (group,) = result["odometry"]["groups"]
    assert (group["frame_id"], group["child_frame_id"], group["retained_samples"], group["incomplete"]) == \
        ("odom", "base_link", 19, 0)
    assert group["position_m_as_received"]["y"]["pstdev"] < 1e-5 and group["linear_speed_norm"]["max"] < 2e-4
    assert group["all_zero_declared_covariances"] == 38  # declared zero: NOT certainty
    q = group["orientation_quaternion_as_received"]
    assert abs(q["x"]["max"]) > 1e-3 and abs(q["y"]["max"]) > 1e-3  # non-planar beyond the controller's 1e-3
    assert group["covered_header_span_ns"] == 360_000_000 and group["covered_receipt_span_ns"] > 18 * 10**9
    assert result["movement_authorized"] is False and result["source_association_verified"] is False


def test_real_3_markdown_report_is_deterministic_and_keeps_evidences_apart():
    from tools.rover_passive_journal import render_capture_markdown
    result = analyze_capture(ROOT / REAL_3, REAL_3_CAPTURE)
    text = render_capture_markdown(result)
    assert text == render_capture_markdown(analyze_capture(ROOT / REAL_3, REAL_3_CAPTURE))
    assert "Footer del colector `capture_complete`: `null`" in text
    assert "Recibo externo `capture_complete`: `true`" in text and "Retorno: `0`" in text
    assert "no se deriva" not in text and "not attributed to any cause" in text
    assert "not independent proof of physical rest" in text and "**no** es certeza" in text
