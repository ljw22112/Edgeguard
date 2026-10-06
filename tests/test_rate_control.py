from types import SimpleNamespace as NS

from edgeguard.rate_control import RateController


def tr(i, kind, x, y, vx=0.0, vy=0.0, seen=0.0):
    return NS(id=i, kind=kind, x=[x, y], pos=(x, y), vel=(vx, vy), last_seen=seen)


def test_far_goes_slow_after_hold_and_near_is_immediate():
    rc = RateController(near_m=10, horizon_s=0, reach_s=5, hold_s=3)
    w = tr("w1", "worker", 0, 0)
    f = tr("f1", "forklift", 60, 0)
    assert rc.update([w, f], 0.0) == {"w1": 10.0, "f1": 10.0}       # start fast
    assert rc.update([w, f], 1.0) == {}                              # far, but still holding
    w.last_seen = f.last_seen = 3.5
    assert rc.update([w, f], 3.5) == {"w1": 2.0, "f1": 2.0}
    # forklift drives towards the worker at 3 m/s: (20 - 10) m / 3 m/s < 5 s -> fast at once
    f2 = tr("f1", "forklift", 20, 0, vx=-3.0, seen=4.0)
    w.last_seen = 4.0
    assert rc.update([w, f2], 4.0) == {"w1": 10.0, "f1": 10.0}
    assert rc.counts() == {"fast": 2, "slow": 0}


def test_hysteresis_and_stale_tracks():
    rc = RateController(near_m=10, horizon_s=0, slack=0, reach_s=0, hold_s=0)
    w, f = tr("w1", "worker", 0, 0), tr("f1", "forklift", 9, 0)
    rc.update([w, f], 0.0)
    assert rc.rate == {"w1": 10.0, "f1": 10.0}
    f.pos = (11, 0)
    rc.update([w, f], 0.0)
    assert rc.rate == {"w1": 10.0, "f1": 10.0}                       # 11 m < 1.2 x 10 m while fast
    f.pos = (13, 0)
    rc.update([w, f], 0.0)
    assert rc.rate == {"w1": 2.0, "f1": 2.0}
    f.pos = (11, 0)
    rc.update([w, f], 0.0)
    assert rc.rate["w1"] == 2.0                                      # 11 m > 10 m while slow
    gone = tr("f1", "forklift", 1, 0, seen=-10.0)                    # stale: ignored
    assert rc.update([w, gone], 0.0) == {}


def test_parallel_traffic_far_away_stays_slow():
    rc = RateController(hold_s=0)
    w = tr("w1", "worker", 0, 0, vx=1.0)
    f = tr("f1", "forklift", 0, 20, vx=2.5)                          # same direction, 20 m apart
    rc.update([w, f], 0.0)
    assert rc.rate == {"w1": 2.0, "f1": 2.0}
    f.vel = (0.0, -2.5)                                # turns towards the worker: 4.8 s to reach
    assert rc.update([w, f], 0.0) == {"w1": 10.0, "f1": 10.0}
