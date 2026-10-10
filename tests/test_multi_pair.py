"""Many-to-many bookkeeping and standoffs (v1.2): per-pair forklift plans, creeping limits,
who goes first after a standoff, STEP ASIDE."""
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.alerting import AlertState, decide, _aside_vector   # noqa: E402
from edgeguard.device_policy import ForkliftLimit                   # noqa: E402
from edgeguard.risk import RiskConfig, assess, go_safe, _limit      # noqa: E402
from edgeguard.tracking import Track                                # noqa: E402
from edgeguard.worker_cue import WaitCue                            # noqa: E402


def trk(oid, kind, x, y, vx=0.0, vy=0.0, t0=0.0, n=8, speed=None, heading=0.0):
    tr = Track(oid, kind)
    for k in range(n):
        t = t0 + k * 0.1
        kw = {} if speed is None else {"speed": speed, "heading": heading, "yaw_rate": 0.0}
        tr.update(t, x=x + vx * k * 0.1, y=y + vy * k * 0.1, **kw)
    return tr


def test_clear_for_one_worker_keeps_the_other_workers_limit():
    fl = ForkliftLimit("failsafe")
    fl.on_alert(0.0, "raise", 0.5, src="w1")
    fl.on_alert(0.1, "raise", 1.2, src="w2")
    assert fl.effective(0.2) == 0.5
    fl.on_alert(0.3, "clear", None, src="w1")
    assert fl.effective(0.4) == 1.2              # w2 still needs its plan
    fl.on_alert(0.5, "clear", None, src="w2")
    assert fl.effective(0.6) is None


@pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler")
def test_cpp_forklift_keeps_one_plan_per_worker(tmp_path):
    src = tmp_path / "t.cpp"
    src.write_text(r'''
#include <cstdio>
#include "device_policy.h"
int main() {
  policy::ForkliftLimit fl;
  fl.onAlert(0.0f, false, 0.5f, "w1");
  fl.onAlert(0.1f, false, 1.2f, "w2");
  std::printf("%.2f ", fl.effective(0.2f));
  fl.onAlert(0.3f, true, 0.0f, "w1");
  std::printf("%.2f ", fl.effective(0.4f));
  fl.onAlert(0.5f, true, 0.0f, "w2");
  std::printf("%.2f\n", fl.effective(0.6f));
}
''')
    exe = tmp_path / "t"
    subprocess.run(["g++", "-std=c++17", "-Wall", "-I", os.path.join(ROOT, "firmware", "common"), str(src), "-o", str(exe)],
                   check=True)
    assert subprocess.run([str(exe)], capture_output=True, text=True).stdout.split() == ["0.50", "1.20", "-1.00"]


def test_creeping_limit_becomes_a_stop():
    cfg = RiskConfig(min_move=0.3)
    assert _limit(0.05, 2.0, cfg) == 0.0 and _limit(0.5, 2.0, cfg) == 1.0


def test_go_check_counts_a_truck_that_is_still_speeding_up():
    cfg = RiskConfig()
    # worker 3 m short of the lane, walking across at 1.2 m/s; truck 6 m before the crossing
    w = trk("w", "worker", 0.0, -3.0, n=8)
    f = trk("f", "forklift", -6.0, 0.0, n=8, speed=0.6)
    # at its current crawl the truck arrives long after him; but it was going 2.5 m/s and will
    # speed up again once let go - somewhere in between it meets him
    assert not go_safe(w.pos, (0.0, 1.2), f, cfg, 2.5)


def test_standoff_truck_first_when_its_way_is_clear():
    cfg = RiskConfig(wait_keepalive=True, go_check=True, aside_cue=True)
    st = AlertState()
    st.level, st.intent, st.f_speed, st.last_any, st.last_sent = 2, (0.0, 1.2), 2.0, 0.0, 0.0
    w = trk("w", "worker", 0.0, -2.6)              # waiting off the lane, wants to cross
    f = trk("f", "forklift", -5.0, 0.0, speed=0.0)  # stopped for him
    r = assess(w, f, cfg)
    decide(st, r, w, f, cfg, 0.5)
    assert r.hold and r.speed_limit == cfg.pass_speed and "still to pass" in r.reason


def test_standoff_worker_in_the_way_steps_aside_and_truck_waits():
    cfg = RiskConfig(wait_keepalive=True, go_check=True, aside_cue=True)
    st = AlertState()
    st.level, st.intent, st.f_speed, st.last_any, st.last_sent = 2, (0.0, 1.2), 2.0, 0.0, 0.0
    w = trk("w", "worker", 0.0, -0.5)              # standing in the truck's lane
    f = trk("f", "forklift", -5.0, 0.0, speed=0.0)
    r = assess(w, f, cfg)
    ev, acts = decide(st, r, w, f, cfg, 0.5)
    assert ev == "aside" and set(acts) == {"w"}
    dx, dy = acts["w"]["aside"]
    assert abs(dx) < 0.05 and dy < -1.0           # to the near (south) edge: |y| = r_safe + 0.8
    r = assess(w, f, cfg)
    decide(st, r, w, f, cfg, 0.6)
    assert r.speed_limit == 0.0                    # truck holds while he steps aside
    assert _aside_vector((0.0, -3.0), f, 2.0, cfg) is None   # already off its path


def test_worker_cue_aside_starts_a_wait():
    c = WaitCue()
    c.on_alert(0.0, "aside", src="f1")
    assert c.led(0.5) and c.motor(0.5)            # long burst, then WAIT at the edge
    c.on_alert(1.0, "clear", src="f1")
    assert not c.led(1.05)


def test_route_predictor_follows_the_turn():
    from edgeguard.predict import RoutePredictor
    route = [(2.0, 0.0), (4.0, 0.0), (4.0, 2.0), (4.0, 6.0)]        # straight 4 m, then left
    p = RoutePredictor((0.0, 0.0), 2.0, route)
    pts = p.positions([0.0, 1.0, 3.0])
    assert pts[0] == (0.0, 0.0) and abs(pts[1][0] - 2.0) < 1e-6 and abs(pts[2][0] - 4.0) < 1e-6 and abs(pts[2][1] - 2.0) < 1e-6
    p2 = RoutePredictor((2.5, 0.0), 1.0, route)                      # waypoint (2, 0) already passed
    assert abs(p2.positions([1.0])[0][0] - 3.5) < 1e-6


def test_turning_away_route_does_not_alarm_the_worker_ahead():
    cfg = RiskConfig()
    w = trk("w", "worker", 7.0, 0.0)                                 # standing straight ahead
    f = trk("f", "forklift", 0.0, 0.0, speed=2.0)
    assert assess(w, f, cfg).level >= 2                              # CTRV: straight on, into him
    f.route = [(2.0, 0.0), (3.0, 0.0), (3.0, 3.0), (3.0, 8.0)]       # but it turns left at x = 3
    assert assess(w, f, cfg).level < 2


def test_standing_picker_noise_is_not_walking():
    cfg = RiskConfig(still_speed=0.4)
    w = trk("w", "worker", 6.0, -2.2, vx=0.0, vy=0.3)                 # 0.3 m/s of tracker noise toward the lane
    f = trk("f", "forklift", 0.0, 0.0, speed=2.0)
    assert assess(w, f, cfg).level < 2
    assert assess(w, f, RiskConfig()).level >= 1                     # without the gate he "walks" in
