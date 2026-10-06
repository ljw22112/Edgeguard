"""Monte-Carlo comparison: proximity / TTC baselines vs guidance-based prediction.

    python -m sim.evaluate --n 250 --out results

Metrics (alarm = WARNING or higher, i.e. the worker's wearable vibrates):
  timely detection  share of true conflicts alarmed >= LEAD_REQ s before contact
  false alarm rate  share of non-conflict encounters that triggered any alarm
  median lead time  seconds between first alarm and contact (conflicts only)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard.risk import RiskConfig, assess                    # noqa: E402
from edgeguard.tracking import Track                             # noqa: E402
from sim.scenarios import GENERATORS, ground_truth, R_SAFE       # noqa: E402

LEAD_REQ = 1.0          # s: reaction + braking from ~2.5 m/s at 2.5 m/s^2
POS_NOISE = 0.15        # m, UWB
SPEED_NOISE = 0.05      # m/s
HEADING_NOISE = math.radians(2)
YAW_NOISE = 0.03        # rad/s
DEBOUNCE = 3            # consecutive frames (0.3 s) before an alarm fires, all methods

METHODS = {
    "Proximity 3 m": ("distance", RiskConfig(r_safe=R_SAFE, distance_threshold=3.0)),
    "Proximity 5 m": ("distance", RiskConfig(r_safe=R_SAFE, distance_threshold=5.0)),
    "TTC < 3 s": ("ttc", RiskConfig(r_safe=R_SAFE)),
    "Guidance (CPA/LOS)": ("guidance", RiskConfig(r_safe=R_SAFE)),
    "Guidance + CTRV": ("guidance_ctrv", RiskConfig(r_safe=R_SAFE)),
}
try:
    from edgeguard.learned import available as _lstm_ok
    if _lstm_ok():
        METHODS["Guidance + CTRV + LSTM"] = ("guidance_lstm", RiskConfig(r_safe=R_SAFE))
except Exception:                                   # torch not installed: skip the learned method
    pass


def run_episode(rng, name, times, w, f):
    gt = ground_truth(times, w, f)
    tw, tf = Track("worker_01", "worker"), Track("forklift_01", "forklift")
    first = {m: None for m in METHODS}
    alarm_steps = {m: 0 for m in METHODS}
    streak = {m: 0 for m in METHODS}
    for t, (wx, wy), (fx, fy, th, sp, yaw) in zip(times, w, f):
        tw.update(t, wx + rng.gauss(0, POS_NOISE), wy + rng.gauss(0, POS_NOISE))
        tf.update(t, fx + rng.gauss(0, POS_NOISE), fy + rng.gauss(0, POS_NOISE),
                  speed=max(0.0, sp + rng.gauss(0, SPEED_NOISE)),
                  heading=th + rng.gauss(0, HEADING_NOISE),
                  yaw_rate=yaw + rng.gauss(0, YAW_NOISE))
        if t < 0.5:                       # let the filters settle
            continue
        if gt["conflict"] and t > gt["t_contact"]:
            break
        for m, (method, cfg) in METHODS.items():
            if assess(tw, tf, cfg, method).level >= 2:
                streak[m] += 1
                if streak[m] >= DEBOUNCE:
                    alarm_steps[m] += 1
                    if first[m] is None:
                        first[m] = t
            else:
                streak[m] = 0
    return gt, first, alarm_steps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=250, help="episodes per scenario type")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    os.makedirs(a.out, exist_ok=True)

    agg = {m: {"tp": 0, "pos": 0, "fa": 0, "neg": 0, "leads": []} for m in METHODS}
    per_scn = defaultdict(lambda: {m: {"alarm": 0, "ok": 0, "n": 0, "leads": []} for m in METHODS})
    labels = defaultdict(lambda: [0, 0])
    for gen in GENERATORS:
        for _ in range(a.n):
            name, times, w, f = gen(rng)
            gt, first, _ = run_episode(rng, name, times, w, f)
            labels[name][0 if gt["conflict"] else 1] += 1
            for m in METHODS:
                s = per_scn[name][m]
                s["n"] += 1
                if gt["conflict"]:
                    agg[m]["pos"] += 1
                    lead = None if first[m] is None else gt["t_contact"] - first[m]
                    if lead is not None:
                        agg[m]["leads"].append(lead)
                        s["leads"].append(lead)
                    ok = lead is not None and lead >= LEAD_REQ
                    agg[m]["tp"] += ok
                    s["ok"] += ok
                    s["alarm"] += first[m] is not None
                else:
                    agg[m]["neg"] += 1
                    fa = first[m] is not None
                    agg[m]["fa"] += fa
                    s["alarm"] += fa
                    s["ok"] += not fa

    summary = {}
    for m, v in agg.items():
        summary[m] = {
            "timely_detection": v["tp"] / max(1, v["pos"]),
            "false_alarm_rate": v["fa"] / max(1, v["neg"]),
            "median_lead_s": statistics.median(v["leads"]) if v["leads"] else None,
            "conflicts": v["pos"], "non_conflicts": v["neg"],
        }
    for v in per_scn.values():
        for x in v.values():
            ls = x.pop("leads")
            x["median_lead_s"] = round(statistics.median(ls), 2) if ls else None
    out = {"summary": summary,
           "per_scenario": {k: dict(v) for k, v in per_scn.items()},
           "labels": {k: {"conflict": c, "non_conflict": n} for k, (c, n) in labels.items()},
           "settings": {"n_per_scenario": a.n, "seed": a.seed, "lead_required_s": LEAD_REQ,
                        "pos_noise_m": POS_NOISE, "r_safe_m": R_SAFE}}
    with open(os.path.join(a.out, "evaluation.json"), "w") as fh:
        json.dump(out, fh, indent=2)

    print(f"{'method':<22}{'timely det.':>12}{'false alarm':>13}{'median lead':>13}")
    for m, s in summary.items():
        ml = "-" if s["median_lead_s"] is None else f"{s['median_lead_s']:.1f} s"
        print(f"{m:<22}{s['timely_detection']:>11.1%}{s['false_alarm_rate']:>12.1%}{ml:>13}")
    print("\nlabels:", dict(out["labels"]))
    return out


if __name__ == "__main__":
    main()
