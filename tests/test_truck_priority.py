"""Truck priority with the stopping envelope and stop points (edgeguard/alerting.py, docs/site-compare.md)."""
import math

from edgeguard.alerting import envelope_limit
from edgeguard.risk import RiskConfig


class T:
    def __init__(self, x, y, vx=0.0, vy=0.0, heading=0.0):
        self.x, self.y, self.vel, self.heading = x, y, (vx, vy), heading
        self.pos = (x, y)
        self.speed = math.hypot(vx, vy)


CFG = RiskConfig(env_v2=True, env_lateral=3.0, env_pass_floor=2.0, env_margin=0.3)


def test_person_in_path_gives_stop_point_short_of_him():
    stop = []
    lim = envelope_limit(T(4.0, 0.4), T(0.0, 0.0, 3.0), CFG, out_stop=stop)
    assert lim is not None and lim < 3.0
    sx, sy = stop[0]
    assert sy == 0.0 and 4.0 - sx >= math.sqrt(CFG.r_safe ** 2 - 0.4 ** 2) + 0.29


def test_standing_truck_does_not_start_into_a_person_ahead():
    assert envelope_limit(T(2.0, 0.0), T(0.0, 0.0, 0.0, 0.0, heading=0.0), CFG) < 0.5


def test_person_beside_path_who_could_step_in_caps_at_pass_floor():
    lim = envelope_limit(T(3.0, 2.2), T(0.0, 0.0, 3.0), CFG)
    assert lim == CFG.env_pass_floor


def test_held_worker_beside_path_does_not_slow_the_truck():
    assert envelope_limit(T(4.0, 2.2), T(0.0, 0.0, 3.0), CFG, held=True) is None


def test_far_or_behind_is_ignored():
    assert envelope_limit(T(-3.0, 0.0), T(0.0, 0.0, 3.0), CFG) is None
    assert envelope_limit(T(5.0, 3.5), T(0.0, 0.0, 3.0), CFG) is None
