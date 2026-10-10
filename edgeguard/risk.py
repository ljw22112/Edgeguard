"""Risk assessment: guidance-based collision prediction plus baselines.

Levels: 0 SAFE, 1 CAUTION, 2 WARNING, 3 DANGER

Methods
-------
guidance       CV prediction, analytic CPA / LOS-rate geometry
guidance_ctrv  worker CV + forklift CTRV (IMU yaw rate), sampled closest approach
guidance_lstm  worker LSTM (learned) + forklift CTRV; falls back to CV until 2 s of history
distance       baseline proximity alarm (WARNING if R < threshold)
ttc            baseline time-to-collision R / Vc
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field

from .geometry import encounter, vo_speed_scale, INF
from .predict import (CVPredictor, CTRVPredictor, RoutePredictor, StopAfterPredictor, min_separation,
                      speed_scale_on_path, braking_scale)

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
    # --- policy parameters (tuned by sim/train_policy.py) ---------------------------
    lane_lookahead: float = 6.0    # m: a standing worker this far ahead in the lane holds the alert
    stand_speed: float = 0.5       # m/s: below this a worker counts as standing
    worker_react: float = 0.8      # s: assumed reaction time of a buzzed worker (speed planning)
    brake_decel: float = 2.0       # m/s^2: deceleration assumed when capping the speed
    brake_margin: float = 0.5      # m: stopping-distance margin before the conflict point
    pass_speed: float = 1.0        # m/s: passing speed while a worker waits at the lane edge
    wait_keepalive: bool = False   # resend WAIT to the worker every refresh_s while the alert is active
    still_speed: float = 0.0       # m/s: a worker slower than this is predicted to stand still
    aside_cue: bool = False        # tell a worker standing in a stopped truck's lane to STEP ASIDE
    min_move: float = 0.0          # m/s: speed commands below this become a stop
    go_check: bool = False         # keep a waiting worker held until walking on is safe (alerting.decide)
    trust_hold: bool = False       # WARNING plans for a worker who stops (WAIT-until-GO tag), DANGER never
    release_worker: bool = False   # send the waiting worker GO once the forklift is past (alerting.decide)
    wait_lateral: float = 2.5      # m: "waiting at the lane edge" distance from the lane
    clear_hold: float = 2.0        # s: risk must stay low this long before an alert clears
    debounce: int = 2              # evaluations at WARNING before the first alert
    # --- site map (edgeguard/sitemap.py) ------------------------------------------------
    occl_t_margin: float = 0.0     # s added to t_warn / t_danger (evaluated: +1 s made blind corners worse)
    occl_r_margin: float = 0.5     # m added to r_safe when racks block the line of sight (sim/occlusion_eval.py)
    occl_debounce: int = 1         # occluded pairs alert on the first WARNING evaluation

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
    speed_limit: float = None   # m/s for the forklift (speed_scale x current speed)
    occluded: bool = False      # no line of sight between them (site map)

    def to_dict(self):
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, float):
                d[k] = None if math.isinf(v) else round(v, 3)
        return d


def forklift_predictor(forklift, speed=None):
    """Planned route if the truck's fleet system shares one (Track.route), else CTRV."""
    v = forklift.speed if speed is None else speed
    if getattr(forklift, "route", None):
        return RoutePredictor(forklift.pos, v, forklift.route)
    return CTRVPredictor(forklift.pos, v, _heading(forklift), forklift.yaw_rate)


def _heading(track):
    """Direction of travel.  While moving use the velocity (a reversing forklift
    travels opposite to where it faces); when slow, fall back to the IMU heading."""
    vx, vy = track.vel
    if math.hypot(vx, vy) > 0.3 or track.heading is None:
        return math.atan2(vy, vx)
    return track.heading


def _lane_block(worker, forklift, cfg):
    """Distance along the forklift's lane to a worker standing in it, or None.

    Time-independent on purpose: once the forklift has slowed down, the
    time-based prediction says "no conflict within 5 s" and would release the
    alert, the forklift speeds up again, and the conflict comes back too late."""
    geo = forklift_predictor(forklift, 1.0)
    steps = [i * 0.2 for i in range(int(cfg.lane_lookahead / 0.2) + 1)]
    for d, (x, y) in zip(steps, geo.positions(steps)):
        if math.hypot(worker.pos[0] - x, worker.pos[1] - y) < cfg.r_safe:
            return d
    return None


def waiting_at_lane(worker, forklift, cfg, lateral=None, lookahead=None):
    """True if the worker stands next to the forklift's lane ahead (within `lateral`).

    Used only to *hold* an alert that is already active: a worker who stopped at
    the aisle edge because the tag vibrated will usually walk on, so the forklift
    should pass at walking pace instead of resuming full speed."""
    lateral = cfg.wait_lateral if lateral is None else lateral
    lookahead = cfg.lane_lookahead if lookahead is None else lookahead
    geo = forklift_predictor(forklift, 1.0)
    steps = [i * 0.2 for i in range(1, int(lookahead / 0.2) + 1)]
    return any(math.hypot(worker.pos[0] - x, worker.pos[1] - y) < lateral
               for x, y in geo.positions(steps))


class _Profile:
    """Positions of a truck on its current heading that speeds up from v0 to v1 at `acc` m/s^2."""
    def __init__(self, forklift, v0, v1, acc=1.0):
        self.f, self.v0, self.v1, self.acc = forklift, v0, v1, acc
        sp = abs(forklift.speed)
        self.kappa = forklift.yaw_rate / sp if sp > 0.3 else 0.0     # path curvature (1/m)

    def positions(self, times):
        sign = -1.0 if self.v1 < 0 or (self.v1 == 0 and self.v0 < 0) else 1.0
        a0, a1 = abs(self.v0), abs(self.v1)
        t_up = max(0.0, (a1 - a0) / self.acc)
        arcs = [a0 * t + 0.5 * self.acc * t * t if t < t_up
                else a0 * t_up + 0.5 * self.acc * t_up * t_up + a1 * (t - t_up) for t in times]
        geo = CTRVPredictor(self.f.pos, sign, _heading(self.f), sign * self.kappa)   # unit speed: time = arc
        return geo.positions(arcs)


def go_safe(worker_pos, intent_vel, forklift, cfg, f_speed=None):
    """Would the waiting worker be safe if he walked on now with his intended velocity?
    The forklift may keep its current speed, or speed up again to its speed before the alert
    (f_speed; a truck held for this worker resumes when the pair clears) - any constant speed in
    between and the acceleration itself (1 m/s^2) must be safe: a truck that is still speeding
    up passes points at other times than one already at cruising speed."""
    pw = CVPredictor(worker_pos, intent_vel)
    v0 = forklift.speed
    v1 = f_speed if f_speed is not None and abs(f_speed) > abs(v0) else v0      # signed (reversing)
    preds = [forklift_predictor(forklift, v0 + k / 10 * (v1 - v0)) for k in range(11 if v1 != v0 else 1)]
    if v1 != v0 and not getattr(forklift, "route", None):
        preds.append(_Profile(forklift, v0, v1))
    return all(min_separation(pw, pf, cfg.horizon)[1] >= cfg.r_safe for pf in preds)


def truck_path_clear(worker_pos, forklift, cfg, speed):
    """Can the (stopped) forklift move off at `speed` (signed) without coming within r_safe
    of the worker standing at worker_pos?"""
    pw = CVPredictor(worker_pos, (0.0, 0.0))
    pf = forklift_predictor(forklift, speed)
    _, d_min = min_separation(pw, pf, cfg.horizon)
    return d_min >= cfg.r_safe


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


def assess(worker, forklift, cfg: RiskConfig, method="guidance_ctrv", occluded=False) -> PairRisk:
    if occluded and (cfg.occl_t_margin or cfg.occl_r_margin or cfg.occl_debounce):
        import dataclasses
        cfg = dataclasses.replace(cfg, t_danger=cfg.t_danger + cfg.occl_t_margin,
                                  t_warn=cfg.t_warn + cfg.occl_t_margin, r_safe=cfg.r_safe + cfg.occl_r_margin)
        r = _assess(worker, forklift, cfg, method)
        r.occluded = True
        if r.level > 0:
            r.reason += " (blind corner: no line of sight)"
        return r
    return _assess(worker, forklift, cfg, method)


def _assess(worker, forklift, cfg: RiskConfig, method="guidance_ctrv") -> PairRisk:
    enc = encounter(worker.pos, worker.vel, forklift.pos, forklift.vel, cfg.r_safe)
    moving = forklift.speed > cfg.moving_speed
    t_min, d_min = enc.tcpa, enc.dcpa
    scale = 1.0

    if method == "distance":
        level = 2 if enc.range < cfg.distance_threshold else 0
        reason = f"distance {enc.range:.1f} m vs threshold {cfg.distance_threshold:.1f} m"
        scale = 0.3 if level else 1.0          # zone systems drop the truck to creep speed
    elif method == "ttc":
        level = 3 if enc.ttc < cfg.ttc_danger else 2 if enc.ttc < cfg.ttc_warn else 0
        reason = f"TTC {enc.ttc:.1f} s"
        scale = 0.3 if level else 1.0
    else:
        if method in ("guidance_ctrv", "guidance_lstm"):
            pw = None
            if method == "guidance_lstm":
                from .learned import predictor_or_none
                pw = predictor_or_none(worker, forklift)
            # a worker standing still is predicted to stay put: at 0.1-0.35 m UWB noise the tracker's
            # velocity of a standing picker wanders by a few tenths of m/s, enough to "walk" him into
            # the lane within the warning horizon (most false alarms at pick faces)
            still = worker.speed < getattr(cfg, "still_speed", 0.0)
            pw = pw or CVPredictor(worker.pos, (0.0, 0.0) if still else worker.vel)
            pf = forklift_predictor(forklift)
            t_min, d_min = min_separation(pw, pf, cfg.horizon)
        elif t_min > cfg.horizon:
            t_min = INF
        level = _level_from_geometry(cfg, t_min, d_min, enc.range, moving)
        # only a (nearly) standing worker: someone walking across is covered by the
        # prediction and will usually be gone before the forklift arrives
        lane = (_lane_block(worker, forklift, cfg)
                if moving and method != "guidance" and worker.speed < cfg.stand_speed else None)
        if lane is not None and level < 2:
            level = 2
        if level >= 2 and moving:
            if method in ("guidance_ctrv", "guidance_lstm"):
                # The alert also tells the worker to stop, so plan the forklift for a
                # worker who walks on for the reaction time and then stops - possibly
                # right in the lane.  Take the stricter of: velocity obstacle against
                # that motion, and the stopping distance to where the paths meet.
                stopping = StopAfterPredictor(worker.pos, worker.vel, t_react=cfg.worker_react)
                bk = dict(a_dec=cfg.brake_decel, margin=cfg.brake_margin)
                scale = min(speed_scale_on_path(stopping, pf, cfg.r_safe, horizon=cfg.horizon),
                            braking_scale(stopping, pf, forklift.speed, cfg.r_safe, cfg.horizon, **bk))
                # the worker who does not stop: always for DANGER; for WARNING only when the tag
                # cannot hold the worker (cfg.trust_hold: WAIT-until-GO tags, sim/online_sim.Mover)
                if level >= 3 or not cfg.trust_hold:
                    scale = min(scale, braking_scale(pw, pf, forklift.speed, cfg.r_safe, cfg.horizon, **bk))
            else:
                scale = vo_speed_scale(worker.pos, worker.vel, forklift.pos, forklift.vel,
                                       cfg.r_safe, horizon=cfg.t_warn)
        if level == 0:
            reason = "clear"
        elif lane is not None and d_min >= cfg.r_safe:
            reason = f"worker in the forklift lane {lane:.1f} m ahead"
        elif d_min < cfg.r_safe:
            reason = (f"collision course: LOS rate {enc.los_rate:+.2f} rad/s, "
                      f"closing {enc.closing_speed:.1f} m/s, miss {d_min:.1f} m in {t_min:.1f} s")
        else:
            reason = f"near miss predicted: {d_min:.1f} m in {t_min:.1f} s"

    return PairRisk(worker.id, forklift.id, level, LEVELS[level], method, enc.range,
                    enc.closing_speed, enc.los_rate, enc.tcpa, enc.dcpa, enc.ttc,
                    t_min, d_min, scale, reason, _limit(scale, forklift.speed, cfg))


def _limit(scale, speed, cfg):
    """Absolute speed command; below cfg.min_move it is a stop (a truck creeping at a few cm/s
    still reaches a waiting worker, and drive controllers do not hold such speeds anyway)."""
    v = round(scale * speed, 2)
    return 0.0 if v < getattr(cfg, "min_move", 0.0) else v


class RiskEngine:
    """Keeps tracks and evaluates every worker x forklift pair."""

    def __init__(self, cfg: RiskConfig | None = None, method="guidance_ctrv", sitemap=None):
        self.cfg = cfg or RiskConfig()
        self.method = method
        self.tracks = {}
        self.sitemap = sitemap                 # edgeguard.sitemap.SiteMap or None

    def update(self, track_factory, obj_id, kind, t, **meas):
        tr = self.tracks.get(obj_id)
        if tr is None:
            tr = self.tracks[obj_id] = track_factory(obj_id, kind)
        if tr.update(t, **meas) is False:
            return False                     # late (out-of-order) sample, ignored by the track
        return tr

    def evaluate(self, method=None, stale_s=2.0, only=None, gate_m=None):
        """Assess worker x forklift pairs; tracks silent for `stale_s` are skipped.

        only   : evaluate just the pairs that involve this object id (the one that
                 sent the new sample) - keeps the cost per sample O(N) instead of O(N^2)
        gate_m : pairs farther apart than this (and not closing fast enough to get
                 near within the horizon) get a cheap SAFE result without prediction
        """
        import time
        method = method or self.method
        now = time.monotonic()
        live = [t for t in self.tracks.values()
                if t.x is not None and now - getattr(t, "last_seen", now) <= stale_s]
        workers = [t for t in live if t.kind == "worker"]
        lifts = [t for t in live if t.kind == "forklift"]
        if gate_m is None:
            gate_m = self.cfg.r_safe + self.cfg.m_caution + 1.0
        out = []
        for w in workers:
            for f in lifts:
                if only is not None and only not in (w.id, f.id):
                    continue
                dx, dy = w.pos[0] - f.pos[0], w.pos[1] - f.pos[1]
                reach = (w.speed + f.speed) * self.cfg.horizon + gate_m
                if dx * dx + dy * dy > reach * reach:
                    out.append(_far(w, f, method, math.hypot(dx, dy)))
                else:
                    occl = bool(self.sitemap) and self.sitemap.blocked(w.pos, f.pos)
                    out.append(assess(w, f, self.cfg, method, occluded=occl))
        return out


def _far(w, f, method, rng):
    """Pair that cannot meet within the horizon even head-on at current speeds."""
    return PairRisk(w.id, f.id, 0, LEVELS[0], method, rng, 0.0, 0.0, INF, rng, INF,
                    INF, rng, 1.0, "clear (out of reach)")
