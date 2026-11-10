"""Experimental comparison of the agri_demo_001 line, generated ONLY from conserved evidence (no inference, no
re-evaluation). It reuses the existing analyses as recorded:
- per Hermes turn: run.json, capture_summary.json (tool offers/requests/executions), native_usage_reviewed.json;
- acceptance as recorded at the time: accept_h3.json (H3 protocol), accept_h3b.json (H3b protocol), and for the
  pilot the effective acceptance chosen by the existing pilot_report (post-fix when present);
- the H2 execution view (no model involved);
- the pilot protocol and its amendment, kept apart.
Every figure keeps its denominator, the keys it counts and its source file. Cases are never pooled into a global
reliability rate: H3, H3b and the pilot use different prompts, tools and acceptance protocols.

Also: the explanation rubric and a PENDING human review sheet with the literal texts, their hashes and references.

    python -m reporting.agri_experiment_comparison comparison --out <file.md> [--json <file.json>]
    python -m reporting.agri_experiment_comparison review-sheet --out <file.md>
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from reporting import agri_scenario_summary as summary

ROOT = summary.PROJECT_ROOT
EVIDENCE = ROOT / "evaluation/observability"
H1 = EVIDENCE / "agri_planning_h1_nous_2026_10_24"
H3 = EVIDENCE / "agri_scenario_h3_nous_2026_10_24"
H3B = EVIDENCE / "agri_scenario_h3b_nous_2026_10_24"
PILOT = EVIDENCE / "agri_scenario_pilot_nous_2026_10_24"
PILOT_AUDIT = EVIDENCE / "agri_scenario_pilot_audit_2026_10_25"
H2_VIEW = EVIDENCE / "agri_scenario_view_h2_2026_10_24/scenario_view.json"
NOT_KEYS = {"parse"}  # acceptance entries that describe the answer, not a compared key
PRESENCE = "present"  # accept-h3 checks some fields only for presence (evidence_source, explanation)


def _rel(path: Path) -> str:
    return Path(path).resolve().relative_to(ROOT).as_posix()


def _load(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).is_file() else None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _outcomes(entries: dict | None) -> dict | None:
    """{match, total, failed keys} over compared keys only; None when the protocol has no such class."""
    if not isinstance(entries, dict):
        return None
    keys = {k: v for k, v in entries.items() if k not in NOT_KEYS and v != PRESENCE}
    presence = sorted(k for k, v in entries.items() if v == PRESENCE)
    if not keys:
        return None  # nothing was compared (e.g. an unparseable answer)
    counts = Counter(keys.values())
    return {"match": counts.get("match", 0), "total": len(keys), "presence_only": presence,
            "failed": sorted(k for k, v in keys.items() if v != "match"), "values": dict(counts)}


def _turn(case: str, directory: Path, protocol: str) -> dict:
    """Invocation, model requests and tools of one Hermes turn, as recorded."""
    run, capture = _load(directory / "run.json") or {}, _load(directory / "capture_summary.json") or {}
    usage = _load(directory / "native_usage_reviewed.json") or {}
    trial = capture.get("mcp_tool_trial") or {}
    calls = trial.get("tool_calls") or []
    auxiliary = usage.get("auxiliary") or {}
    return {
        "case": case, "protocol": protocol, "source_dir": _rel(directory),
        "invocations": run.get("hermes_invocations"), "return_code": run.get("return_code"),
        "model_requests_main": usage.get("api_calls"), "model_requests_auxiliary": auxiliary.get("api_calls"),
        "plugin_llm_calls": trial.get("llm_calls"), "plugin_llm_errors": trial.get("llm_errors"),
        "tools_offered": trial.get("offered"), "tools_requested": trial.get("requested_tool_names") or [],
        "tool_calls_ok": sum(c.get("status") == "ok" for c in calls), "tool_calls": len(calls),
        "tool_verdict": trial.get("verdict"),
        "elapsed_wall_s": run.get("elapsed_wall_s"),
        "tokens": {k: usage.get(k) for k in ("input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens",
                                              "total_tokens")},
        "tokens_auxiliary": auxiliary.get("total_tokens"), "turn_exit_reason": usage.get("turn_exit_reason"),
        "sources": {"run": _rel(directory / "run.json"), "tools": _rel(directory / "capture_summary.json"),
                    "usage": _rel(directory / "native_usage_reviewed.json")},
    }


def _h1() -> dict:
    row = _turn("H1", H1, "generación y validación de artefactos de misión a partir de una especificación completa")
    binding = _load(H1 / "h1_binding.json") or {}
    artifacts = binding.get("artifacts") or {}
    approved = sum((a.get("validation") or {}).get("execution_status") == "APPROVED" for a in artifacts.values())
    row.update(answer="NOT_EVALUATED (los artefactos se juzgan por la vinculación)", parse=None,
               decisions={"given_by_operator": "todos los valores (vehículos, ids, offsets, altitud, home, límites y "
                                               "acciones), las herramientas a usar y su orden",
                          "by_hermes": "trasladar la especificación en español a los argumentos estructurados de "
                                       "update_mission_draft (incluido geometry_intent) sin inventar campos, encadenar "
                                       "draft_id y draft_revision en las 4 llamadas y devolver el JSON final",
                          "by_code": "coordenadas desde los offsets, validación determinista, finalización y "
                                     "vinculación por hash frente a H0"},
               acceptance=binding.get("status"), acceptance_source=_rel(H1 / "h1_binding.json"),
               structured={"match": approved, "total": len(artifacts), "failed": [],
                           "counted": "artefactos BOUND con validación APPROVED y geometría igual a H0"},
               critical=None, explanation="no aplica: no se usa texto del modelo")
    return row


def _h3() -> dict:
    row = _turn("H3", H3, "accept-h3 (get_mission_state; claves sin clases)")
    accepted = _load(H3 / "accept_h3.json") or {}
    outcomes = accepted.get("answer_outcomes") or {}
    row.update(answer="RECEIVED", parse=outcomes.get("parse"), acceptance=accepted.get("status"),
               acceptance_source=_rel(H3 / "accept_h3.json"), structured=_outcomes(outcomes),
               critical=None, critical_note="el protocolo H3 no separaba claves críticas; "
               "r1_movement_authorized es crítica solo bajo el protocolo H3b posterior (clasificación retrospectiva). "
               "Además comprobó la presencia de evidence_source y explanation; contando esas dos como aciertos, la "
               "evidencia de H3 dice «24 de 25 claves»",
               explanation="clasificación manual en el README de H3 (no registrada como revisión humana de Joel): "
                           "error crítico «MET autoriza mover el rover», orden basado en la admisión, MET impreciso")
    return row


def _h3b() -> dict:
    row = _turn("H3b", H3B, "accept-h3b (get_scenario_view; claves factuales y críticas)")
    accepted = _load(H3B / "accept_h3b.json") or {}
    factual = accepted.get("factual") or {}
    row.update(answer="RECEIVED", parse=factual.get("parse"), acceptance=accepted.get("status"),
               acceptance_source=_rel(H3B / "accept_h3b.json"), structured=_outcomes(factual),
               critical=_outcomes(accepted.get("critical")),
               explanation="UNREVIEWED por Joel; revisión asistida (ChatGPT, transmitida por Joel) con errores "
                           "factuales: " + _rel(H3B / "explanation_review_assisted.json"))
    return row


def _form_only(run_dir: Path, accepted: dict) -> list[str]:
    """Failed reached_points keys whose CONTENT equals the view received but whose FORM differs (objects instead of
    a list of strings). Describes the rejection; the recorded acceptance is unchanged."""
    received = _load(run_dir / "tool_result_as_received.json") or []
    view = received[0].get("result") if received else {}
    expected = {r.get("run_id", "")[:8]: sorted(p for p, s in (r.get("points") or {}).items() if s == "REACHED")
                for r in ((view or {}).get("scenario") or {}).get("runs") or []}
    found = []
    for run in ((accepted.get("answer") or {}).get("runs") or []):
        key, value = f"runs[{str(run.get('run_id', ''))[:8]}].reached_points", run.get("reached_points")
        if (accepted.get("factual") or {}).get(key) == "mismatch" and isinstance(value, list) and value \
                and all(isinstance(v, dict) for v in value):
            content = sorted(v.get("poi") for v in value if v.get("status") == "REACHED")
            if content == expected.get(str(run.get("run_id", ""))[:8]) and len(content) == len(value):
                found.append(key)
    return found


def _attempts(run_dir: Path) -> list[dict]:
    """Model-request events as captured (no interpretation), in order."""
    events = []
    for path in sorted((run_dir / "capture").glob("hermes-events-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            if e.get("event_type") in ("llm_error", "llm_call"):
                events.append({k: e.get(k) for k in ("event_type", "recorded_at_utc", "api_request_ref", "error_type",
                                                     "status_code", "reason", "retry_count", "finish_reason")})
    return events


def _pilot() -> dict:
    report = summary.pilot_report(PILOT, PILOT_AUDIT)
    protocol, amendment = _load(PILOT / "protocol.json") or {}, _load(PILOT / "protocol_amendment_01.json") or {}
    rows = []
    for row in report["rows"]:
        run_dir = PILOT / row["key"]
        effective = run_dir / ("accept_h3b_post_fix.json" if (run_dir / "accept_h3b_post_fix.json").is_file()
                               else "accept_h3b.json")
        accepted = _load(effective) or {}
        tokens = row.get("tokens") or {}
        attempts = _attempts(run_dir) if row["failed_attempts"] else []
        counters = [a["retry_count"] for a in attempts if a["event_type"] == "llm_error"]
        rows.append({
            "case": row["key"], "segment": "tras enmienda 01" if row["after_amendment"] else "protocolo original",
            "answer": "RECEIVED" if row["answer_received"] else "NO_ANSWER_TECHNICAL",
            "tools_requested": row["requested_tools"], "view_calls": row["view_calls"],
            "logical_requests": row["logical_requests_observed"], "completed_requests": row["completed_requests"],
            "failed_attempts": row["failed_attempts"], "client_retries": row["client_retries"],
            "attempt_sequence": attempts,
            "retry_counter_monotonic": all(b > a for a, b in zip(counters, counters[1:])) if counters else None,
            "form_only_keys": _form_only(run_dir, accepted),
            "original_acceptance_error": effective.name == "accept_h3b_post_fix.json"
            and "status" not in (_load(run_dir / "accept_h3b.json") or {}),
            "parse": row["parse"], "acceptance": row["acceptance"],
            "structured": _outcomes(accepted.get("factual")), "critical": _outcomes(accepted.get("critical")),
            "elapsed_wall_s": row["elapsed_wall_s"], "timed_out": row["timed_out"],
            "tokens_total": tokens.get("total_tokens"), "model_requests_main": tokens.get("api_calls"),
            "acceptance_source": _rel(effective) if effective.is_file() else None})
    segments = {}
    for name in ("protocolo original", "tras enmienda 01"):
        part = [r for r in rows if r["segment"] == name]
        answered = [r for r in part if r["answer"] == "RECEIVED"]
        segments[name] = {"invocations": len(part), "keys": [r["case"] for r in part],
                          "answered": f"{len(answered)}/{len(part)}",
                          "structured_validated": f"{sum(r['acceptance'] == 'STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED' for r in part)}/{len(part)}"}
    return {"rows": rows, "segments": segments, "pilot_report_denominators": report["denominators"],
            "protocol_sha256": _sha((PILOT / "protocol.json").read_bytes()),
            "protocol_prompt": protocol.get("prompt_sha256") or (protocol.get("fixed_inputs") or {}).get("prompt_sha256"),
            "amendment": {"after": amendment.get("after"), "driver_changes": amendment.get("driver_changes"),
                          "unchanged": amendment.get("unchanged")},
            "sources": {"report": "reporting.agri_scenario_summary.pilot_report(" + _rel(PILOT) + ", " + _rel(PILOT_AUDIT) + ")",
                        "protocol": _rel(PILOT / "protocol.json"), "amendment": _rel(PILOT / "protocol_amendment_01.json")}}


def _h2() -> dict:
    view = _load(H2_VIEW) or {}
    scenario = view.get("scenario") or {}
    runs = []
    for run in scenario.get("runs") or []:
        points = run.get("points") or {}
        errors = run.get("position_errors_m") or {}
        runs.append({"vehicle": f"{run.get('vehicle_id')}/{run.get('simulated_vehicle')}",
                     "result": run.get("result_status"),
                     "points_reached": f"{sum(p == 'REACHED' for p in points.values())}/{len(points)}",
                     "max_horizontal_error_m": round(max((e.get("horizontal") or 0) for e in errors.values()), 2)
                     if errors else None,
                     "return_home": run.get("return_home"), "landing": run.get("landing")})
    return {"sequence": scenario.get("sequence"), "order": (scenario.get("order") or {}).get("status"),
            "scenario_status": scenario.get("status"), "runs": runs, "tolerances": scenario.get("tolerances"),
            "source": _rel(H2_VIEW), "model_involved": False}


def comparison() -> dict:
    return {"schema": "tfg.agri-experiment-comparison/1", "inference_executed": False,
            "turns": [_h1(), _h3(), _h3b()], "h2": _h2(), "pilot": _pilot(),
            "not_pooled": "H3, H3b y el piloto no se agregan: prompts, herramientas y protocolos de aceptación distintos"}


def _f(value, missing="—"):
    return missing if value is None else value


def _ratio(outcome):
    return "n/a" if not outcome else f"{outcome['match']}/{outcome['total']}"


def render(result: dict) -> str:
    turns, h2, pilot = result["turns"], result["h2"], result["pilot"]
    lines = ["# Comparación experimental de agri_demo_001 (generada)", "",
             "Generada por `reporting/agri_experiment_comparison.py` desde la evidencia conservada. No ejecuta "
             "inferencias ni reevalúa respuestas: cada aceptación es la registrada en su momento. "
             "**H3, H3b y el piloto no se agregan en una tasa**: usan prompts, herramientas y protocolos distintos.", "",
             "**Unidades:** *invocación* = una ejecución de Hermes; *petición al modelo* = llamada de API registrada "
             "por Hermes (principal o auxiliar); *intento interno* = intento de una petición registrado por Hermes, "
             "fallido o completado (solo lo registra el piloto). Llamarlo reintento depende del contador `retry_count`.", "",
             "## 1. Invocaciones, peticiones y herramientas", "",
             "| Caso | Protocolo | Invocaciones | Peticiones al modelo (principal + auxiliar) | Errores de llamada (plugin) | Herramientas ofrecidas | Pedidas | Ejecutadas sin error | Veredicto | Fuente |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t in turns:
        lines.append(f"| {t['case']} | {t['protocol']} | {_f(t['invocations'])} | {_f(t['model_requests_main'])} + "
                     f"{_f(t['model_requests_auxiliary'])} | {_f(t['plugin_llm_errors'])}/{_f(t['plugin_llm_calls'])} | "
                     f"{_f(t['tools_offered'])} | {len(t['tools_requested'])} | {t['tool_calls_ok']}/{t['tool_calls']} | "
                     f"`{_f(t['tool_verdict'])}` | `{t['sources']['tools']}` |")
    lines += ["", "## 2. Respuesta, formato y exactitud estructurada", "",
              "| Caso | Respuesta | Formato | Claves estructuradas coincidentes | Claves críticas coincidentes | Claves fallidas | Aceptación registrada | Fuente |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t in turns:
        failed = sorted(set((t["structured"] or {}).get("failed", [])) | set((t["critical"] or {}).get("failed", [])))
        lines.append(f"| {t['case']} | {t['answer']} | {_f(t['parse'])} | {_ratio(t['structured'])} | {_ratio(t['critical'])} | "
                     f"{', '.join(failed) or 'ninguna'} | `{t['acceptance']}` | `{t['acceptance_source']}` |")
    lines += ["", "- **H1:** «coincidentes» cuenta los artefactos `BOUND` con validación `APPROVED`: "
              + turns[0]["structured"]["counted"] + ".",
              "- **H3, dos denominadores que no se mezclan:** **22/23** cuenta solo las claves comparadas con el "
              "valor esperado (22 coinciden; falla `r1_movement_authorized`). **24/25**, en la evidencia de H3, suma "
              "además dos comprobaciones de **presencia** (`evidence_source`, `explanation`) que no comparan valores.",
              "- **H3:** " + turns[1]["critical_note"].split(". Además")[0] + ".",
              "- **H1:** decisiones dadas por el operador: " + turns[0]["decisions"]["given_by_operator"]
              + ". Aportación de Hermes: " + turns[0]["decisions"]["by_hermes"] + ". Lo hizo el código: "
              + turns[0]["decisions"]["by_code"] + ".",
              "- **H3b:** factuales y críticas según `accept-h3b`.", "",
              "## 3. Explicación libre y estado de revisión", "",
              "| Caso | Estado |", "| --- | --- |"]
    lines += [f"| {t['case']} | {t['explanation']} |" for t in turns]
    lines += ["| Piloto | Revisión humana PENDIENTE: `" + _rel(PILOT / "explanation_review_sheet.md") + "`; observaciones "
              "asistidas, no humanas |", "",
              "## 4. Tiempos y tokens conocidos (por invocación)", "",
              "| Caso | Tiempo de pared (s) | Tokens de entrada | Salida | Caché leída | Razonamiento | Total | Total auxiliar | Fin de turno | Fuente |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t in turns:
        k = t["tokens"]
        lines.append(f"| {t['case']} | {_f(t['elapsed_wall_s'])} | {_f(k['input_tokens'])} | {_f(k['output_tokens'])} | "
                     f"{_f(k['cache_read_tokens'])} | {_f(k['reasoning_tokens'])} | {_f(k['total_tokens'])} | "
                     f"{_f(t['tokens_auxiliary'])} | `{_f(t['turn_exit_reason'])}` | `{t['sources']['usage']}` |")
    lines += ["", "Los tokens son los normalizados por Hermes (`native_usage_reviewed.json`). El coste figura como "
              "estimación 0,0 (modelo gratuito) y no se compara.", "",
              "## 5. Ejecución aérea H2 (sin modelo)", "",
              f"Secuencia `{(h2['sequence'] or {}).get('sequence_id')}`: {(h2['sequence'] or {}).get('job_state')}/"
              f"{(h2['sequence'] or {}).get('result_status')}; orden `{h2['order']}`; escenario `{h2['scenario_status']}`. "
              f"Tolerancias {h2['tolerances']}. Fuente: `{h2['source']}`.", "",
              "| Vehículo | Resultado | POI alcanzados | Error horizontal máximo (m; incluye despegue, waypoints y regreso) | Regreso | Aterrizaje |",
              "| --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {r['vehicle']} | {r['result']} | {r['points_reached']} | {_f(r['max_horizontal_error_m'])} | "
              f"{r['return_home']} | {r['landing']} |" for r in h2["runs"]]
    lines += ["", "Los errores son observaciones del ejecutor por AP_DDS en una sola ejecución SITL; no son una "
              "medida de precisión física.", "",
              "## 6. Piloto (10 invocaciones del mismo protocolo H3b; enmienda separada)", "",
              f"- **Protocolo:** `{pilot['sources']['protocol']}` (SHA-256 `{pilot['protocol_sha256'][:16]}…`).",
              f"- **Enmienda 01:** tras {pilot['amendment']['after']}. Cambios del driver: "
              + "; ".join(pilot["amendment"]["driver_changes"] or []) + ".",
              "- **Sin cambios:** " + "; ".join(pilot["amendment"]["unchanged"] or []) + ".", "",
              "| Segmento | Invocaciones | Con respuesta | `STRUCTURED_VALIDATED…` |", "| --- | --- | --- | --- |"]
    lines += [f"| {name} ({', '.join(s['keys'])}) | {s['invocations']} | {s['answered']} | {s['structured_validated']} |"
              for name, s in pilot["segments"].items()]
    lines += ["", "| Clave | Segmento | Respuesta | Peticiones lógicas (completadas) | Intentos fallidos | Reintentos derivados | Formato | Factuales | Críticas | Claves rechazadas | Aceptación | s | Tokens |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in pilot["rows"]:
        failed = sorted(set((r["structured"] or {}).get("failed", [])) | set((r["critical"] or {}).get("failed", [])))
        form = set(r["form_only_keys"])
        rejected = [f"{k} (forma)" if k in form else k for k in failed]
        factual = _ratio(r["structured"]) + (f" ({len(form)} por forma)" if form else "")
        retries = r["client_retries"] if r["retry_counter_monotonic"] is not False else f"{r['client_retries']}?"
        lines.append(f"| {r['case']} | {r['segment']} | {r['answer']} | {r['logical_requests']} ({r['completed_requests']}) | "
                     f"{r['failed_attempts']} | {retries} | {_f(r['parse'])} | {factual} | "
                     f"{_ratio(r['critical'])} | {', '.join(rejected) or '—'} | `{_f(r['acceptance'])}` | "
                     f"{r['elapsed_wall_s']} | {_f(r['tokens_total'])} |")
    lines += ["", f"- **Denominadores del informe del piloto:** {pilot['pilot_report_denominators']}. Fuente: "
              f"`{pilot['sources']['report']}`.",
              "- Wilson 95 % para 6/10 = [0,354; 0,879] es solo descriptivo: las invocaciones comparten prefijo y "
              "caché, y los parámetros de muestreo son desconocidos (`pilot_analysis.json`).",
              "- `r03` no llamó a la herramienta y su salida no es JSON: «Factuales» y «Críticas» no se aplican (n/a).",
              "- **«Reintentos derivados»** es un cálculo de `pilot_report` (intentos fallidos seguidos de un intento "
              "completado), no un contador de Hermes. `?` indica que el contador `retry_count` registrado no es "
              "monótono y el número de reintentos no puede afirmarse.", ""]
    for r in pilot["rows"]:
        if r["form_only_keys"]:
            lines.append(f"- **{r['case']}:** `{_f(r['acceptance'])}` por **forma**: " + ", ".join(r["form_only_keys"])
                         + " se escribió como objetos (`{poi, status}`) en lugar de una lista de cadenas. El contenido "
                         "coincide con la vista recibida (mismos POI `REACHED`); el rechazo se conserva y **no** se "
                         "cuenta como hechos incorrectos."
                         + (" Su evaluación original terminó con una excepción del evaluador, corregida después; ambas "
                            "aceptaciones se conservan." if r["original_acceptance_error"] else ""))
        if r["attempt_sequence"]:
            steps = "; ".join(f"{a['recorded_at_utc'][11:19]} {a['event_type']}"
                              + (f" {a['error_type']}/{a['status_code'] or a['reason']} retry_count={a['retry_count']}"
                                 if a["event_type"] == "llm_error" else f" ({a['finish_reason']})")
                              for a in r["attempt_sequence"])
            refs = sorted({a["api_request_ref"] for a in r["attempt_sequence"]})
            lines.append(f"- **{r['case']}:** eventos registrados ({len(refs)} petición lógica, `{', '.join(refs)}`): "
                         f"{steps}."
                         + (" El contador `retry_count` vuelve a 0 en el último fallo: los registros no permiten "
                            "afirmar cuántos de esos intentos contó Hermes como reintentos de un mismo ciclo."
                            if r["retry_counter_monotonic"] is False else "")
                         + (" La petición siguiente (respuesta final) no tiene evento antes del timeout de 300 s; no se "
                            "reinvocó." if r["answer"] != "RECEIVED" else ""))
    lines.append("")
    return "\n".join(lines)


# --- Explanation rubric and pending human review sheet -----------------------------------------------------------

RUBRIC = [  # (id, criterion, what counts as correct, how ambiguity is treated, mapping to the 25/10 pilot sheet)
    ("autorizacion", "Autorización y órdenes al rover",
     "Dice que R1 no está autorizado y que no se enviaron órdenes; no presenta MET ni la secuencia como permiso",
     "«podría moverse», «queda habilitado»: AMBIGUO salvo que niegue la autorización en la misma frase", "rover"),
    ("completitud", "Completitud del escenario",
     "Incompleto porque R1 no se ha ejecutado; no lo da por cerrado ni por fallido",
     "«finalizó la fase aérea» sin decir que el escenario sigue incompleto: INCOMPLETO", "completitud"),
    ("orden", "Orden y fundamento temporal",
     "drone_01 antes que drone_02, acreditado por marcas de ejecución y despacho, no por horas de admisión",
     "«en secuencia» sin fundamento: INCOMPLETO; fundamento en la admisión: INCORRECTO", "secuencia"),
    ("met", "Significado completo de MET",
     "Las dos condiciones (secuencia COMPLETED y POI_A1 REACHED por drone_01) y que MET es precondición, no permiso",
     "Una sola condición: INCOMPLETO; «PASSED» por COMPLETED: anotar como impreciso", "r1_dependencia"),
    ("capacidades", "Capacidades inventadas",
     "No afirma imágenes, detecciones, velocidad comandada o medida, marco común, vuelo simultáneo ni permisos actuales",
     "Mencionarlas como límites no es inventarlas; frases que puedan leerse como hechos: AMBIGUO", "capacidades"),
    ("contradicciones", "Contradicciones con la respuesta estructurada",
     "Ninguna frase contradice sus propios campos (p. ej. texto «autorizado» con r1_movement_authorized false)",
     "Si depende de la lectura, AMBIGUO con la cita literal", "contradicciones"),
    ("atribucion", "Atribución y límites de la evidencia",
     "Atribuye los hechos a la vista o al registro histórico; no sugiere reejecución ni estado actual",
     "«volvieron a ejecutarse», «actualmente»: AMBIGUO; afirmación de estado actual: INCORRECTO", "alcance"),
]
VALUES = "`CORRECTO`, `INCOMPLETO`, `AMBIGUO`, `INCORRECTO`, `NO MENCIONA`"


def _explanations() -> list[dict]:
    items = []
    for case, path in (("H3", H3 / "accept_h3.json"), ("H3b", H3B / "accept_h3b.json")):
        accepted = _load(path) or {}
        items.append({"case": case, "path": path, "status": accepted.get("status"),
                      "text": (accepted.get("answer") or {}).get("explanation")})
    for key in sorted(p.name for p in PILOT.iterdir() if p.is_dir() and p.name.startswith("pilot-real-")):
        run_dir = PILOT / key
        path = run_dir / ("accept_h3b_post_fix.json" if (run_dir / "accept_h3b_post_fix.json").is_file()
                          else "accept_h3b.json")
        accepted = _load(path)
        answer = (accepted or {}).get("answer")
        items.append({"case": key, "path": path if accepted else None, "status": (accepted or {}).get("status"),
                      "text": answer.get("explanation") if isinstance(answer, dict) else None})
    return items


def render_review_sheet() -> str:
    lines = ["# Rúbrica de explicaciones y hoja de revisión humana (PENDIENTE)", "",
             "Generada por `reporting/agri_experiment_comparison.py review-sheet`.",
             "- **Análisis retrospectivo.** La rúbrica es posterior a H3, H3b y el piloto. No cambia ninguna "
             "aceptación registrada ni sustituye sus criterios.",
             "- **Revisión humana: PENDIENTE.** Las columnas «Valoración» y «Nota» están vacías. Las observaciones "
             "asistidas existentes se citan por referencia y nunca cuentan como revisión de Joel.",
             f"- **Valores:** {VALUES}. Si una frase admite dos lecturas, se marca `AMBIGUO` y se copia literal en "
             "la nota; no se resuelve a favor del modelo.",
             "- Mencionar una capacidad **como límite** («sin imágenes») no es inventarla.", "",
             "## Rúbrica", "", "| Id | Criterio | Correcto si | Ambigüedad | Criterio equivalente en la hoja del piloto (25/10) |",
             "| --- | --- | --- | --- | --- |"]
    lines += [f"| `{i}` | {c} | {ok} | {amb} | `{m}` |" for i, c, ok, amb, m in RUBRIC]
    lines += ["", "**Observaciones asistidas existentes (no humanas):**",
              f"- H3b: `{_rel(H3B / 'explanation_review_assisted.json')}` (ChatGPT, transmitida por Joel);",
              f"- piloto: `{_rel(PILOT / 'explanation_observations_assisted.json')}` y "
              f"`{_rel(PILOT / 'explanation_review_sheet.md')}`;",
              "- H3: revisión manual descrita en `docs/hermes-planning.md` (apartado H3).", ""]
    for item in _explanations():
        lines += [f"## {item['case']}", ""]
        if not isinstance(item["text"], str):
            lines += ["Sin explicación analizable: no hubo respuesta, o la salida no se pudo analizar. "
                      "No hay nada que valorar con esta rúbrica.", ""]
            continue
        data = item["path"].read_bytes()
        lines += [f"- **Referencia:** `{_rel(item['path'])}` (SHA-256 del archivo `{_sha(data)}`), campo "
                  f"`answer.explanation`.",
                  f"- **SHA-256 del texto (UTF-8):** `{_sha(item['text'].encode('utf-8'))}`.",
                  f"- **Estado automático:** `{item['status']}`.", "", "Texto literal:", ""]
        lines += ["> " + line if line else ">" for line in item["text"].splitlines()]
        lines += ["", "| Criterio | Valoración (pendiente) | Nota (pendiente) |", "| --- | --- | --- |"]
        lines += [f"| {c} |  |  |" for _, c, _, _, _ in RUBRIC]
        lines += ["", "Revisor: ________  Fecha: ________", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("comparison")
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--json", type=Path, default=None)
    r = sub.add_parser("review-sheet")
    r.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    for target in (args.out, getattr(args, "json", None)):
        if target is not None and target.exists():
            parser.error(f"{target} exists: generated files are never overwritten")
    if args.command == "comparison":
        result = comparison()
        args.out.write_text(render(result), encoding="utf-8")
        if args.json:
            args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        args.out.write_text(render_review_sheet(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
