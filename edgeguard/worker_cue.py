"""Worker tag WAIT / GO cue (Python reference of firmware/common/worker_cue.h).

A vibration burst alone makes people stop for a moment and walk on - often straight back into
the forklift's path (simulation: most remaining collisions).  The tag therefore holds a WAIT
state while an alert is active and shows GO when the MEC app says the way is clear:

  raise / refresh with vibrate  -> WAIT: first burst (DANGER 1.5 s, WARNING 0.6 s), red LED,
                                   then a short pulse every second
  raise / refresh / wait        -> stay in WAIT (the MEC app re-sends `wait` every second)
  aside                         -> STEP ASIDE to the lane edge, then WAIT there (long burst)
  clear / release               -> GO: LED off, two short pulses
  no message for HOLD_IDLE_S    -> GO by itself (lost clear, MEC app silent: never pin people) - unless the
                                   tag's own D2D rule sees a truck close (keep=True), then up to HOLD_MAX_S

Each forklift holds the worker separately (key = forklift id): a clear from one forklift does
not send the worker into the path of another one that still makes him wait.
"""
from __future__ import annotations

HOLD_IDLE_S = 2.5
HOLD_MAX_S = 20.0                              # longest WAIT kept through MEC silence for a near truck
PULSE_PERIOD_S, PULSE_ON_S = 1.0, 0.15
GO_PULSES = ((0.0, 0.08), (0.16, 0.24))       # (on, off) offsets after GO, seconds
MAX_HOLDS = 4                                  # forklifts tracked at once (firmware array size)


class WaitCue:
    def __init__(self):
        self.holds = {}                        # forklift id -> hold expires at
        self.since, self.burst_until, self.go_at = 0.0, 0.0, None

    @property
    def waiting(self):
        return bool(self.holds)

    def _drop(self, t, key):
        self.holds.pop(key, None)
        if not self.holds:
            self.go_at = t

    def on_alert(self, t, event, vibrate=False, danger=False, src="", ts=None):
        """src: the forklift the alert is about (alert["forklift"], or the relaying forklift).
        ts: the MEC app's send time - a message overtaken by a newer one (a late clear) is dropped."""
        key = src
        if ts is not None:
            last = self.__dict__.setdefault("last_ts", {})
            if ts < last.get(key, -1e18):
                return
            last[key] = ts
        self.tick(t)
        if event == "aside":                          # step to the lane edge and wait there
            event, vibrate, danger = "raise", True, True
        if event in ("clear", "release"):
            if key in self.holds:
                self._drop(t, key)
            return
        if event not in ("raise", "refresh", "wait"):
            return
        if key in self.holds:
            self.holds[key] = t + HOLD_IDLE_S
            if vibrate and event == "raise":
                self.burst_until = t + (1.5 if danger else 0.6)
        elif vibrate and len(self.holds) < MAX_HOLDS:
            if not self.holds:
                self.since, self.go_at = t, None
            self.holds[key] = t + HOLD_IDLE_S
            self.burst_until = t + (1.5 if danger else 0.6)

    def tick(self, t, keep=False):
        for k in [k for k, u in self.holds.items() if t >= u]:   # nothing heard: give up that hold
            if keep and t - self.since < HOLD_MAX_S:
                self.holds[k] = t + 0.2                      # a truck is near (D2D): keep waiting for now
            else:
                self._drop(t, k)

    def led(self, t, keep=False):
        self.tick(t, keep)
        return self.waiting

    def motor(self, t, keep=False):
        self.tick(t, keep)
        if t < self.burst_until:
            return True
        if self.waiting:
            return (t - self.since) % PULSE_PERIOD_S < PULSE_ON_S
        if self.go_at is not None:
            dt = t - self.go_at
            return any(a <= dt < b for a, b in GO_PULSES)
        return False
