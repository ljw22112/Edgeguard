"""Stopping guarantee of the stop point ("movement authority"), property-based (docs/safety-case.md, claim C2).

The forklift module brakes for a stop point from its own position every 0.1 s control cycle:
    v_cap(d) = a * (-tau + sqrt(tau^2 + 2 d / a)),   a = STOP_DECEL = 2.3 m/s^2, tau = STOP_REACT = 0.1 s
on a drive that decelerates at 2.5 m/s^2 and applies a received command 0.2 s late (sim/online_sim.Mover).

Claim 1 (in time): if the stop point arrives while the truck could still stop for it with that plan
(v0 <= v_cap(d0 - v0 * 0.2), the distance left when the command takes effect), the truck never passes it.
Claim 2 (late): otherwise it passes it by no more than its physical stopping distance from the moment the command
takes effect, v0 * (0.2 + 0.1) + v0^2 / (2 * 2.5) - d0.
Claim 3: speeds never go negative and the truck comes to rest (no creeping into the point).
Checked over thousands of random cases on the exact device and drive code the simulations use.
"""
import math

from hypothesis import given, settings, strategies as st

from edgeguard.device_policy import ForkliftLimit
from sim.online_sim import DT, Mover, Path

A_DRIVE, CMD_DELAY = 2.5, 0.2


def run(v0, d0, t_end=None, hb=True):
    """Truck on a straight line at v0 (its nominal speed), stop point d0 ahead, sent at t = 0."""
    t_end = t_end or d0 / v0 + 8.0                # long enough to reach the point and stop
    n = int(t_end / DT) + 400
    pts = [(v0 * DT * i, 0.0) for i in range(n)]
    m = Mover("f", "forklift", Path(pts, [(0.0, 1, 0.0)] * n))
    m.fl = ForkliftLimit("coop")
    m.v = v0
    m.on_alert(0.0, "raise", None, src="w", stop_at=(d0, 0.0), ts=0.0)
    t, min_v = 0.0, v0
    while t < t_end:
        if hb and abs(t - round(t)) < 1e-9:
            m.pending.append((t, "hb", None, ""))
            if t > 0:
                m.on_alert(t, "refresh", None, src="w", stop_at=(d0, 0.0), ts=t)    # MEC keeps it alive
        m.step(t, DT)
        min_v = min(min_v, m.v)
        t = round(t + DT, 6)
    return m.path.pos(m.s)[0], m.v, min_v


def v_cap(d):
    a, tau = ForkliftLimit.STOP_DECEL, ForkliftLimit.STOP_REACT
    return 0.0 if d <= 0 else a * (-tau + math.sqrt(tau * tau + 2 * d / a))


@settings(max_examples=1500, deadline=None)
@given(v0=st.floats(0.3, 3.5), d0=st.floats(0.05, 25.0))
def test_stop_point_in_time_is_never_passed(v0, d0):
    d_eff = d0 - v0 * CMD_DELAY
    if d_eff <= 0 or v0 > v_cap(d_eff):
        return                                   # not in time: claim 2
    x, v, min_v = run(v0, d0)
    assert x <= d0 + 1e-9, (v0, d0, x)
    assert v < 1e-6 and min_v >= 0.0


@settings(max_examples=1500, deadline=None)
@given(v0=st.floats(0.3, 3.5), d0=st.floats(0.05, 25.0))
def test_late_stop_point_overshoot_is_bounded(v0, d0):
    x, v, min_v = run(v0, d0)
    bound = max(0.0, v0 * (CMD_DELAY + 0.1) + v0 * v0 / (2 * A_DRIVE) - d0)
    assert x - d0 <= bound + 1e-6, (v0, d0, x - d0, bound)
    assert min_v >= 0.0


@settings(max_examples=300, deadline=None)
@given(v0=st.floats(0.3, 3.5), d0=st.floats(2.0, 25.0))
def test_stop_point_held_through_mec_silence(v0, d0):
    """No refresh, no heartbeat after the first message: the point is part of the held plan (silence never
    lifts a plan), so the truck still stops short of it."""
    d_eff = d0 - v0 * CMD_DELAY
    if d_eff <= 0 or v0 > v_cap(d_eff):
        return
    x, v, _ = run(v0, d0, hb=False)
    assert x <= d0 + 1e-9 and v < 1e-6


@settings(max_examples=2000, deadline=None)
@given(ahead=st.floats(2.0, 15.0), lat=st.floats(-1.49, 1.49), err=st.floats(-1.0, 1.0),
       margin=st.floats(0.1, 0.8))
def test_stop_point_placement_keeps_r_safe(ahead, lat, err, margin):
    """Claim 4: a truck stopped at the stop point the MEC app places for a person standing in its path is at least
    r_safe from him, as long as the error of his position along the path is within env_margin."""
    from edgeguard.alerting import envelope_limit
    from edgeguard.risk import RiskConfig
    err = max(-margin, min(margin, err))

    class T:
        def __init__(self, x, y, vx=0.0):
            self.x, self.y, self.pos, self.vel, self.speed, self.heading = x, y, (x, y), (vx, 0.0), abs(vx), 0.0

    cfg = RiskConfig(env_v2=True, env_lateral=3.0, env_margin=margin)
    stop = []
    envelope_limit(T(ahead + err, lat), T(0.0, 0.0, 2.0), cfg, out_stop=stop)   # estimate is off by err
    if not stop:
        return
    sx, sy = stop[0]
    assert math.hypot(ahead - sx, lat - sy) >= cfg.r_safe - 1e-6
