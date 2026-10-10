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


class StopAfterPredictor:
    """A worker who has just been told to stop (tag vibrates): keeps walking for the
    reaction time, then decelerates to a standstill.  Used to plan the forklift's
    speed consistently with the instruction we are giving the worker."""

    def __init__(self, pos, vel, t_react=0.8, decel=2.0):
        self.pos, self.vel, self.tr, self.a = pos, vel, t_react, decel

    def positions(self, times):
        x, y = self.pos
        vx, vy = self.vel
        v = math.hypot(vx, vy)
        ux, uy = (vx / v, vy / v) if v > 1e-6 else (0.0, 0.0)
        t_stop = v / self.a
        out = []
        for t in times:
            if t <= self.tr:
                d = v * t
            else:
                tt = min(t - self.tr, t_stop)
                d = v * self.tr + v * tt - 0.5 * self.a * tt * tt
            out.append((x + ux * d, y + uy * d))
        return out


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


class RoutePredictor:
    """Forklift on its planned route (polyline of waypoints from the fleet / WMS system or the
    driver's tablet) at constant speed; past the last waypoint it keeps the last direction.
    Knowing the route removes the guesswork of CTRV at intersections: a truck that will turn
    away does not alarm the worker standing straight ahead, one that will turn into an aisle
    warns the worker there before it starts turning."""
    def __init__(self, pos, speed, route):
        self.pos, self.v = pos, abs(speed)
        pts = [tuple(pos)] + [tuple(p) for p in route]
        # start from the route point nearest to the truck (skip waypoints already passed)
        best = min(range(1, len(pts)), key=lambda i: math.hypot(pts[i][0] - pos[0], pts[i][1] - pos[1]))
        if best + 1 < len(pts):
            a, b = pts[best], pts[best + 1]
            ab = (b[0] - a[0], b[1] - a[1])
            if (pos[0] - a[0]) * ab[0] + (pos[1] - a[1]) * ab[1] > 0:   # already past waypoint `best`
                best += 1
        self.pts = [tuple(pos)] + pts[best:]
        self.cum = [0.0]
        for a, b in zip(self.pts, self.pts[1:]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))

    def positions(self, times):
        out = []
        for t in times:
            s = self.v * t
            if len(self.pts) < 2:
                out.append(self.pos)
                continue
            i = min(len(self.cum) - 2, max(0, next((k for k in range(1, len(self.cum)) if self.cum[k] >= s),
                                                    len(self.cum) - 1) - 1))
            a, b = self.pts[i], self.pts[i + 1]
            seg = self.cum[i + 1] - self.cum[i] or 1e-9
            f = (s - self.cum[i]) / seg                 # > 1 past the end: extrapolate the last leg
            out.append((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])))
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


def braking_scale(pred_worker, pred_forklift, speed, r_safe, horizon=5.0, dt=0.1,
                  a_dec=2.0, t_react=0.4, margin=0.5):
    """Stopping-distance cap for the speed command.

    The velocity-obstacle scale only guarantees separation for a few seconds; if
    the worker stops *in* the forklift's lane, any k > 0 just postpones the hit.
    Find the first point on the forklift's predicted path that comes within
    r_safe of the worker's predicted path, and allow at most the speed from
    which the forklift can still stop before it:  v*t_react + v^2/(2a) <= D.
    """
    if speed < 0.05:
        return 1.0
    n = int(round(horizon / dt))
    times = [i * dt for i in range(n + 1)]
    pw, pf = pred_worker.positions(times), pred_forklift.positions(times)
    for t, a, b in zip(times, pw, pf):
        if math.hypot(a[0] - b[0], a[1] - b[1]) < r_safe:
            d = max(0.0, speed * t - margin)               # distance left along the path
            v_ok = -a_dec * t_react + math.sqrt((a_dec * t_react) ** 2 + 2 * a_dec * d)
            return round(max(0.0, min(1.0, v_ok / speed)), 2)
    return 1.0
