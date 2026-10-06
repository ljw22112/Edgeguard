"""EdgeGuard MEC application.

Runs on the MEC host next to the site.  The CSE notifies it of every new
location / motion contentInstance; it updates the tracks, runs the guidance
risk engine and writes `risk` (summary) and `alert` (actions) back to the CSE,
where the worker tag and forklift module are subscribed.

    uvicorn mec_app.app:app --host 0.0.0.0 --port 9090
"""
from __future__ import annotations

import logging
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
from edgeguard.risk import RiskEngine, LEVELS         # noqa: E402
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


class AlertState:
    """Edge-triggered alerts with debounce and hold, per worker/forklift pair."""

    def __init__(self, debounce=2, refresh_s=1.0, hold_s=1.0):
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
    if kind not in ("worker", "forklift"):
        return
    t = p.get("ts", rx) / 1000.0
    meas = {"x": p["x"], "y": p["y"], "src_ts": p.get("ts")}
    if kind == "forklift":
        meas.update(speed=p.get("speed"), heading=p.get("heading"), yaw_rate=p.get("yaw_rate"))
    with lock:
        state["rx"] += 1
        if p.get("ts"):
            state["ingest_ms"].append(rx - p["ts"])
        engine.update(Track, p["id"], kind, t, **meas)
        risks = engine.evaluate()
        now = time.time()
        for r in risks:
            key = (r.worker, r.forklift)
            st = state["pairs"].setdefault(key, {"alert": AlertState()})
            st["risk"] = r
            ev = st["alert"].step(r.level, now)
            if ev:
                alert = {
                    "event": ev, "level": LEVELS[r.level],
                    "worker": r.worker, "forklift": r.forklift,
                    "actions": {r.worker: {"vibrate": ev != "clear" and r.level >= 2},
                                r.forklift: {"beacon": ev != "clear" and r.level >= 2,
                                             "speed_scale": 1.0 if ev == "clear" else r.speed_scale}},
                    "reason": r.reason, "metrics": r.to_dict(),
                    "src_ts": p.get("ts"), "mec_rx_ts": rx, "mec_tx_ts": now_ms(),
                }
                outbox.put_nowait((PATHS["alert"], alert))
                to_cloud("alert", alert)
                state["alerts_sent"] += 1
                state["alert_log"].appendleft({k: alert[k] for k in
                                               ("event", "level", "worker", "forklift", "reason",
                                                "mec_tx_ts")} | {"speed_scale": r.speed_scale})
                log.info("ALERT %s %s %s-%s: %s", ev, alert["level"], r.worker, r.forklift, r.reason)
        hz = MEC.get("risk_publish_hz", 2)
        if risks and now - state["last_risk_pub"] >= 1.0 / hz:
            state["last_risk_pub"] = now
            summary = {"ts": now_ms(), "pairs": [r.to_dict() for r in risks]}
            outbox.put_nowait((PATHS["risk"], summary))
            if now - state.get("last_cloud_risk", 0) >= 1.0 / CLOUD.get("risk_hz", 1):
                state["last_cloud_risk"] = now
                to_cloud("risk", summary)


app = FastAPI(title="EdgeGuard MEC App")


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
                      "vel": [round(v, 2) for v in t.vel],
                      "stale": now - getattr(t, "last_seen", now) > 2.0}
                  for k, t in engine.tracks.items() if t.x is not None}
        pairs = []
        for (wid, fid), s_ in state["pairs"].items():
            if "risk" not in s_:
                continue
            d = s_["risk"].to_dict()
            w, f = engine.tracks.get(wid), engine.tracks.get(fid)
            if w is not None and f is not None and w.x is not None and f.x is not None:
                d["worker_path"], d["forklift_path"] = _paths(w, f)
            pairs.append(d)
        ing = sorted(state["ingest_ms"])
        stats = {"samples": state["rx"], "alerts_sent": state["alerts_sent"],
                 "ingest_ms_median": ing[len(ing) // 2] if ing else None,
                 "method": engine.method, "r_safe": engine.cfg.r_safe}
        return {"tracks": tracks, "pairs": pairs, "alerts": list(state["alert_log"]),
                "stats": stats, "server_ms": now_ms()}


@app.get("/")
def dashboard():
    return FileResponse(os.path.join(STATIC, "dashboard.html"))
