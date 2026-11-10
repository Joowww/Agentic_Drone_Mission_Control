"""One-command OFFLINE demo of the TFG over the project's real code; no Gazebo, Docker, ROS 2 or LLM.

    .venv/bin/python -m tools.demo_toni_offline [--out NEW_DIR]

Stages (each reports PASS, BLOCKED or FAILED per check, against what the system SHOULD do):
  1. mission input and validation (MissionDefinition + LangGraph waypoint graph), including an
     infeasible copy that the graph must reject and replan;
  2. QGC .plan: strict exporter on the SAME mission (refused without AMSL, exported with a declared
     one), verified and re-imported; plus the historical QGC 5.1.5 re-save compared (read only);
  3-6. agricultural slice: SYNTHETIC red-card observation -> validations (and invalid variants) ->
     R1 proposal through the existing preparation -> coordinator request without authorization;
  7. summary.
Stages 3-6 do NOT depend on 1-2: their drone mission is the one of the re-identified H2 record.

Nothing here calls a model, starts a process, touches reservations or policies, or admits anything.
Everything written goes to a NEW directory (default: a fresh temporary one, printed at the end).
Exit code 0 only when every check matched its expectation.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MISSION = ROOT / 'missions/examples/simulation_navigation_3waypoint.json'
DECLARED_HOME_AMSL_M = 584.0  # declared for the demo (the SITL launch site); not measured
QGC_ORIGINAL = ROOT / 'evaluation/observability/hermes_finalized_package_two_drones_2026_10_30/package/plans/drone_01.plan'
QGC_RESAVED = ROOT / 'evaluation/observability/qgc_import_hermes_two_drones_2026_10_30/qgc_saved/drone_01.qgc_resaved.plan'
PASS, BLOCKED, FAILED = 'PASS', 'BLOCKED', 'FAILED'


class Stage:
    def __init__(self, number, title, link):
        self.number, self.title, self.link = number, title, link
        self.checks, self.facts = [], {}

    def check(self, label, ok, *, expected=PASS, detail=''):
        """ok True -> the expected status was observed; otherwise FAILED."""
        status = expected if ok else FAILED
        self.checks.append({'label': label, 'status': status, 'expected': expected, 'detail': detail})
        return ok

    def fail(self, label, exc):
        self.checks.append({'label': label, 'status': FAILED, 'expected': PASS,
                            'detail': f'{type(exc).__name__}: {exc}'})

    @property
    def ok(self):
        return bool(self.checks) and all(c['status'] == c['expected'] for c in self.checks)

    def as_dict(self):
        return {'stage': self.number, 'title': self.title, 'link': self.link, 'ok': self.ok,
                'checks': self.checks, 'facts': self.facts}


def _quiet(fn, *args, **kwargs):
    """Run a project function whose nodes print, keeping their trace lines for the report."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        value = fn(*args, **kwargs)
    trace = [line.strip() for line in buffer.getvalue().splitlines() if line.strip().startswith(('[NODE]', '[ROUTER]'))]
    return value, trace


# ------------------------------------------------------------------ stage 1 --
def stage_mission(out, state):
    stage = Stage(1, 'Entrada y validación de misión (LangGraph)', 'CHAINED -> 2')
    from inputs.json_loader import load_mission_json
    from graph.waypoint_mission_graph import waypoint_mission_graph as graph
    mission = load_mission_json(str(MISSION))
    state['mission'] = mission
    stage.check('misión JSON cargada como MissionDefinition', mission.mission_id == 'simulation_navigation_3waypoint_001',
                detail=f'{mission.mission_id}: {len(mission.route.waypoints)} waypoints')
    result, trace = _quiet(graph.invoke, {'mission': mission})
    stage.facts['valid'] = {'status': result['mission_status'], 'trace': trace}
    stage.check('grafo de validación: misión viable', result['mission_status'] == 'FEASIBLE' and not result.get('failure_reasons'),
                detail=f"{result['mission_status']} · {' → '.join(t.split('] ', 1)[-1] for t in trace if t.startswith('[NODE]'))}")
    data = json.loads(MISSION.read_text(encoding='utf-8'))
    data['environment']['wind_speed_kmh'] = 45.0
    windy = out / 'mission_wind_45kmh.json'
    windy.write_text(json.dumps(data, indent=2), encoding='utf-8')
    bad, trace = _quiet(graph.invoke, {'mission': load_mission_json(str(windy))})
    stage.facts['infeasible'] = {'status': bad['mission_status'], 'reasons': bad.get('failure_reasons'),
                                 'replan_actions': bad.get('replan_actions'), 'trace': trace}
    stage.check('misma misión con viento de 45 km/h: rechazada y replanteada',
                bad['mission_status'] == 'NOT FEASIBLE' and bool(bad.get('replan_actions'))
                and any('[NODE] waypoint_replanner' in t for t in trace), expected=BLOCKED,
                detail=f"{bad['mission_status']} · {(bad.get('replan_actions') or ['-'])[0]}")
    return stage


# ------------------------------------------------------------------ stage 2 --
def stage_qgc(out, state):
    stage = Stage(2, 'QGroundControl .plan: exportación estricta, verificación y reimportación', 'CHAINED <- 1')
    from inputs.qgc_plan_export import build_plan, plan_bytes, refusal_reasons, verify_plan
    from inputs.qgroundcontrol_adapter import load_qgroundcontrol_plan
    from models.qgc_import import QGroundControlImportContext
    from tools.qgc_plan_compare import compare_plans
    mission = state['mission']
    reasons = refusal_reasons(mission)
    stage.check('sin altitud AMSL del home: el exportador se niega', bool(reasons) and any('AMSL' in r for r in reasons),
                expected=BLOCKED, detail=reasons[0] if reasons else '')
    plan, _ = build_plan(mission, planned_home_amsl_m=DECLARED_HOME_AMSL_M)
    path = out / 'simulation_navigation_3waypoint.plan'
    path.write_bytes(plan_bytes(plan))
    verified = verify_plan(path, mission, planned_home_amsl_m=DECLARED_HOME_AMSL_M)
    stage.facts['export'] = {'path': str(path), 'items': len(plan['mission']['items']), 'status': verified['status']}
    stage.check(f'con AMSL declarada ({DECLARED_HOME_AMSL_M:g} m): exportado y verificado',
                verified['status'] == 'FILE_MATCHES_EXPECTATIONS',
                detail=f"{len(plan['mission']['items'])} ítems · {verified['status']}")
    context = QGroundControlImportContext(
        battery_percent=mission.vehicle.battery_percent,
        battery_consumption_percent_per_minute=mission.vehicle.battery_consumption_percent_per_minute,
        wind_speed_kmh=mission.environment.wind_speed_kmh, wind_direction_from_deg=mission.environment.wind_direction_from_deg,
        minimum_battery_reserve_percent=mission.constraints.minimum_battery_reserve_percent,
        maximum_wind_speed_kmh=mission.constraints.maximum_wind_speed_kmh,
        maximum_altitude_m=mission.constraints.maximum_altitude_m, vehicle_id=mission.vehicle.vehicle_id)
    back = load_qgroundcontrol_plan(str(path), context)
    navigate = [w for w in back.mission.route.waypoints if w.altitude_m > 0]
    same = len(navigate) == len(mission.route.waypoints) and all(
        abs(a.latitude - b.latitude) < 1e-7 and abs(a.longitude - b.longitude) < 1e-7 and abs(a.altitude_m - b.altitude_m) < 1e-6
        for a, b in zip(navigate, mission.route.waypoints))
    stage.check('el .plan generado se reimporta con los mismos waypoints', same,
                detail=f'{back.source_item_count} ítems leídos · {len(navigate)} waypoints iguales a la misión')
    comparison = compare_plans(QGC_ORIGINAL.read_bytes(), QGC_RESAVED.read_bytes())
    stage.facts['historical_qgc'] = {'status': comparison['status'], 'counts': comparison['counts']}
    stage.check('[independiente, HISTÓRICO 30/10] .plan de Hermes re-guardado por QGC 5.1.5: sin cambios semánticos',
                comparison['status'] == 'NO_SEMANTIC_DIFFERENCES',
                detail=f"{comparison['status']} · {comparison['counts']['PRESENTATION']} PRESENTATION, "
                       f"{comparison['counts']['SEMANTIC_CHANGE']} SEMANTIC_CHANGE")
    return stage


# --------------------------------------------------------------- stages 3-6 --
def stage_observation(out, state):
    stage = Stage(3, 'Observación SINTÉTICA de una cartulina roja (no hay cámara)', 'CHAINED -> 4')
    from datetime import datetime, timezone
    from tools import agri_observation_task as task
    case = task.example_case(state.get('now_utc') or datetime.now(timezone.utc).isoformat())
    state['case'] = case
    obs = case['observation']
    stage.facts['observation'] = obs
    stage.check('contrato tfg.agri.drone-observation/1 completo', set(obs) == task.OBSERVATION_KEYS,
                detail=f"{obs['drone_id']} · {obs['detection']['colour']} ({obs['detection']['confidence']}) · "
                       f"frame {obs['target']['frame']} ({obs['target']['x']}, {obs['target']['y']}) · fuente {obs['source']['kind']}")
    return stage


def stage_validation(out, state):
    stage = Stage(4, 'Validación de procedencia, coordenadas y frame', 'CHAINED <- 3, -> 5')
    from tools import agri_observation_task as task
    case = state['case']
    policy = {'allow_synthetic': True}

    def validate(observation, context=None):
        return task.validate_observation(observation, context=context or case['context'], ledger=task.Ledger(),
                                         now_utc=case['now_utc'], policy=policy)
    valid = validate(case['observation'])
    stage.facts['valid'] = {'status': valid['status'], 'reasons': valid['reasons']}
    stage.check('observación del ejemplo: aceptada', valid['status'] == 'ACCEPTED', detail='ninguna objeción')
    obs = case['observation']
    variants = [
        ('coordenadas de cámara (píxeles)', {**obs, 'target': {'frame': 'camera_image_px', 'x': 320.0, 'y': 240.0}}, None,
         'CAMERA_COORDINATES_ARE_NOT_NAVIGATION_COORDINATES'),
        ('confianza 0,5', {**obs, 'detection': {**obs['detection'], 'confidence': 0.5}}, None, 'CONFIDENCE_TOO_LOW'),
        ('fuente «cámara del dron»', {**obs, 'source': {'kind': 'DRONE_CAMERA_PIPELINE'}}, None,
         'PERCEPTION_SOURCE_NOT_IMPLEMENTED'),
        ('sin transformación acreditada', obs, {**case['context'], 'transform': None}, 'TRANSFORM_ABSENT'),
    ]
    for label, variant, context, reason in variants:
        result = validate(variant, context)
        stage.check(f'variante inválida, {label}: rechazada', result['status'] == 'REJECTED' and reason in result['reasons'],
                    expected=BLOCKED, detail=reason)
    return stage


def stage_proposal(out, state):
    stage = Stage(5, 'Propuesta de tarea terrestre R1 (preparación R1 existente)', 'CHAINED <- 4, -> 6')
    from tools import agri_observation_task as task
    result, real = task.run_example(out / 'agri_red_card', case=state['case'])
    state['agri'] = (result, real)
    proposal = result['proposal'] or {}
    stage.facts['proposal'] = {k: proposal.get(k) for k in ('status', 'origin', 'colour', 'target_in_rover_frame',
                                                            'authorization', 'proposal_sha256')}
    stage.check('propuesta PROPOSED_PENDING_VALIDATION, autorización ABSENT',
                proposal.get('status') == 'PROPOSED_PENDING_VALIDATION' and proposal.get('authorization') == 'ABSENT',
                detail=f"objetivo {proposal.get('target_in_rover_frame')} · origen {proposal.get('origin')}")
    prepared = result.get('preparation') or {}
    stage.check('la preparación R1 existente genera el mismo candidato',
                bool(prepared.get('candidate')) and prepared['candidate']['target_in_rover_frame']['value']
                == proposal.get('target_in_rover_frame'),
                detail=f"etapas {prepared.get('stages')}")
    stage.check('con los hechos de solo lectura del executor real: no elegible (política desactivada)',
                bool(real) and real['stages']['eligibility'] == 'NOT_ELIGIBLE'
                and 'operational_rover_policy_enabled' in real['blockers'], expected=BLOCKED,
                detail=f"bloqueos {real['blockers'] if real else None}")
    return stage


def stage_decision(out, state):
    stage = Stage(6, 'Decisión final', 'CHAINED <- 5')
    result, _ = state['agri']
    request = result.get('request') or {}
    decision = json.loads((out / 'agri_red_card' / 'decision.json').read_text(encoding='utf-8'))
    stage.facts['decision'] = result['decision']
    stage.check('petición al coordinador sin autorización: BLOCKED, sin llamar al executor',
                request.get('request_status') == 'BLOCKED' and request.get('executor_called') is False
                and decision['executor_admit_calls'] == 0, expected=BLOCKED,
                detail=f"{request.get('reason')} · admisiones {decision['executor_admit_calls']} ({decision['executor_kind']})")
    stage.check('resultado: ROVER_TASK_PENDING_AUTHORIZATION, movement_authorized False',
                result['decision'] == 'ROVER_TASK_PENDING_AUTHORIZATION' and result['movement_authorized'] is False,
                expected=BLOCKED, detail=result['decision'])
    return stage


STAGES = (stage_mission, stage_qgc, stage_observation, stage_validation, stage_proposal, stage_decision)
DEPENDS = {stage_qgc: stage_mission, stage_validation: stage_observation, stage_proposal: stage_validation,
           stage_decision: stage_proposal}
NOT_CLAIMED = ['percepción visual (no hay cámara ni detector)', 'transformación acreditada dron → odom del rover',
               'ejecución conjunta dron-rover', 'ningún movimiento del rover', 'ninguna llamada a un LLM en esta demo']


def run(out_dir=None, *, now_utc=None, emit=print):
    """Run every stage; returns (stages, exit_code). Writes only inside out_dir."""
    if out_dir is None:
        out = Path(tempfile.mkdtemp(prefix='tfg-demo-toni-'))
    else:
        out = Path(out_dir)
        if out.exists() and any(out.iterdir()):
            raise FileExistsError(f'{out} exists and is not empty: use a NEW directory')
        out.mkdir(parents=True, exist_ok=True)
    state, stages, done = {'now_utc': now_utc}, [], {}
    emit('TFG · demo offline (código real del proyecto; sin Gazebo, Docker, ROS 2 ni LLM)')
    for fn in STAGES:
        needed = DEPENDS.get(fn)
        if needed is not None and not done.get(needed):
            stage = Stage(STAGES.index(fn) + 1, fn.__name__, 'SKIPPED')
            stage.checks.append({'label': 'etapa previa necesaria', 'status': FAILED, 'expected': PASS,
                                 'detail': f'depends on {needed.__name__}, which failed'})
        else:
            try:
                stage = fn(out, state)
            except Exception as exc:  # a missing file, module or contract: reported, never hidden
                stage = Stage(STAGES.index(fn) + 1, fn.__name__, 'ERROR')
                stage.fail('dependencia o contrato no disponible', exc)
        done[fn] = stage.ok
        stages.append(stage)
        emit(f'\n[{stage.number}] {stage.title}  ({stage.link})')
        for c in stage.checks:
            mark = c['status'] if c['status'] == c['expected'] else f"{c['status']} (se esperaba {c['expected']})"
            emit(f"    {mark:<8} {c['label']}" + (f"\n             {c['detail']}" if c['detail'] else ''))
    counts = {s: sum(c['status'] == s for st in stages for c in st.checks) for s in (PASS, BLOCKED, FAILED)}
    unexpected = [c for st in stages for c in st.checks if c['status'] != c['expected']]
    emit('\n[7] Resumen')
    emit(f"    PASS {counts[PASS]} · BLOCKED {counts[BLOCKED]} (todos esperados: rechazos y bloqueos del sistema) · "
         f"FAILED {counts[FAILED]}")
    emit('    No se demuestra: ' + '; '.join(NOT_CLAIMED) + '.')
    emit(f'    Evidencias de esta ejecución: {out}')
    summary = {'stages': [s.as_dict() for s in stages], 'counts': counts, 'ok': not unexpected,
               'not_claimed': NOT_CLAIMED, 'offline': True, 'movement_authorized': False}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + '\n', encoding='utf-8')
    code = 0 if not unexpected else 1
    emit(f"    Resultado: {'DEMO COMPLETA, todo según lo esperado' if code == 0 else 'HAY FALLOS: revisar arriba'}")
    return stages, code


def main(argv=None):
    parser = argparse.ArgumentParser(description='One-command offline TFG demo (real project code; no Gazebo/Docker/ROS/LLM)')
    parser.add_argument('--out', type=Path, default=None, help='NEW directory for the evidence (default: a fresh temp dir)')
    args = parser.parse_args(argv)
    try:
        _, code = run(args.out)
    except FileExistsError as exc:
        print(f'[REFUSED] {exc}', file=sys.stderr)
        return 2
    return code


if __name__ == '__main__':
    sys.exit(main())
