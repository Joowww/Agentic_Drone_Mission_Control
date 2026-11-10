#!/usr/bin/env bash
# Isolated check of the AFFECTED parts of bundle 2026.10.28-r2, under `env -i` with an empty HOME, from a copy outside
# the repository. Compose project tfg-entrega-r2-prueba, so no volume of another project is used.
#   isolated_check_r2.sh TEST_ROOT   (TEST_ROOT holds the bundle copy at ./bundle; logs go to ./logs)
set -u
T=$1
cd "$T/bundle" || exit 2
L=$T/logs
P=tfg-entrega-r2-prueba
mkdir -p "$L" "$T/results" "$T/planning_store"
export TFG_WORK_DIR=$T/results TFG_PLANNING_STORE=$T/planning_store TFG_UID=$(id -u) TFG_GID=$(id -g)
printf 'step\trc\tresult\tdetail\n' > "$L/summary.tsv"
rec() { printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >> "$L/summary.tsv"; echo "$1 rc=$2 $3 $4"; }
expect() {  # expect ID RC_WANTED TEXT LOGFILE RC
    local id=$1 want=$2 text=$3 log=$4 rc=$5
    if [ "$rc" = "$want" ] && grep -qF -- "$text" "$log"; then rec "$id" "$rc" PASS "$text"; else rec "$id" "$rc" FAIL "$text"; fi
}
dc() { docker compose -p "$P" -f compose.yaml "$@"; }

{ echo "pwd=$PWD"; env | sort; id; docker version --format 'client {{.Client.Version}} server {{.Server.Version}}'; docker compose version; } > "$L/00_environment.log" 2>&1
case "$PWD" in *Agentic_Drone_Mission_Control*) rec 00_outside_repo 1 FAIL "$PWD";; *) rec 00_outside_repo 0 PASS "$PWD";; esac

sha256sum -c SHA256SUMS > "$L/01_sha256sum.log" 2>&1; rc=$?
expect 01_sha256sum 0 "imagenes/tfg-app-2026.10.28.tar: OK" "$L/01_sha256sum.log" $rc

docker load -i imagenes/tfg-app-2026.10.28.tar > "$L/02_docker_load_app.log" 2>&1; rc=$?
python3 -I -c "
import json, subprocess, sys
bad = 0
for image in json.load(open('VERSIONES.json'))['images']:
    got = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image['tag']], capture_output=True, text=True).stdout.strip()
    bad += got != image['image_id']
    print('MATCH' if got == image['image_id'] else 'MISMATCH', image['tag'], got)
sys.exit(bad)" >> "$L/02_docker_load_app.log" 2>&1; rc2=$?
expect 02_load_app_and_ids 0 "MATCH tfg/app:2026.10.28" "$L/02_docker_load_app.log" $((rc + rc2))

dc --profile app --profile qgc --profile planning config > "$L/03_compose_config.yaml" 2> "$L/03_compose_config.stderr"; rc=$?
python3 -I -c "
import sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
bad = []
services = sorted(c['services'])
print('services', services, 'volumes', sorted(c.get('volumes', {})), 'networks', sorted(c.get('networks', {})))
if services != ['app', 'hermes', 'qgc']: bad.append(('services', services))
if sorted(c.get('volumes', {})) != ['hermes-home']: bad.append('volumes')
for name, svc in c['services'].items():
    if 'build' in svc: bad.append((name, 'build'))
    for v in svc.get('volumes', []):
        src = v.get('source', '')
        print(name, v['type'], src, '->', v['target'], 'ro' if v.get('read_only') else 'rw')
        if v['type'] == 'bind' and 'Agentic_Drone_Mission_Control' in src: bad.append((name, src))
print('SERVICES_OK' if not bad else 'BAD ' + repr(bad))
sys.exit(1 if bad else 0)" "$L/03_compose_config.yaml" > "$L/03_compose_services.log" 2>&1; rc2=$?
expect 03_compose_config_app_qgc_hermes_only 0 "SERVICES_OK" "$L/03_compose_services.log" $((rc + rc2))

{ grep -inc ollama compose.yaml LEEME.md "$L/03_compose_config.yaml"; grep -in 'ollama\|planner-menu' compose.yaml LEEME.md "$L/03_compose_config.yaml"; } > "$L/04_no_ollama.log" 2>&1
if grep -qi 'ollama\|planner-menu' compose.yaml LEEME.md "$L/03_compose_config.yaml"; then rec 04_no_ollama_usage 1 FAIL "see log"; else rec 04_no_ollama_usage 0 PASS "no ollama/planner-menu in compose, LEEME or resolved config"; fi

printf '6\n' | dc run --rm -T app > "$L/05_offline_menu.log" 2>&1; rc=$?
if [ "$rc" = 0 ] && [ "$(grep -c 'NOT AVAILABLE' "$L/05_offline_menu.log")" = 4 ] && grep -qF "5. Agricultural scenario" "$L/05_offline_menu.log" \
    && grep -qF "AI planning is the separate Hermes service" "$L/05_offline_menu.log" && ! grep -qi ollama "$L/05_offline_menu.log"; then
    rec 05_offline_menu 0 PASS "4 NOT AVAILABLE, option 5 present, Hermes named, no ollama"
else rec 05_offline_menu "$rc" FAIL "see log"; fi

dc run --rm -T app -m tools.agri_scenario_flow query --out /work/consulta_1 > "$L/06_query.log" 2>&1; rc=$?
expect 06_offline_scenario_query 0 "Escenario: AERIAL_COMPLETED_GROUND_PENDING" "$L/06_query.log" $rc

dc run --rm -T hermes /opt/tfg/deploy/planner/hermes_home.py check > "$L/07_hermes_check.log" 2>&1; rc=$?
expect 07_hermes_check_two_tools 0 "PLANNING_SAFE" "$L/07_hermes_check.log" $rc

dc run --rm -T hermes -c "
import yaml
c = yaml.safe_load(open('/hermes/planning/config.yaml'))
s = c['mcp_servers']['tfg-mission-control']
print('provider', c['model']['provider'], 'model', c['model']['default'])
print('server', s['command'], s['args'], 'tools', s['tools'])
print('tool_search', c['tools']['tool_search'])
print('other_servers', sorted(n for n in c['mcp_servers'] if n != 'tfg-mission-control'))
" > "$L/08_hermes_tool_filter.log" 2>&1; rc=$?
expect 08_hermes_filter_in_config 0 "'include': ['update_mission_draft', 'finalize_mission_draft']" "$L/08_hermes_tool_filter.log" $rc

dc --profile app --profile qgc --profile planning down > "$L/09_down.log" 2>&1
dc run --rm -T hermes /opt/tfg/deploy/planner/hermes_home.py status > "$L/10_status_after_down.log" 2>&1; rc=$?
ls "$T/results" >> "$L/10_status_after_down.log"
if [ "$rc" = 0 ] && grep -qF "PLANNING_SAFE" "$L/10_status_after_down.log" && grep -qF "auth.json): ABSENT" "$L/10_status_after_down.log" \
    && grep -qx consulta_1 "$L/10_status_after_down.log"; then
    rec 10_persistence_after_down 0 PASS "config kept in volume, no login, results kept"
else rec 10_persistence_after_down "$rc" FAIL "see log"; fi
dc --profile app --profile qgc --profile planning down > "$L/11_down_final.log" 2>&1
docker volume ls --filter "name=$P" > "$L/12_leftovers.log" 2>&1; docker ps -a --filter "name=$P" >> "$L/12_leftovers.log" 2>&1
echo; cat "$L/summary.tsv"
! grep -q FAIL "$L/summary.tsv"
