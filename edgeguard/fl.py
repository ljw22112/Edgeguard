"""Federated learning coordinated through oneM2M (oneM2M TR-0084 roles), for the worker-motion predictor.

Why federated: worker trajectories are personal data.  Each site (the MEC host of a warehouse) trains
on its own walking data and only model weights leave the site; the coordinator never sees a position.

Model: a small MLP that predicts a worker's displacement 1 s and 2 s ahead from the last 0.8 s of
velocity (what the risk engine's constant-velocity guess gets wrong at stops and turns).

oneM2M resources (IN-CSE; SDT types egs:flTsk / egs:flPrt in config/onem2m/edgeguard.fcp):

  EdgeGuardFL (AE, coordinator)
    task          egs:flTsk     model, rounds, clients per round, quorum, timeout, status, model version
    rounds        CNT           one CIN per round: {round, selected, model_version, deadline}
    models        CNT           one CIN per global model version: {version, parent, round, participants,
                                weights, metrics}   (model lineage)
  fl_<site> (AE, one per client, created by the client)
    participant   egs:flPrt     sample count, availability, compute score, last round, model version
    updates       CNT           one CIN per round it trained: {round, n, weights, loss}
  subscriptions   clients -> rounds (selection), coordinator -> every updates container

Coordinator: discovers participants by label (egs:fl/participant), selects up to `cpr` available
clients with enough samples (preferring the ones that waited longest), waits for updates until the
round timeout, aggregates with FedAvg if at least `quorum` arrived (else repeats the round), publishes
the new version.  Clients that drop out are skipped; clients that register later join the next round.
"""
from __future__ import annotations

import base64
import json
import math
import random
import threading
import time

import numpy as np

H_IN, HORIZONS = 8, (1.0, 2.0)          # 8 past velocity samples (0.8 s at 10 Hz) -> displacement at 1 s, 2 s
N_IN, N_OUT, N_HID = 2 * H_IN, 2 * len(HORIZONS), 24


# --- data: walking traces, different per site (aisle layout, pace, how often people stop / turn) -----
SITES = {
    "seoul":   dict(aisle=4.0, speed=1.25, p_stop=0.20, p_turn=0.55, stop_s=(1.0, 3.0)),
    "busan":   dict(aisle=6.0, speed=1.45, p_stop=0.10, p_turn=0.35, stop_s=(0.5, 2.0)),
    "incheon": dict(aisle=3.0, speed=1.05, p_stop=0.35, p_turn=0.65, stop_s=(1.5, 4.0)),
    "daejeon": dict(aisle=5.0, speed=1.30, p_stop=0.25, p_turn=0.45, stop_s=(1.0, 2.5)),
}


def walk(site, seconds, rng, dt=0.1):
    """A worker walking a rectangular aisle grid: straight legs, decelerating into stops and turns."""
    p = SITES[site]
    x, y, heading = 0.0, 0.0, rng.choice([0.0, math.pi / 2, math.pi, -math.pi / 2])
    v, target_v, pts = 0.0, p["speed"] * rng.uniform(0.85, 1.15), []
    leg = p["aisle"] * rng.integers(1, 4)
    pause, travelled = 0.0, 0.0
    for _ in range(int(seconds / dt)):
        if pause > 0:
            pause -= dt
            v = max(0.0, v - 1.5 * dt)
        else:
            left = leg - travelled
            want = target_v if left > 1.2 else target_v * max(0.15, left / 1.2)   # slow down at the end of a leg
            v += np.clip(want - v, -1.5 * dt, 1.0 * dt)
            travelled += v * dt
            if travelled >= leg:
                travelled, leg = 0.0, p["aisle"] * rng.integers(1, 4)
                if rng.random() < p["p_turn"]:
                    heading += rng.choice([math.pi / 2, -math.pi / 2])
                if rng.random() < p["p_stop"]:
                    pause = rng.uniform(*p["stop_s"])
                target_v = p["speed"] * rng.uniform(0.85, 1.15)
        x += v * math.cos(heading) * dt + rng.normal(0, 0.01)
        y += v * math.sin(heading) * dt + rng.normal(0, 0.01)
        pts.append((x, y))
    return np.array(pts)


def windows(track, dt=0.1):
    """(features, targets): last H_IN velocities -> displacement after each horizon (worker frame free)."""
    vel = np.diff(track, axis=0) / dt
    steps = [int(round(h / dt)) for h in HORIZONS]
    X, Y = [], []
    for i in range(H_IN, len(vel) - max(steps)):
        X.append(vel[i - H_IN:i].ravel())
        pos = track[i]
        Y.append(np.concatenate([track[i + s] - pos for s in steps]))
    return np.array(X, dtype=np.float32), np.array(Y, dtype=np.float32)


def site_data(site, seconds, seed):
    rng = np.random.default_rng(seed)
    Xs, Ys = [], []
    for _ in range(max(1, int(seconds // 120))):
        X, Y = windows(walk(site, 120, rng))
        Xs.append(X)
        Ys.append(Y)
    return np.concatenate(Xs), np.concatenate(Ys)


# --- model -------------------------------------------------------------------------------------
def init_weights(seed=0):
    r = np.random.default_rng(seed)
    return {"W1": (r.normal(0, 1, (N_IN, N_HID)) / math.sqrt(N_IN)).astype(np.float32),
            "b1": np.zeros(N_HID, np.float32),
            "W2": (r.normal(0, 1, (N_HID, N_OUT)) / math.sqrt(N_HID)).astype(np.float32),
            "b2": np.zeros(N_OUT, np.float32)}


def cv_guess(X):
    """Constant velocity: what the risk engine assumes without a learned model."""
    v = X[:, -2:]
    return np.concatenate([v * h for h in HORIZONS], axis=1)


def predict(w, X):
    h = np.tanh(X @ w["W1"] + w["b1"])
    return cv_guess(X) + h @ w["W2"] + w["b2"]            # residual on top of constant velocity


def ade(w, X, Y):
    """Average displacement error at the 2 s horizon (m)."""
    P = cv_guess(X) if w is None else predict(w, X)
    return float(np.mean(np.linalg.norm(P[:, -2:] - Y[:, -2:], axis=1)))


def train(w, X, Y, epochs=30, lr=0.01, batch=128, seed=0):
    """Local training (Adam on mean squared error); returns new weights and the final loss."""
    w = {k: v.copy() for k, v in w.items()}
    m = {k: np.zeros_like(v) for k, v in w.items()}
    s = {k: np.zeros_like(v) for k, v in w.items()}
    r, t, loss = np.random.default_rng(seed), 0, 0.0
    for _ in range(epochs):
        idx = r.permutation(len(X))
        for j in range(0, len(X), batch):
            b = idx[j:j + batch]
            x, y = X[b], Y[b]
            z = x @ w["W1"] + w["b1"]
            h = np.tanh(z)
            err = cv_guess(x) + h @ w["W2"] + w["b2"] - y
            loss = float(np.mean(err ** 2))
            g2 = 2 * err / len(b)
            grads = {"W2": h.T @ g2, "b2": g2.sum(0)}
            gh = g2 @ w["W2"].T * (1 - h ** 2)
            grads.update(W1=x.T @ gh, b1=gh.sum(0))
            t += 1
            for k in w:
                m[k] = 0.9 * m[k] + 0.1 * grads[k]
                s[k] = 0.999 * s[k] + 0.001 * grads[k] ** 2
                w[k] -= lr * (m[k] / (1 - 0.9 ** t)) / (np.sqrt(s[k] / (1 - 0.999 ** t)) + 1e-8)
    return w, loss


def fedavg(updates):
    """updates: [(n_samples, weights)] -> sample-weighted average."""
    total = sum(n for n, _ in updates)
    return {k: sum(n * w[k] for n, w in updates) / total for k in updates[0][1]}


def pack(w):
    arr = np.concatenate([w[k].ravel() for k in ("W1", "b1", "W2", "b2")]).astype(np.float32)
    return base64.b64encode(arr.tobytes()).decode()


def unpack(b64):
    arr = np.frombuffer(base64.b64decode(b64), dtype=np.float32)
    out, i = {}, 0
    for k, shape in (("W1", (N_IN, N_HID)), ("b1", (N_HID,)), ("W2", (N_HID, N_OUT)), ("b2", (N_OUT,))):
        n = int(np.prod(shape))
        out[k] = arr[i:i + n].reshape(shape).copy()
        i += n
    return out


# --- oneM2M roles --------------------------------------------------------------------------------
COORD = "EdgeGuardFL"
TASK_CND = "org.edgeguard.safety.moduleclass.federatedLearningTask"
PRT_CND = "org.edgeguard.safety.moduleclass.federatedLearningParticipant"


class Coordinator:
    def __init__(self, cse, notify_url, rounds=6, cpr=3, quorum=2, min_samples=500, local_epochs=8,
                 lr=0.01, timeout=6.0, seed=0, log=print):
        self.c, self.nu, self.log = cse, notify_url, log
        self.cfg = dict(rounds=rounds, cpr=cpr, quorum=quorum, min_samples=min_samples,
                        local_epochs=local_epochs, lr=lr, timeout=timeout)
        self.rng = random.Random(seed)
        self.w = init_weights(seed)
        self.version, self.updates, self.lock = 0, {}, threading.Lock()
        self.waited, self.history = {}, []
        self.subscribed = set()

    def setup(self):
        c = self.c
        c.delete(COORD)
        c.create_ae(COORD, "Nedgeguard.fl", lbl=["egs:fl/coordinator"])
        c.create_fcnt(COORD, "egs:flTsk", "task", TASK_CND,
                      {"mdlNm": "worker-motion-mlp", "rnds": self.cfg["rounds"], "curRd": 0, "cpr": self.cfg["cpr"],
                       "quorm": self.cfg["quorum"], "minSm": self.cfg["min_samples"], "lclEp": self.cfg["local_epochs"],
                       "lrnRt": self.cfg["lr"], "rdTmo": self.cfg["timeout"], "tskSt": "created", "mdlVr": 0},
                      lbl=["egs:fl/task"])
        c.create_container(COORD, "rounds", mni=100)
        c.create_container(COORD, "models", mni=100)
        from .onem2m import RETRIEVE, DISCOVERY, NOTIFY, CREATE, ALL_OPS
        # clients may read the task, rounds and models and subscribe - CREATE is limited to subscriptions
        acp = c.create_acp(COORD, "acp_fl", [([c.origin], ALL_OPS),
                                             (["Sfl*"], RETRIEVE | DISCOVERY | NOTIFY | CREATE, (23,))], [c.origin])
        for path, tp in (("task", "egs:flTsk"), ("rounds", "m2m:cnt"), ("models", "m2m:cnt")):
            c.set_acpi(f"{COORD}/{path}", f"{COORD}/acp_fl", acp.get("ri"), tp=tp)
        self._publish_model(round_=0, participants=[], metrics={})

    def participants(self):
        """Discovery by label, then the participants' own status."""
        out = []
        for path in self.c.discover_label("egs:fl/participant", ty=28):
            try:
                p = self.c.request("GET", path)["egs:flPrt"]
            except Exception:
                continue
            ae = path.split("/")[0]
            out.append({"ae": ae, "path": path, **p})
            if ae not in self.subscribed:           # follow its updates container
                self.c.create_subscription(f"{ae}/updates", "sub_coord", [f"{self.nu}/{ae}"])
                self.subscribed.add(ae)
        return out

    def select(self, parts):
        ok = [p for p in parts if p.get("avail") and p.get("smpCt", 0) >= self.cfg["min_samples"]]
        ok.sort(key=lambda p: (-self.waited.get(p["ae"], 0), -p.get("cmpSc", 0.0), self.rng.random()))
        sel = [p["ae"] for p in ok[:self.cfg["cpr"]]]
        for p in ok:
            self.waited[p["ae"]] = 0 if p["ae"] in sel else self.waited.get(p["ae"], 0) + 1
        return sel, ok

    def on_update(self, ae, con):
        with self.lock:
            self.updates.setdefault(con["round"], {})[ae] = con

    def run_round(self, r):
        parts = self.participants()
        sel, eligible = self.select(parts)
        self.c.update_fcnt(f"{COORD}/task", "egs:flTsk", {"curRd": r, "tskSt": "training"})
        deadline = time.time() + self.cfg["timeout"]
        self.c.create_cin(f"{COORD}/rounds", {"round": r, "selected": sel, "model_version": self.version,
                                              "deadline_ms": int(deadline * 1000), "epochs": self.cfg["local_epochs"],
                                              "lr": self.cfg["lr"]})
        while time.time() < deadline:
            with self.lock:
                got = set(self.updates.get(r, {}))
            if set(sel) <= got:
                break
            time.sleep(0.1)
        with self.lock:
            ups = dict(self.updates.get(r, {}))
        ups = {a: u for a, u in ups.items() if a in sel and u.get("base_version") == self.version}
        rec = {"round": r, "eligible": [p["ae"] for p in eligible], "selected": sel, "received": sorted(ups),
               "dropped": sorted(set(sel) - set(ups))}
        if len(ups) >= self.cfg["quorum"]:
            self.w = fedavg([(u["n"], unpack(u["weights"])) for u in ups.values()])
            self.version += 1
            rec.update(aggregated=True, version=self.version)
            self._publish_model(r, sorted(ups), {"train_loss": round(float(np.mean([u["loss"] for u in ups.values()])), 5)})
        else:
            rec.update(aggregated=False, version=self.version)
        self.history.append(rec)
        self.log(f"round {r}: selected {sel}, received {sorted(ups)}"
                 + (f", dropped {rec['dropped']}" if rec["dropped"] else "")
                 + (f" -> model v{self.version}" if rec["aggregated"] else " -> below quorum, model kept"))
        return rec

    def _publish_model(self, round_, participants, metrics):
        self.c.create_cin(f"{COORD}/models", {"version": self.version, "parent": max(0, self.version - 1),
                                              "round": round_, "participants": participants,
                                              "weights": pack(self.w), "metrics": metrics})
        self.c.update_fcnt(f"{COORD}/task", "egs:flTsk", {"mdlVr": self.version})

    def run(self):
        r = 1
        while len([h for h in self.history if h.get("aggregated")]) < self.cfg["rounds"] and r <= 3 * self.cfg["rounds"]:
            self.run_round(r)
            r += 1
        self.c.update_fcnt(f"{COORD}/task", "egs:flTsk", {"tskSt": "done"})
        return self.w


class Client:
    """One site's FL client: its data never leaves this object; only weights go to oneM2M."""

    def __init__(self, cse, site, X, Y, notify_url, compute=1.0, log=print):
        self.c, self.site, self.X, self.Y, self.nu, self.compute, self.log = cse, site, X, Y, notify_url, compute, log
        self.ae = f"fl_{site}"
        self.online, self.version, self.rounds_done = True, 0, []
        self.crash_next = False              # demo: the next selected round fails mid-training

    def register(self):
        c = self.c
        c.delete(self.ae)
        c.create_ae(self.ae, "Nedgeguard.flclient", lbl=["egs:fl/client", f"egs:site/{self.site}"])
        c.create_fcnt(self.ae, "egs:flPrt", "participant", PRT_CND,
                      {"site": self.site, "smpCt": int(len(self.X)), "avail": True, "cmpSc": self.compute,
                       "lstRd": 0, "mdlVr": 0, "prtSt": "idle"}, lbl=["egs:fl/participant", f"egs:site/{self.site}"])
        c.create_container(self.ae, "updates", mni=20)
        from .onem2m import RETRIEVE, DISCOVERY, NOTIFY, ALL_OPS
        from .onem2m import CREATE
        # the coordinator may read the participant and the updates and subscribe (CREATE: subscriptions only)
        acp = c.create_acp(self.ae, "acp_fl", [([c.origin], ALL_OPS),
                                               (["SEdgeGuardFL"], RETRIEVE | DISCOVERY | NOTIFY | CREATE, (23,))], [c.origin])
        for path, tp in (("participant", "egs:flPrt"), ("updates", "m2m:cnt")):
            c.set_acpi(f"{self.ae}/{path}", f"{self.ae}/acp_fl", acp.get("ri"), tp=tp)
        c.create_subscription(f"{COORD}/rounds", f"sub_{self.site}", [self.nu])

    def set_online(self, on):
        self.online = on
        try:
            self.c.update_fcnt(f"{self.ae}/participant", "egs:flPrt", {"avail": on, "prtSt": "idle" if on else "offline"})
        except Exception:
            pass

    def on_round(self, con):
        if self.ae not in con.get("selected", []) or not self.online:
            return
        threading.Thread(target=self._train, args=(con,), daemon=True).start()

    def _train(self, con):
        r = con["round"]
        self.c.update_fcnt(f"{self.ae}/participant", "egs:flPrt", {"prtSt": f"training round {r}"})
        m = self.c.latest(f"{COORD}/models")                 # the global model this round starts from
        w, loss = train(unpack(m["weights"]), self.X, self.Y, epochs=con.get("epochs", 8), lr=con.get("lr", 0.01),
                        seed=r)
        if self.crash_next:                                    # demo: the site's MEC host fails mid-round
            self.crash_next = False
            self.set_online(False)
        if not self.online:                                    # went offline while training: nothing is sent
            return
        self.c.create_cin(f"{self.ae}/updates", {"round": r, "n": int(len(self.X)), "weights": pack(w),
                                                 "loss": round(loss, 5), "base_version": m["version"]})
        self.version = m["version"]
        self.rounds_done.append(r)
        self.c.update_fcnt(f"{self.ae}/participant", "egs:flPrt", {"lstRd": r, "mdlVr": m["version"], "prtSt": "idle"})
