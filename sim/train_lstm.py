"""Train the worker-trajectory LSTM on simulated encounters.

    python -m sim.train_lstm --n 400 --epochs 15

Training episodes use a different random seed from sim.evaluate, so the
comparison there is on unseen encounters.  Reports ADE/FDE (average / final
displacement error over 3 s) against the constant-velocity Kalman baseline.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard.learned import HIST, FUT, POS_SCALE, build_model, features, DEFAULT_WEIGHTS  # noqa: E402
from edgeguard.tracking import Track                                                       # noqa: E402
from sim.evaluate import POS_NOISE, SPEED_NOISE, HEADING_NOISE, YAW_NOISE                 # noqa: E402
from sim.scenarios import GENERATORS, EXTRA_GENERATORS                                     # noqa: E402


def make_dataset(n_per_gen, seed, stride=2):
    rng = random.Random(seed)
    X, Y, CV = [], [], []
    for gen in GENERATORS + EXTRA_GENERATORS:      # incl. running, zigzag, reversing
        for _ in range(n_per_gen):
            _, times, w, f = gen(rng)
            tw, tf = Track("w", "worker"), Track("f", "forklift")
            for i, (t, (wx, wy), (fx, fy, th, sp, yaw)) in enumerate(zip(times, w, f)):
                tw.update(t, wx + rng.gauss(0, POS_NOISE), wy + rng.gauss(0, POS_NOISE))
                tf.update(t, fx + rng.gauss(0, POS_NOISE), fy + rng.gauss(0, POS_NOISE),
                          speed=max(0.0, sp + rng.gauss(0, SPEED_NOISE)),
                          heading=th + rng.gauss(0, HEADING_NOISE),
                          yaw_rate=yaw + rng.gauss(0, YAW_NOISE))
                if len(tw.history) < HIST or i + FUT >= len(times) or i % stride:
                    continue
                hist = [(x, y) for _, x, y in tw.history]
                lx, ly = hist[-1]
                fxp, fyp = tf.pos
                X.append(features(hist, (fxp - lx, fyp - ly), tf.vel))
                Y.append([((w[i + k][0] - lx) / POS_SCALE, (w[i + k][1] - ly) / POS_SCALE)
                          for k in range(1, FUT + 1)])
                (px, py), (vx, vy) = tw.pos, tw.vel
                CV.append([((px + vx * k * 0.1) - lx) / POS_SCALE for k in range(1, FUT + 1)] +
                          [((py + vy * k * 0.1) - ly) / POS_SCALE for k in range(1, FUT + 1)])
    X = torch.tensor(X, dtype=torch.float32)
    Y = torch.tensor(Y, dtype=torch.float32)
    CV = torch.tensor(CV, dtype=torch.float32).view(-1, 2, FUT).transpose(1, 2)
    return X, Y, CV


def rotate(X, Y, ang):
    c, s = torch.cos(ang), torch.sin(ang)

    def rot(a, b):
        return a * c - b * s, a * s + b * c
    X = X.clone()
    Y = Y.clone()
    for i in (0, 2, 4):
        X[..., i], X[..., i + 1] = rot(X[..., i], X[..., i + 1])
    Y[..., 0], Y[..., 1] = rot(Y[..., 0], Y[..., 1])
    return X, Y


def ade_fde(pred, y):
    d = torch.linalg.norm((pred - y) * POS_SCALE, dim=-1)
    return d.mean().item(), d[:, -1].mean().item()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--out", default=DEFAULT_WEIGHTS)
    a = ap.parse_args()
    torch.manual_seed(a.seed)
    torch.set_num_threads(max(1, os.cpu_count() or 1))

    t0 = time.time()
    X, Y, CV = make_dataset(a.n, a.seed)
    n = len(X)
    perm = torch.randperm(n)
    va, tr = perm[: n // 10], perm[n // 10:]
    print(f"samples {n} (train {len(tr)}, val {len(va)}) built in {time.time() - t0:.0f}s")

    model = build_model()
    opt = torch.optim.Adam(model.parameters(), lr=2e-3)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, a.epochs)
    for ep in range(a.epochs):
        model.train()
        idx = tr[torch.randperm(len(tr))]
        for b in range(0, len(idx), 512):
            j = idx[b:b + 512]
            ang = torch.rand(len(j), 1) * 2 * math.pi
            xb, yb = rotate(X[j], Y[j], ang)
            loss = torch.nn.functional.smooth_l1_loss(model(xb), yb, beta=0.02)
            opt.zero_grad()
            loss.backward()
            opt.step()
        sched.step()
        model.eval()
        with torch.no_grad():
            ade, fde = ade_fde(model(X[va]), Y[va])
        print(f"epoch {ep + 1:2d}  val ADE {ade:.3f} m  FDE {fde:.3f} m")

    cv_ade, cv_fde = ade_fde(CV[va], Y[va])
    with torch.no_grad():
        ade, fde = ade_fde(model(X[va]), Y[va])
    print(f"\nconstant-velocity Kalman: ADE {cv_ade:.3f} m  FDE {cv_fde:.3f} m")
    print(f"LSTM                    : ADE {ade:.3f} m  FDE {fde:.3f} m")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "hidden": 64}, a.out)
    with open(os.path.join(os.path.dirname(a.out), "worker_lstm_metrics.json"), "w") as fh:
        json.dump({"val_samples": len(va), "lstm": {"ade_m": ade, "fde_m": fde},
                   "cv_kalman": {"ade_m": cv_ade, "fde_m": cv_fde},
                   "horizon_s": FUT * 0.1, "train_seed": a.seed, "episodes_per_scenario": a.n}, fh, indent=2)
    print("saved", a.out)


if __name__ == "__main__":
    main()
