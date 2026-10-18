"""Deterministic local routes, not agricultural coverage or obstacle avoidance."""
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tools.simulation_mission_mapper import METERS_PER_DEGREE_LATITUDE

MAX_RADIUS_M = 1000.0
MAX_ABS_LATITUDE = 75.0
METHOD = "local_linear_111320_cos_home_v1"
RECTANGLE_FIELDS = ("length_m", "width_m", "orientation_deg", "traversal", "home_position")
SHARED_FIELDS = ("home_latitude", "home_longitude", "home_altitude_m", "altitude_reference",
                 "altitude_m", "return_to_home", "close_route")


class Offset(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    north_m: float
    east_m: float


class RelativeRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["offsets", "rectangle"] | None = None
    home_latitude: float | None = Field(None, ge=-90, le=90)
    home_longitude: float | None = Field(None, ge=-180, le=180)
    # Explicit zero: this model expresses all altitudes relative to home.
    home_altitude_m: float | None = Field(None, ge=0)
    altitude_reference: Literal["relative_to_home"] | None = None
    altitude_m: float | None = Field(None, gt=0)
    return_to_home: bool | None = None
    close_route: bool | None = None
    offsets: list[Offset] | None = Field(None, max_length=200)
    length_m: float | None = Field(None, gt=0)
    width_m: float | None = Field(None, gt=0)
    orientation_deg: float | None = Field(None, ge=0, lt=360)
    traversal: Literal["clockwise", "counterclockwise"] | None = None
    home_position: Literal["corner", "center"] | None = None


def merge_relative_route_intent(current: RelativeRouteRequest | None,
                                update: RelativeRouteRequest) -> RelativeRouteRequest:
    """Null/omitted values preserve facts; explicit mode changes discard old shape fields.

    Shared parameters survive a mode change; the offsets sequence replaces as a
    whole. Neither mode nor other decisions are inferred from supplied dimensions.
    """
    values = current.model_dump() if current else {}
    if current and update.mode is not None and update.mode != current.mode:
        obsolete = ((*RECTANGLE_FIELDS, "offsets") if current.mode is not None else
                    ("offsets",) if update.mode == "rectangle" else RECTANGLE_FIELDS)
        for key in obsolete:
            values.pop(key, None)
    values.update(update.model_dump(exclude_none=True))
    merged = RelativeRouteRequest.model_validate(values)
    generate_relative_route(merged)  # Validate known facts even while decisions remain missing.
    return merged


def _local_points(request):
    """One implementation of local geometry for partial validation and final generation."""
    start_point = None
    if request.mode == "offsets":
        points = [(p.north_m, p.east_m) for p in request.offsets]
        if math.hypot(*points[0]) < 0.001:
            raise ValueError("First offset must differ from home; the validator rejects a zero horizontal leg")
        if not any(math.hypot(*point) > 0.001 for point in points):
            raise ValueError("Degenerate route: all points are at home")
        if len(points) > 1 and math.dist(points[0], points[-1]) < 0.001:
            raise ValueError("Provide an open sequence; close_route controls the repeated first point")
    else:
        length, width = request.length_m, request.width_m
        if min(length, width) < 0.01:
            raise ValueError("Rectangle dimensions must be at least 0.01 m")
        angle = math.radians(request.orientation_deg)
        u, v = (math.cos(angle), math.sin(angle)), (-math.sin(angle), math.cos(angle))
        start = (0, 0) if request.home_position == "corner" else (-length / 2, -width / 2)
        corners = [(start[0], start[1]), (start[0] + length, start[1]),
                   (start[0] + length, start[1] + width), (start[0], start[1] + width)]
        if request.traversal == "counterclockwise":
            corners = [corners[i] for i in (0, 3, 2, 1)]
        points = [(a * u[0] + b * v[0], a * u[1] + b * v[1]) for a, b in corners]
        start_point = points[0]
        if request.home_position == "corner":
            points = points[1:]  # HOME already represents A; avoid an unflyable zero-length leg.
    if request.close_route:
        if len(points) < 2:
            raise ValueError("A closed route needs at least two distinct points")
        points.append(start_point if start_point is not None else points[0])
    if any(math.dist(a, b) < 0.001 for a, b in zip(points, points[1:])):
        raise ValueError("Consecutive points must be at least 0.001 m apart")
    if any(math.hypot(*point) > MAX_RADIUS_M for point in points):
        raise ValueError("Every point must be within 1000 m of home")
    return points


def generate_relative_route(request: RelativeRouteRequest) -> dict:
    """Validate known facts, then return all missing decisions or the ordered route.

    Rectangle heading is the length edge clockwise from north. Clockwise order
    A,B,C,D; counterclockwise A,D,C,B. At a corner HOME represents A, so the
    waypoints start at B/D. Closure ends at A, independently of return-to-home.
    """
    if (request.home_latitude is not None and abs(request.home_latitude) > MAX_ABS_LATITUDE
            or request.home_altitude_m not in (None, 0)):
        raise ValueError("Local routes require |latitude| <= 75 and home_altitude_m=0 (relative reference)")
    if any(value is not None and not 0.01 <= value <= 2 * MAX_RADIUS_M
           for value in (request.length_m, request.width_m)):
        raise ValueError("Known rectangle dimensions must be within 0.01..2000 m")
    # With unknown home placement, even the most permissive supported placement
    # must fit. This bound validates dimensions; it does not select a placement.
    scale = 1 if request.home_position == "corner" else 2
    known_radius = math.hypot(request.length_m or 0, request.width_m or 0) / scale
    if known_radius > MAX_RADIUS_M:
        raise ValueError("Known dimensions/home position exceed the 1000 m local radius")
    if request.offsets is not None and not request.offsets:
        raise ValueError("Offsets must contain at least one point")
    irrelevant = RECTANGLE_FIELDS if request.mode == "offsets" else ("offsets",) if request.mode == "rectangle" else ()
    if any(getattr(request, key) is not None for key in irrelevant):
        raise ValueError("Parameters of the other route mode are not accepted; change mode explicitly")
    shape = ("offsets",) if request.mode == "offsets" else RECTANGLE_FIELDS if request.mode == "rectangle" else ()
    missing = [key for key in ("mode", *SHARED_FIELDS, *shape) if getattr(request, key) is None]
    points = None
    if request.mode is not None and all(getattr(request, key) is not None for key in shape):
        points = _local_points(request)
    elif request.offsets:
        # Validate the typed offsets even if their mode is still a pending choice.
        # The stored/requested mode remains None and generation remains blocked.
        _local_points(request.model_copy(update={"mode": "offsets"}))
    coordinates = []
    if points is not None and request.home_latitude is not None and request.home_longitude is not None:
        scale = METERS_PER_DEGREE_LATITUDE * math.cos(math.radians(request.home_latitude))
        coordinates = [(request.home_latitude + north / METERS_PER_DEGREE_LATITUDE,
                        request.home_longitude + east / scale) for north, east in points]
        if any(abs(lat) > MAX_ABS_LATITUDE or not -180 < lon < 180 for lat, lon in coordinates):
            raise ValueError("Route crosses the supported latitude/domain or antimeridian boundary")
    if missing:
        return {"status": "INCOMPLETE", "missing_fields": missing}
    waypoints = []
    for i, (latitude, longitude) in enumerate(coordinates, 1):
        waypoints.append({"waypoint_id": f"WP{i}", "latitude": latitude, "longitude": longitude,
                          "altitude_m": request.altitude_m, "action": "navigate"})
    return {"status": "GENERATED", "missing_fields": [], "waypoints": waypoints,
            "effective_offsets": [{"north_m": n, "east_m": e} for n, e in points],
            "provenance": {"method": METHOD, "parameters": request.model_dump(mode="json", exclude_none=True),
                           "maximum_radius_m": MAX_RADIUS_M, "maximum_absolute_latitude": MAX_ABS_LATITUDE,
                           "source": "DETERMINISTIC_GENERATION", "input_authentication": "NOT_VERIFIED",
                           "altitude_reference": "relative_to_home"}}
