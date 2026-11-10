#!/usr/bin/env bash
# Offline walkthrough of the application image (service `app` of deploy/compose.yaml).
#
# Each step runs the EXISTING command in its own throwaway container: no network, read-only image, the only
# writable place is /work (= WORK_DIR). It prints what it is doing, the origin of the data (REAL_HISTORICAL
# conserved copies or SYNTHETIC), where the results stay and whether the expected outcome was observed.
# Nothing is deleted or overwritten: WORK_DIR must not exist. Ctrl+C stops the step in progress; the results
# already written stay in WORK_DIR.
#
#   deploy/app/student_walkthrough.sh NEW_WORK_DIR [COMPOSE_FILE]
set -uo pipefail

WORK=${1:?usage: student_walkthrough.sh NEW_WORK_DIR [COMPOSE_FILE]}
COMPOSE=${2:-"$(cd "$(dirname "$0")/.." && pwd)/compose.yaml"}
if [ -e "$WORK" ]; then
    echo "$WORK exists: use a new directory (nothing is overwritten)" >&2
    exit 2
fi
mkdir -p "$WORK/i_reports" && WORK=$(cd "$WORK" && pwd)
export TFG_WORK_DIR="$WORK" TFG_UID="${TFG_UID:-$(id -u)}" TFG_GID="${TFG_GID:-$(id -g)}"
trap 'echo; echo "Interrupted: results so far are kept in $WORK"; exit 130' INT
printf 'step\texpected_rc\trc\texpected_text\tresult\n' > "$WORK/walkthrough.tsv"
FAILED=0

# step ID ORIGIN TITLE EXPECTED_RC EXPECTED_TEXT -- ARGS (passed to python3 inside the container)
step() {
    local id=$1 origin=$2 title=$3 want_rc=$4 want_text=$5
    shift 6
    echo
    echo "== [$id] $title"
    echo "   origen: $origin · resultados: $WORK/$id.log (y /work/... dentro del contenedor)"
    docker compose -f "$COMPOSE" run --rm -T app "$@" > "$WORK/$id.log" 2>&1
    local rc=$? result=PASS
    if [ "$rc" != "$want_rc" ] || ! grep -qF -- "$want_text" "$WORK/$id.log"; then
        result=FAIL
        FAILED=$((FAILED + 1))
    fi
    grep -E 'Motivo|motivo|BLOCKED|INCOMPLETE|missing|REFUSED|Error|error' "$WORK/$id.log" | head -3 | sed 's/^/   · /'
    echo "   rc=$rc (esperado $want_rc) · texto esperado: \"$want_text\" · $result"
    printf '%s\t%s\t%s\t%s\t%s\n' "$id" "$want_rc" "$rc" "$want_text" "$result" >> "$WORK/walkthrough.tsv"
}

SITE=missions/sites
FLEET=missions/fleets/agri_demo_fleet.json
TEMPLATE=missions/templates/agri_poi_visit_v1.json
QGC=evaluation/observability/qgc_first_import_2026_10_27

step a_query REAL_HISTORICAL "Consulta del escenario H2 (copias conservadas): aéreo completado, R1 pendiente" \
    0 "Escenario: AERIAL_COMPLETED_GROUND_PENDING" -- -m tools.agri_scenario_flow query --out /work/a_query
step b_demo SYNTHETIC "Demo sintética nominal (TEST_DOUBLE; nunca una ejecución física)" \
    0 "Escenario: SYNTHETIC_COMPLETE" -- -m tools.agri_scenario_flow demo --variant complete --out /work/b_demo
step c1_demo_lost SYNTHETIC "Demo con respuesta de admisión perdida (incertidumbre)" \
    0 "admission reply lost" -- -m tools.agri_scenario_flow demo --variant lost_admission_response --out /work/c_demo
step c2_resume SYNTHETIC "Reanudación sobre el mismo almacenamiento (recuperación)" \
    0 "Coordinador R1: VERIFIED_SYNTHETIC" -- -m tools.agri_scenario_flow demo --variant lost_admission_response \
    --out /work/c_demo --resume
step c3_single_admission SYNTHETIC "Comprobación: una sola admisión tras la recuperación" \
    0 "admit_calls=1 jobs=1" -- -c "import json; d = json.load(open('/work/c_demo/executor_test_double.json')); \
print(f\"admit_calls={d['admit_calls']} jobs={len(d['jobs'])}\"); assert d['admit_calls'] == 1 and len(d['jobs']) == 1"
step d_validate_site SYNTHETIC "Validación del emplazamiento sintético" \
    0 '"status": "VALID"' -- -m tools.scenario_package validate-site $SITE/synthetic_orchard_v1.site.json
step e1_dronelab_site TEMPLATE "Plantilla DroneLab: validación (datos sin medir)" \
    1 '"status": "INCOMPLETE"' -- -m tools.scenario_package validate-site $SITE/dronelab.template.site.json
step e2_dronelab_package TEMPLATE "Plantilla DroneLab: exportación rechazada por datos ausentes" \
    0 "BLOCKED_MISSING_DATA" -- -m tools.scenario_package package --template $TEMPLATE \
    --site $SITE/dronelab.template.site.json --fleet $FLEET --target field --out /work/e_dronelab
step f_package SYNTHETIC "Exportación de un paquete SITL para dos drones" \
    0 "A2 drone_02: GENERATED" -- -m tools.scenario_package package --template $TEMPLATE \
    --site $SITE/synthetic_orchard_v1.site.json --fleet $FLEET --target sitl --out /work/f_package
step g_verify SYNTHETIC "Verificación del paquete exportado" \
    0 '"status": "INTEGRITY_VERIFIED"' -- -m tools.scenario_package verify /work/f_package
step h_compare REAL_HISTORICAL "Comparación de los archivos conservados de la primera importación en QGC" \
    0 "NO_SEMANTIC_DIFFERENCES" -- -m tools.qgc_plan_compare $QGC/comparison/original.plan \
    $QGC/qgc_saved/drone_01.qgc_resaved.plan --out /work/h_compare
step i1_scenario_report REAL_HISTORICAL "Informe determinista del escenario (vista H2 conservada)" \
    0 "# Informe determinista del escenario agri_demo_001" -- -m reporting.agri_scenario_summary report \
    --view-file evaluation/observability/agri_scenario_view_h2_2026_10_24/scenario_view.json
step i2_comparison REAL_HISTORICAL "Comparación experimental (evidencia conservada, sin inferencias)" \
    0 "" -- -m reporting.agri_experiment_comparison comparison --out /work/i_reports/comparison.md \
    --json /work/i_reports/comparison.json
step i3_review_sheet REAL_HISTORICAL "Hoja de revisión humana (PENDIENTE)" \
    0 "" -- -m reporting.agri_experiment_comparison review-sheet --out /work/i_reports/review_sheet.md
step n_no_network CHECK "Comprobación: el contenedor no tiene red (ni proveedor LLM alcanzable)" \
    0 "NO_NETWORK" -- -c "import socket
try:
    socket.create_connection(('pypi.org', 443), 3)
    print('NETWORK_REACHABLE')
except OSError as exc:
    print('NO_NETWORK', type(exc).__name__)"

echo
echo "Resumen: $WORK/walkthrough.tsv · fallos: $FAILED"
echo "Resultados en $WORK (propiedad de uid $TFG_UID). Para salir de un paso en curso: Ctrl+C."
[ "$FAILED" -eq 0 ]
