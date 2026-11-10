#!/usr/bin/env bash
# Checks of the planning profile with TEST DOUBLES (deploy/planner/doubles/fake_provider.py): no real model, no
# inference, no simulator or vehicle. Every container runs on the internal `test` network (no egress).
# Each check prints PASS/FAIL; results stay in NEW_WORK_DIR (nothing is deleted or overwritten).
#
#   deploy/planner/planning_checks.sh NEW_WORK_DIR [COMPOSE_FILE]
set -uo pipefail

WORK=${1:?usage: planning_checks.sh NEW_WORK_DIR [COMPOSE_FILE]}
COMPOSE=${2:-"$(cd "$(dirname "$0")/.." && pwd)/compose.yaml"}
if [ -e "$WORK" ]; then
    echo "$WORK exists: use a new directory (nothing is overwritten)" >&2
    exit 2
fi
mkdir -p "$WORK/store" "$WORK/ro_store" && WORK=$(cd "$WORK" && pwd)
chmod 0555 "$WORK/ro_store"
export TFG_WORK_DIR="$WORK" TFG_PLANNING_STORE="$WORK/store" TFG_UID="${TFG_UID:-$(id -u)}" TFG_GID="${TFG_GID:-$(id -g)}"
C=(docker compose --progress quiet -f "$COMPOSE" --profile planning-test)
LAUNCH=/opt/tfg/deploy/planner/hermes_home.py
HERMES=/opt/hermes/agent/.venv/bin/hermes
printf 'check\tresult\tdetail\n' > "$WORK/checks.tsv"
FAILED=0
trap 'echo; echo "Interrupted: results so far are kept in $WORK"; "${C[@]}" stop fake-provider >/dev/null 2>&1; exit 130' INT

result() {  # ID PASS|FAIL DETAIL
    [ "$2" = PASS ] || FAILED=$((FAILED + 1))
    echo "   $2 · $3"
    printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$WORK/checks.tsv"
}
run() {  # LOG ARGS... (one throwaway hermes-test container)
    local log=$1
    shift
    "${C[@]}" run --rm -T "$@" > "$WORK/$log" 2>&1
}
provider() {  # SCENARIO [DELAY]: (re)start the fake provider
    "${C[@]}" rm -sf fake-provider >/dev/null 2>&1
    FAKE_SCENARIO=$1 FAKE_DELAY_S=${2:-60} "${C[@]}" up -d fake-provider >/dev/null 2>&1
    sleep 2
}
finalizations() { find "$WORK/store" -name finalization.json 2>/dev/null | wc -l; }
drafts() { find "$WORK/store" -name draft.json 2>/dev/null | wc -l; }
chat_requests() { grep -c "/chat/completions" "$WORK/fake_provider_requests.jsonl" 2>/dev/null || echo 0; }
PLAN_PROMPT="Prepara la misión agri_demo_001 H1 sector A con los datos del operador (TEST DOUBLE)."

echo "== [1] Hermes y servidor MCP presentes en la imagen (sin red, sin inferencia)"
# The TEST DOUBLE home is prepared before any Hermes call (Hermes initializes the home it is given).
run 03_test_home.log hermes-test "$LAUNCH" prepare-test-home /work/hermes_test_home http://fake-provider:8000/v1
run 01_hermes_version.log -e HERMES_HOME=/tmp/hermes-version --entrypoint "$HERMES" hermes-test --version
grep -qiE "hermes" "$WORK/01_hermes_version.log" && ! grep -qi "error" "$WORK/01_hermes_version.log" && result 01_hermes_version PASS "$(head -1 "$WORK/01_hermes_version.log")" \
    || result 01_hermes_version FAIL "see 01_hermes_version.log"
run 02_mcp_tools.log hermes-test -c "
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
    params = StdioServerParameters(command='/opt/tfg/.venv/bin/python', args=['-m', 'tools.hermes_mcp_server'], cwd='/opt/tfg')
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = sorted(t.name for t in (await s.list_tools()).tools)
            print('SERVER_TOOLS', len(names), ' '.join(names))
asyncio.run(main())"
grep -q "SERVER_TOOLS" "$WORK/02_mcp_tools.log" && result 02_mcp_server_starts PASS \
    "$(grep -o 'SERVER_TOOLS [0-9]*' "$WORK/02_mcp_tools.log") (the server publishes all; Hermes must offer 2)" \
    || result 02_mcp_server_starts FAIL "see 02_mcp_tools.log"

echo "== [2] Restricción de herramientas (configuración comprobada antes de arrancar Hermes)"
grep -q "^TEST DOUBLE home" "$WORK/03_test_home.log" && result 03_test_double_home PASS "provider custom at the fake provider" \
    || result 03_test_double_home FAIL "see 03_test_home.log"
run 04_check.log hermes-test "$LAUNCH" check
grep -q "^PLANNING_SAFE" "$WORK/04_check.log" && result 04_planning_safe PASS "test home planning-safe" \
    || result 04_planning_safe FAIL "see 04_check.log"
mkdir -p "$WORK/tampered_home" && cp "$WORK/hermes_test_home/config.yaml" "$WORK/tampered_home/config.yaml"
sed -i 's/^        - finalize_mission_draft$/        - finalize_mission_draft\n        - start_simulation/' "$WORK/tampered_home/config.yaml"
run 05_tampered.log -e HERMES_HOME=/work/tampered_home hermes-test "$LAUNCH" run -z "x"
rc=$?
grep -q "not planning-safe" "$WORK/05_tampered.log" && [ $rc -ne 0 ] && result 05_tampered_config_refused PASS "rc=$rc" \
    || result 05_tampered_config_refused FAIL "rc=$rc; see 05_tampered.log"
run 06_toolsets_override.log hermes-test "$LAUNCH" run -z "x" --toolsets terminal
rc=$?
grep -q "fixes --toolsets" "$WORK/06_toolsets_override.log" && [ $rc -eq 2 ] && result 06_toolsets_override_refused PASS "rc=$rc" \
    || result 06_toolsets_override_refused FAIL "rc=$rc"

echo "== [3] Doble: planificación completa (update → finalize) con el servidor MCP real"
provider planning
run 07_planning.log hermes-test "$LAUNCH" run -z "$PLAN_PROMPT"
rc=$?
cp "$WORK/fake_provider_requests.jsonl" "$WORK/07_provider_requests.jsonl" 2>/dev/null
offered=$(python3 -c "
import json,sys
sets={tuple(sorted(json.loads(l)['offered_tools'])) for l in open('$WORK/07_provider_requests.jsonl') if json.loads(l)['path'].endswith('/chat/completions')}
sets.discard(())  # auxiliary Hermes calls offer no tool at all
print(';'.join(','.join(s) for s in sets))" 2>/dev/null)
[ "$offered" = "mcp__tfg_mission_control__finalize_mission_draft,mcp__tfg_mission_control__update_mission_draft" ] \
    && result 07_only_planning_tools_offered PASS "every request offering tools offered exactly the 2 planning tools (auxiliary calls: none)" \
    || result 07_only_planning_tools_offered FAIL "offered: ${offered:-none}"
[ "$(drafts)" -eq 1 ] && [ "$(finalizations)" -eq 1 ] && result 08_persisted PASS "1 draft, 1 finalization.json (rc=$rc)" \
    || result 08_persisted FAIL "drafts=$(drafts) finalizations=$(finalizations) rc=$rc"
python3 -c "
import json, pathlib, sys
records = [json.loads(p.read_text()) for p in pathlib.Path('$WORK/store').rglob('finalization.json')]
exports = [(r.get('validation') or {}).get('qgc_export') or {} for r in records]
sys.exit(0 if exports and all(e.get('status') == 'REFUSED' and e.get('reasons') for e in exports) else 1)" \
    && result 09_strict_export_refused PASS "qgc_export REFUSED (no AMSL in the draft): no .plan invented" \
    || result 09_strict_export_refused FAIL "no REFUSED qgc_export found"
run 10_status.log hermes-test "$LAUNCH" status
grep -q "completa · validación FEASIBLE/APPROVED · exportación .plan REFUSED" "$WORK/10_status.log" && result 10_status_after_container_removed PASS \
    "a new container reads the persisted result" || result 10_status_after_container_removed FAIL "see 10_status.log"

echo "== [4] Doble: respuesta inválida, timeout con cancelación y proveedor ausente (nada nuevo se da por terminado)"
before=$(finalizations)
provider invalid
sent=$(chat_requests)
run 11_invalid.log hermes-test "$LAUNCH" run -z "$PLAN_PROMPT"
rc=$?
[ "$(chat_requests)" -gt "$sent" ] && [ "$(finalizations)" -eq "$before" ] && result 11_invalid_response PASS "rc=$rc; no new finalization" \
    || result 11_invalid_response FAIL "rc=$rc"
provider timeout 600
sent=$(chat_requests)
"${C[@]}" run --rm -T --name tfg-planning-cancel hermes-test "$LAUNCH" run -z "$PLAN_PROMPT" > "$WORK/12_timeout_cancel.log" 2>&1 &
pid=$!
sleep 20
docker kill -s INT tfg-planning-cancel >/dev/null 2>&1
sleep 5
docker kill tfg-planning-cancel >/dev/null 2>&1
wait $pid
rc=$?
[ "$(chat_requests)" -gt "$sent" ] && [ "$(finalizations)" -eq "$before" ] && result 12_timeout_cancel PASS "provider silent; Ctrl+C after 20 s; rc=$rc; no new finalization" \
    || result 12_timeout_cancel FAIL "rc=$rc"
"${C[@]}" rm -sf fake-provider >/dev/null 2>&1
run 13_absent.log hermes-test "$LAUNCH" run -z "$PLAN_PROMPT"
rc=$?
! grep -q "not logged" "$WORK/13_absent.log" && [ "$(finalizations)" -eq "$before" ] && result 13_provider_absent PASS "rc=$rc; no new finalization" \
    || result 13_provider_absent FAIL "rc=$rc"

echo "== [5] Doble: error de escritura del almacén (solo lectura)"
provider planning
TFG_PLANNING_STORE="$WORK/ro_store" run 14_write_error.log hermes-test "$LAUNCH" run -z "$PLAN_PROMPT"
rc=$?
[ -z "$(ls -A "$WORK/ro_store")" ] && grep -q "returned no draft_id" "$WORK/14_write_error.log" \
    && result 14_write_error PASS "rc=$rc; nothing written; the tool error reached the provider; nothing claimed" \
    || result 14_write_error FAIL "rc=$rc"

echo "== [6] Recorrido Ollama del menú (opciones 1/3) contra el doble"
run 15_ollama_extract.log hermes-test -c "
from agents.mission_planner import extract_mission_plan_draft
d = extract_mission_plan_draft('Misión agri_demo_001 H1 sector A (TEST DOUBLE)')
print('EXTRACTED', d.mission_id, d.vehicle_id, d.cruise_speed_kmh)"
grep -q "EXTRACTED agri_demo_001_h1_sector_a drone_01 35.0" "$WORK/15_ollama_extract.log" \
    && result 15_ollama_double_extraction PASS "ChatOllama via OLLAMA_HOST -> MissionPlanDraft" \
    || result 15_ollama_double_extraction FAIL "see 15_ollama_extract.log"
provider invalid
run 16_ollama_invalid.log hermes-test -c "
from agents.mission_planner import extract_mission_plan_draft
try:
    extract_mission_plan_draft('x')
    print('UNEXPECTED_SUCCESS')
except Exception as exc:
    print('REJECTED', type(exc).__name__)"
grep -q "^REJECTED" "$WORK/16_ollama_invalid.log" && result 16_ollama_invalid_rejected PASS "$(grep -o 'REJECTED.*' "$WORK/16_ollama_invalid.log")" \
    || result 16_ollama_invalid_rejected FAIL "see 16_ollama_invalid.log"
"${C[@]}" rm -sf fake-provider >/dev/null 2>&1
printf '3\nMisión de prueba\nexit\n' | "${C[@]}" run --rm -T hermes-test main.py > "$WORK/17_menu_ollama_absent.log" 2>&1
grep -q "PLANNER ERROR" "$WORK/17_menu_ollama_absent.log" && result 17_menu_provider_absent PASS "menu option 3 reports [PLANNER ERROR] and continues" \
    || result 17_menu_provider_absent FAIL "see 17_menu_ollama_absent.log"

echo "== [8] Ejecutor de capturas con el doble: home pedido, recorrido completo y login (sin cuenta real)"
# Base (unfiltered) trial home pointed at the TEST DOUBLE; the runner adds and removes the tools filter itself.
run 20_trial_double_prepare.log hermes-test "$LAUNCH" prepare-trial /work/trial_double
sed -i 's#^  provider: nous$#  provider: custom\n  base_url: http://fake-provider:8000/v1#; s#^  default: poolside/laguna-s-2.1:free$#  default: tfg-test-double#' \
    "$WORK/trial_double/config.yaml"
mkdir -p "$WORK/store_runner" "$WORK/runner_private"
provider planning
lines_before=$(wc -l < "$WORK/fake_provider_requests.jsonl" 2>/dev/null || echo 0)
# HERMES_HOME of the container is set to a DIFFERENT, empty and read-only home (/hermes/planning of the image):
# only --hermes-home names the trial home. A child that inherited the container value could not succeed.
TFG_PLANNING_STORE="$WORK/store_runner" run 20_runner_execute.log -e HERMES_HOME=/hermes/planning hermes-test \
    -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case agri-planning-container \
    --hermes-home /work/trial_double --hermes-bin "$HERMES" --private-root /work/runner_private --timeout 300 \
    --run-id double-runner-check --execute
python3 - "$WORK" "$lines_before" > "$WORK/20_21_analysis.txt" <<'PY'
import json, pathlib, sys
work, before = pathlib.Path(sys.argv[1]), int(sys.argv[2])
run = json.loads(next(work.glob("runner_private/*/run.json")).read_text())
records = [json.loads(l) for l in (work / "fake_provider_requests.jsonl").read_text().splitlines()[before:]]
chat = [r for r in records if r["path"].endswith("/chat/completions")]
offered = {tuple(sorted(r["offered_tools"])) for r in chat} - {()}
print("RC", run.get("return_code"), "TIMED_OUT", run.get("timed_out"), "RESTORE_OK", run["restore"]["ok"])
print("CHAT_REQUESTS", len(chat), "TRIAL_HOME_STATE", (work / "trial_double" / "sessions").is_dir())
print("OFFERED", ";".join(",".join(s) for s in sorted(offered)))
PY
grep -q "^RC 0 TIMED_OUT False RESTORE_OK True" "$WORK/20_21_analysis.txt" && grep -qE "CHAT_REQUESTS [1-9][0-9]* TRIAL_HOME_STATE True" "$WORK/20_21_analysis.txt" \
    && result 20_child_uses_requested_home PASS "container HERMES_HOME=/hermes/planning; Hermes ran in /work/trial_double and reached the double" \
    || result 20_child_uses_requested_home FAIL "see 20_21_analysis.txt and 20_runner_execute.log"
grep -qx "OFFERED mcp__tfg_mission_control__finalize_mission_draft,mcp__tfg_mission_control__update_mission_draft" "$WORK/20_21_analysis.txt" \
    && result 21_runner_only_planning_tools PASS "runner turn offered exactly the 2 planning tools" \
    || result 21_runner_only_planning_tools FAIL "see 20_21_analysis.txt"
TFG_PLANNING_STORE="$WORK/store_runner" run 22_runner_status.log hermes-test "$LAUNCH" status
grep -q "completa · validación FEASIBLE/APPROVED · exportación .plan REFUSED" "$WORK/22_runner_status.log" \
    && [ -z "$(find "$WORK/store_runner" -name '*.plan')" ] \
    && result 22_runner_persisted_refused PASS "another container reads the finalization; qgc_export REFUSED, no .plan" \
    || result 22_runner_persisted_refused FAIL "see 22_runner_status.log"
run 23_runner_review.log hermes-test -m observability.hermes_capture_run review --mcp-tool-trial \
    --trial-case agri-planning-container --private-dir "/work/runner_private/$(ls "$WORK/runner_private" | head -1)" \
    --evidence-dir /work/runner_review
grep -q '"mcp_tool_trial_verdict": "PLANNING_CALLS_WITHIN_ALLOWED_TOOLS"' "$WORK/23_runner_review.log" \
    && result 23_runner_review PASS "PLANNING_CALLS_WITHIN_ALLOWED_TOOLS" || result 23_runner_review FAIL "see 23_runner_review.log"
run 24_login_prepare.log hermes-test "$LAUNCH" prepare-trial /work/trial_login
timeout 120 "${C[@]}" run --rm -T -e HERMES_HOME=/work/trial_login -e HERMES_PORTAL_BASE_URL=http://fake-provider:8000 \
    hermes-test "$LAUNCH" login > "$WORK/24_login_double.log" 2>&1
rc=$?
grep -q "Portal: http://fake-provider:8000" "$WORK/24_login_double.log" && ! grep -q "refused" "$WORK/24_login_double.log" \
    && [ ! -e "$WORK/trial_login/auth.json" ] \
    && result 24_login_trial_home_double PASS "login starts the Nous flow for the unfiltered trial home against the double (rc=$rc; no credential saved)" \
    || result 24_login_trial_home_double FAIL "rc=$rc; see 24_login_double.log"
"${C[@]}" rm -sf fake-provider >/dev/null 2>&1

echo "== [7] Secretos"
hits=$(grep -rIlE "Bearer [A-Za-z0-9._-]{16,}|sk-[A-Za-z0-9]{20,}|(api[_-]?key|token)\"?[:=] *\"?[A-Za-z0-9]{16,}" "$WORK" 2>/dev/null | wc -l)
[ "$hits" -eq 0 ] && result 18_no_secrets_in_logs PASS "no credential patterns in $WORK" || result 18_no_secrets_in_logs FAIL "$hits file(s)"
run 19_image_secrets.log --entrypoint sh hermes-test -c 'find /hermes /opt/tfg /tmp /root -xdev \( -name auth.json -o -name ".env" -o -name "id_rsa*" -o -name ".netrc" \) 2>/dev/null; ls -A /hermes/planning'
[ ! -s "$WORK/19_image_secrets.log" ] && result 19_no_credentials_in_image PASS "no auth.json/.env/keys; empty planning home in the image" \
    || result 19_no_credentials_in_image FAIL "see 19_image_secrets.log"

echo
echo "Resumen: $WORK/checks.tsv · fallos: $FAILED (TEST DOUBLES: nada de esto es una inferencia real)"
[ "$FAILED" -eq 0 ]
