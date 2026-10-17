"""Stress scenarios of the many-to-many sim (sim/robust_eval.py)."""
from sim.multi_sim import run_episode
from sim.robust_eval import SCENARIOS, job


def test_empty_stress_is_the_normal_episode():
    assert run_episode(123, 8, 4) == run_episode(123, 8, 4, stress={})


def test_every_scenario_runs():
    for sc in SCENARIOS:
        r = job((321, sc, {}))
        assert r["forklift_nominal_m"] > 0 and r["collisions"] >= 0


def test_mec_restart_keeps_the_same_floor():
    a, b = run_episode(55, 8, 4), run_episode(55, 8, 4, stress={"mec_down_s": 2.5})
    assert a["conflicts"] == b["conflicts"] and a["forklift_nominal_m"] == b["forklift_nominal_m"]
