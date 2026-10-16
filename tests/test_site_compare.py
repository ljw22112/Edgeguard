"""Site-practice baselines in the many-to-many simulation (sim/site_compare.py) and the audit traces."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.multi_sim import PROX_WARN_M, ZONE_KMH, run_episode   # noqa: E402

SEED = 12345


def test_every_system_runs_on_the_same_episode():
    out = {s: run_episode(SEED, 8, 4, system=s) for s in ("none", "speed_zone", "proximity", "proximity_tight", "edgeguard")}
    assert len({r["conflicts"] for r in out.values()}) == 1                # same floor, same people, same trucks
    assert out["none"]["forklift_m"] >= out["speed_zone"]["forklift_m"]    # zoning only ever slows trucks
    assert out["none"]["alarms"] == out["speed_zone"]["alarms"] == 0
    assert out["proximity"]["alarms"] > out["proximity_tight"]["alarms"] > 0
    assert out["proximity"]["alarms"] > out["edgeguard"]["alarms"]


def test_speed_zone_caps_the_trucks():
    tr = []
    run_episode(SEED, 4, 2, system="speed_zone", trace=tr)
    assert max(e["v"] for e in tr if e["type"] == "fstep") <= ZONE_KMH / 3.6 + 1e-3        # trace rounds to mm/s


def test_proximity_alarm_is_distance_only():
    """Inside the warning zone the truck is limited whatever the direction (no prediction)."""
    tr = []
    run_episode(SEED, 8, 4, system="proximity", trace=tr)
    limited = [e for e in tr if e["type"] == "fstep" and e["limits"]]
    assert limited and all(min(e["limits"].values()) <= 1.4 for e in limited)
    assert PROX_WARN_M == 6.0


def test_attentive_driver_never_adds_collisions_without_a_system():
    a = run_episode(SEED, 8, 4, system="none")
    b = run_episode(SEED, 8, 4, system="none", attentive=True)
    assert b["collisions"] <= a["collisions"]


def test_trace_records_alerts_and_pairs():
    tr = []
    run_episode(SEED, 8, 4, trace=tr)
    kinds = {e["type"] for e in tr}
    assert {"send", "deliver", "pair", "fstep", "env"} <= kinds
    assert all("reason" in e for e in tr if e["type"] == "send")
