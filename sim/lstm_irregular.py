"""Does the worker LSTM survive irregular sampling?  (known limitation until v0.8)

    python -m sim.lstm_irregular --per-gen 40 --out results/lstm_irregular.json

Held-out encounters (seed different from training).  The worker's UWB reports are thinned /
jittered as on a real network, then the LSTM is fed either
  index : the last 20 samples as if 0.1 s apart (what v0.7 did), or
  time  : edgeguard.learned.resample() - positions on the 10 Hz grid by time (v0.8),
and compared with the constant-velocity Kalman track.  ADE / FDE over 3 s against the truth.
Samples where resample() refuses (gap > 0.35 s) fall back to CV in the time variant - counted.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard.learned import FUT, HIST, POS_SCALE, features, load, resample   # noqa: E402
from edgeguard.tracking import Track                                           # noqa: E402
from sim.evaluate import POS_NOISE, SPEED_NOISE, HEADING_NOISE, YAW_NOISE      # noqa: E402
from sim.scenarios import GENERATORS, EXTRA_GENERATORS                         # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# keep(i, rng) -> report sample i?   jitter(rng) -> timestamp offset (s)
CASES = {
    "regular 10 Hz":              (lambda i, r: True, lambda r: 0.0),
    "jitter +-40 ms":             (lambda i, r: True, lambda r: r.uniform(-0.04, 0.04)),
    "20 % uplink loss":           (lambda i, r: r.random() >= 0.2, lambda r: 0.0),
    "40 % loss + jitter":         (lambda i, r: r.random() >= 0.4, lambda r: r.uniform(-0.04, 0.04)),
    "5 Hz":                       (lambda i, r: i % 2 == 0, lambda r: 0.0),
    "adaptive 2 Hz -> 10 Hz":     (None, lambda r: 0.0),          # 2 Hz until 1.5 s before the sample
}


def run_case(name, n_per_gen, seed):
    keep, jit = CASES[name]
    rng = random.Random(seed)
    model = load()
    ex = {"index": [], "time": [], "cv": []}
    fallback = total = 0
    for gen in GENERATORS + EXTRA_GENERATORS:
        for _ in range(n_per_gen):
            _, times, w, f = gen(rng)
            idx = [i for i in range(len(times))]
            for i0 in range(HIST + 25, len(times) - FUT, 7):     # evaluation points
                tw, tf = Track("w", "worker"), Track("f", "forklift")
                for i in range(0, i0 + 1):
                    t = times[i]
                    fx, fy, th, sp, yaw = f[i]
                    tf.update(t, fx + rng.gauss(0, POS_NOISE), fy + rng.gauss(0, POS_NOISE),
                              speed=max(0.0, sp + rng.gauss(0, SPEED_NOISE)), heading=th + rng.gauss(0, HEADING_NOISE),
                              yaw_rate=yaw + rng.gauss(0, YAW_NOISE))
                    if keep is None:
                        rep = (i % 5 == 0) if t < times[i0] - 1.5 else True
                    else:
                        rep = keep(i, rng) or i == i0
                    if rep:
                        tw.update(t + (jit(rng) if i != i0 else 0.0), w[i][0] + rng.gauss(0, POS_NOISE),
                                  w[i][1] + rng.gauss(0, POS_NOISE))
                if len(tw.history) < HIST:
                    continue
                total += 1
                lx, ly = tw.history[-1][1], tw.history[-1][2]
                truth = torch.tensor([[(w[i0 + k][0] - lx) / POS_SCALE, (w[i0 + k][1] - ly) / POS_SCALE]
                                      for k in range(1, FUT + 1)])
                fxp, fyp = tf.pos
                frel = (fxp - lx, fyp - ly)
                (px, py), (vx, vy) = tw.pos, tw.vel
                cv = torch.tensor([[((px + vx * k * 0.1) - lx) / POS_SCALE, ((py + vy * k * 0.1) - ly) / POS_SCALE]
                                   for k in range(1, FUT + 1)])
                hidx = [(x, y) for _, x, y in list(tw.history)[-HIST:]]
                with torch.no_grad():
                    pi = model(torch.tensor([features(hidx, frel, tf.vel)], dtype=torch.float32))[0]
                    hr = resample(tw.history)
                    if hr is None:
                        fallback += 1
                        pt = cv
                    else:
                        pt = model(torch.tensor([features(hr, frel, tf.vel)], dtype=torch.float32))[0]
                for k, p in (("index", pi), ("time", pt), ("cv", cv)):
                    d = torch.linalg.norm((p - truth) * POS_SCALE, dim=-1)
                    ex[k].append((d.mean().item(), d[-1].item()))
    res = {k: {"ade_m": round(sum(a for a, _ in v) / len(v), 3), "fde_m": round(sum(b for _, b in v) / len(v), 3)}
           for k, v in ex.items()}
    res["samples"], res["time_fallback_to_cv"] = total, fallback
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-gen", type=int, default=40)
    ap.add_argument("--out", default="results/lstm_irregular.json")
    a = ap.parse_args()
    torch.set_num_threads(1)
    out = {}
    for name in CASES:
        r = run_case(name, a.per_gen, 424242)
        out[name] = r
        print(f"{name:24s} n={r['samples']:5d}  ADE index {r['index']['ade_m']:.3f}  time {r['time']['ade_m']:.3f}  "
              f"cv {r['cv']['ade_m']:.3f}   FDE index {r['index']['fde_m']:.3f}  time {r['time']['fde_m']:.3f}  "
              f"cv {r['cv']['fde_m']:.3f}   fallback {r['time_fallback_to_cv']}", flush=True)
    json.dump(out, open(os.path.join(ROOT, a.out), "w"), indent=1)


if __name__ == "__main__":
    main()
