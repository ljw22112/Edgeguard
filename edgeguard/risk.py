"""Risk assessment: guidance-based collision prediction plus baselines.

Levels: 0 SAFE, 1 CAUTION, 2 WARNING, 3 DANGER

Methods
-------
guidance       CV prediction, analytic CPA / LOS-rate geometry
guidance_ctrv  worker CV + forklift CTRV (IMU yaw rate), sampled closest approach
distance       baseline proximity alarm (WARNING if R < threshold)
ttc            baseline time-to-collision R / Vc
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field

from .geometry import encounter, vo_speed_scale, INF
from .predict import CVPredictor, CTRVPredictor, min_separation

LEVELS = ["SAFE", "CAUTION", "WARNING", "DANGER"]


@dataclass
class RiskConfig:
    r_safe: float = 1.5            # forklift footprint radius + worker radius (m)
    t_danger: float = 1.5          # s
    t_warn: float = 3.0            # s
    t_caution: float = 5.0         # s
    m_warn: float = 0.3            # extra margin over r_safe for WARNING (m)
    m_caution: float = 1.0         # extra margin over r_safe for CAUTION (m)
    horizon: float = 5.0           # prediction horizon (s)
    moving_speed: float = 0.2      # forklift counts as moving above this (m/s)
    distance_threshold: float = 3.0
    ttc_warn: float = 3.0
    ttc_danger: float = 1.5


@dataclass
class PairRisk:
    worker: str
    forklift: str
    level: int
    level_name: str
    method: str
    range: float
    closing_speed: float
    los_rate: float
    tcpa: float
    dcpa: float
    ttc: float
    t_min: float
    d_min: float
    speed_scale: float
    reason: str

    def to_dict(self):
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, float):
                d[k] = None if math.isinf(v) else round(v, 3)
        return d


def _heading(track):
    if track.heading is not None:
        return track.heading
    vx, vy = track.vel
    return math.atan2(vy, vx)


def _level_from_geometry(cfg: RiskConfig, t_min, d_min, R, forklift_moving):
    rs = cfg.r_safe
    if d_min < rs and t_min <= cfg.t_danger:
        return 3
    if d_min < rs + cfg.m_warn and t_min <= cfg.t_warn:
        return 2
    if d_min < rs + cfg.m_caution and t_min <= cfg.t_caution:
        return 1
    if forklift_moving and R < rs + 0.5:      # proximity floor
        return 1
    return 0


def assess(worker, forklift, cfg: RiskConfig, method="guidance_ctrv") -> PairRisk:
    enc = encounter(worker.pos, worker.vel, forklift.pos, forklift.vel, cfg.r_safe)
    moving = forklift.speed > cfg.moving_speed
    t_min, d_min = enc.tcpa, enc.dcpa
    scale = 1.0

    if method == "distance":
        level = 2 if enc.range < cfg.distance_threshold else 0
        reason = f"distance {enc.range:.1f} m vs threshold {cfg.distance_threshold:.1f} m"
    elif method == "ttc":
        level = 3 if enc.ttc < cfg.ttc_danger else 2 if enc.ttc < cfg.ttc_warn else 0
        reason = f"TTC {enc.ttc:.1f} s"
    else:
        if method == "guidance_ctrv":
            pw = CVPredictor(worker.pos, worker.vel)
            pf = CTRVPredictor(forklift.pos, forklift.speed, _heading(forklift),
                               forklift.yaw_rate)
            t_min, d_min = min_separation(pw, pf, cfg.horizon)
        elif t_min > cfg.horizon:
            t_min = INF
        level = _level_from_geometry(cfg, t_min, d_min, enc.range, moving)
        if level >= 2 and moving:
            scale = vo_speed_scale(worker.pos, worker.vel, forklift.pos, forklift.vel,
                                   cfg.r_safe, horizon=cfg.t_warn)
        if level == 0:
            reason = "clear"
        elif d_min < cfg.r_safe:
            reason = (f"collision course: LOS rate {enc.los_rate:+.2f} rad/s, "
                      f"closing {enc.closing_speed:.1f} m/s, miss {d_min:.1f} m in {t_min:.1f} s")
        else:
            reason = f"near miss predicted: {d_min:.1f} m in {t_min:.1f} s"

    return PairRisk(worker.id, forklift.id, level, LEVELS[level], method, enc.range,
                    enc.closing_speed, enc.los_rate, enc.tcpa, enc.dcpa, enc.ttc,
                    t_min, d_min, scale, reason)


class RiskEngine:
    """Keeps tracks and evaluates every worker x forklift pair."""

    def __init__(self, cfg: RiskConfig | None = None, method="guidance_ctrv"):
        self.cfg = cfg or RiskConfig()
        self.method = method
        self.tracks = {}

    def update(self, track_factory, obj_id, kind, t, **meas):
        tr = self.tracks.get(obj_id)
        if tr is None:
            tr = self.tracks[obj_id] = track_factory(obj_id, kind)
        tr.update(t, **meas)
        return tr

    def evaluate(self, method=None, stale_s=2.0):
        """Assess every worker x forklift pair; tracks silent for `stale_s` are skipped."""
        import time
        method = method or self.method
        now = time.monotonic()
        live = [t for t in self.tracks.values()
                if t.x is not None and now - getattr(t, "last_seen", now) <= stale_s]
        workers = [t for t in live if t.kind == "worker"]
        lifts = [t for t in live if t.kind == "forklift"]
        return [assess(w, f, self.cfg, method) for w in workers for f in lifts]
