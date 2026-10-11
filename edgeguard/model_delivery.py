"""Federated model delivery to the MEC apps: canary, activate, monitor, roll back (closing the FL loop).

The FL coordinator (edgeguard/fl.py) publishes every global model version in EdgeGuardFL/models.  At each
site the MEC app's ModelManager is subscribed to it.  For each new version it

  1. canary: evaluates the model on the site's own held-out walking data against the active model (or
     constant velocity when none is active) - a model that is not better by `margin` is rejected;
  2. activates it: the risk engine's worker predictor (method guidance_fl) uses it from the next sample;
  3. monitors it on live data, shadow-evaluating the previous version on the same windows - if the
     previous one is better by `margin` for `patience` windows in a row, it rolls back.

Every step is visible in oneM2M: <site AE>/model is an egs:mdlDp flexContainer (version, previous version,
status canary / active / rejected / rolled_back, canary / baseline / live error), with its history kept as
flexContainerInstances.
"""
from __future__ import annotations

import threading
import time

import numpy as np

from . import fl
from .onem2m import OneM2MClient

TP, CND = "egs:mdlDp", "org.edgeguard.safety.moduleclass.modelDeployment"


class ModelRegistry:
    """What the risk engine predicts with (process-wide)."""

    def __init__(self):
        self.version, self.w, self.uses, self.lock = None, None, 0, threading.Lock()

    def set(self, version, w):
        with self.lock:
            self.version, self.w = version, w

    def get(self):
        with self.lock:
            return self.version, self.w


REGISTRY = ModelRegistry()


class FLPredictor:
    """Worker positions from the active federated model: displacement at 1 s and 2 s from the last 0.8 s of
    10 Hz positions, linear in between, the 1-2 s velocity carried on after 2 s."""

    def __init__(self, hist, w):
        hist = np.asarray(hist, dtype=np.float32)
        vel = np.diff(hist[-(fl.H_IN + 1):], axis=0) / 0.1
        out = fl.predict(w, vel.ravel()[None, :])[0]
        self.origin = tuple(map(float, hist[-1]))
        self.p1 = (self.origin[0] + float(out[0]), self.origin[1] + float(out[1]))
        self.p2 = (self.origin[0] + float(out[2]), self.origin[1] + float(out[3]))

    def positions(self, times):
        (x0, y0), (x1, y1), (x2, y2) = self.origin, self.p1, self.p2
        out = []
        for t in times:
            if t <= 1.0:
                out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
            else:
                out.append((x1 + (x2 - x1) * (t - 1.0), y1 + (y2 - y1) * (t - 1.0)))
        return out


def predictor_or_none(worker_track):
    version, w = REGISTRY.get()
    if w is None:
        return None
    from .learned import resample
    hist = resample(getattr(worker_track, "history", ()))
    if hist is None or len(hist) < fl.H_IN + 1:
        return None
    REGISTRY.uses += 1
    return FLPredictor(hist, w)


class ModelManager:
    def __init__(self, c: OneM2MClient, site_ae, holdout, registry=REGISTRY, margin=0.02, patience=3, log=print):
        self.c, self.ae, self.holdout, self.reg = c, site_ae, holdout, registry
        self.margin, self.patience, self.log = margin, patience, log
        self.active = None            # (version, weights)
        self.previous = None
        self.history: list[dict] = []
        self.worse = 0
        self.lock = threading.Lock()

    def setup(self):
        self.c.create_ae(self.ae, api="Nedgeguard.mec", lbl=["egs:fl/site"])
        self.c.create_fcnt(self.ae, TP, "model", CND, {"dplSt": "none"}, lbl=["egs:fl/deployment"], mni=50)
        return self

    def _status(self, **attrs):
        self.c.update_fcnt(f"{self.ae}/model", TP, attrs)

    def _err(self, w, X, Y):
        return fl.ade(w, X, Y)

    def on_model(self, con):
        """A new global model (contentInstance of EdgeGuardFL/models)."""
        with self.lock:
            v = int(con["version"])
            if self.active and v <= self.active[0]:
                return "old"
            w = fl.unpack(con["weights"])
            X, Y = self.holdout
            cand = self._err(w, X, Y)
            base = self._err(self.active[1] if self.active else None, X, Y)
            self._status(mdlVr=v, dplSt="canary", cnyEr=round(cand, 4), bslEr=round(base, 4))
            if cand < base * (1 - self.margin):
                self.previous, self.active, self.worse = self.active, (v, w), 0
                self.reg.set(v, w)
                self._status(mdlVr=v, prvVr=self.previous[0] if self.previous else -1, dplSt="active",
                             cnyEr=round(cand, 4), bslEr=round(base, 4))
                dec = "active"
            else:
                self._status(mdlVr=self.active[0] if self.active else -1, dplSt="rejected", cnyEr=round(cand, 4), bslEr=round(base, 4))
                dec = "rejected"
            self.history.append({"t": time.time(), "version": v, "decision": dec, "canary_err": round(cand, 3),
                                 "baseline_err": round(base, 3)})
            self.log(f"model v{v}: canary {cand:.3f} m vs {base:.3f} m -> {dec}")
            return dec

    def observe(self, X, Y):
        """A window of live data (the site's recent worker tracks): live error of the active model, shadow
        error of the previous one; roll back after `patience` windows in which the previous one is better."""
        with self.lock:
            if not self.active:
                return None
            live = self._err(self.active[1], X, Y)
            prev = self._err(self.previous[1] if self.previous else None, X, Y)
            self.worse = self.worse + 1 if prev < live * (1 - self.margin) else 0
            out = {"version": self.active[0], "live_err": round(live, 3), "previous_err": round(prev, 3), "worse": self.worse}
            if self.worse >= self.patience:
                bad = self.active[0]
                if self.previous:
                    self.active, self.previous = self.previous, None
                    self.reg.set(*self.active)
                else:
                    self.active = None
                    self.reg.set(None, None)
                self.worse = 0
                self._status(mdlVr=self.active[0] if self.active else -1, prvVr=bad, dplSt="rolled_back",
                             lvErr=round(live, 4), bslEr=round(prev, 4))
                self.history.append({"t": time.time(), "version": bad, "decision": "rolled_back",
                                     "live_err": round(live, 3), "previous_err": round(prev, 3),
                                     "now_active": self.active[0] if self.active else None})
                self.log(f"model v{bad}: live {live:.3f} m vs previous {prev:.3f} m -> rolled back")
                out["rolled_back"] = True
            else:
                self._status(lvErr=round(live, 4))
            return out
