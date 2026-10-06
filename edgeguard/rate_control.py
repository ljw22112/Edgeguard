"""Adaptive reporting rate: devices far from any counterpart report slowly.

The shared CSE pays for every sample twice (one write, one notification to the MEC app),
so the sample rate of the whole site is the scaling limit.  Most of the time most
workers are nowhere near a forklift; for them 2 Hz is plenty.  A device is switched
back to the full rate as soon as any counterpart is close or closing in:

    near  <=>  d < near_m + horizon_s * (speed_a + speed_b + slack)      worst-case heading
          or   closing speed > 0  and  (d - near_m) / closing < reach_s     actually approaching

The first term covers a vehicle that turns towards someone; the second gives every real
approach `reach_s` (5 s, longer than the 4 s warning horizon) at the full rate.  Detecting
a new approach at the slow rate costs at most one slow period plus the command delivery.

Going fast is immediate; going slow needs `hold_s` of being far (and 20 % extra margin),
so a device never toggles at the boundary.  Worst-case extra position age at the slow
rate is 1/slow_hz (0.5 s), which the horizon covers several times over.

The MEC app publishes changes to `<ae>/control` as {"rates": {device_id: hz}}; devices
are subscribed to it and adjust their publish period (firmware: handleAlert / handleCmd).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class RateController:
    near_m: float = 8.0
    horizon_s: float = 2.0
    reach_s: float = 5.0
    slack: float = 0.5               # m/s added to the summed speeds (sudden starts)
    fast_hz: float = 10.0
    slow_hz: float = 2.0
    hold_s: float = 3.0
    stale_s: float = 3.0             # tracks not seen for this long are ignored
    rate: dict = field(default_factory=dict)        # device -> commanded hz
    far_since: dict = field(default_factory=dict)

    @staticmethod
    def _speed(tr):
        vx, vy = tr.vel if tr.vel is not None else (0.0, 0.0)
        return math.hypot(vx, vy)

    def _near(self, a, b, sa, margin):
        dx, dy = b.pos[0] - a.pos[0], b.pos[1] - a.pos[1]
        d = math.hypot(dx, dy)
        if d < margin * (self.near_m + self.horizon_s * (sa + self._speed(b) + self.slack)):
            return True
        if d < 1e-6:
            return True
        (avx, avy), (bvx, bvy) = (a.vel or (0.0, 0.0)), (b.vel or (0.0, 0.0))
        closing = ((avx - bvx) * dx + (avy - bvy) * dy) / d          # > 0: getting closer
        return closing > 0 and (d - self.near_m) / closing < margin * self.reach_s

    def update(self, tracks, now):
        """tracks: iterable of Track; now: same clock as Track.last_seen. Returns {id: hz} changes."""
        live = [t for t in tracks if t.x is not None and now - t.last_seen < self.stale_s
                and not t.id.startswith("untagged_")]
        workers = [t for t in live if t.kind == "worker"]
        forklifts = [t for t in live if t.kind == "forklift"]
        changes = {}
        for t in live:
            others = forklifts if t.kind == "worker" else workers
            st = self._speed(t)
            margin = 1.0
            if self.rate.get(t.id) == self.fast_hz:
                margin = 1.2                          # hysteresis: harder to leave fast mode
            near = any(self._near(t, o, st, margin) for o in others)
            if near:
                self.far_since.pop(t.id, None)
                want = self.fast_hz
            else:
                since = self.far_since.setdefault(t.id, now)
                want = self.slow_hz if now - since >= self.hold_s else self.rate.get(t.id, self.fast_hz)
            if self.rate.get(t.id) != want:
                self.rate[t.id] = want
                changes[t.id] = want
        return changes

    def counts(self):
        fast = sum(1 for v in self.rate.values() if v == self.fast_hz)
        return {"fast": fast, "slow": len(self.rate) - fast}
