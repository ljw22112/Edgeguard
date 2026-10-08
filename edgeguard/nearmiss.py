"""Near-miss analytics: actual close passes between a worker and a moving forklift.

Alerts say what the system *predicted*; a near miss is what *happened*: the measured distance
of a pair dropped below `threshold_m` while the forklift was moving.  One event per encounter,
at the closest approach.  Events are binned on a 1 m grid; the busiest cells are hotspots with
a suggested fix.  `alerted` tells whether an alert (WARNING or DANGER) had already gone out in
that encounter - a near miss without one is a gap in coverage worth investigating.
"""
from __future__ import annotations

import collections
import math

ADVICE = {
    "blind_corner": "Blind corner: add the rack to the site map / install a convex mirror",
    "speed": "Fast forklift traffic: declare a speed-limited zone",
    "unalerted": "Close passes without a prior alert: check tag coverage and anchor placement",
    "crossing": "Frequent crossing point: separate the walkway or mark a crossing",
}


class NearMissTracker:
    def __init__(self, threshold_m=2.0, cell_m=1.0, sep_margin=1.0, min_speed=0.3, keep=200):
        self.threshold_m, self.cell_m, self.sep_margin, self.min_speed = threshold_m, cell_m, sep_margin, min_speed
        self.open = {}                                  # pair -> current encounter
        self.events = collections.deque(maxlen=keep)
        self.cells = collections.Counter()
        self.cell_info = collections.defaultdict(lambda: {"occluded": 0, "unalerted": 0, "speed": 0.0})
        self.total = 0

    def observe(self, pair, d, mid, t, f_speed, occluded=False, level=0):
        """Feed one assessment of a pair; returns a finished event or None."""
        e = self.open.get(pair)
        if e is None:
            if d > self.threshold_m + self.sep_margin + 3.0:
                return None                             # far apart: nothing to follow
            e = self.open[pair] = {"d_min": math.inf, "alerted": False}
        if level >= 2:
            e["alerted"] = True
        if d < e["d_min"]:
            e.update(d_min=d, x=mid[0], y=mid[1], t=t, speed=f_speed, occluded=occluded,
                     alerted_before=e["alerted"])
        elif d > e["d_min"] + self.sep_margin:          # moving apart again: the encounter is over
            return self._close(pair)
        return None

    def sweep(self, live_pairs):
        """Close encounters whose pair is no longer evaluated (one side left / went silent)."""
        out = []
        for pair in [p for p in self.open if p not in live_pairs]:
            ev = self._close(pair)
            if ev:
                out.append(ev)
        return out

    def _close(self, pair):
        e = self.open.pop(pair, None)
        if not e or e["d_min"] >= self.threshold_m or e.get("speed", 0.0) < self.min_speed:
            return None
        ev = {"worker": pair[0], "forklift": pair[1], "t": e["t"], "d_min": round(e["d_min"], 2),
              "x": round(e["x"], 2), "y": round(e["y"], 2), "forklift_speed": round(e["speed"], 2),
              "occluded": bool(e["occluded"]), "alerted": bool(e["alerted_before"])}
        self.events.appendleft(ev)
        self.total += 1
        c = (math.floor(ev["x"] / self.cell_m) * self.cell_m, math.floor(ev["y"] / self.cell_m) * self.cell_m)
        self.cells[c] += 1
        info = self.cell_info[c]
        info["occluded"] += ev["occluded"]
        info["unalerted"] += not ev["alerted"]
        info["speed"] += ev["forklift_speed"]
        return ev

    def hotspots(self, n=5):
        out = []
        for (x, y), cnt in self.cells.most_common(n):
            info = self.cell_info[(x, y)]
            if info["occluded"] / cnt >= 0.5:
                why = "blind_corner"
            elif info["unalerted"] / cnt >= 0.3:
                why = "unalerted"
            elif info["speed"] / cnt > 2.0:
                why = "speed"
            else:
                why = "crossing"
            out.append({"x": x, "y": y, "count": cnt, "advice": why, "text": ADVICE[why]})
        return out

    def summary(self):
        return {"threshold_m": self.threshold_m, "cell_m": self.cell_m, "total": self.total,
                "unalerted": sum(1 for e in self.events if not e["alerted"]),
                "cells": [[x, y, n] for (x, y), n in self.cells.items()],
                "hotspots": self.hotspots(), "events": list(self.events)[:50]}
