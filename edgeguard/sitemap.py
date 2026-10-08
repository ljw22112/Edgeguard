"""Site map: racks / walls that block line of sight.

Collision-avoidance products judge distance; people judge what they can see.  At a blind corner
neither the driver nor the worker can see the other, so nobody starts to yield on their own and
the warning has to come earlier.  The risk engine asks `blocked(worker, forklift)` and, if the
line of sight is cut, adds `occl_t_margin` to the warning / danger time thresholds.

Obstacles are axis-aligned rectangles [x0, y0, x1, y1] in site metres (config `sitemap.obstacles`).
UWB still measures through racks (it ranges to the ceiling anchors), so occlusion changes only the
alert timing, never what is tracked.
"""
from __future__ import annotations


class SiteMap:
    def __init__(self, obstacles=()):
        self.rects = [tuple(map(float, (min(r[0], r[2]), min(r[1], r[3]), max(r[0], r[2]), max(r[1], r[3]))))
                      for r in obstacles]

    def __bool__(self):
        return bool(self.rects)

    def blocked(self, p, q):
        """True if the segment p-q passes through any obstacle (Liang-Barsky clipping)."""
        for x0, y0, x1, y1 in self.rects:
            if _clips(p, q, x0, y0, x1, y1):
                return True
        return False


def _clips(p, q, x0, y0, x1, y1):
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for d, lo, hi, start in ((dx, x0, x1, p[0]), (dy, y0, y1, p[1])):
        if abs(d) < 1e-12:
            if start < lo or start > hi:
                return False
            continue
        a, b = (lo - start) / d, (hi - start) / d
        if a > b:
            a, b = b, a
        t0, t1 = max(t0, a), min(t1, b)
        if t0 > t1:
            return False
    return t1 - t0 > 1e-9


def from_config(cfg):
    sm = (cfg or {}).get("sitemap") or {}
    return SiteMap(sm.get("obstacles") or [])
