"""Planar frame chain site -> rover map/odom -> base_link: closed-form checks and every refusal. No vehicle."""
from datetime import datetime, timedelta, timezone
import math

import pytest

from multiagent import frames2d as f, rover_sitl_interfaces as si

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
SHA = "a" * 64


def T(parent, child, x, y, yaw, *, sm=0.02, sr=0.001, accredited=True, valid=True, **kw):
    start, end = (NOW - timedelta(hours=1), NOW + timedelta(hours=1)) if valid else (NOW - timedelta(hours=2), NOW - timedelta(hours=1))
    return f.Transform(parent, child, x, y, yaw, sm, sr, start, end, "TEST_FIXTURE_SURVEY", SHA, accredited, **kw)


SITE_ODOM = T("site", "odom", 1.0, -1.5, math.pi / 2)      # odom origin at site (1,-1.5), axes rotated +90 deg
GOAL = {"frame": "site", "x_m": 8.0, "y_m": 4.0, "sigma_m": 0.12}
AREA = [(-10.0, -10.0), (30.0, -10.0), (30.0, 30.0), (-10.0, 30.0)]
LOC = {"frame": "odom", "x_m": 5.5, "y_m": -5.0, "yaw_rad": math.pi / 2, "sigma_m": 0.05, "validated": True,
       "source": "TEST_FIXTURE_LOCALIZATION", "source_sha256": "b" * 64, "observed_at": NOW - timedelta(seconds=0.2)}
LIMITS = {"max_total_sigma_m": 0.5, "localization_max_age_s": 1.0, "max_distance_m": 5.0}


def close(a, b, tol=1e-9):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_closed_form_site_to_odom_and_back():
    odom_from_site = SITE_ODOM.inverse()
    assert close(odom_from_site.apply(8.0, 4.0), (5.5, -7.0))        # R(-90)((8,4)-(1,-1.5)) = R(-90)(7,5.5)
    assert close(SITE_ODOM.apply(5.5, -7.0), (8.0, 4.0))
    ident = f.compose(SITE_ODOM, odom_from_site)
    assert close((ident.x_m, ident.y_m, ident.yaw_rad), (0.0, 0.0, 0.0), 1e-12)


def test_composition_order_and_uncertainty():
    odom_base = T("odom", "base_link", 2.0, 0.0, math.pi / 2, sm=0.03, sr=0.002)
    site_base = f.compose(SITE_ODOM, odom_base)
    assert close(site_base.apply(1.0, 0.0), SITE_ODOM.apply(*odom_base.apply(1.0, 0.0)))
    assert math.isclose(site_base.yaw_rad, math.pi) or math.isclose(site_base.yaw_rad, -math.pi)
    lever = 2.0
    assert math.isclose(site_base.sigma_m, math.sqrt(0.02 ** 2 + 0.03 ** 2 + (lever * 0.001) ** 2))
    with pytest.raises(ValueError, match="FRAME_MISMATCH"):
        f.compose(odom_base, SITE_ODOM)


def test_the_matrix_form_is_rover_v2_and_passes_its_rules():
    d = SITE_ODOM.to_rover_matrix()
    assert (d["source_frame"], d["target_frame"]) == ("odom", "site")
    assert si.transform_problems(d, source_frame="odom", target_frame="site", now=NOW) == []


def test_the_graph_resolves_chains_and_refuses_unknown_and_inconsistent_loops():
    g = f.FrameGraph([SITE_ODOM, T("odom", "map", 0.0, 0.0, 0.0)])
    t = g.resolve("map", "site", now=NOW)
    assert close(t.apply(8.0, 4.0), (5.5, -7.0))
    with pytest.raises(ValueError, match="UNKNOWN_FRAME"):
        g.resolve("camera_optical", "site", now=NOW)
    with pytest.raises(ValueError, match="SAME_FRAME"):
        g.resolve("site", "site", now=NOW)
    good_loop = f.FrameGraph([SITE_ODOM, T("odom", "map", 0.0, 0.0, 0.0), T("site", "map", 1.0, -1.5, math.pi / 2)])
    assert close(good_loop.resolve("map", "site", now=NOW).apply(8.0, 4.0), (5.5, -7.0))
    bad_loop = f.FrameGraph([SITE_ODOM, T("odom", "map", 0.0, 0.0, 0.0), T("site", "map", 1.3, -1.5, math.pi / 2)])
    with pytest.raises(ValueError, match="CIRCULAR_INCONSISTENT"):
        bad_loop.resolve("map", "site", now=NOW)


@pytest.mark.parametrize("bad, reason", [
    (T("site", "odom", 1.0, -1.5, math.pi / 2, valid=False), "EXPIRED_OR_NOT_YET_VALID"),
    (T("odom", "site", 1.0, -1.5, math.pi / 2, sm=-0.1), "UNCERTAINTY_INVALID"),  # traversed through its inverse
    (T("site", "odom", 1.0, -1.5, math.pi / 2, accredited=False), "NOT_ACCREDITED"),
    (T("site", "odom", float("nan"), -1.5, 0.0), "POSE_NOT_FINITE"),
    (T("site", "odom", 1.0, -1.5, 0.0, unit_length="mm"), "UNITS_INVALID"),
    (T("site", "odom", 1.0, -1.5, 0.0, sm=-1.0), "UNCERTAINTY_INVALID"),
])
def test_an_unusable_transform_is_refused(bad, reason):
    with pytest.raises(ValueError, match=reason):
        f.FrameGraph([bad]).resolve("odom", "site", now=NOW)


def test_goal_for_rover_ok_with_base_link_closed_form():
    out = f.goal_for_rover(GOAL, f.FrameGraph([SITE_ODOM]), rover_frame="odom", localization=LOC, limits=LIMITS,
                           now=NOW, authorized_area=AREA)
    assert out["status"] == "OK", out["reasons"]
    assert close((out["goal_rover"]["x_m"], out["goal_rover"]["y_m"]), (5.5, -7.0))
    # rover at (5.5,-5) facing +y of odom (yaw 90): the goal is 2 m straight behind it
    assert close((out["goal_base_link"]["x_m"], out["goal_base_link"]["y_m"]), (-2.0, 0.0))
    assert out["goal_rover"]["sigma_m"] > GOAL["sigma_m"]


@pytest.mark.parametrize("kw, reason", [
    (dict(graph=f.FrameGraph([])), "UNKNOWN_FRAME"),
    (dict(graph=f.FrameGraph([T("site", "odom", 1.0, -1.5, math.pi / 2, valid=False)])), "CHAIN_NOT_USABLE"),
    (dict(localization=None), "ROVER_LOCALIZATION_NOT_ACCREDITED"),
    (dict(localization={**LOC, "validated": False}), "ROVER_LOCALIZATION_NOT_ACCREDITED"),
    (dict(localization={**LOC, "frame": "map"}), "ROVER_LOCALIZATION_FRAME_MISMATCH"),
    (dict(localization={**LOC, "observed_at": NOW - timedelta(seconds=5)}), "ROVER_LOCALIZATION_STALE"),
    (dict(localization={**LOC, "x_m": float("inf")}), "ROVER_POSE_NOT_FINITE"),
    (dict(localization={**LOC, "source_sha256": None}), "ROVER_LOCALIZATION_PROVENANCE_MISSING"),
    (dict(goal={**GOAL, "sigma_m": 0.6}), "UNCERTAINTY_TOO_HIGH"),
    (dict(goal={**GOAL, "x_m": 50.0}), "GOAL_OUTSIDE_AUTHORIZED_AREA"),
    (dict(goal={**GOAL, "y_m": float("nan")}), "GOAL_INVALID"),
    (dict(authorized_area=None), "AUTHORIZED_AREA_UNKNOWN"),
    (dict(limits={**LIMITS, "max_distance_m": 1.0}), "GOAL_BEYOND_MAX_DISTANCE"),
    (dict(limits={"localization_max_age_s": 1.0, "max_distance_m": 5.0}), "UNCERTAINTY_LIMIT_UNKNOWN"),
])
def test_goal_for_rover_refusals(kw, reason):
    args = dict(goal=GOAL, graph=f.FrameGraph([SITE_ODOM]), localization=LOC, limits=LIMITS, authorized_area=AREA)
    args.update(kw)
    out = f.goal_for_rover(args.pop("goal"), args.pop("graph"), rover_frame="odom", now=NOW, **args)
    assert out["status"] == "REFUSED" and any(r.startswith(reason) for r in out["reasons"]), out["reasons"]


def test_an_unknown_frame_is_never_replaced_by_zero():
    out = f.goal_for_rover({**GOAL, "frame": "camera_optical"}, f.FrameGraph([SITE_ODOM]), rover_frame="odom",
                           localization=LOC, limits=LIMITS, now=NOW, authorized_area=AREA)
    assert out["status"] == "REFUSED" and out["goal_rover"] is None


def test_performance_of_a_thousand_conversions():
    import time
    g = f.FrameGraph([SITE_ODOM, T("odom", "map", 0.5, 0.0, 0.1)])
    t0 = time.perf_counter()
    for i in range(1000):
        g.resolve("map", "site", now=NOW).apply(float(i % 20), 4.0)
    assert time.perf_counter() - t0 < 2.0
