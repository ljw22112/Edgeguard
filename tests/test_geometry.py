import math

import pytest

from edgeguard.geometry import (cpa, encounter, los_kinematics, miss_distance_from_los,
                                in_collision_cone, vo_speed_scale)
from edgeguard.predict import CVPredictor, CTRVPredictor, min_separation
from edgeguard.risk import RiskConfig, assess
from edgeguard.tracking import Track


def test_head_on_cpa():
    # worker 10 m ahead of forklift, forklift 2 m/s toward worker
    tc, dc = cpa((10, 0), (-2, 0))
    assert tc == pytest.approx(5.0)
    assert dc == pytest.approx(0.0)


def test_diverging_cpa_is_now():
    tc, dc = cpa((5, 0), (1, 0))
    assert tc == 0.0 and dc == pytest.approx(5.0)


def test_cbdr_means_collision():
    # crossing paths that meet at the origin at t=4: constant bearing
    e = encounter((0, -4), (0, 1), (-8, 0), (2, 0), r_safe=1.5)
    assert abs(e.los_rate) < 1e-9          # bearing does not change
    assert e.closing_speed > 0
    assert e.dcpa == pytest.approx(0.0, abs=1e-9)
    assert e.in_collision_cone


def test_los_form_equals_cpa():
    r, v = (6.0, 3.0), (-2.0, -0.4)
    R, _, _, lam_dot = los_kinematics(r, v)
    _, dc = cpa(r, v)
    assert miss_distance_from_los(R, lam_dot, math.hypot(*v)) == pytest.approx(dc)


def test_parallel_aisle_is_not_a_collision():
    # worker walking in the next aisle 2.5 m away, forklift passing: close but safe
    e = encounter((5, 2.5), (-1, 0), (0, 0), (2, 0), r_safe=1.5)
    assert e.dcpa == pytest.approx(2.5)
    assert not e.in_collision_cone


def test_cone_matches_cpa():
    for r, v in [((8, 1), (-3, 0)), ((8, 3), (-3, 0)), ((4, -1), (-1, 0.5))]:
        tc, dc = cpa(r, v)
        assert in_collision_cone(r, v, 1.5) == (dc < 1.5 and tc > 0)


def test_vo_speed_scale_slows_forklift():
    # worker crossing in front; slowing the forklift lets the worker pass
    k = vo_speed_scale((6, -3), (0, 1.2), (0, 0), (2.5, 0), r_safe=1.5)
    assert 0.0 <= k < 1.0
    # no conflict -> full speed
    assert vo_speed_scale((6, 6), (1, 0), (0, 0), (2.5, 0), 1.5) == 1.0


def test_ctrv_turn_cap():
    p = CTRVPredictor((0, 0), 2.0, 0.0, 1.0)     # left turn, capped at 90 deg
    x, y = p.positions([10.0])[0]
    assert x == pytest.approx(2.0, abs=1e-6)     # radius v/w = 2
    assert y > 10                                 # continues straight north


def test_min_separation_matches_cpa_for_cv():
    a, b = CVPredictor((0, -4), (0, 1)), CVPredictor((-8, 0.5), (2, 0))
    t, d = min_separation(a, b, horizon=8, dt=0.01)
    tc, dc = cpa((0 + 8, -4 - 0.5), (0 - 2, 1 - 0))
    assert t == pytest.approx(tc, abs=0.02) and d == pytest.approx(dc, abs=0.02)


def _track(kind, pos, vel, yaw=0.0):
    t = Track(kind + "_1", kind)
    sp, hd = math.hypot(*vel), math.atan2(vel[1], vel[0])
    t.update(0.0, pos[0], pos[1], speed=sp, heading=hd, yaw_rate=yaw)
    return t


def test_assess_levels():
    cfg = RiskConfig()
    f = _track("forklift", (0, 0), (2.5, 0))
    assert assess(_track("worker", (3, 0), (0, 0)), f, cfg).level == 3   # 1.2 s ahead
    assert assess(_track("worker", (7, 0), (0, 0)), f, cfg).level == 2
    # side aisle: at most CAUTION (dashboard only, no vibration)
    assert assess(_track("worker", (6, 2.6), (0, 0)), f, cfg).level <= 1
    w = _track("worker", (1.5, 2.4), (0, 0))       # standing next to the path
    assert assess(w, f, cfg, method="distance").level == 2               # baseline alarms
    assert assess(w, f, cfg).level <= 1                                  # guidance does not


def test_ctrv_sees_turn_into_worker():
    cfg = RiskConfig()
    f = _track("forklift", (0, 0), (2.0, 0), yaw=0.8)   # turning left
    w = _track("worker", (2.5, 4.5), (0, 0))
    assert assess(w, f, cfg, "guidance").level == 0      # straight-line model misses it
    assert assess(w, f, cfg, "guidance_ctrv").level >= 2


def test_ctrv_mid_turn_stops_at_aisle_axis():
    # 60 degrees into a left turn: only 30 degrees remain until heading north
    p = CTRVPredictor((0, 0), 2.0, math.radians(60), 1.0)
    x1, _ = p.positions([5.0])[0]
    x2, _ = p.positions([9.0])[0]
    assert x1 == pytest.approx(x2, abs=1e-6)      # moving straight north afterwards


def test_speed_command_follows_turn():
    from edgeguard.predict import speed_scale_on_path
    cfg = RiskConfig()
    f = _track("forklift", (0, 0), (2.0, 0), yaw=0.8)     # turning left toward the worker
    w = _track("worker", (2.5, 4.5), (0, 0))
    r = assess(w, f, cfg, "guidance_ctrv")
    assert r.level >= 2 and r.speed_scale < 1.0          # straight-line VO would say 1.0
    # a slow enough forklift lets the worker stay clear
    pw = CVPredictor((2.5, 4.5), (0, 0))
    pf = CTRVPredictor((0, 0), 2.0, 0.0, 0.8)
    assert speed_scale_on_path(pw, pf, 1.5, horizon=3.0) == r.speed_scale
