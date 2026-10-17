"""EdgeGuard against what sites use today, on the same floor, the same episodes and the same sensing noise.

    python -m sim.site_compare --episodes 300           # results/site_compare.json, docs/img/site_compare*.png

Floor: sim/multi_sim.py (36 x 24 m, three aisles each way, 8 workers and 4 forklifts per 25 s episode,
everyone starting at random times).  Systems (sources in docs/site-compare.md):
  none        no system: drivers and walkers rely on their own attention
  speed_zone  automated speed zoning: trucks capped at 5 km/h, the usual pedestrian-area limit
  proximity   UWB proximity warning as sold today: warning zone 6 m -> truck slowed to walking speed (1.4 m/s)
              and the tag vibrates; danger zone 3 m -> truck stops; no notion of direction
  proximity_tight  the same with zones narrowed to 4 m / 2 m, as sites do to cut nuisance alarms
  edgeguard   this project: collision-course prediction on the MEC host, WAIT / GO / STEP ASIDE, per-pair
              speed plans, GO check, D2D fall-back
Two crews: "inattentive" (nobody looks: what the system alone prevents) and "attentive driver" (the driver
brakes for a person right in front after a 1 s reaction).  Test seeds: --offset 5000 (never used to train, pick
or audit).  "edgeguard_prev" is the policy before truck priority (results/policy_previous.json); both EdgeGuard
rows run with the devices' D2D fall-back and emergency brake.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.multi_sim import DT, T_END, run_episode                               # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEMS = [("none", "No system"), ("speed_zone", "Speed zoning 5 km/h"), ("proximity", "UWB proximity 6/3 m"),
           ("proximity_tight", "UWB proximity 4/2 m"), ("edgeguard_prev", "EdgeGuard (previous policy)"),
           ("edgeguard", "EdgeGuard")]
PREV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results", "policy_previous.json")
CREWS = [("inattentive", False), ("attentive driver", True)]


def job(a):
    seeds, system, attentive, n_w, n_f, comply = a
    if system.startswith("edgeguard"):      # EdgeGuard with its devices' D2D fall-back and emergency brake
        over = json.load(open(PREV))["policy"] if system == "edgeguard_prev" else None
        if over is not None:                # the previous policy: its own parameters, none of the new modes
            over = {**over, "truck_priority": False, "env_v2": False, "stop_point": False, "prompt_ease": False,
                    "aside_check_others": False, "env_walk_in": False, "plan_confirm": False, "msg_order": False}
        return [run_episode(s, n_w, n_f, comply=comply, system="edgeguard", attentive=attentive, over=over, d2d=True)
                for s in seeds]
    return [run_episode(s, n_w, n_f, comply=comply, system=system, attentive=attentive) for s in seeds]


def summarize(res, n_ep, n_w, n_f):
    tot = {k: sum(r[k] for r in res) for k in res[0]}
    hours = n_ep * n_f * T_END / 3600
    return {"collisions": tot["collisions"], "conflicts": tot["conflicts"],
            "collisions_per_1000_conflicts": round(1000 * tot["collisions"] / max(1, tot["conflicts"]), 2),
            "throughput": round(tot["forklift_m"] / tot["forklift_nominal_m"], 4),
            "forklift_lost_s": round(tot["forklift_lost_s"] / (n_ep * n_f), 2),
            "worker_lost_s": round(tot["worker_wait_s"] / (n_ep * n_w), 2),
            "alarms_per_forklift_hour": round(tot["alarms"] / hours, 1),
            "unneeded_alarm_share": round(tot["alarms_unneeded"] / tot["alarms"], 3) if tot["alarms"] else None}


LABELS = {"none": "No system", "speed_zone": "Speed zoning\n5 km/h", "proximity": "UWB proximity\n6 m / 3 m",
          "proximity_tight": "UWB proximity\n4 m / 2 m", "edgeguard_prev": "EdgeGuard\n(previous)", "edgeguard": "EdgeGuard"}
COLORS = {"none": "#9aa0a6", "speed_zone": "#c58b2c", "proximity": "#3f78b5", "proximity_tight": "#8db8e3", "edgeguard_prev": "#f1d77a", "edgeguard": "#e2ad00"}


def charts(out, path_png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    keys = [k for k, _ in SYSTEMS if all(k in out["crews"][c] for c, _ in CREWS)]
    edge = "#15181b"
    crew = out["crews"]
    fig, axs = plt.subplots(2, 2, figsize=(12.5, 8.6))
    w = 0.38
    xs = list(range(len(keys)))
    panels = ((axs[0][0], "collisions_per_1000_conflicts", "Collisions per 1,000 conflicts (log scale, lower is safer)", "{:.1f}"),
              (axs[0][1], "throughput", "Forklift throughput (share of nominal distance, higher is better)", "{:.0%}"),
              (axs[1][0], "worker_lost_s", "Worker time lost per 25 s episode (s, lower is better)", "{:.1f}"),
              (axs[1][1], "alarms_per_forklift_hour", "Alarms per forklift-hour (lower = fewer interruptions)", "{:.0f}"))
    for ax, key, title, fmt in panels:
        for j, (cname, _) in enumerate(CREWS):
            vals = [crew[cname][k][key] for k in keys]
            bars = ax.bar([x + (j - 0.5) * w for x in xs], vals, w, color=[COLORS[k] for k in keys], edgecolor=edge,
                          linewidth=0.8, hatch=None if j == 0 else "//", alpha=1.0 if j == 0 else 0.75)
            for b, v in zip(bars, vals):
                y = b.get_height()
                ax.text(b.get_x() + b.get_width() / 2, max(y, 0.12) if key.startswith("collisions") else y,
                        fmt.format(v), ha="center", va="bottom", fontsize=7.5)
        if key.startswith("collisions"):
            ax.set_yscale("symlog", linthresh=1.0)
            ax.set_ylim(0, 3000)
        if key == "throughput":
            ax.set_ylim(0, 1.08)
        if key == "alarms_per_forklift_hour":
            ax.set_ylim(0, 1.28 * max(crew["inattentive"][k][key] for k in keys))
            for i, k in enumerate(keys):
                u = crew["inattentive"][k]["unneeded_alarm_share"]
                if u is not None:
                    ax.text(i, crew["inattentive"][k][key] * 1.08 + 40, f"{u:.0%} not needed", ha="center", fontsize=7.5, color="#8a2f24")
        ax.set_title(title, fontsize=9.5)
        ax.set_xticks(xs)
        ax.set_xticklabels([LABELS[k] for k in keys], fontsize=8.5)
        ax.spines[["top", "right"]].set_visible(False)
    fig.legend([Patch(facecolor="white", edgecolor=edge), Patch(facecolor="white", edgecolor=edge, hatch="//")],
               ["nobody looks out (what the system alone prevents)", "attentive driver (brakes for a person in front, 1 s reaction)"],
               loc="lower center", ncol=2, frameon=False, fontsize=9)
    fig.suptitle(f"EdgeGuard vs. systems used on sites today: same floor, same {out['episodes']} episodes "
                 f"({out['workers']} workers, {out['forklifts']} forklifts, simulation)", fontsize=11)
    fig.tight_layout(rect=(0, 0.04, 1, 0.96))
    fig.savefig(path_png, dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 4.9))
    for k in keys:
        for (cname, _), m in zip(CREWS, ("o", "s")):
            v = crew[cname][k]
            ax.scatter(v["throughput"], v["collisions_per_1000_conflicts"] + 0.1, s=120, color=COLORS[k], edgecolor=edge,
                       marker=m, zorder=3)
        v = crew["inattentive"][k]
        ax.annotate(LABELS[k].replace("\n", " "), (v["throughput"], v["collisions_per_1000_conflicts"] + 0.1),
                    textcoords="offset points", xytext=(-30, 10) if k == "speed_zone" else (9, -3), fontsize=8.5)
    ax.set_yscale("log")
    ax.set_xlabel("forklift throughput (higher is better)")
    ax.set_ylabel("collisions per 1,000 conflicts + 0.1 (log, lower is better)")
    ax.set_title("Safe and productive at once: bottom right is best\n(circle: nobody looks out, square: attentive driver)", fontsize=9.5)
    ax.grid(alpha=0.3, which="both")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path_png.replace(".png", "_tradeoff.png"), dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=300)
    ap.add_argument("--offset", type=int, default=200)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--forklifts", type=int, default=4)
    ap.add_argument("--comply", type=float, default=1.0)
    ap.add_argument("--charts-only", action="store_true")
    ap.add_argument("--only", nargs="*", help="run only these systems and merge into the existing results")
    a = ap.parse_args()
    out_json = os.path.join(ROOT, "results", "site_compare.json")
    png = os.path.join(ROOT, "docs", "img", "site_compare.png")
    if a.charts_only:
        charts(json.load(open(out_json)), png)
        return
    seeds = [random.Random(7 + a.offset + i).randrange(1 << 30) for i in range(a.episodes)]
    n = os.cpu_count() or 1
    out = {"episodes": a.episodes, "workers": a.workers, "forklifts": a.forklifts, "comply": a.comply, "seed_offset": a.offset,
           "dt": DT, "crews": {}}
    if a.only and os.path.exists(out_json):
        out = json.load(open(out_json))
    with Pool(n) as pool:
        for cname, attentive in CREWS:
            out["crews"].setdefault(cname, {})
            for key, label in SYSTEMS:
                if a.only and key not in a.only:
                    continue
                res = sum(pool.map(job, [(seeds[i::n], key, attentive, a.workers, a.forklifts, a.comply) for i in range(n)]), [])
                s = summarize(res, a.episodes, a.workers, a.forklifts)
                out["crews"][cname][key] = s
                print(f"{cname:17s} {label:22s} collisions {s['collisions']:3d}/{s['conflicts']} "
                      f"({s['collisions_per_1000_conflicts']:6.2f} per 1000)  throughput {s['throughput']:.3f}  "
                      f"worker lost {s['worker_lost_s']:.2f} s  alarms/h {s['alarms_per_forklift_hour']}  "
                      f"unneeded {s['unneeded_alarm_share']}", flush=True)
                json.dump(out, open(out_json, "w"), indent=1)
    charts(out, png)


if __name__ == "__main__":
    main()
