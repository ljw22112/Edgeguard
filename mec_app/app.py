"""EdgeGuard MEC application.

Runs on the MEC host next to the site.  The CSE notifies it of every new
location / motion contentInstance; it updates the tracks, runs the guidance
risk engine and writes `risk` (summary) and `alert` (actions) back to the CSE,
where the worker tag and forklift module are subscribed.

    uvicorn mec_app.app:app --host 0.0.0.0 --port 9090
"""
from __future__ import annotations

import logging
import math
import os
import queue
import sys
import threading
import time
from collections import deque

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard import config                          # noqa: E402
from edgeguard.onem2m import parse_notification, now_ms  # noqa: E402
from edgeguard.risk import RiskEngine, LEVELS, waiting_at_lane  # noqa: E402
from edgeguard.tracking import Track                  # noqa: E402

log = logging.getLogger("edgeguard.mec")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CFG = config.load()
PATHS = config.paths(CFG)
MEC = CFG["mec"]
engine = RiskEngine(config.risk_config(CFG), method=MEC.get("method", "guidance_ctrv"))
cse = config.client(CFG)
outbox: "queue.Queue[tuple[str, dict]]" = queue.Queue(maxsize=1000)
state = {"pairs": {}, "last_risk_pub": 0.0, "alerts_sent": 0, "rx": 0,
         "network": {"cell_load": None, "congested": False}, "location_fixes": 0,
         "alert_log": deque(maxlen=60), "ingest_ms": deque(maxlen=200)}
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
lock = threading.Lock()


def publisher():
    """Write contentInstances to the CSE off the request path."""
    while True:
        path, con = outbox.get()
        delay = MEC.get("emulated_extra_delay_ms", 0)
        if delay:
            time.sleep(delay / 1000)
        try:
            cse.create_cin(path, con)
        except Exception as e:                       # keep the loop alive
            log.warning("publish to %s failed: %s", path, e)


threading.Thread(target=publisher, daemon=True).start()

# Optional cloud sync: risk summaries and alerts copied to the cloud IN-CSE.
# Runs on its own queue so a slow or broken WAN never delays local alerts.
CLOUD = CFG.get("cloud_sync") or {}
cloud_box: "queue.Queue[tuple[str, dict]]" = queue.Queue(maxsize=500)
state["cloud"] = {"sent": 0, "failed": 0, "dropped": 0}
if CLOUD.get("enabled"):
    from edgeguard.onem2m import OneM2MClient
    cloud = OneM2MClient(CLOUD["base_url"], CLOUD["cse_rn"], CLOUD.get("origin", CFG["cse"]["origin"]),
                         str(CLOUD.get("rvi", "2a")), timeout=2.0)
    CLOUD_AE = CLOUD.get("ae", "EdgeGuard")

    def cloud_worker():
        ready = False
        while True:
            path, con = cloud_box.get()
            try:
                if not ready:
                    cloud.create_ae(CLOUD_AE)
                    for c in ("risk", "alert"):
                        cloud.create_container(CLOUD_AE, c)
                    ready = True
                cloud.create_cin(f"{CLOUD_AE}/{path}", con)
                state["cloud"]["sent"] += 1
            except Exception as e:
                state["cloud"]["failed"] += 1
                log.warning("cloud sync failed (%s): %s", path, e)

    threading.Thread(target=cloud_worker, daemon=True).start()


def to_cloud(kind, con):
    if not CLOUD.get("enabled"):
        return
    try:
        cloud_box.put_nowait((kind, con))
    except queue.Full:
        state["cloud"]["dropped"] += 1


# --- ETSI MEC services: Location API fallback + RNIS-aware alert margin ---------------
MS = CFG.get("mec_services") or {}
BASE_T = (engine.cfg.t_danger, engine.cfg.t_warn)


def mec_services_loop():
    from edgeguard.mec_services import LocationClient, RnisClient, SiteFrame
    frame = SiteFrame(MS["origin"]["lat"], MS["origin"]["lon"])
    loc = LocationClient(MS["base_url"], MS.get("location_api", "location/v3"), frame=frame)
    rnis = RnisClient(MS["base_url"], MS.get("rnis_api", "rni/v2"))
    users = MS.get("users", {})                    # worker id -> UE address (e.g. acr:10.0.0.1)
    stale_s = MS.get("uwb_stale_s", 0.5)
    last_rnis = 0.0
    while True:
        now = time.monotonic()
        for wid, addr in users.items():
            tr = engine.tracks.get(wid)
            seen = getattr(tr, "uwb_seen", None) if tr else None
            if seen is not None and now - seen < stale_s:
                continue                           # UWB is fine, no need for a coarse fix
            try:
                u = loc.user(addr)
            except Exception as e:
                log.debug("location query failed: %s", e)
                continue
            if u:
                state["location_fixes"] += 1
                handle_sample({"id": wid, "kind": "worker", "ts": now_ms(), "x": u["x"], "y": u["y"],
                               "pos_sigma": max(0.3, u["accuracy"]), "source": "mec-location"})
        if now - last_rnis >= MS.get("rnis_poll_s", 1.0):
            last_rnis = now
            try:
                load = rnis.cell_load(MS.get("cell_id"))
            except Exception:
                load = None
            congested = load is not None and load >= MS.get("congestion_prb_pct", 80)
            if congested != state["network"]["congested"]:
                log.info("RNIS: cell load %s%% -> %s", load, "congested" if congested else "normal")
            state["network"] = {"cell_load": load, "congested": congested}
            margin = MS.get("congested_margin_s", 0.5) if congested else 0.0
            engine.cfg.t_danger, engine.cfg.t_warn = BASE_T[0] + margin, BASE_T[1] + margin
        time.sleep(MS.get("poll_s", 0.25))


class AlertState:
    """Edge-triggered alerts with debounce and hold, per worker/forklift pair."""

    def __init__(self, debounce=2, refresh_s=1.0, hold_s=2.0):
        self.level, self.streak, self.last_sent, self.below_since = 0, 0, 0.0, None
        self.debounce, self.refresh_s, self.hold_s = debounce, refresh_s, hold_s

    def step(self, level, now):
        """Return 'raise', 'refresh', 'clear' or None."""
        if level >= 2:
            self.below_since = None
            self.streak += 1
            fire = level == 3 or self.streak >= self.debounce
            if fire and level > self.level:
                self.level, self.last_sent = level, now
                return "raise"
            if fire and now - self.last_sent >= self.refresh_s:
                self.level, self.last_sent = level, now        # may step down DANGER -> WARNING
                return "refresh"
            return None
        self.streak = 0
        if self.level >= 2:
            self.below_since = self.below_since or now
            if now - self.below_since >= self.hold_s:
                self.level, self.below_since = level, None
                return "clear"
        else:
            self.level = level
        return None


def handle_sample(p: dict):
    rx = now_ms()
    kind = p.get("kind")
    if kind == "camera":
        return handle_camera(p, rx)
    if kind not in ("worker", "forklift"):
        return
    t = p.get("ts", rx) / 1000.0
    meas = {"x": p["x"], "y": p["y"], "src_ts": p.get("ts"),
            "pos_sigma": p.get("pos_sigma"), "source": p.get("source", "uwb")}
    if kind == "forklift":
        meas.update(speed=p.get("speed"), heading=p.get("heading"), yaw_rate=p.get("yaw_rate"))
    with lock:
        state["rx"] += 1
        if p.get("ts"):
            state["ingest_ms"].append(rx - p["ts"])
        engine.update(Track, p["id"], kind, t, **meas)
        evaluate_and_alert(p.get("ts"), rx, only=p["id"])


CAM = CFG.get("camera") or {}
PASS_SPEED = 1.0          # m/s: forklift speed when passing a worker waiting at the lane edge
state["untagged_seq"] = 0
state["camera"] = {"frames": 0, "matched": 0, "untagged": 0}


def handle_camera(p: dict, rx: int):
    """Fuse camera person detections with the tag tracks.

    A detection near a tagged worker is the same person (the tag already covers
    them).  Anyone else is a worker without a working tag: they get an
    `untagged_N` track so forklift alerts still fire (they cannot be vibrated)."""
    gate = CAM.get("fuse_gate_m", 1.5)
    t = p.get("ts", rx) / 1000.0
    now = time.monotonic()
    with lock:
        state["rx"] += 1
        state["camera"]["frames"] += 1
        tagged = [tr for tr in engine.tracks.values()
                  if tr.kind == "worker" and tr.x is not None and not tr.id.startswith("untagged_")
                  and now - getattr(tr, "uwb_seen", 0) < 1.0]
        untagged = [tr for tr in engine.tracks.values()
                    if tr.id.startswith("untagged_") and tr.x is not None and now - tr.last_seen < 2.0]
        used = set()
        for d in p.get("persons", []):
            x, y = d["x"], d["y"]
            if any(math.hypot(tr.pos[0] - x, tr.pos[1] - y) < gate for tr in tagged):
                state["camera"]["matched"] += 1
                continue
            best = min((tr for tr in untagged if tr.id not in used),
                       key=lambda tr: math.hypot(tr.pos[0] - x, tr.pos[1] - y), default=None)
            if best is not None and math.hypot(best.pos[0] - x, best.pos[1] - y) < 2.0:
                tid = best.id
            else:
                state["untagged_seq"] += 1
                tid = f"untagged_{state['untagged_seq']}"
                state["camera"]["untagged"] += 1
            used.add(tid)
            engine.update(Track, tid, "worker", t, x=x, y=y, src_ts=p.get("ts"),
                          pos_sigma=CAM.get("pos_sigma", 0.4), source="camera")
        evaluate_and_alert(p.get("ts"), rx)


def evaluate_and_alert(src_ts, rx, only=None):
    """Assess the pairs touched by the new sample and emit alerts; caller holds `lock`."""
    risks = engine.evaluate(only=only)
    now = time.time()
    for r in risks:
        key = (r.worker, r.forklift)
        st = state["pairs"].setdefault(key, {"alert": AlertState()})
        st["alert"].refresh_s = 0.5 if state["network"]["congested"] else 1.0
        if r.level < 2 and st["alert"].level >= 2:
            w_tr, f_tr = engine.tracks.get(r.worker), engine.tracks.get(r.forklift)
            if w_tr is not None and f_tr is not None and f_tr.speed > 0.2 \
                    and waiting_at_lane(w_tr, f_tr, engine.cfg):
                # keep the alert: pass the waiting worker at walking pace
                limit = round(min(PASS_SPEED, f_tr.speed), 2)
                r.level, r.level_name = 2, LEVELS[2]
                r.reason = "worker waiting at the lane edge: pass at walking pace"
                r.speed_limit, r.speed_scale = limit, round(limit / max(f_tr.speed, 1e-6), 2)
                r.hold = True
        st["risk"] = r
        ev = st["alert"].step(r.level, now)
        # a tighter speed limit must reach the forklift now, not at the next periodic refresh
        if ev is None and r.level >= 2 and st["alert"].level >= 2 and r.speed_limit is not None \
                and st.get("sent_limit") is not None and r.speed_limit < st["sent_limit"] - 0.3:
            ev = "refresh"
            st["alert"].last_sent = now
        if ev:
            st["sent_limit"] = None if ev == "clear" else r.speed_limit
        if ev:
            untagged = r.worker.startswith("untagged_")
            # vibrate on a new or escalated alert and while DANGER; not on every refresh
            # or hold, so a worker who has stopped is not buzzed every second
            # (the speed limit assumes the worker stops when buzzed, so keep buzzing a
            # worker who is still walking into the conflict)
            w_tr = engine.tracks.get(r.worker)
            walking_in = w_tr is not None and w_tr.speed > 0.3 and r.closing_speed > 0.2
            buzz = ev == "raise" or (ev == "refresh" and not getattr(r, "hold", False)
                                     and (r.level >= 3 or walking_in))
            alert = {
                "event": ev, "level": LEVELS[r.level],
                "worker": r.worker, "forklift": r.forklift,
                "actions": {r.worker: {"vibrate": buzz and not untagged},
                            r.forklift: {"beacon": ev != "clear" and r.level >= 2,
                                         "speed_scale": 1.0 if ev == "clear" else r.speed_scale,
                                         # absolute limit: a ratio of an already reduced speed
                                         # would let the truck speed up again
                                         "speed_limit": None if ev == "clear" else r.speed_limit}},
                "reason": r.reason + (" (person seen by camera, no tag)" if untagged else ""),
                "metrics": r.to_dict(),
                "pos": {k: [round(v, 2) for v in engine.tracks[k].pos] for k in (r.worker, r.forklift)
                        if k in engine.tracks and engine.tracks[k].x is not None},
                "src_ts": src_ts, "mec_rx_ts": rx, "mec_tx_ts": now_ms(),
            }
            outbox.put_nowait((PATHS["alert"], alert))
            to_cloud("alert", alert)
            state["alerts_sent"] += 1
            state["alert_log"].appendleft({k: alert[k] for k in
                                           ("event", "level", "worker", "forklift", "reason",
                                            "mec_tx_ts")} | {"speed_scale": r.speed_scale})
            log.info("ALERT %s %s %s-%s: %s", ev, alert["level"], r.worker, r.forklift, alert["reason"])
    hz = MEC.get("risk_publish_hz", 2)
    if risks and now - state["last_risk_pub"] >= 1.0 / hz:
        state["last_risk_pub"] = now
        summary = {"ts": now_ms(), "pairs": [s_["risk"].to_dict() for s_ in state["pairs"].values()
                                             if "risk" in s_ and s_["risk"].level > 0]}
        outbox.put_nowait((PATHS["risk"], summary))
        if now - state.get("last_cloud_risk", 0) >= 1.0 / CLOUD.get("risk_hz", 1):
            state["last_cloud_risk"] = now
            to_cloud("risk", summary)


app = FastAPI(title="EdgeGuard MEC App")


@app.on_event("startup")
def _start_mec_services():
    if MS.get("enabled"):
        threading.Thread(target=mec_services_loop, daemon=True).start()


@app.post("/notify")
async def notify(req: Request):
    body = await req.json()
    kind, payload = parse_notification(body)
    if kind == "cin" and isinstance(payload, dict):
        handle_sample(payload)
    return Response(status_code=200, headers={"X-M2M-RSC": "2000"})


@app.get("/health")
def health():
    ing = sorted(state["ingest_ms"])
    return {"ok": True, "method": engine.method, "samples": state["rx"],
            "alerts_sent": state["alerts_sent"], "cloud": state["cloud"],
            "network": state["network"], "location_fixes": state["location_fixes"],
            "camera": state["camera"],
            "ingest_ms_median": ing[len(ing) // 2] if ing else None}


def _paths(w, f):
    """Predicted paths for the dashboard (same predictors as the risk engine)."""
    from edgeguard.predict import CVPredictor, CTRVPredictor
    from edgeguard.risk import _heading
    times = [i * 0.25 for i in range(13)]                  # 0 .. 3 s
    pw = None
    if engine.method == "guidance_lstm":
        from edgeguard.learned import predictor_or_none
        pw = predictor_or_none(w, f)
    pw = pw or CVPredictor(w.pos, w.vel)
    pf = CTRVPredictor(f.pos, f.speed, _heading(f), f.yaw_rate)
    rnd = lambda pts: [[round(x, 2), round(y, 2)] for x, y in pts]   # noqa: E731
    return rnd(pw.positions(times)), rnd(pf.positions(times))


@app.get("/state")
def snapshot():
    with lock:
        now = time.monotonic()
        tracks = {k: {"kind": t.kind, "pos": [round(v, 2) for v in t.pos],
                      "source": getattr(t, "source", "uwb"),
                      "vel": [round(v, 2) for v in t.vel],
                      "stale": now - getattr(t, "last_seen", now) > 2.0}
                  for k, t in engine.tracks.items() if t.x is not None}
        pairs = []
        for (wid, fid), s_ in state["pairs"].items():
            if "risk" not in s_:
                continue
            d = s_["risk"].to_dict()
            w, f = engine.tracks.get(wid), engine.tracks.get(fid)
            if any(t_ is None or t_.x is None or now - getattr(t_, "last_seen", now) > 2.0 for t_ in (w, f)):
                continue                             # one side went silent: drop the pair card
            if True:
                d["worker_path"], d["forklift_path"] = _paths(w, f)
            pairs.append(d)
        ing = sorted(state["ingest_ms"])
        stats = {"samples": state["rx"], "alerts_sent": state["alerts_sent"],
                 "ingest_ms_median": ing[len(ing) // 2] if ing else None,
                 "method": engine.method, "r_safe": engine.cfg.r_safe,
                 "network": state["network"], "location_fixes": state["location_fixes"]}
        return {"tracks": tracks, "pairs": pairs, "alerts": list(state["alert_log"]),
                "stats": stats, "server_ms": now_ms()}


@app.get("/")
def dashboard():
    return FileResponse(os.path.join(STATIC, "dashboard.html"))
