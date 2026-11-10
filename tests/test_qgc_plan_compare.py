"""The QGC re-save comparator, exercised with synthetic changes to a .plan produced by our exporter."""
import copy
import json

import pytest

from inputs.json_loader import load_mission_json
from inputs.qgc_plan_export import build_plan, plan_bytes
from tools.qgc_plan_compare import compare_plans, main, write_comparison


@pytest.fixture(scope="module")
def plan():
    mission = load_mission_json("missions/examples/agri_demo_001_sector_a.json")
    return build_plan(mission, planned_home_amsl_m=584.0)[0]  # TAKEOFF, SPEED, WP, WP, LAND


def _saved(plan, change=None, *, indent=4):
    data = copy.deepcopy(plan)
    if change:
        change(data)
    return json.dumps(data, indent=indent).encode()


def _rows(result, category):
    return [r for r in result["differences"] if r["category"] == category]


def test_identical_bytes(plan):
    assert compare_plans(plan_bytes(plan), plan_bytes(plan))["status"] == "IDENTICAL_BYTES"


def test_presentation_only(plan):
    def reorder(d):
        d["mission"] = dict(reversed(list(d["mission"].items())))
        d["mission"]["items"][2]["params"][6] = 5  # 5.0 -> 5
    result = compare_plans(plan_bytes(plan), _saved(plan, reorder, indent=2))
    assert result["status"] == "NO_SEMANTIC_DIFFERENCES"
    assert {r["category"] for r in result["differences"]} == {"PRESENTATION"}


def test_qgc_metadata_is_separated(plan):
    def qgc(d):
        d["groundStation"] = "QGroundControl 9.9"
        d["mission"]["hoverSpeed"] = 5.0
        del d["mission"]["items"][1]["Altitude"], d["mission"]["items"][1]["AltitudeMode"]  # DO_CHANGE_SPEED
        d["mission"]["items"][2]["AMSLAltAboveTerrain"] = 589.0
    result = compare_plans(plan_bytes(plan), _saved(plan, qgc))
    assert result["status"] == "NO_SEMANTIC_DIFFERENCES"
    assert len(_rows(result, "QGC_METADATA")) == 5 and not _rows(result, "SEMANTIC_CHANGE")


@pytest.mark.parametrize("change, fragment", [
    (lambda d: d["mission"]["items"][4].__setitem__("command", 20), "command NAV_LAND -> NAV_RETURN_TO_LAUNCH"),
    (lambda d: d["mission"]["items"][2]["params"].__setitem__(6, 15.0), "param7 (altitude)"),
    (lambda d: d["mission"]["items"][2].__setitem__("frame", 0), "frame"),
    (lambda d: d["mission"]["items"][1]["params"].__setitem__(1, 5.0), "param2 (speed_mps)"),
    (lambda d: d["mission"]["items"][3]["params"].__setitem__(4, 41.2752), "param5 (latitude)"),
    (lambda d: d["mission"]["plannedHomePosition"].__setitem__(2, 0.0), "planned home AMSL altitude"),
    (lambda d: d["mission"].__setitem__("firmwareType", 12), "firmwareType"),
])
def test_semantic_changes(plan, change, fragment):
    result = compare_plans(plan_bytes(plan), _saved(plan, change))
    assert result["status"] == "SEMANTIC_DIFFERENCES"
    assert any(fragment in r["detail"] for r in _rows(result, "SEMANTIC_CHANGE")), result["differences"]


def test_yaw_null_and_zero_are_not_equivalent(plan):
    result = compare_plans(plan_bytes(plan), _saved(plan, lambda d: d["mission"]["items"][2]["params"].__setitem__(3, 0)))
    row = _rows(result, "SEMANTIC_CHANGE")[0]
    assert "param4 (yaw)" in row["detail"] and "not equivalent" in row["detail"]
    # null where ArduPilot does not accept NaN is flagged as such
    result = compare_plans(plan_bytes(plan), _saved(plan, lambda d: d["mission"]["items"][2]["params"].__setitem__(0, None)))
    assert "NaN is not accepted here" in _rows(result, "SEMANTIC_CHANGE")[0]["detail"]


def test_nan_token_is_not_treated_as_null(plan):
    text = _saved(plan).decode().replace("null,\n                    41.27507186", "NaN,\n                    41.27507186")
    result = compare_plans(plan_bytes(plan), text.encode())
    assert result["status"] == "UNDETERMINED"
    assert any("non-standard JSON constant" in r["detail"] for r in result["differences"])


def test_removed_and_added_items(plan):
    removed = compare_plans(plan_bytes(plan), _saved(plan, lambda d: d["mission"]["items"].pop()))
    assert [r["detail"] for r in _rows(removed, "REMOVED")] == ["item NAV_LAND absent from the saved file"]
    def add(d):
        d["mission"]["items"].insert(4, copy.deepcopy(d["mission"]["items"][3]))
        for n, item in enumerate(d["mission"]["items"], 1):
            item["doJumpId"] = n
    added = compare_plans(plan_bytes(plan), _saved(plan, add))
    assert added["status"] == "SEMANTIC_DIFFERENCES" and len(_rows(added, "ADDED")) == 1
    # QGC renumbering without DO_JUMP references is metadata, not a semantic change
    assert all(r["category"] != "SEMANTIC_CHANGE" for r in added["differences"])


def test_undetermined_cases(plan):
    cases = [
        lambda d: d["mission"]["items"][2].__setitem__("qgcExtraField", 1),
        lambda d: d["mission"]["items"][2].__setitem__("autoContinue", 1),
        lambda d: d["mission"]["items"][2].__setitem__("AltitudeMode", 0),
        lambda d: d["mission"]["items"][2]["params"].__setitem__(4, 41.27507186 + 1e-9),  # same degE7 integer
        lambda d: d["mission"]["items"][2].__setitem__("Altitude", 6.0),  # disagrees with param7
        lambda d: d["mission"]["items"][2].__setitem__("type", "ComplexItem"),
    ]
    for change in cases:
        result = compare_plans(plan_bytes(plan), _saved(plan, change))
        assert _rows(result, "UNDETERMINED"), result["differences"]
        assert result["status"] in ("UNDETERMINED", "SEMANTIC_DIFFERENCES")


@pytest.mark.parametrize("saved, fragment", [
    (b"{ not json", "invalid JSON"),
    (b'{"fileType": "Plan", "fileType": "Plan", "mission": {"items": []}}', "duplicate keys"),
    (b'{"fileType": "Plan"}', "not a plan"),
    (b"\xff\xfe", "not UTF-8"),
])
def test_unreadable_saved_file_is_explicit(plan, saved, fragment):
    result = compare_plans(plan_bytes(plan), saved)
    assert result["status"] == "UNREADABLE_SAVED" and fragment in result["error"]


def test_cli_keeps_copies_and_text_diff(plan, tmp_path):
    original, saved = tmp_path / "a.plan", tmp_path / "b.plan"
    original.write_bytes(plan_bytes(plan))
    saved.write_bytes(_saved(plan, lambda d: d["mission"]["items"].pop()))
    out = tmp_path / "cmp"
    assert main([str(original), str(saved), "--out", str(out)]) == 1
    assert (out / "original.plan").read_bytes() == original.read_bytes()
    assert (out / "saved.plan").read_bytes() == saved.read_bytes()
    assert "-                \"command\": 21" in (out / "text.diff").read_text()
    assert json.loads((out / "comparison.json").read_text())["status"] == "SEMANTIC_DIFFERENCES"
    assert "REMOVED" in (out / "comparison.md").read_text()
    assert main([str(original), str(saved), "--out", str(out)]) == 3  # never overwritten
    bad = tmp_path / "bad.plan"
    bad.write_bytes(b"{")
    assert write_comparison(original, bad, tmp_path / "cmp2")["status"] == "UNREADABLE_SAVED"
    assert (tmp_path / "cmp2/saved.plan").read_bytes() == b"{"
