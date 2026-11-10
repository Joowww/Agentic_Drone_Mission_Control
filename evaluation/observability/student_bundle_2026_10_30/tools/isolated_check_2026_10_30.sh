#!/usr/bin/env bash
# Isolated check of the AFFECTED parts of bundle 2026.10.30 (Hermes finalizations -> package -> .plan), under
# `env -i` with an empty HOME, from a hard-linked copy outside the repository. Compose project tfg-entrega-2030-prueba.
#   isolated_check_2026_10_30.sh TEST_ROOT   (TEST_ROOT holds the bundle copy at ./bundle; logs go to ./logs)
set -u
T=$1
cd "$T/bundle" || exit 2
L=$T/logs
P=tfg-entrega-2030-prueba
STORE=$T/planning_store_SYNTHETIC
mkdir -p "$L" "$T/results" "$STORE"
export TFG_WORK_DIR=$T/results TFG_PLANNING_STORE=$STORE TFG_UID=$(id -u) TFG_GID=$(id -g)
printf 'step\trc\tresult\tdetail\n' > "$L/summary.tsv"
rec() { printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >> "$L/summary.tsv"; echo "$1 rc=$2 $3 $4"; }
expect() {  # expect ID RC_WANTED TEXT LOGFILE RC
    if [ "$5" = "$2" ] && grep -qF -- "$3" "$4"; then rec "$1" "$5" PASS "$3"; else rec "$1" "$5" FAIL "$3"; fi
}
dc() { docker compose -p "$P" -f compose.yaml "$@"; }

{ echo "pwd=$PWD"; env | sort; id; docker version --format 'client {{.Client.Version}} server {{.Server.Version}}'; } > "$L/00_environment.log" 2>&1
case "$PWD" in *Agentic_Drone_Mission_Control*) rec 00_outside_repo 1 FAIL "$PWD";; *) rec 00_outside_repo 0 PASS "$PWD";; esac

sha256sum -c SHA256SUMS > "$L/01_sha256sum.log" 2>&1; rc=$?
expect 01_sha256sum 0 "imagenes/tfg-app-2026.10.30.tar: OK" "$L/01_sha256sum.log" $rc

docker load -i imagenes/tfg-app-2026.10.30.tar > "$L/02_load.log" 2>&1; rc=$?
python3 -I -c "
import json, subprocess, sys
bad = 0
for image in json.load(open('VERSIONES.json'))['images']:
    got = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image['tag']], capture_output=True, text=True).stdout.strip()
    bad += got != image['image_id']
    print('MATCH' if got == image['image_id'] else 'MISMATCH', image['tag'], got)
sys.exit(bad)" >> "$L/02_load.log" 2>&1; rc2=$?
expect 02_load_and_ids 0 "MATCH tfg/app:2026.10.30" "$L/02_load.log" $((rc + rc2))

dc --profile app --profile qgc --profile planning config > "$L/03_config.yaml" 2> "$L/03_config.stderr"; rc=$?
python3 -I -c "
import sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
bad = []
app = c['services']['app']
mounts = {v['target']: v for v in app.get('volumes', [])}
print('services', sorted(c['services']), 'app network_mode', app.get('network_mode'))
for t, v in sorted(mounts.items()):
    print('app', v['type'], v.get('source'), '->', t, 'ro' if v.get('read_only') else 'rw')
if sorted(c['services']) != ['app', 'hermes', 'qgc']: bad.append('services')
if app.get('network_mode') != 'none': bad.append('app network')
if not mounts.get('/planning_store', {}).get('read_only'): bad.append('store not read-only')
if mounts.get('/work', {}).get('read_only'): bad.append('/work not writable')
for name, svc in c['services'].items():
    for v in svc.get('volumes', []):
        src = str(v.get('source', ''))
        if 'docker.sock' in src or 'Agentic_Drone_Mission_Control' in src: bad.append((name, src))
    if 'build' in svc: bad.append((name, 'build'))
print('CONFIG_OK' if not bad else 'BAD ' + repr(bad))
sys.exit(1 if bad else 0)" "$L/03_config.yaml" > "$L/03_config_checks.log" 2>&1; rc2=$?
grep -qi ollama "$L/03_config.yaml" compose.yaml LEEME.md && rc2=1 && echo "ollama referenced" >> "$L/03_config_checks.log"
expect 03_compose_config 0 "CONFIG_OK" "$L/03_config_checks.log" $((rc + rc2))

# SYNTHETIC test finalizations: the planner image's own MCP tools called directly (no Hermes, no model, no network).
printf 'SINTÉTICO: finalizaciones de PRUEBA creadas el %s llamando directamente a update_mission_draft y\nfinalize_mission_draft desde tfg/planner:2026.10.28, sin Hermes, sin modelo y sin red. No son planificación real.\n' \
    "$(date -u +%FT%TZ)" > "$STORE/SYNTHETIC_TEST_FINALIZATIONS.txt"
docker run --rm --network none --read-only --tmpfs /tmp --user "$TFG_UID:$TFG_GID" --cap-drop ALL \
    --security-opt no-new-privileges:true -v "$STORE:/opt/tfg/missions/generated" tfg/planner:2026.10.28 -c "
import json
from tools import hermes_mcp_server as s
common = {'vehicle_type': 'multirotor', 'autopilot': 'ArduPilot', 'cruise_speed_kmh': 35.0, 'battery_percent': 100.0,
          'battery_consumption_percent_per_minute': 0.8, 'objective_type': 'precision_agriculture', 'return_to_home': True,
          'wind_speed_kmh': 0.0, 'wind_direction_from_deg': 0.0, 'minimum_battery_reserve_percent': 20.0,
          'maximum_wind_speed_kmh': 30.0, 'maximum_altitude_m': 120.0, 'low_battery_action': 'RETURN_TO_HOME',
          'unsafe_wind_action': 'RETURN_TO_HOME', 'communication_loss_action': 'RETURN_TO_HOME'}
out = {}
for vehicle, sector, east in (('drone_01', 'a', -4.0), ('drone_02', 'b', 4.0)):
    data = {**common, 'mission_id': f'synthetic_test_sector_{sector}', 'name': f'SYNTHETIC test sector {sector.upper()}',
            'vehicle_id': vehicle, 'objective_target': f'synthetic_test_sector_{sector}',
            'geometry_intent': {'mode': 'offsets', 'home_latitude': 41.275, 'home_longitude': 1.987, 'home_altitude_m': 0.0,
                                'altitude_reference': 'relative_to_home', 'altitude_m': 5.0, 'return_to_home': True,
                                'close_route': False,
                                'offsets': [{'north_m': 8.0, 'east_m': east}, {'north_m': 16.0, 'east_m': east}]}}
    draft = s.update_mission_draft(s.MissionPlanDraft.model_validate(data))
    final = s.finalize_mission_draft(draft['draft_id'], draft.get('draft_revision'))
    out[vehicle] = {'draft_id': draft['draft_id'], 'finalization_id': final['finalization_id'], 'status': final['status'],
                    'qgc_export': (final['validation'].get('qgc_export') or {}).get('status')}
print(json.dumps(out))
" > "$L/04_synthetic_finalizations.log" 2>&1; rc=$?
expect 04_synthetic_finalizations 0 '"status": "VALIDATED"' "$L/04_synthetic_finalizations.log" $rc
IDS=$(tail -1 "$L/04_synthetic_finalizations.log")
A1=$(python3 -I -c "import json,sys; d=json.loads(sys.argv[1])['drone_01']; print(d['draft_id']+'/'+d['finalization_id'])" "$IDS")
A2=$(python3 -I -c "import json,sys; d=json.loads(sys.argv[1])['drone_02']; print(d['draft_id']+'/'+d['finalization_id'])" "$IDS")
(cd "$STORE" && find . -type f -print0 | sort -z | xargs -0 sha256sum) > "$L/04_store_before.sha256"

dc run --rm -T app -c "import os; print('STORE', sorted(os.listdir('/planning_store'))); print('DOCKER_SOCKET', os.path.exists('/var/run/docker.sock'))
try:
    open('/planning_store/write_probe', 'w')
    print('STORE_WRITABLE')
except OSError as exc:
    print('STORE_READ_ONLY', type(exc).__name__, exc.errno)" > "$L/05_store_mount.log" 2>&1; rc=$?
grep -q "DOCKER_SOCKET False" "$L/05_store_mount.log" && grep -q "'drafts'" "$L/05_store_mount.log" || rc=1
expect 05_store_read_only_no_socket 0 "STORE_READ_ONLY" "$L/05_store_mount.log" $rc

PKG=(-m tools.scenario_package package-finalized --store /planning_store --assign "drone_01=$A1@TAKEOFF_A"
     --assign "drone_02=$A2@TAKEOFF_B" --site missions/sites/synthetic_hermes_rehearsal_v1.site.json
     --fleet missions/fleets/agri_demo_fleet.json --target sitl)
dc run --rm -T app "${PKG[@]}" --out /work/paquete_hermes_1 > "$L/06_package.log" 2>&1; rc=$?
grep -q "HERMES_drone_02 drone_02: GENERATED" "$L/06_package.log" || rc=1
expect 06_package_two_plans 0 "HERMES_drone_01 drone_01: GENERATED" "$L/06_package.log" $rc
ls -l "$T/results/paquete_hermes_1/plans" >> "$L/06_package.log" 2>&1

dc run --rm -T app -m tools.scenario_package verify /work/paquete_hermes_1 > "$L/07_verify.log" 2>&1; rc=$?
expect 07_verify 0 '"status": "INTEGRITY_VERIFIED"' "$L/07_verify.log" $rc

cp -r "$STORE" "$T/planning_store_ALTERED"
sed -i '0,/"altitude_m": 5.0/s//"altitude_m": 6.0/' "$T/planning_store_ALTERED/drafts/${A1%%/*}/${A1##*/}/mission.json"
TFG_PLANNING_STORE=$T/planning_store_ALTERED dc run --rm -T app "${PKG[@]}" --out /work/paquete_alterado > "$L/08_altered.log" 2>&1; rc=$?
[ -e "$T/results/paquete_alterado" ] && rc=99
expect 08_altered_input_refused 2 "[REFUSED] ValueError: Mission sidecar/path/hash does not match its snapshot" "$L/08_altered.log" $rc

(cd "$STORE" && find . -type f -print0 | sort -z | xargs -0 sha256sum) > "$L/09_store_after.sha256"
cmp -s "$L/04_store_before.sha256" "$L/09_store_after.sha256"; rc=$?
echo "store unchanged by app runs: rc=$rc" > "$L/09_store_unchanged.log"
expect 09_store_unchanged 0 "rc=0" "$L/09_store_unchanged.log" $rc

dc --profile app --profile qgc --profile planning down > "$L/10_down.log" 2>&1
dc run --rm -T app -m tools.scenario_package verify /work/paquete_hermes_1 > "$L/10_verify_after_down.log" 2>&1; rc=$?
expect 10_results_persist_after_down 0 '"status": "INTEGRITY_VERIFIED"' "$L/10_verify_after_down.log" $rc
(env -u TFG_PLANNING_STORE docker compose -p "$P" -f compose.yaml run --rm -T app -c "import os; print('EMPTY_DEFAULT', sorted(os.listdir('/planning_store')))") > "$L/11_default_empty_store.log" 2>&1; rc=$?
expect 11_default_empty_store 0 "EMPTY_DEFAULT ['LEEME.txt']" "$L/11_default_empty_store.log" $rc
dc --profile app --profile qgc --profile planning down >> "$L/10_down.log" 2>&1
find "$T/results" -type f | LC_ALL=C sort | xargs -d '\n' sha256sum > "$L/12_result_files.sha256"
docker ps -a --filter "name=$P" > "$L/13_leftovers.log" 2>&1; docker volume ls --filter "name=$P" >> "$L/13_leftovers.log" 2>&1
echo; cat "$L/summary.tsv"
! grep -q FAIL "$L/summary.tsv"
