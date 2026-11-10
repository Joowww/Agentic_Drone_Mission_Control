"""Coordinator extras: observations arriving out of order, several cards, and the spatial error budget of the
site -> rover transform (first-order sigma vs. a deterministic sweep of perturbed transforms). Offline fixtures."""
from datetime import timedelta
import itertools
import math

from multiagent import frames2d as f
from tests.test_multiagent_coordinator import NOW, coord, g, obs, through_validated


def at(dt):
    return NOW + timedelta(seconds=dt)


def observe(c, o, dt):
    return c.handle({"type": "OBSERVATION", "source": "TEST_FIXTURE", "at": at(dt), "observation": o})


def test_an_older_report_of_the_same_card_arriving_late_never_replaces_the_newer_one():
    c = through_validated(coord())
    assert observe(c, obs("newer", dt=2), 2.5)["outcome"] == "APPLIED"
    late = observe(c, obs("older", dt=1), 3.0)
    assert late["outcome"] == "OUT_OF_ORDER_OBSERVATION" and "not newer than newer" in late["reason"]
    assert c.states()["G1"]["observation_id"] == "newer" and g(c) == "TARGET_VALIDATED"
    assert observe(c, obs("newest", dt=3.2), 3.5)["outcome"] == "APPLIED"     # a newer report still refreshes it
    assert c.states()["G1"]["observation_id"] == "newest"


def test_a_second_card_with_no_waiting_task_is_recorded_not_attached():
    c = through_validated(coord())
    observe(c, obs("red", dt=1), 1.5)
    yellow = obs("yellow", dt=1.2)
    yellow["detection"] = {**yellow["detection"], "object_class": "yellow_card", "target_id": "card_yellow_2"}
    out = observe(c, yellow, 2.0)
    assert out["outcome"] == "UNASSIGNED_TARGET" and "card_yellow_2" in out["reason"]
    assert c.states()["G1"]["observation_id"] == "red"                       # the planned target is untouched
    assert c.summary()["unassigned_targets"] == [{"target_id": "card_yellow_2", "observation_id": "yellow",
                                                  "poi": "POI_3"}]
    restored = coord()
    restored.restore(c.snapshot())
    assert restored.summary()["unassigned_targets"] == c.summary()["unassigned_targets"]


def test_the_first_order_sigma_bounds_the_error_of_perturbed_transforms():
    """Sweep the transform within +-1 sigma (translation and heading): the converted goal never moves farther than
    the propagated 1-sigma budget times sqrt(3) (corners of the box), and the composition is exact without noise."""
    s_t, s_r = 0.05, 0.01
    base = dict(parent="site", child="odom", x_m=1.0, y_m=-1.5, yaw_rad=math.pi / 2, not_before=NOW - timedelta(hours=1),
                expires=NOW + timedelta(hours=1), source="TEST_FIXTURE", source_sha256="e" * 64, accredited=True)
    nominal = f.Transform(**base, sigma_m=s_t, sigma_rad=s_r).inverse()                      # odom <- site
    goal = (8.0, 4.0)
    gx, gy = nominal.apply(*goal)
    lever = math.hypot(*goal)
    sigma = math.sqrt(s_t ** 2 + (lever * s_r) ** 2)
    worst = 0.0
    for dx, dy, dyaw in itertools.product((-1, 0, 1), repeat=3):
        t = f.Transform(**{**base, "x_m": base["x_m"] + dx * s_t / math.sqrt(2), "y_m": base["y_m"] + dy * s_t / math.sqrt(2),
                           "yaw_rad": base["yaw_rad"] + dyaw * s_r}, sigma_m=s_t, sigma_rad=s_r).inverse()
        px, py = t.apply(*goal)
        worst = max(worst, math.hypot(px - gx, py - gy))
    assert 0 < worst <= sigma * math.sqrt(3) + 1e-9
    back = f.compose(f.Transform(**base, sigma_m=0.0, sigma_rad=0.0), f.Transform(**base, sigma_m=0.0, sigma_rad=0.0).inverse())
    assert abs(back.x_m) < 1e-12 and abs(back.y_m) < 1e-12 and abs(back.yaw_rad) < 1e-12
