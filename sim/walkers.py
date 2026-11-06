"""Walker models for sim/multi_sim.py.

"straight" (the default of every result so far): each worker walks a straight line from start to goal at one
constant speed and ignores everyone else.

"social" (Helbing and Molnar's social force model, through PySocialForce, MIT, github.com/yuxiang-gao/PySocialForce):
the same people with the same starts, goals and start times, but they
  * steer toward a waypoint offset sideways from the straight line, then the goal (people do not walk rulers),
  * relax toward their own desired speed (tau = 0.5 s) and avoid each other (Moussaid et al. social force),
  * fluctuate: a random force each step (Helbing's fluctuation term), so heading and speed wander,
  * hesitate: now and then slow to a near stop for a moment and walk on (looking at a pick list, a phone).
Nobody avoids forklifts in either model ("nobody looks out"); stopping for a WAIT or a buzz is applied on top by
the simulator as before.  The positions are computed for the whole episode first and become the worker's path.
"""
from __future__ import annotations

import logging
import math
import os
import random

SF_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "socialforce.toml")
FLUCT_SIGMA = 0.6          # m/s per sqrt(s): random force (Helbing's fluctuation term)
WAYPOINT_SIDE = (0.3, 1.2)  # sideways offset of the mid-route waypoint, m
HESITATE_RATE = 0.06       # hesitations per second of walking
HESITATE_S = (0.6, 2.0)    # how long a hesitation lasts


def _psf():
    """Import PySocialForce without its side effects (a DEBUG console logger and a file.log in the cwd)."""
    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib.pyplot  # noqa: F401  - imported first, so its import-time debug lines are not printed

    class _NoFile(logging.NullHandler):
        def __init__(self, *a, **k):
            super().__init__()

    root = logging.getLogger()                   # pysocialforce configures logging.getLogger("root"), i.e. the root logger
    level, handlers = root.level, list(root.handlers)
    real_file = logging.FileHandler
    logging.FileHandler = _NoFile
    try:
        import pysocialforce as psf
    finally:
        logging.FileHandler = real_file
        root.handlers[:] = handlers
        root.setLevel(level)
    return psf


def straight(spec, times):
    out = []
    for t in times:
        s = min(spec["length"], spec["v"] * max(0.0, t - spec["t0"]))
        out.append((spec["start"][0] + spec["u"][0] * s, spec["start"][1] + spec["u"][1] * s))
    return out


def social(specs, times, seed):
    """specs: one dict per worker (start, u, length, v, t0, standing) -> list of position lists."""
    import numpy as np
    psf = _psf()
    rng = random.Random(seed ^ 0x50C1A1)
    dt = times[1] - times[0]
    n = len(specs)
    goal, wp, active_from = [], [], []
    state = np.zeros((n, 6))
    for i, s in enumerate(specs):
        sx, sy = s["start"]
        if s.get("standing") or s["length"] <= 0:
            gx, gy = sx, sy
            wp.append(None)
        else:
            gx, gy = sx + s["u"][0] * s["length"], sy + s["u"][1] * s["length"]
            side = rng.choice((-1, 1)) * rng.uniform(*WAYPOINT_SIDE)
            f = rng.uniform(0.35, 0.65)
            wp.append((sx + s["u"][0] * s["length"] * f - s["u"][1] * side, sy + s["u"][1] * s["length"] * f + s["u"][0] * side))
        goal.append((gx, gy))
        first = wp[-1] or (gx, gy)
        dx, dy = first[0] - sx, first[1] - sy
        d = math.hypot(dx, dy) or 1.0
        v = 0.0 if wp[-1] is None else s["v"]
        state[i] = (sx, sy, v * dx / d, v * dy / d, first[0], first[1])
        active_from.append(s["t0"])
    sim = psf.Simulator(state, config_file=SF_CONFIG)
    desired = sim.peds.initial_speeds.copy()          # each walker's own desired speed
    start = np.array([s["start"] for s in specs], dtype=float)
    hes_until = [-1.0] * n
    arrived = [None] * n                                       # where a walker stopped at his goal
    out = [[] for _ in range(n)]
    for t in times:
        st = sim.peds.state
        for i in range(n):
            if t < active_from[i]:                             # not started yet: stands at the start
                st[i, 0:2] = start[i]
            out[i].append((float(st[i, 0]), float(st[i, 1])))
        sim.step_once()
        st = sim.peds.state
        for i in range(n):
            if wp[i] is None:
                st[i, 2:4] = 0.0
                continue
            if t + dt < active_from[i]:
                continue
            if arrived[i] is None and wp[i] is False and math.hypot(st[i, 0] - goal[i][0], st[i, 1] - goal[i][1]) < 0.4:
                arrived[i] = (float(st[i, 0]), float(st[i, 1]))       # at the goal: stops there
            if arrived[i] is not None:
                st[i, 0:2] = arrived[i]
                st[i, 2:4] = 0.0
                continue
            if wp[i] and math.hypot(st[i, 0] - wp[i][0], st[i, 1] - wp[i][1]) < 0.6:
                st[i, 4:6] = goal[i]                           # waypoint passed: head for the goal
                wp[i] = False
            moving = math.hypot(st[i, 2], st[i, 3]) > 0.2
            if moving and hes_until[i] < t and rng.random() < HESITATE_RATE * dt:
                hes_until[i] = t + rng.uniform(*HESITATE_S)
            sim.peds.initial_speeds[i] = desired[i] * (0.15 if t < hes_until[i] else 1.0)   # max_speeds follow it
            st[i, 2] += rng.gauss(0.0, FLUCT_SIGMA) * math.sqrt(dt)
            st[i, 3] += rng.gauss(0.0, FLUCT_SIGMA) * math.sqrt(dt)
    return out


def summary(paths, times):
    """Path statistics of a walker model (for the report): speed spread and straightness."""
    dt = times[1] - times[0]
    speeds, straight_ratio = [], []
    for p in paths:
        steps = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(p, p[1:])]
        moving = [s / dt for s in steps if s / dt > 0.2]
        if len(moving) < 10:
            continue
        speeds += moving
        walked = sum(steps)
        chord = math.hypot(p[-1][0] - p[0][0], p[-1][1] - p[0][1])
        if walked > 2.0:
            straight_ratio.append(chord / walked)
    if not speeds:
        return {}
    mu = sum(speeds) / len(speeds)
    sd = (sum((s - mu) ** 2 for s in speeds) / len(speeds)) ** 0.5
    return {"speed_mean": round(mu, 3), "speed_cv": round(sd / mu, 3),
            "straightness": round(sum(straight_ratio) / len(straight_ratio), 3) if straight_ratio else None}
