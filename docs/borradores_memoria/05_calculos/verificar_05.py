"""Cálculos auxiliares del borrador 05_fundamentos_matematicos.md.

NO es evidencia operacional: recalcula ejemplos y repite decisiones a partir de evidencias selladas,
que solo se leen. No ejecuta simulación, ROS ni inferencias, y no escribe fuera de su salida estándar.

Las secciones 4 y 5 reflejan el validador vigente al ejecutarse. La salida anterior a la corrección del
redondeo (31/10/2026, posterior a H2) se conserva en salida_verificar_05_antes_correccion.txt.

Uso, desde la raíz del repositorio:
    python3 -B docs/borradores_memoria/05_calculos/verificar_05.py > docs/borradores_memoria/05_calculos/salida_verificar_05.txt
"""
import contextlib
import io
import json
import math
import struct
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from models.mission_definition import MissionDefinition  # noqa: E402
from planning.site_geometry import local_to_geo  # noqa: E402
from tools.hermes_mission_validation import validate_mission  # noqa: E402
from tools.ros2_flight_control import _extract_float  # noqa: E402
from tools.route_geometry import analyze_waypoint_route, haversine_distance_km  # noqa: E402
from tools.simulation_mission_executor import (  # noqa: E402
    ALTITUDE_TOLERANCE_M, HORIZONTAL_TOLERANCE_M, _horizontal_distance_metres,
)
from tools.simulation_mission_mapper import map_mission_route_to_simulation  # noqa: E402

H2 = ROOT / "simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24"
CHILDREN = ("child_1_2f7db1f6", "child_2_febf7c4f")
M_PER_DEG = 111_320.0  # constante del proyecto (tools/simulation_mission_mapper.py)


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def ulp32(x: float) -> float:
    return 2.0 ** (math.frexp(abs(x))[1] - 24)


def section(title):
    print(f"\n== {title}")


# ---------------------------------------------------------------------------
section("1. Cadena de posición de H2: texto archivado -> parser -> error -> decisión")
for child in CHILDREN:
    report = json.loads((H2 / child / "report.json").read_text())
    mission = MissionDefinition.model_validate(json.loads((H2 / child / "mission.json").read_text()))
    diag = report["executor_result"]["operation_diagnostics"]
    ops = diag["initial"] + diag["recent"]
    print(f"{child}: operaciones={diag['total_operations']} omitidas={diag['omitted_operations']}")
    reads = [o for o in ops if o["operation"] == "read_position"]
    parsed_all, f32_all, matches = 0, 0, 0
    for o in reads:
        text = o["transport"]["output"]
        values = [_extract_float(k, text) for k in ("latitude", "longitude", "altitude")]
        parsed_all += 1
        f32_all += all(f32(v) == v for v in values)
        obs = o["observation"]
        matches += values == [obs["latitude"], obs["longitude"], obs["altitude_amsl_m"]]
    print(f"  lecturas de posición={parsed_all}; reparseadas == observación registrada: {matches}; "
          f"todos los valores exactamente float32: {f32_all}")
    launch = reads[0]["observation"]
    targets = {w["waypoint_id"]: w for w in map_mission_route_to_simulation(
        mission, simulation_home_latitude=launch["latitude"], simulation_home_longitude=launch["longitude"])}
    last_alt = mission.route.waypoints[-1].altitude_m
    targets["SIMULATION_HOME"] = {"waypoint_id": "SIMULATION_HOME", "latitude": launch["latitude"],
                                  "longitude": launch["longitude"], "altitude_m": last_alt}
    recorded = {e["waypoint_id"]: e for e in report["executor_result"]["events"]
                if e["event"] in ("WAYPOINT_REACHED", "RETURN_HOME_REACHED")}
    for o in reads:
        stage = o["stage"]
        if not stage.startswith("WAYPOINT_WAIT:"):
            continue
        wp = stage.split(":", 1)[1]
        t = targets[wp]
        text = o["transport"]["output"]
        lat, lon, alt = (_extract_float(k, text) for k in ("latitude", "longitude", "altitude"))
        eh = _horizontal_distance_metres(lat, lon, float(t["latitude"]), float(t["longitude"]))
        ev = abs(alt - (launch["altitude_amsl_m"] + float(t["altitude_m"])))
        ok = eh <= HORIZONTAL_TOLERANCE_M and ev <= ALTITUDE_TOLERANCE_M
        rec = recorded.get(wp)
        same = rec is not None and ok and rec["horizontal_error_m"] == eh and rec["altitude_error_m"] == ev
        print(f"  {wp:16s} lectura {o['started_at_utc'][11:23]}-{o['finished_at_utc'][11:23]} "
              f"e_h={eh:8.4f} m e_v={ev:6.3f} m llegada={ok}" + ("  == valor registrado" if same else ""))

# ---------------------------------------------------------------------------
section("2. Paso de representación float32 en la posición de H2")
lat0, lon0 = -35.36326217651367, 149.1652069091797
cos0 = math.cos(math.radians(lat0))
step_lat_deg, step_lon_deg = ulp32(lat0), ulp32(lon0)
step_n, step_e = step_lat_deg * M_PER_DEG, step_lon_deg * M_PER_DEG * cos0
print(f"paso latitud  = 2^{int(math.log2(step_lat_deg))} grados = {step_lat_deg:.6e} deg = {step_n:.4f} m (111 320 m/deg)")
print(f"paso longitud = 2^{int(math.log2(step_lon_deg))} grados = {step_lon_deg:.6e} deg = {step_e:.4f} m (111 320 m/deg * cos lat)")
print(f"con 111 318,845 m/deg (ArduPilot): {step_lat_deg * 111318.84502145034:.4f} m / "
      f"{step_lon_deg * 111318.84502145034 * cos0:.4f} m")
print(f"semipasos: {step_n / 2:.4f} m N, {step_e / 2:.4f} m E; semidiagonal = {math.hypot(step_n, step_e) / 2:.4f} m")

# ---------------------------------------------------------------------------
section("3. Emulación de la conversión observada en el binario: double(f32(f32(int) * f32(1e-7)))")
c = f32(1e-7)
print(f"f32(1e-7) = {c!r}; sesgo relativo = {(c - 1e-7) / 1e-7:.4e}")
for name, center, scale in (("lat", round(lat0 * 1e7), M_PER_DEG), ("lon", round(lon0 * 1e7), M_PER_DEG * cos0)):
    worst = worst_unbiased = 0.0
    hits = set()
    for i in range(center - 262_144, center + 262_145):
        out = f32(f32(float(i)) * c)
        hits.add(out)
        worst = max(worst, abs(out - i * 1e-7))
        worst_unbiased = max(worst_unbiased, abs(out - i * c))
    print(f"{name}: enteros ±262144 alrededor de {center}: valores distintos={len(hits)}; "
          f"máx |salida - int*1e-7| = {worst:.3e} deg = {worst * scale:.4f} m; "
          f"sin el sesgo de la constante = {worst_unbiased:.3e} deg = {worst_unbiased * scale:.4f} m")
for v in (lat0, lon0, -35.36326217651367, 149.1652374267578):
    reach = [i for i in range(round(v * 1e7) - 200, round(v * 1e7) + 201) if f32(f32(float(i)) * c) == v]
    print(f"valor archivado {v!r}: lo producen {len(reach)} enteros de 1e-7 deg (p. ej. {reach[:1]})")

# ---------------------------------------------------------------------------
section("4. Duración prevista de H2 por el validador vigente (sin viento)")
for child in CHILDREN:
    mission = MissionDefinition.model_validate(json.loads((H2 / child / "mission.json").read_text()))
    home = mission.route.home
    pts = [("HOME", home)] + [(w.waypoint_id, w) for w in mission.route.waypoints] + [("HOME", home)]
    route = quiet(analyze_waypoint_route, mission.route)
    print(f"{child} {mission.mission_id}: cruise_speed_kmh={mission.vehicle.cruise_speed_kmh}; "
          f"speed_kmh={[w.speed_kmh for w in mission.route.waypoints]}; viento={mission.environment.wind_speed_kmh} km/h")
    raw_total = rounded_total_min = 0.0
    for (a_id, a), (b_id, b), leg in zip(pts, pts[1:], route["legs"]):
        d_raw = 1000 * haversine_distance_km(a.latitude, a.longitude, b.latitude, b.longitude)
        v = leg["speed_kmh"] if leg["speed_kmh"] is not None else mission.vehicle.cruise_speed_kmh
        t_raw = d_raw / 1000 / v * 3600
        t_pub = round(leg["distance_km"] / v * 60, 2)
        raw_total += t_raw
        rounded_total_min += t_pub
        print(f"  {a_id}->{b_id}: d={d_raw:.4f} m (redondeada {leg['distance_km']} km) v={v} km/h "
              f"t sin redondeo={t_raw:.3f} s; t del validador={t_pub} min")
    safety = quiet(validate_mission, mission)
    from safety.mission_safety_analysis import evaluate_mission_safety  # noqa: E402
    evaluation = quiet(evaluate_mission_safety, mission)
    flight, battery = evaluation["flight_analysis"], evaluation["battery_result"]
    print(f"  total sin redondeos = {raw_total:.3f} s; emulación previa (suma de tiempos redondeados por tramo) = "
          f"{rounded_total_min} min = {rounded_total_min * 60:.1f} s")
    print(f"  validador actual: total mostrado = {flight['total_flight_time_minutes']} min; total exacto = "
          f"{flight.get('total_flight_time_minutes_exact')} min = "
          f"{(flight.get('total_flight_time_minutes_exact') or 0) * 60:.3f} s; batería requerida mostrada = "
          f"{battery['required_battery_percent']} pp (exacta = "
          f"{(flight.get('total_flight_time_minutes_exact') or 0) * mission.vehicle.battery_consumption_percent_per_minute:.5f} pp); "
          f"mission_status={safety['mission_status']}")

# ---------------------------------------------------------------------------
section("5. Tramos cortos y vertical por tools.hermes_mission_validation.validate_mission")
base = json.loads((H2 / CHILDREN[0] / "mission.json").read_text())
home = base["route"]["home"]
for label, dn in (("0,4 m al norte", 0.4), ("0,6 m al norte", 0.6), ("vertical (misma lat/lon)", 0.0),
                  ("0,49 m", 0.49), ("0,51 m", 0.51)):
    data = json.loads(json.dumps(base))
    data["route"]["waypoints"][0].update(latitude=home["latitude"] + dn / M_PER_DEG, longitude=home["longitude"])
    mission = MissionDefinition.model_validate(data)
    result = validate_mission(mission)
    from safety.mission_safety_analysis import evaluate_mission_safety  # noqa: E402,F811
    leg = quiet(evaluate_mission_safety, mission)["flight_analysis"]["leg_results"][0]
    print(f"{label}: d={leg['distance_km']} km -> {leg['flight_result'].get('status')} "
          f"({leg['flight_result'].get('message', '')}); mission_status={result['mission_status']}; "
          f"execution_status={result['execution_status']}; failure_reasons={result['failure_reasons']}; "
          f"errors={result['errors']}; replan_status={result['replan_status']!r}; replan_actions={result['replan_actions']}")

# ---------------------------------------------------------------------------
section("6. Cambio de base: orientación geográfica y posición del despegue según beta")
origin = (-35.363262, 149.165237)
for beta in (0.0, 30.0):
    takeoff = local_to_geo(-6, -6, origin_latitude=origin[0], origin_longitude=origin[1], y_axis_bearing_deg=beta)
    print(f"beta={beta}: TAKEOFF_A local (-6,-6) -> {takeoff[0]:.9f}, {takeoff[1]:.9f}")
t0 = local_to_geo(-6, -6, origin_latitude=origin[0], origin_longitude=origin[1], y_axis_bearing_deg=0.0)
t30 = local_to_geo(-6, -6, origin_latitude=origin[0], origin_longitude=origin[1], y_axis_bearing_deg=30.0)
print(f"desplazamiento geográfico del despegue entre beta=0 y beta=30: "
      f"{1000 * haversine_distance_km(*t0, *t30):.3f} m (cuerda teórica 2*|r|*sin(15 deg) = "
      f"{2 * math.hypot(6, 6) * math.sin(math.radians(15)):.3f} m)")
