#!/usr/bin/env bash
# Exact command blocks of documentation/demo_toni_2026_11_04.md, run in order (offline, no simulator, no LLM).
set -e
cd ~/TFG/Agentic_Drone_Mission_Control
OUT=$(mktemp -d)
echo "== §2"; .venv/bin/python -c "from pathlib import Path; from observability.hermes_capture_run import verify_manifest; verify_manifest(Path('evaluation/observability/agri_planning_h1_nous_2026_10_24')); import json; b=json.load(open('evaluation/observability/agri_planning_h1_nous_2026_10_24/h1_binding.json')); print('H1', b['status'], {v: a['mission_sha256'][:12] for v, a in b['artifacts'].items()}, b['flight_authorization'])"
echo "== §3"; .venv/bin/python -c "import asyncio; from tools import hermes_mcp_server as s; t=asyncio.run(s.mcp.list_tools()); print(len(t)); print(', '.join(x.name for x in t))"
echo "== §4a"; .venv/bin/python -c "
from inputs.json_loader import load_mission_json
from graph.waypoint_mission_graph import waypoint_mission_graph as g
s = g.invoke({'mission': load_mission_json('missions/examples/simulation_navigation_3waypoint.json')})
print('RESULT', s['mission_status'], s.get('failure_reasons'))" 2>&1 | grep -E 'NODE|ROUTER|RESULT'
echo "== §4b"; .venv/bin/python -c "
import json
from inputs.json_loader import load_mission_json
from graph.waypoint_mission_graph import waypoint_mission_graph as g
m = json.load(open('missions/examples/simulation_navigation_3waypoint.json')); m['environment']['wind_speed_kmh'] = 45.0
json.dump(m, open('$OUT/wind45.json', 'w'))
s = g.invoke({'mission': load_mission_json('$OUT/wind45.json')})
print('RESULT', s['mission_status'], s['failure_reasons'], s['replan_actions'])" 2>&1 | grep -E 'NODE|ROUTER|RESULT'
echo "== §6a"; .venv/bin/python -c "
from pathlib import Path
from inputs.json_loader import load_mission_json
from inputs.qgc_plan_export import refusal_reasons, build_plan, plan_bytes, verify_plan
m = load_mission_json('missions/examples/simulation_navigation_3waypoint.json')
print('SIN AMSL:', refusal_reasons(m))
plan, log = build_plan(m, planned_home_amsl_m=584.0); p = Path('$OUT/demo_3wp.plan'); p.write_bytes(plan_bytes(plan))
print('CON AMSL 584:', len(plan['mission']['items']), 'items;', verify_plan(p, m, planned_home_amsl_m=584.0)['status'])"
echo "== §6b"; P=evaluation/observability/hermes_finalized_package_two_drones_2026_10_30/package/plans
Q=evaluation/observability/qgc_import_hermes_two_drones_2026_10_30/qgc_saved
.venv/bin/python -m tools.qgc_plan_compare $P/drone_01.plan $Q/drone_01.qgc_resaved.plan --out $OUT/cmp01
echo "== §6c"; .venv/bin/python -c "
from inputs.qgroundcontrol_adapter import load_qgroundcontrol_plan
from models.qgc_import import QGroundControlImportContext as C
r = load_qgroundcontrol_plan('$Q/drone_01.qgc_resaved.plan', C(battery_percent=100, battery_consumption_percent_per_minute=0.8, wind_speed_kmh=0, wind_direction_from_deg=0, minimum_battery_reserve_percent=20, maximum_wind_speed_kmh=30, maximum_altitude_m=120, vehicle_id='drone_01'))
print('items', r.source_item_count, 'home AMSL', r.planned_home_amsl_m, [w.waypoint_id for w in r.mission.route.waypoints]); print(r.warnings)"
echo "== §7"; .venv/bin/python -m tools.agri_scenario_flow query --out $OUT/query 2>&1 | tail -7
echo "== §10"; .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_rover_pipe_worker.py -k passive 2>&1 | tail -1
echo "== §11"; .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_rover_first_navigation.py tests/test_rover_first_navigation_timing.py 2>&1 | tail -1
