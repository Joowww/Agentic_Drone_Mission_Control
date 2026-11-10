#!/usr/bin/env bash
# Isolated check of the student bundle: run under `env -i` with an empty HOME, from a copy outside the repository.
#   isolated_check.sh TEST_ROOT   (TEST_ROOT holds the bundle copy at ./bundle; logs go to ./logs)
set -u
T=$1
cd "$T/bundle" || exit 2
L=$T/logs
mkdir -p "$L" "$T/results" "$T/planning_store"
export TFG_WORK_DIR=$T/results TFG_PLANNING_STORE=$T/planning_store TFG_UID=$(id -u) TFG_GID=$(id -g)
printf 'step\trc\tresult\tdetail\n' > "$L/summary.tsv"
rec() { printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >> "$L/summary.tsv"; echo "$1 rc=$2 $3 $4"; }
expect() {  # expect ID RC_WANTED TEXT LOGFILE RC
    local id=$1 want=$2 text=$3 log=$4 rc=$5
    if [ "$rc" = "$want" ] && grep -qF -- "$text" "$log"; then rec "$id" "$rc" PASS "$text"; else rec "$id" "$rc" FAIL "$text"; fi
}

{ echo "pwd=$PWD"; echo "HOME=$HOME"; env | sort; id; docker version --format 'client {{.Client.Version}} server {{.Server.Version}}'; docker compose version; } > "$L/00_environment.log" 2>&1
case "$PWD" in *Agentic_Drone_Mission_Control*) rec 00_outside_repo 1 FAIL "$PWD";; *) rec 00_outside_repo 0 PASS "$PWD";; esac

sha256sum -c SHA256SUMS > "$L/01_sha256sum.log" 2>&1; rc=$?
expect 01_sha256sum 0 "imagenes/tfg-planner-2026.10.28.tar: OK" "$L/01_sha256sum.log" $rc

for archive in imagenes/*.tar; do
    docker load -i "$archive" >> "$L/02_docker_load.log" 2>&1 || echo "LOAD_FAILED $archive" >> "$L/02_docker_load.log"
done
python3 -I -c "
import json, subprocess, sys
doc = json.load(open('VERSIONES.json'))
bad = 0
for image in doc['images']:
    got = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image['tag']], capture_output=True, text=True).stdout.strip()
    ok = got == image['image_id']
    bad += not ok
    print(('MATCH' if ok else 'MISMATCH'), image['tag'], got, 'expected', image['image_id'])
sys.exit(bad)" > "$L/03_image_ids.log" 2>&1; rc=$?
grep -q LOAD_FAILED "$L/02_docker_load.log" && rec 02_docker_load 1 FAIL "see log" || rec 02_docker_load 0 PASS "3 archives loaded"
expect 03_image_ids 0 "MATCH tfg/planner:2026.10.28" "$L/03_image_ids.log" $rc

docker compose -f compose.yaml --profile app --profile qgc --profile planning config > "$L/04_compose_config.yaml" 2> "$L/04_compose_config.stderr"; rc=$?
python3 -I -c "
import sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
bad = []
print('project', c.get('name'), 'services', sorted(c['services']))
for name, svc in sorted(c['services'].items()):
    for v in svc.get('volumes', []):
        src = v.get('source', '')
        print(name, v['type'], src, '->', v['target'], 'ro' if v.get('read_only') else 'rw')
        if v['type'] == 'bind' and ('Agentic_Drone_Mission_Control' in src or src.startswith('/home/')):
            bad.append((name, src))
    if 'build' in svc: bad.append((name, 'build section'))
print('volumes', sorted(c.get('volumes', {})), [v.get('name') for v in c.get('volumes', {}).values()])
print('PATHS_OK' if not bad else 'BAD ' + repr(bad))
sys.exit(1 if bad else 0)" "$L/04_compose_config.yaml" > "$L/04_compose_paths.log" 2>&1; rc2=$?
expect 04_compose_config 0 "PATHS_OK" "$L/04_compose_paths.log" $((rc + rc2))

docker compose -f compose.yaml run --rm -T app -m tools.agri_scenario_flow query --out /work/consulta_1 > "$L/05_query.log" 2>&1; rc=$?
expect 05_offline_query 0 "Escenario: AERIAL_COMPLETED_GROUND_PENDING" "$L/05_query.log" $rc

cp -r ejemplos/missions "$TFG_WORK_DIR/entradas"
docker compose -f compose.yaml run --rm -T app -m tools.scenario_package package \
    --template /work/entradas/templates/agri_poi_visit_v1.json --site /work/entradas/sites/synthetic_orchard_v1.site.json \
    --fleet /work/entradas/fleets/agri_demo_fleet.json --target sitl --out /work/paquete_1 > "$L/06_package.log" 2>&1; rc=$?
expect 06_package_from_extracted_inputs 0 "A2 drone_02: GENERATED" "$L/06_package.log" $rc

docker compose -f compose.yaml run --rm -T app -m tools.scenario_package verify /work/paquete_1 > "$L/07_verify.log" 2>&1; rc=$?
expect 07_package_verify 0 '"status": "INTEGRITY_VERIFIED"' "$L/07_verify.log" $rc

mkdir -p "$TFG_WORK_DIR/qgc_guardado"
QGC_PLAN_DIR=$TFG_WORK_DIR/paquete_1/plans QGC_SAVE_DIR=$TFG_WORK_DIR/qgc_guardado \
    docker compose -f compose.yaml --profile qgc config qgc > "$L/08_qgc_config.yaml" 2>&1; rc=$?
{ ls -l "$TFG_WORK_DIR/paquete_1/plans"; grep -A3 'target: /data/plan' "$L/08_qgc_config.yaml"; grep -B3 'target: /data/plan$' "$L/08_qgc_config.yaml"; } > "$L/08_qgc_mount.log" 2>&1
grep -qF "source: $TFG_WORK_DIR/paquete_1/plans" "$L/08_qgc_config.yaml" && [ -r "$TFG_WORK_DIR/paquete_1/plans/drone_01.plan" ] && rc2=0 || rc2=1
expect 08_qgc_would_mount_package 0 "/data/plan" "$L/08_qgc_config.yaml" $((rc + rc2))

docker compose -f compose.yaml run --rm -T planner-menu /opt/tfg/deploy/planner/hermes_home.py status > "$L/09_planner_status_fresh.log" 2>&1; rc=$?
expect 09_planner_fresh_volume_no_login 1 "Credenciales del proveedor (auth.json): ABSENT" "$L/09_planner_status_fresh.log" $rc

docker compose -f compose.yaml run --rm -T planner-menu -c "
import json
from tools import hermes_mcp_server as s
H1 = {'mission_id': 'agri_demo_001_h1_sector_a', 'name': 'agri_demo_001 H1 sector A', 'vehicle_id': 'drone_01',
      'vehicle_type': 'multirotor', 'autopilot': 'ArduPilot', 'cruise_speed_kmh': 35.0, 'battery_percent': 100.0,
      'battery_consumption_percent_per_minute': 0.8, 'objective_type': 'precision_agriculture',
      'objective_target': 'agri_demo_001_sector_a', 'return_to_home': True, 'wind_speed_kmh': 0.0,
      'wind_direction_from_deg': 0.0, 'minimum_battery_reserve_percent': 20.0, 'maximum_wind_speed_kmh': 30.0,
      'maximum_altitude_m': 120.0, 'low_battery_action': 'RETURN_TO_HOME', 'unsafe_wind_action': 'RETURN_TO_HOME',
      'communication_loss_action': 'RETURN_TO_HOME',
      'geometry_intent': {'mode': 'offsets', 'home_latitude': 41.275, 'home_longitude': 1.987, 'home_altitude_m': 0.0,
                          'altitude_reference': 'relative_to_home', 'altitude_m': 5.0, 'return_to_home': True,
                          'close_route': False,
                          'offsets': [{'north_m': 8.0, 'east_m': -4.0}, {'north_m': 16.0, 'east_m': -4.0}]}}
draft = s.update_mission_draft(s.MissionPlanDraft.model_validate(H1))
print('update', draft.get('status'), draft.get('draft_id'), draft.get('draft_revision'))
final = s.finalize_mission_draft(draft['draft_id'], draft.get('draft_revision'))
v = final.get('validation') or {}
print('finalize', final.get('status'), final.get('finalization_id'), v.get('mission_status'), v.get('execution_status'),
      (v.get('qgc_export') or {}).get('status'))
" > "$L/10_planning_store_write.log" 2>&1; rc=$?
expect 10_planning_store_write_direct_tools 0 "finalize" "$L/10_planning_store_write.log" $rc

docker compose -f compose.yaml run --rm -T planner-menu /opt/tfg/deploy/planner/hermes_home.py status > "$L/11_planner_status_reread.log" 2>&1; rc=$?
expect 11_store_reread_new_container 1 "finalización" "$L/11_planner_status_reread.log" $rc

find "$T/results" "$T/planning_store" -type f | LC_ALL=C sort | xargs -d '\n' sha256sum > "$L/12_result_files.sha256"
docker compose -f compose.yaml --profile app --profile qgc --profile planning ps -a > "$L/13_ps_after.log" 2>&1
docker compose -f compose.yaml --profile app --profile qgc --profile planning down > "$L/14_down.log" 2>&1; rc=$?
ls "$T/results" > "$L/15_results_after_down.log" 2>&1
expect 14_down_keeps_results 0 "paquete_1" "$L/15_results_after_down.log" $rc
echo; cat "$L/summary.tsv"
! grep -q FAIL "$L/summary.tsv"
