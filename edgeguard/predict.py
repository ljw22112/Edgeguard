"""Short-horizon motion prediction.

* CV   - constant velocity (workers, and the analytic CPA case)
* CTRV - constant turn rate and velocity (forklifts, using the IMU yaw rate).
  Warehouse aisles are laid out on a grid, so a turning forklift is predicted
  to turn only until its heading lines up with the next aisle direction
  (the next multiple of 90 degrees) and to drive straight after that.

The interface is deliberately small so a learned predictor (LSTM) can be
dropped in later: anything with `.positions(times) -> list[(x, y)]` works.
"""
from __future__ import annotations

import math

MAX_TURN = math.pi / 2


class CVPredictor:
    def __init__(self, pos, vel):
        self.pos, self.vel = pos, vel

    def positions(self, times):
        x, y = self.pos
        vx, vy = self.vel
        return [(x + vx * t, y + vy * t) for t in times]


def _remaining_turn(heading, yaw_rate, grid=MAX_TURN, min_turn=math.radians(10)):
    """Angle left until the heading reaches the next aisle direction."""
    k = heading / grid
    nxt = math.floor(k) + 1 if yaw_rate > 0 else math.ceil(k) - 1
    rem = abs(nxt * grid - heading)
    if rem < min_turn:            # just started a turn from an aisle axis
        rem += grid
    return min(rem, grid)


class CTRVPredictor:
    def __init__(self, pos, speed, heading, yaw_rate, grid_snap=True):
        self.pos, self.v, self.th, self.w = pos, speed, heading, yaw_rate
        self.grid_snap = grid_snap

    def positions(self, times):
        x0, y0 = self.pos
        v, th, w = self.v, self.th, self.w
        if abs(w) < 1e-3:
            return [(x0 + v * math.cos(th) * t, y0 + v * math.sin(th) * t) for t in times]
        turn = _remaining_turn(th, w) if self.grid_snap else MAX_TURN
        t_cap = turn / abs(w)
        out = []
        for t in times:
            tt = min(t, t_cap)
            x = x0 + v / w * (math.sin(th + w * tt) - math.sin(th))
            y = y0 + v / w * (-math.cos(th + w * tt) + math.cos(th))
            if t > t_cap:
                th2 = th + w * t_cap
                x += v * math.cos(th2) * (t - t_cap)
                y += v * math.sin(th2) * (t - t_cap)
            out.append((x, y))
        return out


def min_separation(pred_a, pred_b, horizon=5.0, dt=0.1):
    """Sampled closest approach between two predicted paths -> (t_min, d_min)."""
    n = int(round(horizon / dt))
    times = [i * dt for i in range(n + 1)]
    pa, pb = pred_a.positions(times), pred_b.positions(times)
    best_t, best_d = 0.0, float("inf")
    for t, a, b in zip(times, pa, pb):
        d = math.hypot(a[0] - b[0], a[1] - b[1])
        if d < best_d:
            best_t, best_d = t, d
    return best_t, best_d


def speed_scale_on_path(pred_worker, pred_forklift, r_safe, horizon=3.0, dt=0.1, step=0.05):
    """Velocity-obstacle speed command along the forklift's *predicted* path.

    Slowing the forklift to k x speed keeps it on the same path but reaches each
    point later: position(k, t) = path(k * t).  Returns the largest k in [0, 1]
    that keeps the pair at least r_safe apart for `horizon` seconds.
    """
    n = int(round(horizon / dt))
    times = [i * dt for i in range(n + 1)]
    pw = pred_worker.positions(times)
    k = 1.0
    while k >= -1e-9:
        pf = pred_forklift.positions([max(k, 0.0) * t for t in times])
        if all(math.hypot(a[0] - b[0], a[1] - b[1]) >= r_safe for a, b in zip(pw, pf)):
            return round(max(k, 0.0), 2)
        k -= step
    return 0.0
