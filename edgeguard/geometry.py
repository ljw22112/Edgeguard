"""Collision geometry borrowed from guidance theory.

Conventions (2D, metres, seconds):
    r = p_worker - p_forklift      relative position (LOS vector, forklift -> worker)
    v = v_worker - v_forklift      relative velocity

Key ideas
---------
* LOS rate  (lambda_dot): the rate at which the line of sight rotates.
  Proportional Navigation steers so that lambda_dot -> 0, because a constant
  bearing with decreasing range (CBDR) means a collision course.  We use the
  same fact the other way round: lambda_dot ~ 0 while closing  =>  danger.
* Miss distance.  For straight-line relative motion the closest point of
  approach (CPA) distance can be written in LOS form:
        d_cpa = R^2 * |lambda_dot| / |v|
  and the classic PN "zero-effort miss" uses the closing speed instead:
        ZEM   = R^2 * |lambda_dot| / Vc
* Collision cone / velocity obstacle: the forklift is on a collision course
  when its velocity relative to the worker points inside the cone of
  half-angle asin(R_safe / R) around the LOS.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

INF = float("inf")


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _norm(a):
    return math.hypot(a[0], a[1])


@dataclass(frozen=True)
class Encounter:
    """Guidance quantities for one worker/forklift pair."""

    range: float          # R, current distance between centres (m)
    range_rate: float     # dR/dt (m/s), negative when closing
    closing_speed: float  # Vc = -dR/dt (m/s)
    los_angle: float      # lambda (rad)
    los_rate: float       # lambda_dot (rad/s)
    tcpa: float           # time to closest point of approach (s), 0 if diverging
    dcpa: float           # distance at CPA (m)
    zem: float            # zero-effort miss, PN form (m)
    ttc: float            # classic time-to-collision R / Vc (s)
    in_collision_cone: bool


def cpa(r, v):
    """Closest point of approach for straight-line relative motion.

    Returns (tcpa, dcpa).  If the pair is diverging, tcpa = 0 and dcpa = R.
    """
    vv = _dot(v, v)
    if vv < 1e-9:
        return INF, _norm(r)
    t = -_dot(r, v) / vv
    if t <= 0.0:
        return 0.0, _norm(r)
    return t, _norm((r[0] + v[0] * t, r[1] + v[1] * t))


def los_kinematics(r, v):
    """Return (R, R_dot, lambda, lambda_dot)."""
    R = _norm(r)
    if R < 1e-9:
        return 0.0, 0.0, 0.0, 0.0
    R_dot = _dot(r, v) / R
    lam = math.atan2(r[1], r[0])
    lam_dot = _cross(r, v) / (R * R)
    return R, R_dot, lam, lam_dot


def miss_distance_from_los(R, lam_dot, v_rel_speed):
    """d_cpa written with the LOS rate: R^2 |lambda_dot| / |v|."""
    if v_rel_speed < 1e-9:
        return R
    return R * R * abs(lam_dot) / v_rel_speed


def zero_effort_miss(R, lam_dot, closing_speed):
    """PN zero-effort miss R^2 |lambda_dot| / Vc (inf when not closing)."""
    if closing_speed <= 1e-9:
        return INF
    return R * R * abs(lam_dot) / closing_speed


def in_collision_cone(r, v, r_safe):
    """True if relative motion points inside the collision cone.

    Equivalent to: closing, and the straight-line CPA is inside r_safe.
    """
    R = _norm(r)
    if R <= r_safe:
        return True
    u = (-v[0], -v[1])          # forklift velocity relative to the worker
    su = _norm(u)
    if su < 1e-9 or _dot(u, r) <= 0:
        return False
    half_angle = math.asin(min(1.0, r_safe / R))
    ang = math.acos(max(-1.0, min(1.0, _dot(u, r) / (su * R))))
    return ang < half_angle


def encounter(p_worker, v_worker, p_forklift, v_forklift, r_safe):
    r = (p_worker[0] - p_forklift[0], p_worker[1] - p_forklift[1])
    v = (v_worker[0] - v_forklift[0], v_worker[1] - v_forklift[1])
    R, R_dot, lam, lam_dot = los_kinematics(r, v)
    tc, dc = cpa(r, v)
    vc = -R_dot
    return Encounter(
        range=R,
        range_rate=R_dot,
        closing_speed=vc,
        los_angle=lam,
        los_rate=lam_dot,
        tcpa=tc,
        dcpa=dc,
        zem=zero_effort_miss(R, lam_dot, vc),
        ttc=(R / vc) if vc > 1e-9 else INF,
        in_collision_cone=in_collision_cone(r, v, r_safe),
    )


def vo_speed_scale(p_worker, v_worker, p_forklift, v_forklift, r_safe,
                   horizon=3.0, step=0.05):
    """Velocity-obstacle speed command.

    Largest k in [0, 1] such that, if the forklift keeps its heading at
    k * current speed, the pair stays outside r_safe within `horizon` seconds.
    Returns 1.0 when no slow-down is needed and 0.0 when only stopping helps
    (or not even stopping does, e.g. the worker walks into a parked forklift).
    """
    r = (p_worker[0] - p_forklift[0], p_worker[1] - p_forklift[1])
    k = 1.0
    while k >= -1e-9:
        v = (v_worker[0] - k * v_forklift[0], v_worker[1] - k * v_forklift[1])
        tc, dc = cpa(r, v)
        if dc >= r_safe or tc > horizon:
            return round(max(k, 0.0), 2)
        k -= step
    return 0.0
