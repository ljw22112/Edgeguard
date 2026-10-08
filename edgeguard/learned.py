"""Learned worker-trajectory predictor (LSTM).

Input  : the worker's positions over the last 1.9 s resampled to 10 Hz (resample()), expressed
         relative to the newest sample, plus the forklift's relative position
         and velocity (repeated on every step).
Output : FUT future worker positions (0.1 s .. 3.0 s) relative to the newest sample.

Train with `python -m sim.train_lstm`; the weights live in models/worker_lstm.pt.
PyTorch is only needed when this predictor is used.
"""
from __future__ import annotations

import math
import os

HIST, FUT, DT = 20, 30, 0.1
MAX_GAP_S = 0.8          # interpolate over gaps up to this (swept 0.35 / 0.55 / 0.8 s); longer -> CV fallback
POS_SCALE, VEL_SCALE = 5.0, 3.0
DEFAULT_WEIGHTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "models", "worker_lstm.pt")

_model = None


def build_model(hidden=64):
    import torch.nn as nn

    class WorkerLSTM(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(6, hidden, batch_first=True)
            self.head = nn.Sequential(nn.Linear(hidden, 128), nn.ReLU(), nn.Linear(128, FUT * 2))

        def forward(self, x):                      # x: (B, HIST, 6)
            _, (h, _) = self.lstm(x)
            return self.head(h[-1]).view(-1, FUT, 2)

    return WorkerLSTM()


def features(hist_xy, f_rel, f_vel):
    """hist_xy: list of HIST (x, y) raw samples, oldest first."""
    lx, ly = hist_xy[-1]
    frx, fry = f_rel[0] / POS_SCALE, f_rel[1] / POS_SCALE
    fvx, fvy = f_vel[0] / VEL_SCALE, f_vel[1] / VEL_SCALE
    return [[(x - lx) / POS_SCALE, (y - ly) / POS_SCALE, frx, fry, fvx, fvy] for x, y in hist_xy]


def load(path=DEFAULT_WEIGHTS):
    global _model
    if _model is None:
        import torch
        ck = torch.load(path, map_location="cpu", weights_only=True)
        m = build_model(ck.get("hidden", 64))
        m.load_state_dict(ck["state_dict"])
        m.eval()
        torch.set_num_threads(1)
        _model = m
    return _model


def available(path=DEFAULT_WEIGHTS):
    try:
        import torch  # noqa: F401
    except ImportError:
        return False
    return os.path.exists(path)


def resample(history):
    """Raw (t, x, y) samples -> HIST positions on the 10 Hz grid ending at the newest sample.

    The model was trained on 10 Hz samples.  Real reports are not: uplink loss, jitter and the
    adaptive reporting rate (2 Hz far from forklifts) would otherwise be read as 0.1 s apart and
    give a 5x wrong speed.  Returns None when the samples do not cover the last 1.9 s or have a
    gap longer than MAX_GAP_S inside it (the caller falls back to constant velocity)."""
    h = list(history)
    if len(h) < 2:
        return None
    t_end = h[-1][0]
    t0 = t_end - (HIST - 1) * DT
    if h[0][0] > t0 + 1e-6:
        return None
    k0 = max(i for i in range(len(h)) if h[i][0] <= t0 + 1e-6)
    seg = h[k0:]
    if any(b[0] - a[0] > MAX_GAP_S for a, b in zip(seg, seg[1:])):
        return None
    out, j = [], 0
    for k in range(HIST):
        tk = t0 + k * DT
        while j + 1 < len(seg) and seg[j + 1][0] < tk - 1e-9:
            j += 1
        (ta, xa, ya), (tb, xb, yb) = seg[j], seg[min(j + 1, len(seg) - 1)]
        w = 0.0 if tb <= ta else min(1.0, max(0.0, (tk - ta) / (tb - ta)))
        out.append((xa + w * (xb - xa), ya + w * (yb - ya)))
    return out


class LSTMPredictor:
    """Predicts with the LSTM up to 3 s, then extrapolates the last predicted velocity."""

    def __init__(self, worker_track, forklift_track):
        import torch
        hist = resample(worker_track.history)
        lx, ly = hist[-1]
        fx, fy = forklift_track.pos
        feat = features(hist, (fx - lx, fy - ly), forklift_track.vel)
        with torch.no_grad():
            out = load()(torch.tensor([feat], dtype=torch.float32))[0].numpy() * POS_SCALE
        self.origin = (lx, ly)
        self.path = [(lx + float(dx), ly + float(dy)) for dx, dy in out]
        (ax, ay), (bx, by) = self.path[-2], self.path[-1]
        self.tail_v = ((bx - ax) / DT, (by - ay) / DT)

    def positions(self, times):
        out = []
        for t in times:
            k = int(round(t / DT))
            if k <= 0:
                out.append(self.origin)
            elif k <= FUT:
                out.append(self.path[k - 1])
            else:
                bx, by = self.path[-1]
                extra = t - FUT * DT
                out.append((bx + self.tail_v[0] * extra, by + self.tail_v[1] * extra))
        return out


def usable(worker_track):
    return resample(getattr(worker_track, "history", ())) is not None


def predictor_or_none(worker_track, forklift_track):
    if not usable(worker_track):
        return None
    return LSTMPredictor(worker_track, forklift_track)


__all__ = ["HIST", "FUT", "build_model", "features", "load", "available", "LSTMPredictor", "resample",
           "predictor_or_none", "math"]
