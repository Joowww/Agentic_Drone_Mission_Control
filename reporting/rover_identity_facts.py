"""Facts of a closed rover identity session (the rover's evidence, read-only), for the R1 preparation and reports.

Reads a trial directory ONLY after its manifest verifies (every listed file: size and SHA-256), then reports each
fact with its session, its sources and what it does NOT accredit. the rover's own requirement-matrix labels are kept
verbatim next to the cross-checks made here. Nothing here is a gate: the facts never change the R1 candidate, its
hash or its blockers, and a session's facts are never joined with samples of another session.

Each fact also says whether it concerns a LOCAL PULSE (body-frame bounded control) and/or the navigation to
POI_A1; that scope is a reading of the existing controller/executor paths, not a new requirement.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA = "tfg.rover-identity-facts/1"
BOTH, POI_ONLY = "PULSE_AND_POI_A1", "POI_A1_ONLY"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verify(root: Path) -> list[str]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    problems = []
    for entry in manifest["files"]:
        path = root / entry["path"]
        if (not path.is_file() or path.is_symlink() or path.stat().st_size != entry["size_bytes"]
                or _sha(path.read_bytes()) != entry["sha256"]):
            problems.append(entry["path"])
    return problems


def _jsonl(path: Path, prefix: str | None = None) -> list:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if prefix is not None:
            if not line.startswith(prefix + " "):
                continue
            line = line.split(" ", 1)[1]
        rows.append(json.loads(line))
    return rows


def identity_facts(trial_root: Path) -> dict:
    """Facts of one closed identity session, or NOT_AVAILABLE (absent, unreadable or not manifest-verified)."""
    root = Path(trial_root)
    try:
        problems = _verify(root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"schema": SCHEMA, "status": "NOT_AVAILABLE", "reason": f"MANIFEST_UNREADABLE: {type(exc).__name__}"}
    if problems:
        return {"schema": SCHEMA, "status": "NOT_AVAILABLE", "reason": "MANIFEST_MISMATCH: " + ", ".join(problems[:5])}
    load = lambda name: json.loads((root / name).read_text(encoding="utf-8"))  # noqa: E731
    summary, matrix = load("analysis-summary.json"), {r["requirement"]: r for r in load("requirement-matrix.json")}
    session = summary["session_id"]
    journal = _jsonl(root / "reader/journal.jsonl")
    receipt = load("reader/journal.jsonl.receipt.json")
    footer = next((r for r in journal if r.get("kind") == "footer"), {})
    catalog = next((r for r in journal if r.get("kind") == "scene_catalog"), {})
    names = {e["id"]: e["name"] for e in catalog.get("body") or []}
    trace = [(t, r) for t in ("TFG_IDENTITY_TRACE", "TFG_MODEL_TRACE")
             for r in _jsonl(root / "container-capture/trace.log", t)]
    bridge = next((r for t, r in trace if r.get("event") == "bridge_publisher" and r.get("ros_topic") == "/rover1/odometry"), {})
    odometry_gids = sorted({r.get("message_gid") for r in journal if r.get("topic") == "/rover1/odometry" and r.get("kind") == "sample"})
    rover_entity = next((i for i, n in names.items() if n == "rover1"), None)
    plugins = [r for t, r in trace if r.get("event") == "attached_plugin" and r.get("model_entity") == rover_entity]
    sends = [r for t, r in trace if r.get("event") == "fdm_send" and r.get("model_entity") == rover_entity]
    odometry_plugin = next((p for p in plugins if p.get("name") == "gz::sim::systems::OdometryPublisher"), {})
    ardupilot_plugin = next((p for p in plugins if p.get("name") == "ArduPilotPlugin"), {})
    monitor, monitor_exit = load("container-capture/monitor.json"), load("container-capture/monitor_exit.json")
    stop = load("passive-session/stop-result.json")
    sockets = load("socket-metrics.json")
    row = lambda name: {k: matrix[name].get(k) for k in ("result", "limitation")}  # noqa: E731

    facts = [
        {"id": "odometry_to_bridge", "title": "Odometría → bridge", "state": "OBSERVED"
         if odometry_gids and odometry_gids == [bridge.get("gid")] else "NOT_OBSERVED", "scope": BOTH,
         "detail": f"GID de las {sum(1 for r in journal if r.get('topic') == '/rover1/odometry' and r.get('kind') == 'sample')} "
                   f"muestras retenidas de /rover1/odometry = GID del bridge_publisher (pid {bridge.get('pid')}, "
                   f"{bridge.get('gz_topic')})",
         "not_accredited": "el modelo que origina la odometría ni la parada física",
         "rover_side": row("Odometry GID -> bridge process"),
         "sources": ["reader/journal.jsonl", "container-capture/trace.log"]},
        {"id": "plugin_to_entity", "title": "Plugin → entidad", "state": "OBSERVED" if plugins and sends else "NOT_OBSERVED",
         "scope": BOTH,
         "detail": f"entidad {rover_entity} («{names.get(rover_entity)}» en el catálogo de escena de la misma sesión) carga "
                   + ", ".join(p.get("name") for p in plugins)
                   + f"; socket JSON {(ardupilot_plugin.get('effective_sdf') or {}).get('fdm_addr')}:"
                   f"{(ardupilot_plugin.get('effective_sdf') or {}).get('fdm_port_in')}; {len(sends)} envíos FDM",
         "not_accredited": "la unión traza↔catálogo es por id de entidad dentro de una sesión; la traza no registra el "
                           "nombre del modelo",
         "rover_side": row("Loaded plugin -> actual entity -> pose/FDM send"),
         "sources": ["container-capture/trace.log", "reader/journal.jsonl (scene_catalog)"]},
        {"id": "parameters", "title": "Parámetros (SYSID)", "state": "RECEIVED_ATTRIBUTION_PENDING", "scope": BOTH,
         "detail": "valor 3 recibido (etiqueta de la matriz de requisitos del rover); GUID del solicitante cero en la respuesta pública; GUIDs nativos distintos",
         "not_accredited": "que la respuesta proceda del mismo XRCE/SITL que publica el Status",
         "rover_side": row("Effective SYSID response -> same XRCE/SITL"), "sources": ["reader-analysis.json"]},
        {"id": "fdm_receiver", "title": "Receptor FDM", "state": "NOT_ACCREDITED", "scope": BOTH,
         "detail": "destino de los envíos FDM: " + ", ".join(sorted({f"{s.get('destination_address')}:{s.get('destination_port')}"
                                                                     for s in sends}))
                   + f"; filas de socket relevantes: inodos retenidos {sockets.get('inodes_retained')}, "
                     f"propietarios {sockets.get('owners_retained')}",
         "not_accredited": "qué proceso SITL recibe esos envíos (peer → inode/FD → proceso no observado)",
         "rover_side": row("Peer -> inode/FD -> SITL process"), "sources": ["container-capture/trace.log", "socket-metrics.json"]},
        {"id": "odometry_to_model", "title": "Odometría → modelo", "state": "UNKNOWN", "scope": BOTH,
         "detail": f"OdometryPublisher de la entidad {rover_entity} con odom_topic "
                   f"{(odometry_plugin.get('effective_sdf') or {}).get('odom_topic')!r}; el bridge lee "
                   f"{bridge.get('gz_topic')}",
         "not_accredited": "la correspondencia por defecto del plugin con ese topic",
         "rover_side": row("Odometry -> model via effective publisher route"),
         "sources": ["container-capture/trace.log", "executed-helpers/bridge-config.yaml"]},
        {"id": "frames", "title": "Marcos y transformación del objetivo", "state": "NOT_ACCREDITED", "scope": POI_ONLY,
         "detail": "candidato numérico SE(2) descriptivo; sin error, origen, reloj ni fuente acreditados",
         "not_accredited": "frame_transform; no lo necesita un pulso en el marco del cuerpo",
         "rover_side": row("Target/frame transform"), "sources": ["frame-numeric-candidate.json"]},
        {"id": "reception", "title": "Recepción", "state": "CLOSED_PARTIAL_COVERAGE", "scope": BOTH,
         "detail": f"rc {load('passive-session/reader-result.json').get('return_code')}, reader_closed "
                   f"{receipt.get('reader_closed')}; {sum((footer.get('counts') or {}).values())} muestras retenidas "
                   f"de {(journal[0] if journal else {}).get('max_samples')}; {footer.get('retained_stream_count')}/"
                   f"{footer.get('expected_stream_count')} streams",
         "not_accredited": "cobertura completa de recepción (NavSat ausente en esta ventana)",
         "rover_side": row("Reader closure and stream coverage"),
         "sources": ["reader/journal.jsonl", "reader/journal.jsonl.receipt.json", "passive-session/reader-result.json"]},
        {"id": "monitor", "title": "Monitor", "state": "INCOMPLETE", "scope": BOTH,
         "detail": f"rc {monitor_exit.get('return_code')}; " + "; ".join(monitor.get("errors") or []),
         "not_accredited": "la captura completa del monitor (no se completa retrospectivamente)",
         "rover_side": row("Infrastructure closure / monitor"),
         "sources": ["container-capture/monitor.json", "container-capture/monitor_exit.json"]},
        {"id": "lifecycle_stop", "title": "Parada lifecycle", "state": stop.get("status"), "scope": BOTH,
         "detail": f"operación {stop.get('operation', {}).get('action')} {stop.get('operation', {}).get('state')}, "
                   f"perfil {stop.get('operation', {}).get('profile')}",
         "not_accredited": "nada sobre el monitor: son resultados separados",
         "rover_side": row("Infrastructure closure / monitor"), "sources": ["passive-session/stop-result.json"]},
    ]
    return {"schema": SCHEMA, "status": "OBSERVED", "accredits": False, "movement_authorized": False,
            "session_id": session, "evidence_id": summary.get("evidence_id"),
            "manifest_sha256": _sha((root / "manifest.json").read_bytes()),
            "files_verified": len(json.loads((root / "manifest.json").read_text())["files"]),
            "identity_complete": summary.get("identity_complete"), "odometry_gids": odometry_gids, "facts": facts,
            "not_contemporaneous_with": "otras sesiones (p. ej. la captura /3 del 25/10): sus GID y muestras no se combinan"}
