"""Warehouse encounter scenarios for one worker and one forklift.

Every generator returns ground-truth trajectories sampled at DT:
    {"name", "t": [...], "worker": [(x, y)], "forklift": [(x, y, heading, speed, yaw_rate)]}
Ground truth "conflict" = the true centre distance drops below R_SAFE at some
point if nobody reacts (no intervention is simulated).
"""
from __future__ import annotations

import math
import random

DT = 0.1
T_END = 12.0
R_SAFE = 1.5


def _times():
    n = int(round(T_END / DT))
    return [i * DT for i in range(n + 1)]


def _straight_forklift(x0, y0, heading, speed, times):
    return [(x0 + speed * math.cos(heading) * t, y0 + speed * math.sin(heading) * t,
             heading, speed, 0.0) for t in times]


def _walk(x0, y0, vx, vy, times, stop_at=None):
    out = []
    for t in times:
        tt = t if stop_at is None else min(t, stop_at)
        out.append((x0 + vx * tt, y0 + vy * tt))
    return out


def crossing(rng: random.Random, offset):
    """Forklift along +x, worker along +y, both aimed at the intersection (0,0).
    `offset` = worker arrival time minus forklift arrival time (s)."""
    times = _times()
    vf, vw = rng.uniform(1.5, 3.0), rng.uniform(0.8, 1.5)
    t_meet = rng.uniform(5.0, 8.0)
    angle = math.pi / 2 + rng.uniform(-0.35, 0.35)
    tw = t_meet + offset
    f = _straight_forklift(-vf * t_meet, 0.0, 0.0, vf, times)
    wx, wy = -vw * math.cos(angle) * tw, -vw * math.sin(angle) * tw
    w = _walk(wx, wy, vw * math.cos(angle), vw * math.sin(angle), times)
    return times, w, f


def gen_crossing_conflict(rng):
    return ("crossing_conflict", *crossing(rng, rng.uniform(-0.4, 0.4)))


def gen_crossing_clear(rng):
    return ("crossing_clear", *crossing(rng, rng.choice([-1, 1]) * rng.uniform(1.6, 4.0)))


def gen_head_on(rng):
    times = _times()
    vf, vw = rng.uniform(1.5, 3.0), rng.uniform(0.5, 1.3)
    gap = rng.uniform(18, 28)
    lat = rng.uniform(-0.6, 0.6)
    f = _straight_forklift(0.0, 0.0, 0.0, vf, times)
    w = _walk(gap, lat, -vw, 0.0, times)
    return "head_on_same_aisle", times, w, f


def gen_adjacent_aisle(rng):
    times = _times()
    vf, vw = rng.uniform(1.5, 3.0), rng.uniform(0.6, 1.4)
    lat = rng.choice([-1, 1]) * rng.uniform(2.0, 3.0)
    direction = rng.choice([-1, 1])
    f = _straight_forklift(0.0, 0.0, 0.0, vf, times)
    x0 = rng.uniform(8, 20)
    w = _walk(x0, lat, direction * vw, 0.0, times)
    return "adjacent_aisle_pass", times, w, f


def gen_roadside_picker(rng):
    times = _times()
    vf = rng.uniform(1.5, 3.0)
    f = _straight_forklift(0.0, 0.0, 0.0, vf, times)
    lat = rng.choice([-1, 1]) * rng.uniform(1.9, 2.8)
    x0 = rng.uniform(8, 22)
    w = [(x0 + 0.05 * math.sin(t), lat + 0.05 * math.cos(1.3 * t)) for t in times]
    return "roadside_picker", times, w, f


def _turning_forklift(vf, w, t_turn, times):
    """Drive straight along +x, start a 90-degree turn at t_turn."""
    out, x, y, th = [], 0.0, 0.0, 0.0
    t_end_turn = t_turn + (math.pi / 2) / abs(w)
    prev = 0.0
    for t in times:
        dt = t - prev
        prev = t
        yaw = w if t_turn <= t < t_end_turn else 0.0
        th += yaw * dt
        x += vf * math.cos(th) * dt
        y += vf * math.sin(th) * dt
        out.append((x, y, th, vf, yaw))
    return out


def gen_turn_into_worker(rng):
    times = _times()
    vf = rng.uniform(1.5, 2.5)
    w = rng.choice([-1, 1]) * rng.uniform(0.6, 1.0)
    t_turn = rng.uniform(3.0, 5.0)
    f = _turning_forklift(vf, w, t_turn, times)
    # worker stands in the aisle the forklift turns into
    idx = min(len(times) - 1, int((t_turn + 2.0 + 2.5) / DT))
    tx, ty = f[idx][0], f[idx][1]
    wk = [(tx + rng.uniform(-0.4, 0.4), ty + rng.uniform(-0.4, 0.4))] * len(times)
    return "turn_into_worker", times, wk, f


def gen_turn_away(rng):
    times = _times()
    vf = rng.uniform(1.5, 2.5)
    w = rng.choice([-1, 1]) * rng.uniform(0.6, 1.0)
    t_turn = rng.uniform(3.0, 5.0)
    f = _turning_forklift(vf, w, t_turn, times)
    # worker stands straight ahead of where the forklift turns off
    xs = vf * t_turn + rng.uniform(6.0, 9.0)
    wk = [(xs, rng.uniform(-0.5, 0.5))] * len(times)
    return "turn_away", times, wk, f


def gen_worker_yields(rng):
    """Worker on a crossing collision path who slows down and stops 2-3 m before
    the forklift's path (people decelerate over ~0.6-1.0 s, they do not freeze)."""
    name, times, w, f = gen_crossing_conflict(rng)
    (x0, y0), (x1, y1) = w[0], w[1]
    vx, vy = (x1 - x0) / DT, (y1 - y0) / DT
    v = math.hypot(vx, vy)
    ux, uy = vx / v, vy / v
    stop_dist = rng.uniform(2.2, 3.0)          # distance from the aisle centre line y = 0
    s_stop = (-stop_dist - y0) / uy             # path length until that line
    td = rng.uniform(0.6, 1.0)                  # deceleration time
    s_dec = s_stop - v * td / 2
    t_dec = s_dec / v
    out = []
    for t in times:
        if t <= t_dec:
            s_ = v * t
        elif t <= t_dec + td:
            dt = t - t_dec
            s_ = s_dec + v * dt - 0.5 * (v / td) * dt * dt
        else:
            s_ = s_stop
        out.append((x0 + ux * s_, y0 + uy * s_))
    return "worker_yields", times, out, f


GENERATORS = [gen_crossing_conflict, gen_crossing_clear, gen_head_on, gen_adjacent_aisle,
              gen_roadside_picker, gen_turn_into_worker, gen_turn_away, gen_worker_yields]


# --- extra behaviours used by the online (closed-loop) simulation ---------------------

def gen_running_worker(rng):
    """Worker running (2.0-2.8 m/s) across the forklift's path."""
    times = _times()
    vf, vw = rng.uniform(1.5, 3.0), rng.uniform(2.0, 2.8)
    t_meet = rng.uniform(5.0, 8.0)
    off = rng.uniform(-0.3, 0.3)
    f = _straight_forklift(-vf * t_meet, 0.0, 0.0, vf, times)
    w = _walk(0.0, -vw * (t_meet + off), 0.0, vw, times)
    return "running_worker", times, w, f


def gen_zigzag_worker(rng):
    """Worker weaving (+-0.8 m, 0.4 Hz) while crossing - hard for straight-line prediction."""
    name, times, w, f = gen_crossing_conflict(rng)
    amp, freq = rng.uniform(0.5, 0.9), rng.uniform(0.3, 0.5)
    ph = rng.uniform(0, 2 * math.pi)
    w = [(x + amp * math.sin(2 * math.pi * freq * t + ph), y) for t, (x, y) in zip(times, w)]
    return "zigzag_worker", times, w, f


def gen_reversing_forklift(rng):
    """Forklift reversing out of a bay across a walkway (moves -x while facing +x)."""
    times = _times()
    vf, vw = rng.uniform(1.0, 1.8), rng.uniform(0.8, 1.4)
    t_meet = rng.uniform(5.0, 8.0)
    x0 = vf * t_meet
    f = [(x0 - vf * t, 0.0, 0.0, -vf, 0.0) for t in times]      # heading +x, speed negative
    w = _walk(0.0, -vw * (t_meet + rng.uniform(-0.3, 0.3)), 0.0, vw, times)
    return "reversing_forklift", times, w, f


EXTRA_GENERATORS = [gen_running_worker, gen_zigzag_worker, gen_reversing_forklift]


def ground_truth(times, w, f, r_safe=R_SAFE):
    d = [math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(w, f)]
    contact = next((t for t, x in zip(times, d) if x < r_safe), None)
    return {"conflict": contact is not None, "t_contact": contact, "d_min": min(d)}
