"""UWB tag position from anchor ranges - same algorithm as firmware/common/uwb_position.h.

Kept in Python so the positioning can be exercised in simulations and tests,
and compared one-to-one with the firmware.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Fix:
    x: float = 0.0
    y: float = 0.0
    rms: float = 0.0
    used: int = 0
    rejected: int = -1
    ok: bool = False


def _horizontal(d, dz):
    h2 = d * d - dz * dz
    return math.sqrt(h2) if h2 > 0 else 0.0


def solve(anchors, ranges, tag_z, use):
    idx = [i for i in range(len(anchors)) if i in use]
    if len(idx) < 3:
        return None
    r = [_horizontal(ranges[i], anchors[i][2] - tag_z) for i in idx]
    x0, y0, _ = anchors[idx[0]]
    s11 = s12 = s22 = b1 = b2 = 0.0
    for k in range(1, len(idx)):
        xi, yi, _ = anchors[idx[k]]
        a1, a2 = 2 * (xi - x0), 2 * (yi - y0)
        b = r[0] ** 2 - r[k] ** 2 + xi * xi - x0 * x0 + yi * yi - y0 * y0
        s11 += a1 * a1
        s12 += a1 * a2
        s22 += a2 * a2
        b1 += a1 * b
        b2 += a2 * b
    det = s11 * s22 - s12 * s12
    if abs(det) < 1e-6:
        return None
    x, y = (s22 * b1 - s12 * b2) / det, (s11 * b2 - s12 * b1) / det
    for _ in range(5):                                  # Gauss-Newton refinement
        h11 = h12 = h22 = g1 = g2 = 0.0
        for k, i in enumerate(idx):
            dx, dy = x - anchors[i][0], y - anchors[i][1]
            est = math.hypot(dx, dy)
            if est < 1e-4:
                continue
            jx, jy, e = dx / est, dy / est, est - r[k]
            h11 += jx * jx
            h12 += jx * jy
            h22 += jy * jy
            g1 += jx * e
            g2 += jy * e
        dt = h11 * h22 - h12 * h12
        if abs(dt) < 1e-9:
            break
        ux, uy = (h22 * g1 - h12 * g2) / dt, (h11 * g2 - h12 * g1) / dt
        x, y = x - ux, y - uy
        if abs(ux) + abs(uy) < 1e-4:
            break
    ss = sum((math.hypot(x - anchors[i][0], y - anchors[i][1]) - r[k]) ** 2 for k, i in enumerate(idx))
    return Fix(x, y, math.sqrt(ss / len(idx)), len(idx), -1, True)


def locate(anchors, ranges, tag_z, nlos_rms=0.25):
    """anchors: [(x, y, z)], ranges: slant ranges (m). Drops one NLOS anchor if needed."""
    n = len(anchors)
    best = solve(anchors, ranges, tag_z, set(range(n)))
    if best is None:
        return Fix()
    if n >= 4 and best.rms > nlos_rms:
        full = best
        for drop in range(n):
            f = solve(anchors, ranges, tag_z, set(range(n)) - {drop})
            if f and f.rms < full.rms * 0.5 and (best.rejected < 0 or f.rms < best.rms):
                best = f
                best.rejected = drop
    return best
