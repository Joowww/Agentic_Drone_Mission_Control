"""Independent check of each derived mission in a package-finalized package against its original finalization.

    python evaluation/observability/hermes_finalized_package_two_drones_2026_10_30/tools/check_correspondence.py PACKAGE STORE
Recomputes, from the files themselves (package copies, the store and the site), vehicle, takeoff, geographic and
vertical references and each waypoint's north/east offset; prints JSON and exits 1 on any mismatch."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from inputs.qgc_plan_export import ALT_DECIMALS, LATLON_DECIMALS  # noqa: E402  (the exporter's declared precision)
from planning.site_geometry import geo_to_local, local_to_geo, local_to_north_east  # noqa: E402

TOLERANCE_M = 1e-6


def main(package: Path, store: Path) -> int:
    instance = json.loads((package / "instance.json").read_bytes())
    manifest = json.loads((package / "manifest.json").read_bytes())
    site = json.loads((package / "site.json").read_bytes())
    geo, frame = site["geo_reference"], site["local_frame"]
    points = {p["point_id"]: p for p in site["points"]}
    results, problems = [], []
    for entry, artifact in zip(instance["aerial"], manifest["artifacts"]):
        vehicle, source = entry["vehicle_id"], entry["source"]
        takeoff_id = next(a["takeoff_point"] for a in instance["inputs"]["assignments"] if a["vehicle_id"] == vehicle)
        snapshot = store / "drafts" / source["draft_id"] / source["finalization_id"]
        original_bytes = (snapshot / "mission.json").read_bytes()
        original, derived = json.loads(original_bytes), json.loads((package / artifact["mission_file"]).read_bytes())
        finalization = json.loads((snapshot / "finalization.json").read_bytes())
        declared = finalization["geometry_intent"]["offsets"]
        takeoff = points[takeoff_id]
        home_expected = local_to_geo(takeoff["x_m"], takeoff["y_m"], origin_latitude=geo["latitude"],
                                     origin_longitude=geo["longitude"], y_axis_bearing_deg=frame["y_axis_bearing_deg"])
        offsets = []
        for w in derived["route"]["waypoints"]:
            x, y = geo_to_local(w["latitude"], w["longitude"], origin_latitude=geo["latitude"],
                                origin_longitude=geo["longitude"], y_axis_bearing_deg=frame["y_axis_bearing_deg"])
            north, east = local_to_north_east(x - takeoff["x_m"], y - takeoff["y_m"], frame["y_axis_bearing_deg"])
            offsets.append({"waypoint_id": w["waypoint_id"], "north_m": north, "east_m": east})
        offset_error = max(max(abs(o["north_m"] - d["north_m"]), abs(o["east_m"] - d["east_m"]))
                           for o, d in zip(offsets, declared))
        unchanged = {k: original[k] == derived[k] for k in original if k not in ("mission_id", "name", "route")}
        same_route_fields = (original["route"]["mode"] == derived["route"]["mode"]
                             and original["route"]["return_to_home"] == derived["route"]["return_to_home"]
                             and [{k: v for k, v in w.items() if k not in ("latitude", "longitude")}
                                  for w in original["route"]["waypoints"]] ==
                             [{k: v for k, v in w.items() if k not in ("latitude", "longitude")}
                              for w in derived["route"]["waypoints"]]
                             and original["route"]["home"]["altitude_m"] == derived["route"]["home"]["altitude_m"])
        plan = json.loads((package / artifact["plan_file"]).read_bytes())
        planned_home = plan["mission"]["plannedHomePosition"]
        checks = {
            "original_unchanged_in_store": hashlib.sha256(original_bytes).hexdigest() == source["mission_sha256"],
            "original_copied_byte_for_byte": (package / f"hermes/{vehicle}/mission.json").read_bytes() == original_bytes,
            "derived_hash_is_new": artifact["mission_sha256"] != source["mission_sha256"]
                                   and hashlib.sha256((package / artifact["mission_file"]).read_bytes()).hexdigest()
                                   == artifact["mission_sha256"],
            "vehicle_matches_assignment": original["vehicle"]["vehicle_id"] == derived["vehicle"]["vehicle_id"] == vehicle,
            "other_mission_fields_unchanged": all(unchanged.values()) and same_route_fields,
            "home_is_selected_takeoff": abs(derived["route"]["home"]["latitude"] - home_expected[0]) < 1e-12
                                        and abs(derived["route"]["home"]["longitude"] - home_expected[1]) < 1e-12,
            "offsets_equal_finalized_geometry": offset_error <= TOLERANCE_M,
            "plan_home_is_takeoff_with_site_amsl": planned_home == [
                round(derived["route"]["home"]["latitude"], LATLON_DECIMALS),
                round(derived["route"]["home"]["longitude"], LATLON_DECIMALS),
                round(site["vertical_reference"]["origin_ground_amsl_m"], ALT_DECIMALS)],
            "approval_not_inherited": entry["approval_inherited"] is False,
            "derived_validated_again": entry["deterministic_validation"]["execution_status"] == "APPROVED",
        }
        problems += [f"{vehicle}: {name}" for name, ok in checks.items() if not ok]
        results.append({"vehicle_id": vehicle, "takeoff_point": takeoff_id, "takeoff_local_xy_m": [takeoff["x_m"], takeoff["y_m"]],
                        "original_mission_sha256": source["mission_sha256"], "derived_mission_sha256": artifact["mission_sha256"],
                        "derived_home": [derived["route"]["home"]["latitude"], derived["route"]["home"]["longitude"]],
                        "plan_planned_home": planned_home, "declared_offsets": declared, "recomputed_offsets": offsets,
                        "max_offset_error_m": offset_error, "checks": checks})
    print(json.dumps({"status": "CORRESPONDS" if not problems else "MISMATCH", "problems": problems,
                      "site": {"id": site["site_id"], "version": site["version"], "status": site["status"],
                               "geo_reference": [geo["latitude"], geo["longitude"]],
                               "origin_ground_amsl_m": site["vertical_reference"]["origin_ground_amsl_m"],
                               "terrain": site["vertical_reference"]["terrain"]},
                      "missions": results}, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
