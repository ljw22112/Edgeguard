"""Worker tag WAIT / GO cue (Python reference of firmware/common/worker_cue.h).

A vibration burst alone makes people stop for a moment and walk on - often straight back into
the forklift's path (simulation: most remaining collisions).  The tag therefore holds a WAIT
state while the alert is active and shows GO when the MEC app says the way is clear:

  raise / refresh with vibrate  -> WAIT: first burst (DANGER 1.5 s, WARNING 0.6 s), red LED,
                                   then a short pulse every second
  raise / refresh / wait        -> stay in WAIT (the MEC app re-sends `wait` every second)
  clear / release               -> GO: LED off, two short pulses
  no message for HOLD_IDLE_S    -> GO by itself (lost clear, MEC app silent: never pin people)
"""
from __future__ import annotations

HOLD_IDLE_S = 2.5
PULSE_PERIOD_S, PULSE_ON_S = 1.0, 0.15
GO_PULSES = ((0.0, 0.08), (0.16, 0.24))       # (on, off) offsets after GO, seconds


class WaitCue:
    def __init__(self):
        self.waiting, self.until, self.since = False, 0.0, 0.0
        self.burst_until, self.go_at = 0.0, None

    def on_alert(self, t, event, vibrate=False, danger=False):
        if event in ("clear", "release"):
            if self.waiting:
                self.waiting, self.go_at = False, t
            return
        if event not in ("raise", "refresh", "wait"):
            return
        if self.waiting and t < self.until:
            self.until = t + HOLD_IDLE_S
            if vibrate and event == "raise":
                self.burst_until = t + (1.5 if danger else 0.6)
        elif vibrate:
            self.waiting, self.since, self.until = True, t, t + HOLD_IDLE_S
            self.burst_until, self.go_at = t + (1.5 if danger else 0.6), None

    def tick(self, t):
        if self.waiting and t >= self.until:       # nothing heard: give up the hold
            self.waiting, self.go_at = False, t

    def led(self, t):
        self.tick(t)
        return self.waiting

    def motor(self, t):
        self.tick(t)
        if t < self.burst_until:
            return True
        if self.waiting:
            return (t - self.since) % PULSE_PERIOD_S < PULSE_ON_S
        if self.go_at is not None:
            dt = t - self.go_at
            return any(a <= dt < b for a, b in GO_PULSES)
        return False
