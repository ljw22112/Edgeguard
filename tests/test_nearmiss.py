"""Near-miss analytics: one event per encounter at the closest approach; hotspots and advice."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from edgeguard.nearmiss import NearMissTracker   # noqa: E402


def _pass(tr, pair, d_min, at, speed=2.0, occluded=False, level=0, t0=0.0):
    """Distance goes 6 -> d_min -> 6 m."""
    evs = []
    seq = [6, 5, 4, 3, d_min + 0.5, d_min, d_min + 0.5, 3, 4, 5, 6]
    for i, d in enumerate(seq):
        lv = level if i < 4 else 0
        e = tr.observe(pair, d, at, t0 + i * 0.1, speed, occluded, lv)
        if e:
            evs.append(e)
    return evs


def test_one_event_at_closest_approach():
    tr = NearMissTracker()
    evs = _pass(tr, ("w1", "f1"), 1.2, (3.4, 7.8), level=2)
    assert len(evs) == 1 and evs[0]["d_min"] == 1.2 and evs[0]["alerted"] and evs[0]["x"] == 3.4
    assert _pass(tr, ("w1", "f1"), 2.5, (0, 0)) == []        # not close enough
    assert _pass(tr, ("w2", "f1"), 1.0, (0, 0), speed=0.1) == []   # forklift standing: not a near miss


def test_sweep_closes_encounters_that_disappear():
    tr = NearMissTracker()
    for i, d in enumerate([5, 3, 1.5]):
        assert tr.observe(("w", "f"), d, (1, 1), i * 0.1, 2.0) is None
    evs = tr.sweep(live_pairs=set())
    assert len(evs) == 1 and not evs[0]["alerted"]


def test_hotspot_advice():
    tr = NearMissTracker()
    for k in range(4):
        _pass(tr, (f"w{k}", "f1"), 1.0, (10.2, 5.5), occluded=True, level=2, t0=k)
    for k in range(3):
        _pass(tr, (f"x{k}", "f2"), 1.3, (2.5, 2.5), level=0, t0=k)
    hs = tr.hotspots()
    assert hs[0]["x"] == 10.0 and hs[0]["count"] == 4 and hs[0]["advice"] == "blind_corner"
    assert hs[1]["advice"] == "unalerted"
    s = tr.summary()
    assert s["total"] == 7 and s["unalerted"] == 3
