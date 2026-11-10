"""Render the human review sheet for the pilot explanations (literal text; review left blank)."""
import json
from pathlib import Path

E = Path("<repo>/evaluation/observability/agri_scenario_pilot_nous_2026_10_24")
CRITERIA = [
    ("secuencia", "Secuencia y prueba del orden (comprobaciones de `order.checks`, no horas de admisión)"),
    ("armado", "Armado/despegue (orden correcto; sin comprobaciones inexistentes)"),
    ("r1_dependencia", "Dependencia completa de R1 (secuencia COMPLETED **y** POI_A1 REACHED por drone_01)"),
    ("rover", "Autorización y órdenes al rover (no autorizado, sin órdenes; MET no autoriza)"),
    ("completitud", "Completitud del escenario (incompleto por R1)"),
    ("capacidades", "Capacidades inventadas (imágenes, detecciones, velocidad, marco común, permisos)"),
    ("alcance", "Alcance histórico (registro único, no reejecución ni estado actual)"),
    ("contradicciones", "Contradicciones con sus propios campos estructurados"),
]


def main():
    assisted = json.loads((E / "explanation_observations_assisted.json").read_text())
    out = [
        "# Hoja de revisión de explicaciones — piloto `agri-scenario-pilot-real`",
        "",
        "**Revisión humana: PENDIENTE.** Esta hoja no contiene ninguna valoración de Joel. Las columnas",
        "«Valoración» y «Nota» están vacías a propósito.",
        "",
        "- **Texto literal:** cada explicación es el campo `explanation` de `accept_h3b.json`, sin corregir.",
        "- **Hechos de referencia:** la vista recibida (`tool_result_as_received.json`, idéntica en todas",
        "  las invocaciones). El [informe determinista](../agri_scenario_report_h2_2026_10_24/README.md)",
        "  los presenta generados por código; no se mezcla con la salida del modelo.",
        "- **Observaciones automáticas:** las heurísticas de palabras clave de `accept-h3b`. No son una",
        "  validación semántica.",
        "- **Observaciones asistidas (Claude, preliminares):** lectura de Claude contra la vista. **No**",
        "  sustituyen la revisión humana ni cambian ningún estado. La revisión asistida de H3b no se",
        "  reutiliza aquí.",
        "",
        "Valores sugeridos para «Valoración»: `CORRECTO`, `INCOMPLETO`, `AMBIGUO`, `INCORRECTO`, `NO MENCIONA`.",
        "",
    ]
    for key in sorted(p.name for p in E.iterdir() if p.is_dir() and p.name.startswith("pilot-real-r")):
        path = E / key / "accept_h3b_post_fix.json"
        original = E / key / "accept_h3b.json"
        acc = (json.loads((path if path.exists() else original).read_text()) if path.exists() or original.exists()
               else {"status": "SIN RESPUESTA (timeout; sin sesión evaluable)"})
        ans = acc.get("answer") or {}
        expl = ans.get("explanation") if isinstance(ans, dict) else None
        flags = (acc.get("explanation_review") or {}).get("heuristic_flags")
        out += [f"## {key}", "",
                f"Estado automático: `{acc.get('status')}`. Claves críticas fallidas: "
                f"{', '.join('`%s`' % k for k, v in (acc.get('critical') or {}).items() if v != 'match') or 'ninguna'}.",
                ""]
        if expl is None and (E / key / "hermes_stdout.txt").exists() and (E / key / "hermes_stdout.txt").stat().st_size:
            out += ["Sin respuesta analizable. Salida literal completa (`hermes_stdout.txt`):", "", "~~~~text"]
            out += (E / key / "hermes_stdout.txt").read_text().splitlines() + ["~~~~"]
        else:
            out += ["Explicación literal:", ""]
            out += ["> " + line if line else ">" for line in (expl or "(sin explicación)").splitlines()]
        out += ["", f"Observaciones automáticas (heurísticas): {', '.join(flags) if flags else 'ningún aviso'}.", ""]
        notes = assisted.get(key, [])
        out += ["Observaciones asistidas (Claude, preliminares):", ""]
        out += [f"- {n}" for n in notes] or ["- (ninguna)"]
        out += ["", "| Criterio | Valoración (pendiente) | Nota (pendiente) |", "| --- | --- | --- |"]
        out += [f"| {label} |  |  |" for _, label in CRITERIA]
        out += ["", "Revisor: ________  Fecha: ________", ""]
    (E / "explanation_review_sheet.md").write_text("\n".join(out))


if __name__ == "__main__":
    main()
