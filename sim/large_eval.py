"""Large-scale evaluation with confidence intervals (fresh seeds, many episodes).

    python -m sim.large_eval site   --episodes 1000 --offset 21000      # systems used on sites today vs EdgeGuard
    python -m sim.large_eval robust --episodes 1000 --offset 23000 --policy current
    python -m sim.large_eval robust --episodes 1000 --offset 23000 --policy results/policy_previous_eval.json
    python -m sim.large_eval report                                      # results/large_eval.json -> tables, chart

Small collision counts say little on their own (0 vs 1 in 300 episodes is not a difference), so every number
here carries a 95 % interval:
  collisions per 1,000 conflicts  Wilson score interval on collisions / conflicts (0 events: upper bound ~ 3/n)
  throughput, worker time lost     percentile bootstrap over episodes (2,000 resamples; ratio of sums)
Per-episode results are stored, so intervals can be recomputed without re-running.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results", "large_eval.json")
KEEP = ("collisions", "conflicts", "near", "forklift_m", "forklift_nominal_m", "worker_wait_s", "alarms", "_w")


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def bootstrap_ratio(num, den, b=2000, seed=1):
    rng = random.Random(seed)
    n = len(num)
    vals = []
    for _ in range(b):
        idx = [rng.randrange(n) for _ in range(n)]
        vals.append(sum(num[i] for i in idx) / max(1e-9, sum(den[i] for i in idx)))
    vals.sort()
    return (vals[int(0.025 * b)], vals[int(0.975 * b) - 1])


def summarize(eps):
    tot = {k: sum(e[k] for e in eps) for k in KEEP}
    lo, hi = wilson(tot["collisions"], tot["conflicts"])
    thr = tot["forklift_m"] / tot["forklift_nominal_m"]
    tlo, thi = bootstrap_ratio([e["forklift_m"] for e in eps], [e["forklift_nominal_m"] for e in eps])
    wl = tot["worker_wait_s"] / tot["_w"]
    wlo, whi = bootstrap_ratio([e["worker_wait_s"] for e in eps], [e["_w"] for e in eps], seed=2)
    return {"episodes": len(eps), "conflicts": tot["conflicts"], "collisions": tot["collisions"],
            "per_1000_conflicts": round(1000 * tot["collisions"] / max(1, tot["conflicts"]), 3),
            "per_1000_ci95": [round(1000 * lo, 3), round(1000 * hi, 3)],
            "close_passes": tot["near"], "throughput": round(thr, 4), "throughput_ci95": [round(tlo, 4), round(thi, 4)],
            "worker_lost_s": round(wl, 3), "worker_lost_ci95": [round(wlo, 3), round(whi, 3)],
            "alarms_per_episode": round(tot["alarms"] / len(eps), 2)}


def _site_job(a):
    seed, system, attentive = a
    from sim.site_compare import job
    r = job(([seed], system, attentive, 8, 4, 1.0))[0]
    r["_w"] = 8
    return {k: r[k] for k in KEEP}


def _robust_job(a):
    seed, sc, over = a
    from sim.robust_eval import job
    r = job((seed, sc, over))
    return {k: r[k] for k in KEEP}


def load():
    return json.load(open(OUT)) if os.path.exists(OUT) else {"site": {}, "robust": {}}


def save(d):
    json.dump(d, open(OUT, "w"))


def run_site(a):
    from sim.site_compare import SYSTEMS, CREWS
    seeds = [random.Random(7 + a.offset + i).randrange(1 << 30) for i in range(a.episodes)]
    d = load()
    d["site"]["meta"] = {"episodes": a.episodes, "seed_offset": a.offset}
    with Pool(os.cpu_count() or 1) as pool:
        for cname, att in CREWS:
            for key, label in SYSTEMS:
                if a.only and key not in a.only:
                    continue
                eps = pool.map(_site_job, [(s, key, att) for s in seeds], chunksize=8)
                d["site"].setdefault(cname, {})[key] = {"label": label, "summary": summarize(eps), "episodes": eps}
                s = d["site"][cname][key]["summary"]
                print(f"{cname:17s} {label:28s} coll {s['collisions']:4d}/{s['conflicts']} "
                      f"[{s['per_1000_ci95'][0]:.2f}, {s['per_1000_ci95'][1]:.2f}] per 1000  thr {s['throughput']:.4f} "
                      f"{s['throughput_ci95']}", flush=True)
                save(d)


def run_robust(a):
    from sim.robust_eval import SCENARIOS, load_policy
    seeds = [random.Random(7 + a.offset + i).randrange(1 << 30) for i in range(a.episodes)]
    over = load_policy(a.policy)
    name = a.name or a.policy
    d = load()
    d["robust"].setdefault("meta", {})[name] = {"episodes": a.episodes, "seed_offset": a.offset, "policy": a.policy}
    with Pool(os.cpu_count() or 1) as pool:
        for sc in SCENARIOS:
            eps = pool.map(_robust_job, [(s, sc, over) for s in seeds], chunksize=8)
            d["robust"].setdefault(name, {})[sc] = {"summary": summarize(eps), "episodes": eps}
            s = d["robust"][name][sc]["summary"]
            print(f"{name:14s} {sc:12s} coll {s['collisions']:3d}/{s['conflicts']} [{s['per_1000_ci95'][0]:.2f}, "
                  f"{s['per_1000_ci95'][1]:.2f}]  thr {s['throughput']:.4f} {s['throughput_ci95']}", flush=True)
            save(d)


def report(_a):
    d = load()
    lines = []
    if d.get("site"):
        m = d["site"]["meta"]
        lines.append(f"Site comparison, {m['episodes']} episodes from seed offset {m['seed_offset']}")
        for cname in ("inattentive", "attentive driver"):
            for key, v in d["site"].get(cname, {}).items():
                s = v["summary"]
                lines.append(f"  {cname:17s} {v['label']:28s} {s['collisions']:4d}/{s['conflicts']}  "
                             f"{s['per_1000_conflicts']:.2f} [{s['per_1000_ci95'][0]:.2f}-{s['per_1000_ci95'][1]:.2f}]/1000  "
                             f"thr {100 * s['throughput']:.1f} % [{100 * s['throughput_ci95'][0]:.1f}-{100 * s['throughput_ci95'][1]:.1f}]  "
                             f"worker {s['worker_lost_s']:.2f} s  alarms {s['alarms_per_episode']}")
    for name, scs in d.get("robust", {}).items():
        if name == "meta":
            continue
        k = sum(v["summary"]["collisions"] for v in scs.values())
        n = sum(v["summary"]["conflicts"] for v in scs.values())
        lo, hi = wilson(k, n)
        lines.append(f"Robust {name}: {k} collisions in {n} conflicts ({sum(v['summary']['episodes'] for v in scs.values())} "
                     f"episodes), 95 % [{1000 * lo:.2f}, {1000 * hi:.2f}] per 1000")
        for sc, v in scs.items():
            s = v["summary"]
            lines.append(f"  {sc:12s} {s['collisions']:3d}/{s['conflicts']}  [{s['per_1000_ci95'][0]:.2f}-{s['per_1000_ci95'][1]:.2f}]  "
                         f"thr {100 * s['throughput']:.1f} % [{100 * s['throughput_ci95'][0]:.1f}-{100 * s['throughput_ci95'][1]:.1f}]")
    print("\n".join(lines))
    chart(d)


def chart(d):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    site = d.get("site", {}).get("inattentive", {})
    if not site:
        return
    keys = list(site)
    labels = [site[k]["label"].replace(" (previous policy)", "\n(previous)").replace("UWB proximity ", "UWB prox.\n")
              for k in keys]
    cols = {"none": "#9aa0a6", "speed_zone": "#c58b2c", "proximity": "#3f78b5", "proximity_tight": "#8db8e3",
            "edgeguard_prev": "#f1d77a", "edgeguard": "#e2ad00"}
    fig, axs = plt.subplots(1, 2, figsize=(12.5, 4.8))
    for ax, key, title in ((axs[0], "per_1000_conflicts", "Collisions per 1,000 conflicts (95 % CI, log)"),
                           (axs[1], "throughput", "Forklift throughput (95 % CI)")):
        vals = [site[k]["summary"][key] for k in keys]
        ci = [site[k]["summary"]["per_1000_ci95" if key.startswith("per") else "throughput_ci95"] for k in keys]
        err = [[max(0, v - c[0]) for v, c in zip(vals, ci)], [max(0, c[1] - v) for v, c in zip(vals, ci)]]
        plot_vals = [max(v, 0.02) for v in vals] if key.startswith("per") else vals
        ax.bar(range(len(keys)), plot_vals, color=[cols.get(k, "#888") for k in keys], edgecolor="#15181b", lw=0.8,
               yerr=err, capsize=4)
        for i, (v, c) in enumerate(zip(vals, ci)):
            txt = (f"{v:.1f}\n[{c[0]:.1f}-{c[1]:.1f}]" if key.startswith("per") else f"{100 * v:.1f} %")
            ax.text(i, (max(c[1], 0.02) * 1.15) if key.startswith("per") else c[1] + 0.02, txt, ha="center", fontsize=7.5)
        if key.startswith("per"):
            ax.set_yscale("log")
            ax.set_ylim(0.01, 3000)
        else:
            ax.set_ylim(0, 1.12)
        ax.set_xticks(range(len(keys)))
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_title(title, fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)
    m = d["site"]["meta"]
    fig.suptitle(f"Same {m['episodes']} fresh episodes for every system (nobody looks out), simulation", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(ROOT, "docs", "img", "large_eval.png"), dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["site", "robust", "report"])
    ap.add_argument("--episodes", type=int, default=1000)
    ap.add_argument("--offset", type=int, default=21000)
    ap.add_argument("--policy", default="current")
    ap.add_argument("--name")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    {"site": run_site, "robust": run_robust, "report": report}[a.what](a)


if __name__ == "__main__":
    main()
