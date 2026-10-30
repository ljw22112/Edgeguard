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
    """docs/img/large_eval.png (systems used on sites today vs EdgeGuard) and docs/img/large_eval_robust.png
    (policies under the 8 scenarios).  Horizontal bars, EdgeGuard emphasised, the others muted."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, muted, grid = "#1f1f1e", "#6b6a64", "#e4e3de"
    plt.rcParams.update({"font.size": 9, "text.color": ink, "axes.labelcolor": ink, "xtick.color": muted,
                         "ytick.color": ink, "axes.edgecolor": "#bdbcb5"})
    site = d.get("site", {}).get("inattentive", {})
    if site:
        keys = [k for k in site if k != "edgeguard_v2"][::-1]           # top: no system ... bottom: EdgeGuard
        name = {"edgeguard": "EdgeGuard (policy v3.1)", "edgeguard_prev": "EdgeGuard, previous policy"}
        labels = [name.get(k, site[k]["label"]) for k in keys]
        col = ["#2a78d6" if k == "edgeguard" else "#9ec5f4" if k == "edgeguard_prev" else "#c9c8c1" for k in keys]
        fig, axs = plt.subplots(1, 2, figsize=(11, 3.9), sharey=True)
        y = range(len(keys))
        ax = axs[0]
        for i, k in enumerate(keys):
            s_ = site[k]["summary"]
            v, (lo, hi) = s_["per_1000_conflicts"], s_["per_1000_ci95"]
            if v > 0:
                ax.barh(i, v, color=col[i], height=0.62, left=0.01)
            ax.plot([max(lo, 0.01), hi], [i, i], color=ink, lw=1.2)
            ax.plot([hi], [i], marker="|", color=ink, ms=8)
            txt = f"{s_['collisions']} in {s_['conflicts']:,}" + (f"  ({v:.1f} per 1,000)" if v > 0 else f"  (95 % CI < {hi:.1f})")
            ax.text(max(hi, v) * 1.35, i, txt, va="center", fontsize=8, color=ink if k == "edgeguard" else muted)
        ax.set_xscale("log")
        ax.set_xlim(0.01, 1e5)
        ax.set_xticks([0.1, 1, 10, 100, 1000])
        ax.set_xticklabels(["0.1", "1", "10", "100", "1,000"])
        ax.set_title("Collisions per 1,000 conflicts (bar: estimate, line: 95 % CI)", fontsize=9.5, loc="left")
        ax = axs[1]
        for i, k in enumerate(keys):
            s_ = site[k]["summary"]
            v, (lo, hi) = s_["throughput"], s_["throughput_ci95"]
            ax.barh(i, 100 * v, color=col[i], height=0.62)
            ax.text(100 * v + 1.2, i, f"{100 * v:.1f} %", va="center", fontsize=8,
                    color=ink if k == "edgeguard" else muted, fontweight="bold" if k == "edgeguard" else None)
        ax.set_xlim(0, 112)
        ax.set_title("Forklift throughput, % of nominal", fontsize=9.5, loc="left")
        for ax in axs:
            ax.grid(axis="x", color=grid, lw=0.8)
            ax.set_axisbelow(True)
            ax.spines[["top", "right"]].set_visible(False)
            ax.tick_params(axis="y", length=0)
        axs[0].set_yticks(list(y))
        axs[0].set_yticklabels(labels)
        m = d["site"]["meta"]
        fig.suptitle(f"Same {m['episodes']:,} fresh simulated episodes for every system, nobody looks out "
                     f"(8 workers, 4 forklifts)", fontsize=10.5, x=0.01, ha="left")
        fig.tight_layout()
        fig.savefig(os.path.join(ROOT, "docs", "img", "large_eval.png"), dpi=150)
        plt.close(fig)
    rob = d.get("robust", {})
    pols = [(n, lab, c) for n, lab, c in (("previous", "previous policy", "#c9e0fa"), ("robust_v2", "v2", "#9ec5f4"),
                                          ("robust_v3", "v3", "#5598e7"), ("robust_v3_1", "v3.1 (adopted)", "#1c5cab")) if n in rob]
    if pols:
        scs = [k for k in rob[pols[0][0]] if k != "meta"]
        nice = {"normal": "normal", "comply_85": "85 % comply", "comply_70": "70 % comply", "bad_network": "bad network",
                "mec_restart": "MEC restart", "noisy_uwb": "noisy UWB", "dense": "dense (12 x 6)",
                "attentive": "attentive driver"}
        fig, axs = plt.subplots(1, 2, figsize=(11, 3.9), gridspec_kw={"width_ratios": [1.7, 1]})
        ax = axs[0]
        w = 0.8 / len(pols)
        for j, (n, lab, c) in enumerate(pols):
            vals = [rob[n][sc]["summary"]["collisions"] for sc in scs]
            xs = [i + (j - (len(pols) - 1) / 2) * w for i in range(len(scs))]
            ax.bar(xs, vals, width=w * 0.92, color=c, label=lab)
            for x, v in zip(xs, vals):
                ax.text(x, v + 0.15, str(v), ha="center", fontsize=7.5, color=muted)
        ax.set_xticks(range(len(scs)))
        ax.set_xticklabels([nice.get(sc, sc) for sc in scs], rotation=20, ha="right")
        ax.set_title("Collisions per scenario (1,000 episodes each)", fontsize=9.5, loc="left")
        ax.legend(frameon=False, fontsize=8)
        ax = axs[1]
        for j, (n, lab, c) in enumerate(pols):
            eps = [e for sc in scs for e in rob[n][sc]["episodes"]]
            coll = sum(e["collisions"] for e in eps)
            conf = sum(e["conflicts"] for e in eps)
            lo, hi = wilson(coll, conf)
            v = 1000.0 * coll / conf
            ax.barh(len(pols) - 1 - j, v, color=c, height=0.6)
            ax.plot([1000 * lo, 1000 * hi], [len(pols) - 1 - j] * 2, color=ink, lw=1.2)
            ax.text(1000 * hi + 0.03, len(pols) - 1 - j, f"{coll} in {conf:,}  ({v:.2f} per 1,000)", va="center",
                    fontsize=8, color=ink)
            lab_y = lab
        ax.set_yticks(range(len(pols)))
        ax.set_yticklabels([lab for _, lab, _ in pols][::-1])
        ax.set_xlim(0, 1.9)
        ax.set_title("All 8 scenarios: per 1,000 conflicts (95 % CI)", fontsize=9.5, loc="left")
        for ax in axs:
            ax.grid(axis="y" if ax is axs[0] else "x", color=grid, lw=0.8)
            ax.set_axisbelow(True)
            ax.spines[["top", "right"]].set_visible(False)
        fig.suptitle("Exceptional conditions: same fresh simulated episodes for every policy", fontsize=10.5,
                     x=0.01, ha="left")
        fig.tight_layout()
        fig.savefig(os.path.join(ROOT, "docs", "img", "large_eval_robust.png"), dpi=150)
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
