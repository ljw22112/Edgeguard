"""Walker models (sim/walkers.py): the straight walker reproduces every earlier result, the social-force walker
behaves like people (plausible speeds, curved but goal-directed paths, avoiding each other) and is repeatable."""
import math
import os
import random

import pytest

from sim import multi_sim as m
from sim import walkers as W

import importlib.util

pytestmark = pytest.mark.skipif(importlib.util.find_spec("pysocialforce") is None, reason="pysocialforce not installed")


def _specs(seed, n=8):
    rng = random.Random(seed)
    return [m._worker_spec(rng) for _ in range(n)]


def test_straight_walker_is_the_old_model():
    times = m._times()
    for seed in range(5):
        a = random.Random(seed)
        b = random.Random(seed)
        assert m._worker(a, times) == W.straight(m._worker_spec(b), times)


def test_social_walkers_are_repeatable_and_plausible():
    times = m._times()
    p1 = W.social(_specs(23000), times, 23000)
    p2 = W.social(_specs(23000), times, 23000)
    assert p1 == p2
    st = W.summary(sum((W.social(_specs(s), times, s) for s in range(23000, 23010)), []), times)
    assert 0.7 < st["speed_mean"] < 1.3                       # walking pace
    assert 0.15 < st["speed_cv"] < 0.45                       # speed varies
    assert 0.85 < st["straightness"] < 0.995                  # curved, but heading for the goal


def test_social_walkers_reach_their_goal_and_wait_for_their_start():
    times = m._times()
    specs = _specs(23001)
    paths = W.social(specs, times, 23001)
    for sp, p in zip(specs, paths):
        if sp["standing"]:
            assert max(math.hypot(q[0] - sp["start"][0], q[1] - sp["start"][1]) for q in p) < 0.5
            continue
        before = [q for t, q in zip(times, p) if t < sp["t0"] - 0.05]
        assert all(math.hypot(q[0] - sp["start"][0], q[1] - sp["start"][1]) < 1e-6 for q in before)
        goal = (sp["start"][0] + sp["u"][0] * sp["length"], sp["start"][1] + sp["u"][1] * sp["length"])
        if sp["t0"] + sp["length"] / max(sp["v"], 0.1) * 1.8 < times[-1]:
            assert math.hypot(p[-1][0] - goal[0], p[-1][1] - goal[1]) < 1.0


def test_social_walkers_keep_apart():
    """Two people walking straight at each other step around one another."""
    times = m._times()
    specs = [{"start": (-6.0, 0.0), "u": (1.0, 0.0), "length": 12.0, "v": 1.2, "t0": 0.0, "standing": False},
             {"start": (6.0, 0.05), "u": (-1.0, 0.0), "length": 12.0, "v": 1.2, "t0": 0.0, "standing": False}]
    W.FLUCT_SIGMA, keep = 0.0, W.FLUCT_SIGMA
    try:
        a, b = W.social(specs, times, 1)
    finally:
        W.FLUCT_SIGMA = keep
    assert min(math.hypot(p[0] - q[0], p[1] - q[1]) for p, q in zip(a, b)) > 0.4


def test_import_leaves_no_log_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    W._psf()
    assert not os.path.exists(tmp_path / "file.log")


def test_episode_runs_with_social_walkers():
    r = m.run_episode(64007, 8, 4, over={}, d2d=True, walker="social")
    assert r["conflicts"] >= 0 and r["forklift_nominal_m"] > 0
