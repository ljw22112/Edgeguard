"""Per-object tracking: a constant-velocity Kalman filter.

Workers report only position (UWB tag).  Forklifts can also report speed,
heading and yaw rate from the IMU / wheel encoder; those are fused as an
extra velocity measurement and the yaw rate is kept for CTRV prediction.
"""
from __future__ import annotations

import math
import time
from collections import deque

import numpy as np


class Track:
    def __init__(self, obj_id: str, kind: str, pos_sigma=0.15, accel_sigma=None,
                 vel_sigma=0.15):
        if accel_sigma is None:               # people walk smoothly, forklifts brake hard
            accel_sigma = 0.8 if kind == "worker" else 1.5
        self.id = obj_id
        self.kind = kind                      # "worker" | "forklift"
        self.x = None                         # [x, y, vx, vy]
        self.P = None
        self.t = None
        self.yaw_rate = 0.0
        self.heading = None
        self.r_pos = pos_sigma ** 2
        self.r_vel = vel_sigma ** 2
        self.q = accel_sigma ** 2
        self.src_ts = None                    # device timestamp of last sample (ms)
        self.history = deque(maxlen=40)       # raw (t, x, y) samples; learned.resample() uses the last 1.9 s

    def _predict(self, dt):
        F = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]], float)
        g = np.array([[0.5 * dt * dt, 0], [0, 0.5 * dt * dt], [dt, 0], [0, dt]])
        Q = g @ g.T * self.q
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

    def update(self, t, x, y, speed=None, heading=None, yaw_rate=None, src_ts=None,
               pos_sigma=None, source="uwb"):
        """t in seconds. heading in radians (0 = +x axis, CCW positive).
        pos_sigma overrides the position noise for this sample (e.g. a coarse
        network-based fix from the MEC Location API)."""
        self.source = source
        self.src_ts = src_ts
        self.last_seen = time.monotonic()
        if self.t is not None and (t < self.t or t - self.t > 2.0):
            self.x = None                     # device restarted or long gap: re-initialise
            self.history.clear()
        if source == "uwb":
            self.uwb_seen = self.last_seen
            self.history.append((t, x, y))      # resampled to 10 Hz by the learned predictor
        vel = None
        if speed is not None and heading is not None:
            vel = (speed * math.cos(heading), speed * math.sin(heading))
            self.heading = heading
        if yaw_rate is not None:
            self.yaw_rate = yaw_rate
        if self.x is None:
            self.x = np.array([x, y, *(vel or (0.0, 0.0))], float)
            self.P = np.diag([self.r_pos, self.r_pos, 4.0, 4.0])
            if vel is not None:
                self.P[2, 2] = self.P[3, 3] = self.r_vel
            self.t = t
            return
        dt = max(1e-3, t - self.t)
        self.t = t
        self._predict(dt)
        if vel is None:
            H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], float)
            z = np.array([x, y])
            R = np.eye(2) * (self.r_pos if pos_sigma is None else pos_sigma ** 2)
        else:
            H = np.eye(4)
            z = np.array([x, y, vel[0], vel[1]])
            rp = self.r_pos if pos_sigma is None else pos_sigma ** 2
            R = np.diag([rp, rp, self.r_vel, self.r_vel])
        y_res = z - H @ self.x
        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y_res
        self.P = (np.eye(4) - K @ H) @ self.P

    @property
    def pos(self):
        return (float(self.x[0]), float(self.x[1]))

    @property
    def vel(self):
        return (float(self.x[2]), float(self.x[3]))

    @property
    def speed(self):
        return math.hypot(self.x[2], self.x[3])
