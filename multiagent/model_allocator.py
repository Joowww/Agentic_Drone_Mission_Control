"""Interface for a MODEL-generated allocation, always scored against the deterministic reference.

``ModelAllocator(adapter)`` is a callable ``allocator(problem) -> (proposal, meta)`` accepted by the Drone/Swarm
Agent. The agent checks the proposal with the same rules as the reference (multiagent.swarm.evaluate_proposal)
and uses it only if it is valid; otherwise the reference allocation is kept and the rejection is recorded.
"""
from __future__ import annotations

import json

from multiagent.interpreters import extract_json

PROMPT = """Assign aerial objectives to drones. Each objective goes to at most one drone; a drone can only take an
objective whose required sensor it carries and only if the declared wind is within its limit. Prefer covering every
objective, then the shortest longest flight. Routes start and end at each drone's takeoff point and must stay
clear of the site's exclusions. Reply with ONE JSON object only:
{"assignments": {"<drone_id>": ["<objective_id>", ...in visiting order]}}
Problem: {problem}"""


def problem_summary(problem) -> dict:
    site = problem.site
    xy = lambda pid: [site.point(pid).x_m, site.point(pid).y_m]  # noqa: E731
    return {"objectives": [{"objective_id": o.objective_id, "point": o.point_id, "xy_m": xy(o.point_id),
                            "required_sensor": o.required_sensor} for o in problem.objectives],
            "drones": [{"drone_id": d.vehicle_id, "takeoff_xy_m": xy(d.takeoff_point), "sensors": d.sensors,
                        "battery_percent": problem.battery_percent.get(d.vehicle_id, d.battery_percent),
                        "max_wind_kmh": d.max_wind_kmh, "available": d.available} for d in problem.drones],
            "wind_speed_kmh": problem.wind_speed_kmh,
            "exclusions": [{"id": z.zone_id, "polygon": z.polygon, "applies_to": z.applies_to} for z in site.exclusions]}


class ModelAllocator:
    def __init__(self, adapter):
        self.adapter = adapter

    def __call__(self, problem):
        prompt = PROMPT.replace("{problem}", json.dumps(problem_summary(problem), sort_keys=True))
        response = self.adapter.complete([{"role": "user", "content": prompt}], json_output=True)
        value = extract_json(response.text)
        return (value if isinstance(value, dict) else {"assignments": None}), {**self.adapter.info, **response.metadata()}
