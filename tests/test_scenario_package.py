import json
import shutil
from pathlib import Path

import pytest

from inputs.qgc_plan_export import ExportRefused, build_plan, plan_bytes, verify_plan
from inputs.json_loader import load_mission_json
from models.fleet import Fleet
from models.scenario_template import ScenarioTemplate
from planning.scenario_instance import (
    H2_ROOT, approval_draft, check_approval, coordination_checks, historical_h2_instance, instantiate,
)
from tools.scenario_package import build_package, main, verify_package

FLEET = Path("missions/fleets/agri_demo_fleet.json")
TEMPLATES = Path("missions/templates")
SITES = Path("missions/sites")
BASE = TEMPLATES / "agri_poi_visit_v1.json"
SITE_V1 = SITES / "synthetic_orchard_v1.site.json"


def _package(tmp_path, name, template=BASE, site=SITE_V1, target="sitl", approval=None):
    return build_package(instantiate(template, site, FLEET), tmp_path / name, target=target, approval=approval)


def _states(manifest):
    return {a["task_id"]: a["state"] for a in manifest["artifacts"]}


def test_b_new_scenario_on_a_synthetic_site(tmp_path):
    manifest = _package(tmp_path, "b")
    assert manifest["provenance"] == "SYNTHETIC" and manifest["package_status"] == "COMPLETE_OFFLINE"
    assert _states(manifest) == {"A1": "GENERATED", "A2": "GENERATED"}
    assert manifest["deployment_ready"] is False
    assert manifest["lifecycle"] == {"exported": "DONE",
                                     "file_checks": "FILE_MATCHES_EXPECTATIONS; importer readback REDUCED",
                                     "imported_in_qgroundcontrol": "NOT_DONE", "uploaded_to_vehicle": "NOT_DONE",
                                     "read_back_from_vehicle": "NOT_DONE", "executed": "NOT_DONE"}
    plans = sorted(p.name for p in (tmp_path / "b/plans").iterdir())
    assert plans == ["drone_01.plan", "drone_02.plan"]  # one .plan per drone, never merged
    assert manifest["ground_tasks"][0]["export"].startswith("FORMAT_PENDING")
    assert verify_package(tmp_path / "b")["status"] == "INTEGRITY_VERIFIED"
    derivation = json.loads((tmp_path / "b/instance.json").read_text())["aerial"][0]["derivation"]
    assert derivation[1]["site_point"] == "POI_1" and derivation[1]["local_xy_m"] == [-4.0, 4.0]


def test_same_input_same_bytes_and_no_overwrite(tmp_path):
    _package(tmp_path, "one")
    _package(tmp_path, "two")
    for path in (tmp_path / "one").rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (tmp_path / "two" / path.relative_to(tmp_path / "one")).read_bytes()
    with pytest.raises(FileExistsError):
        _package(tmp_path, "one")


def test_c_dronelab_template_refuses_geographic_export(tmp_path):
    for target in ("sitl", "field"):
        manifest = _package(tmp_path, f"c_{target}", site=SITES / "dronelab.template.site.json", target=target)
        assert set(_states(manifest).values()) == {"BLOCKED_MISSING_DATA"}
        assert manifest["package_status"] == "PARTIAL" and not (tmp_path / f"c_{target}/plans").exists()


def test_synthetic_site_never_exports_for_the_field(tmp_path):
    manifest = _package(tmp_path, "field", target="field")
    assert set(_states(manifest).values()) == {"BLOCKED_MISSING_DATA"}
    assert "SYNTHETIC site: never a proposal for hardware" in manifest["artifacts"][0]["reasons"]


def test_d_unresolved_or_unknown_vehicle(tmp_path):
    manifest = _package(tmp_path, "d", template=TEMPLATES / "agri_poi_visit_unresolved_fleet_v1.json")
    assert _states(manifest) == {"A1": "GENERATED", "A2": "COMPATIBILITY_PENDING", "A3": "BLOCKED_MISSING_DATA"}
    assert manifest["coordination"]["status"] == "FAIL" and manifest["package_status"] == "PARTIAL"
    assert not (tmp_path / "d/plans/mini_drone_01.plan").exists()


def test_e_route_through_an_exclusion_and_rover_line_needing_planning(tmp_path):
    manifest = _package(tmp_path, "e", template=TEMPLATES / "agri_poi_visit_crossing_v1.json")
    assert _states(manifest) == {"A1": "GENERATED", "A2": "BLOCKED_VALIDATION_FAILED"}
    assert any("TREE_ROW_1" in r for r in manifest["artifacts"][1]["reasons"])
    assert manifest["ground_tasks"][0]["spatial_validation"]["status"] == "REQUIRES_PLANNING"


def test_f_site_change_makes_the_previous_approval_stale(tmp_path):
    bundle = instantiate(BASE, SITE_V1, FLEET)
    approval = approval_draft(bundle["instance"], "SITL_REHEARSAL")
    assert check_approval(approval, bundle["instance"], "SITL_REHEARSAL")["mismatches"] == ["approved_by empty"]
    approval.update(kind="SYNTHETIC_TEST_FIXTURE", approved_by="SYNTHETIC_TEST_FIXTURE (not a person)")
    first = build_package(bundle, tmp_path / "v1", target="sitl", approval=approval)
    second = _package(tmp_path, "v2", site=SITES / "synthetic_orchard_v2.site.json", approval=approval)
    assert first["approval"]["status"] == "BOUND" and second["approval"]["status"] == "STALE"
    assert first["instance_id"] != second["instance_id"]
    assert first["artifacts"][0]["mission_sha256"] != second["artifacts"][0]["mission_sha256"]
    assert "operator approval STALE" in second["deployment_blockers"] and second["deployment_ready"] is False
    assert check_approval(approval, bundle["instance"], "FIELD")["status"] == "STALE"


def test_a_historical_missions_keep_their_references(tmp_path):
    bundle = historical_h2_instance(fleet_path=FLEET)
    instance = bundle["instance"]
    assert instance["provenance"] == "SITL_HISTORICAL" and instance["coordination"]["order"][:2] == [
        "H2_drone_01", "H2_drone_02"]
    for entry in instance["aerial"]:
        assert entry["references"]["declared_home_in_mission"]["latitude"] == 41.275
        assert entry["references"]["effective_home"].startswith("NOT_RECORDED")
        for row in entry["consistency_with_h2"]:  # the rebase reproduces the executor's mapped targets
            assert abs(row["recomputed_error_m"] - row["recorded_horizontal_error_m"]) < 0.005
    manifest = build_package(bundle, tmp_path / "a", target="sitl")
    assert _states(manifest) == {"H2_drone_01": "GENERATED", "H2_drone_02": "GENERATED"}
    assert manifest["site"] is None and verify_package(tmp_path / "a")["status"] == "INTEGRITY_VERIFIED"
    plan = json.loads((tmp_path / "a/plans/drone_01.plan").read_text())
    assert plan["mission"]["plannedHomePosition"][2] == pytest.approx(584.19, abs=1e-3)
    # H2: return to the observed launch coordinate, then LAND; the .plan lands at that same coordinate, no RTL.
    land = plan["mission"]["items"][-1]
    assert land["command"] == 21 and land["params"][4:6] == plan["mission"]["plannedHomePosition"][:2]
    semantics = {r["element"]: r["status"] for r in manifest["artifacts"][0]["conversion"]["semantics"]}
    assert semantics["return coordinate"] == "EXACT" and semantics["landing command"] == "EXACT"
    assert "does not claim dynamic equivalence" in manifest["artifacts"][0]["conversion"]["label_scope"]
    assert semantics["waypoint acceptance"] == "CONDITIONED" and semantics["speed"] == "NOT_IN_PLAN"
    # The 1 mm agreement concerns the geometric reconstruction only.
    assert manifest["lifecycle"]["imported_in_qgroundcontrol"] == "NOT_DONE"
    field = build_package(bundle, tmp_path / "a_field", target="field")
    assert set(_states(field).values()) == {"BLOCKED_MISSING_DATA"}


def test_historical_evidence_must_match_its_sums(tmp_path):
    copy = tmp_path / "h2"
    shutil.copytree(H2_ROOT, copy)
    (copy / "child_1_2f7db1f6/mission.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="SHA256SUMS"):
        historical_h2_instance(copy)


def test_verify_detects_tampering(tmp_path):
    _package(tmp_path, "t")
    plan = tmp_path / "t/plans/drone_01.plan"
    plan.write_text(plan.read_text().replace("-35.3633159", "-35.3633150"))
    result = verify_package(tmp_path / "t")
    assert result["status"] == "FAILED" and any("drone_01.plan" in p for p in result["problems"])
    (tmp_path / "t/extra.txt").write_text("x")
    assert "unlisted file: extra.txt" in verify_package(tmp_path / "t")["problems"]


def test_exporter_refuses_what_it_cannot_express(tmp_path):
    mission = load_mission_json("missions/examples/agri_demo_001_sector_a.json")
    with pytest.raises(ExportRefused, match="AMSL"):
        build_plan(mission, planned_home_amsl_m=None)
    photo = mission.model_copy(deep=True)
    photo.route.waypoints[0].action = "take_photo"
    ground = mission.model_copy(deep=True)
    ground.route.waypoints[0].altitude_m = 0.0
    raised = mission.model_copy(deep=True)
    raised.route.home.altitude_m = 100.0
    for bad, fragment in ((photo, "take_photo"), (ground, "keep the current altitude"), (raised, "ambiguous")):
        with pytest.raises(ExportRefused, match=fragment):
            build_plan(bad, planned_home_amsl_m=100.0)


def test_exporter_items_and_independent_verification(tmp_path):
    mission = load_mission_json("missions/examples/agri_demo_001_sector_a.json")
    plan, log = build_plan(mission, planned_home_amsl_m=100.0)
    # Literal expectations written from the sources (ArduPilot 755258db mode_auto.cpp / AP_Mission.cpp, QGC
    # plan format), not computed by build_plan: command, frame, params, coordinates and altitude.
    expected = [
        (22, 3, [0, 0, 0, None, 41.275, 1.987, 5.0]),
        (178, 2, [1, 2.778, 0, 0, 0, 0, 0]),
        (16, 3, [0, 0, 0, None, 41.27507186, 1.98695219, 5.0]),
        (16, 3, [0, 0, 0, None, 41.27514373, 1.98695219, 5.0]),
        (21, 3, [0, 0, 0, None, 41.275, 1.987, 0]),
    ]
    assert [(i["command"], i["frame"], i["params"]) for i in plan["mission"]["items"]] == expected
    assert [i["doJumpId"] for i in plan["mission"]["items"]] == [1, 2, 3, 4, 5]
    assert [i["Altitude"] for i in plan["mission"]["items"]] == [5.0, 0, 5.0, 5.0, 0]
    assert plan["mission"]["plannedHomePosition"] == [41.275, 1.987, 100.0]
    assert "not validated" in log["items"][1]["note"]
    path = tmp_path / "a.plan"
    path.write_bytes(plan_bytes(plan))
    result = verify_plan(path, mission, planned_home_amsl_m=100.0)
    assert result["status"] == "FILE_MATCHES_EXPECTATIONS" and result["max_degE7_quantization_m"] < 0.02
    assert result["compatibility"].startswith("NOT_ESTABLISHED")
    # Our importer drops TAKEOFF and reduces LAND to a waypoint: visible, never "verified".
    readback = result["importer_readback"]
    assert readback["status"] == "REDUCED" and readback["waypoint_geometry"] == "MATCH"
    assert any("TAKEOFF" in loss for loss in readback["losses"])
    assert any("NAV_LAND represented as an extra navigation waypoint" in loss for loss in readback["losses"])
    assert verify_plan(path, mission, planned_home_amsl_m=101.0)["status"] == "FAILED"


def test_no_return_lands_at_the_last_waypoint_like_the_executor(tmp_path):
    mission = load_mission_json("missions/examples/agri_demo_001_sector_a.json")
    mission.route.return_to_home = False
    plan, log = build_plan(mission, planned_home_amsl_m=100.0)
    assert plan["mission"]["items"][-1]["params"][4:6] == [41.27514373, 1.98695219]
    assert {r["element"]: r["detail"] for r in log["semantics"]}["return coordinate"].startswith("no return")


@pytest.mark.parametrize("index, field, value, fragment", [
    (0, "params", [0, 0, 0, None, 41.275, 1.987, 0], "altitude must be > 0"),
    (2, "frame", 0, "frame 0 != 3"),
    (2, "params", [0, 2, 0, None, 41.27507186, 1.98695219, 5.0], "param2 2 != 0"),
    (1, "params", [1, 2.778, -1, 0, 0, 0, 0], "param3 -1 != 0"),
    (4, "params", [0, 0, 0, None, 0, 0, 0], "lat/lon must be explicit"),
    (4, "command", 20, "not part of"),
])
def test_mavlink_expectations_catch_shared_mistakes(tmp_path, index, field, value, fragment):
    from inputs.qgc_plan_export import check_mavlink_item
    mission = load_mission_json("missions/examples/agri_demo_001_sector_a.json")
    plan, _ = build_plan(mission, planned_home_amsl_m=100.0)
    plan["mission"]["items"][index][field] = value
    assert any(fragment in p for p in check_mavlink_item(plan["mission"]["items"][index]))
    path = tmp_path / "x.plan"
    path.write_bytes(plan_bytes(plan))
    assert verify_plan(path, mission, planned_home_amsl_m=100.0)["status"] == "FAILED"


def test_superseded_v1_package_is_reported_not_reverified():
    root = Path("evaluation/observability/agri_site_fleet_export_2026_10_27/packages/b_synthetic_orchard_v1_sitl")
    if not root.is_dir():
        pytest.skip("27/10 evidence not present in this copy")
    result = verify_package(root)
    assert result["status"] == "INTEGRITY_VERIFIED"
    assert {p["status"] for p in result["plans"]} == {"PROFILE_SUPERSEDED"}


def test_summary_shows_margin_parameters_and_approval(tmp_path):
    from tools.scenario_package import summary_lines
    _package(tmp_path, "s")
    text = "\n".join(summary_lines(tmp_path / "s"))
    assert "margin NOT_ACCREDITED" in text and "WP_RADIUS_M" in text and "operator approval ABSENT" in text
    assert "importer REDUCED" in text
    report = (tmp_path / "s/export_report.md").read_text()
    assert "NOT_ACCREDITED" in report and "CONDITIONED" in report and "755258db" in report


def test_editing_declarations_in_the_template_does_not_produce_an_approved_package(tmp_path):
    data = json.loads((SITES / "dronelab.template.site.json").read_text())
    data["status"] = "VERIFIED_DECLARED"
    for section in ("local_frame", "geo_reference", "vertical_reference"):
        key = "orientation_verification" if section == "local_frame" else "verification"
        data[section][key] = "VERIFIED_DECLARED"
    edited = tmp_path / "edited.site.json"
    edited.write_text(json.dumps(data))
    manifest = build_package(instantiate(BASE, edited, FLEET), tmp_path / "e1", target="field")
    assert set(_states(manifest).values()) == {"BLOCKED_MISSING_DATA"}  # provenance TEMPLATE + no geometry
    assert manifest["layers"]["geometric_validation"] == "INVALID"
    # Even a complete, declared-verified site only yields files: approval stays a separate hash binding.
    full = json.loads(SITE_V1.read_text())
    full.update(status="VERIFIED_DECLARED", provenance={"kind": "MEASURED", "source": "test", "measured_on": "2026-10-27"})
    full["local_frame"]["orientation_verification"] = "VERIFIED_DECLARED"
    full["geo_reference"]["verification"] = full["vertical_reference"]["verification"] = "VERIFIED_DECLARED"
    declared = tmp_path / "declared.site.json"
    declared.write_text(json.dumps(full))
    manifest = build_package(instantiate(BASE, declared, FLEET), tmp_path / "e2", target="field")
    assert set(_states(manifest).values()) == {"GENERATED"}
    assert manifest["approval"]["status"] == "ABSENT" and manifest["deployment_ready"] is False
    assert manifest["layers"] == {"operator_declaration": "VERIFIED_DECLARED", "measurement_provenance": "MEASURED",
                                  "geometric_validation": "VALID", "deployment_approval": "ABSENT"}


def _template(**changes):
    data = json.loads(BASE.read_text())
    data.update(changes)
    return ScenarioTemplate.model_validate(data)


def test_coordination_detects_cycles_unknown_tasks_and_bad_order():
    fleet = Fleet.model_validate_json(FLEET.read_bytes())
    base = json.loads(BASE.read_text())
    cyclic = _template(dependencies=[*base["dependencies"], {"task_id": "A1", "after": "R1", "condition": "COMPLETED"}])
    assert any("cycle" in e for e in coordination_checks(cyclic, fleet)["errors"])
    unknown = _template(dependencies=[{"task_id": "A2", "after": "A9", "condition": "COMPLETED"}])
    assert any("unknown task" in e for e in coordination_checks(unknown, fleet)["errors"])
    wrong_point = _template(dependencies=[{"task_id": "R1", "after": "A1", "condition": "POI_REACHED", "point": "POI_4"}])
    assert any("not visited" in e for e in coordination_checks(wrong_point, fleet)["errors"])
    reordered = _template(execution_order=["A2", "A1", "R1"])
    assert any("before A1" in e for e in coordination_checks(reordered, fleet)["errors"])
    tasks = json.loads(BASE.read_text())["aerial_tasks"]
    tasks[1]["vehicle_id"] = "drone_01"
    assert any("more than one task" in e for e in coordination_checks(_template(aerial_tasks=tasks), fleet)["errors"])
    tasks[1]["vehicle_id"] = "rover_01"
    assert any("air task assigned to rover" in e for e in coordination_checks(_template(aerial_tasks=tasks), fleet)["errors"])
    assert coordination_checks(_template(), fleet)["status"] == "PASS"


def test_cli_validate_and_refuse(tmp_path, capsys):
    assert main(["validate-site", str(SITE_V1)]) == 0
    assert main(["validate-site", str(SITES / "dronelab.template.site.json")]) == 1
    assert main(["validate-fleet", str(FLEET)]) == 0
    out = tmp_path / "p"
    args = ["package", "--template", str(BASE), "--site", str(SITE_V1), "--fleet", str(FLEET), "--target", "sitl",
            "--out", str(out)]
    assert main(args) == 0 and main(args) == 2
    assert main(["verify", str(out)]) == 0
    assert main(["approval-draft", "--package", str(out), "--out", str(tmp_path / "a.json")]) == 0
    assert json.loads((tmp_path / "a.json").read_text())["approved_by"] is None
    assert "COMPLETE_OFFLINE" in capsys.readouterr().out


def test_menu_reuses_the_cli(tmp_path):
    from tools import agri_scenario_flow as flow
    answers = ["3", "b", "", str(SITE_V1), "", "", str(tmp_path / "m"), "3", "d", str(tmp_path / "m"), "4"]
    lines = []

    def read(prompt=""):
        if not answers:
            raise EOFError
        return answers.pop(0)
    assert flow.run_interactive(read, lines.append) is True
    assert any("COMPLETE_OFFLINE" in line for line in lines)
    assert any('"status": "INTEGRITY_VERIFIED"' in line for line in lines)


# --- finalized Hermes missions (real r2 run, read-only) over an explicitly selected site -------------------------
R2 = Path("evaluation/observability/planning_container_real_2026_10_28_r2")
H1_BINDING = Path("evaluation/observability/agri_planning_h1_nous_2026_10_24/h1_binding.json")
SECTOR_A = "e31bd08d-19ed-440e-b815-94f8b9c062d5/0b6af58a-943c-4f06-a631-1a55d4a66d6d"
SECTOR_B = "c244d68c-819e-4324-b99a-7d299b97081d/dd6055ee-5090-40c9-98b9-d0b8cb85e93a"


def _finalized_args(out, store=R2 / "store", evidence=R2, a=SECTOR_A, b=SECTOR_B, site=SITE_V1, takeoff_a="TAKEOFF_A"):
    return ["package-finalized", "--store", str(store), *(["--hermes-evidence", str(evidence)] if evidence else []),
            "--scenario-binding", str(H1_BINDING), "--assign", f"drone_01={a}@{takeoff_a}",
            "--assign", f"drone_02={b}@TAKEOFF_B", "--rover", "rover_01@ROVER_START", "--site", str(site),
            "--fleet", str(FLEET), "--target", "sitl", "--out", str(out)]


def test_finalized_hermes_missions_are_rebased_on_the_selected_takeoff_points(tmp_path):
    before = (R2 / "SHA256SUMS").read_bytes()
    assert main(_finalized_args(tmp_path / "p")) == 0
    manifest = json.loads((tmp_path / "p/manifest.json").read_text())
    instance = json.loads((tmp_path / "p/instance.json").read_text())
    assert manifest["provenance"] == "HERMES_FINALIZED_ON_SYNTHETIC" and manifest["deployment_ready"] is False
    # Sector A fits the synthetic site from TAKEOFF_A; sector B's own offsets touch TREE_ROW_1 from TAKEOFF_B.
    assert _states(manifest) == {"HERMES_drone_01": "GENERATED", "HERMES_drone_02": "BLOCKED_VALIDATION_FAILED"}
    assert manifest["package_status"] == "PARTIAL" and sorted(p.name for p in (tmp_path / "p/plans").iterdir()) == [
        "drone_01.plan"]
    a = instance["aerial"][0]
    assert a["source"]["mission_sha256"].startswith("321ad647") and a["mission_sha256"] != a["source"]["mission_sha256"]
    assert a["approval_inherited"] is False and a["source"]["validation_at_finalization"]["qgc_export"] == "REFUSED"
    assert a["source"]["hermes_run_id"] == "real-hermes-planning-container-20261028-r2"
    assert a["source"]["in_hermes_final_answer"] is True and a["source"]["relocated_from"].startswith("/opt/tfg/")
    assert a["derivation"]["offsets_vs_finalized_geometry_max_diff_m"] == 0.0
    assert [w["local_xy_m"] for w in a["derivation"]["waypoints"]] == [[-8.0, 2.0], [-8.0, 10.0]]
    assert a["deterministic_validation"]["execution_status"] == "APPROVED" and a["planned_home"]["amsl_m"] == 584.0
    assert (tmp_path / "p/hermes/drone_01/mission.json").read_bytes() == (
        R2 / "store/drafts" / SECTOR_A / "mission.json").read_bytes()  # original kept as a source copy
    assert manifest["ground_tasks"][0]["export"].startswith("FORMAT_PENDING")
    assert manifest["coordination"]["status"] == "PASS" and manifest["coordination"]["order"] == [
        "HERMES_drone_01", "HERMES_drone_02", "R1"]
    assert {"task_id": "R1", "after": "HERMES_drone_01", "condition": "POI_REACHED", "point": "POI_A1"} in [
        {k: v for k, v in d.items() if v is not None} for d in manifest["coordination"]["dependencies"]]
    # A structurally valid sequence is not an executable set: every blocked or pending task is a deployment blocker.
    assert {"HERMES_drone_02 BLOCKED_VALIDATION_FAILED", "R1 FORMAT_PENDING"} <= set(manifest["deployment_blockers"])
    assert "La aprobación de la original **no** se hereda" in (tmp_path / "p/export_report.md").read_text()
    assert verify_package(tmp_path / "p")["status"] == "INTEGRITY_VERIFIED"
    assert (R2 / "SHA256SUMS").read_bytes() == before
    assert main(_finalized_args(tmp_path / "q")) == 0
    assert (tmp_path / "p/manifest.json").read_bytes() == (tmp_path / "q/manifest.json").read_bytes()


def test_finalized_refuses_altered_integrity(tmp_path, capsys):
    store = tmp_path / "store"
    shutil.copytree(R2 / "store", store)
    mission = store / "drafts" / SECTOR_A / "mission.json"
    mission.write_bytes(mission.read_bytes().replace(b'"altitude_m": 5.0', b'"altitude_m": 6.0', 1))
    assert main(_finalized_args(tmp_path / "p", store=store, evidence=None)) == 2
    assert "does not match its snapshot" in capsys.readouterr().err and not (tmp_path / "p").exists()
    evidence = tmp_path / "evidence"
    shutil.copytree(R2, evidence)
    (evidence / "review_result.json").write_text("{}")
    assert main(_finalized_args(tmp_path / "p", store=evidence / "store", evidence=evidence)) == 2
    assert "does not match its SHA256SUMS" in capsys.readouterr().err


def test_finalized_refuses_a_wrong_assignment(tmp_path, capsys):
    assert main(_finalized_args(tmp_path / "p", a=SECTOR_B, b=SECTOR_A)) == 2
    assert "is a mission for drone_02, not drone_01" in capsys.readouterr().err
    assert main(_finalized_args(tmp_path / "p", b=SECTOR_A)) == 2
    assert "each finalization_id may be assigned once" in capsys.readouterr().err


def test_finalized_blocks_on_an_incomplete_site_or_a_wrong_takeoff_point(tmp_path):
    assert main(_finalized_args(tmp_path / "t", site=SITES / "dronelab.template.site.json")) == 0
    manifest = json.loads((tmp_path / "t/manifest.json").read_text())
    assert set(_states(manifest).values()) == {"BLOCKED_MISSING_DATA"} and not (tmp_path / "t/plans").exists()
    assert all(a["mission_sha256"] is None for a in manifest["artifacts"])  # no derivation without site data
    assert main(_finalized_args(tmp_path / "w", takeoff_a="POI_1")) == 0
    manifest = json.loads((tmp_path / "w/manifest.json").read_text())
    assert manifest["artifacts"][0]["state"] == "BLOCKED_VALIDATION_FAILED"
    assert any("'POI_1' is not a planned_takeoff point" in r for r in manifest["artifacts"][0]["reasons"])


def test_menu_packages_finalized_missions_through_the_cli(tmp_path):
    from tools import agri_scenario_flow as flow
    answers = ["3", "f", str(R2 / "store"), f"drone_01={SECTOR_A}@TAKEOFF_A drone_02={SECTOR_B}@TAKEOFF_B", "", "",
               str(R2), str(SITE_V1), "", "", str(tmp_path / "m"), "4"]
    lines = []

    def read(prompt=""):
        if not answers:
            raise EOFError
        return answers.pop(0)
    assert flow.run_interactive(read, lines.append) is True
    assert any("HERMES_drone_01 drone_01: GENERATED" in line for line in lines)
    assert verify_package(tmp_path / "m")["status"] == "INTEGRITY_VERIFIED"


REHEARSAL = SITES / "synthetic_hermes_rehearsal_v1.site.json"


def test_finalized_two_drones_on_the_synthetic_rehearsal_site(tmp_path, capsys):
    from tools.scenario_package import summary_lines
    v1 = SITE_V1.read_bytes()
    assert main(_finalized_args(tmp_path / "p", site=REHEARSAL)) == 0
    manifest = json.loads((tmp_path / "p/manifest.json").read_text())
    instance = json.loads((tmp_path / "p/instance.json").read_text())
    assert manifest["site"]["id"] == "synthetic_hermes_rehearsal" and manifest["site"]["status"] == "SYNTHETIC"
    assert _states(manifest) == {"HERMES_drone_01": "GENERATED", "HERMES_drone_02": "GENERATED"}
    assert sorted(p.name for p in (tmp_path / "p/plans").iterdir()) == ["drone_01.plan", "drone_02.plan"]
    assert manifest["package_status"] == "COMPLETE_OFFLINE" and manifest["deployment_ready"] is False
    assert manifest["approval"]["status"] == "ABSENT" and manifest["ground_tasks"][0]["export"].startswith("FORMAT_PENDING")
    assert "R1 FORMAT_PENDING" in manifest["deployment_blockers"] and "operator approval ABSENT" in manifest[
        "deployment_blockers"]
    for entry, takeoff in zip(instance["aerial"], ([-6.0, -6.0], [6.0, -6.0])):
        assert entry["derivation"]["takeoff_local_xy_m"] == takeoff and entry["approval_inherited"] is False
        assert entry["derivation"]["offsets_vs_finalized_geometry_max_diff_m"] == 0.0
        assert entry["mission_sha256"] != entry["source"]["mission_sha256"]
    text = "\n".join(summary_lines(tmp_path / "p"))
    assert "dependency structure PASS (structural only" in text and "deployment_ready=False; blockers: R1" in text
    assert "no indica que los artefactos estén disponibles" in (tmp_path / "p/export_report.md").read_text()
    assert verify_package(tmp_path / "p")["status"] == "INTEGRITY_VERIFIED"
    assert SITE_V1.read_bytes() == v1  # the historical TREE_ROW_1 collision site stays as it is
