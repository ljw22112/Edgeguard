"""Figure for policy training (results/policy_training.png)."""
import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"]   # fixed order
DEFAULT = "#7a7974"


def main(path="results/policy_training.json", out="results/policy_training.png"):
    d = json.load(open(path))
    log, val, chosen = d["training_log"], d["validation"], d["chosen"]
    pens = sorted({r["penalty"] for r in log})
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9.5})
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(15, 4.6), facecolor=SURFACE)
    for i, C in enumerate(pens):
        rows = [r for r in log if r["penalty"] == C]
        a1.plot([r["iter"] for r in rows], [r["collisions_mean_policy"] for r in rows], marker="o", ms=4,
                lw=2, color=SERIES[i], label=f"C = {C:g}")
        a2.plot([r["iter"] for r in rows], [r["throughput_mean_policy"] for r in rows], marker="o", ms=4,
                lw=2, color=SERIES[i], label=f"C = {C:g}")
    a1.set_title("Training: collisions per batch (mean policy)", loc="left", fontweight="bold", color=INK)
    a1.set_xlabel("CEM iteration", color=INK2)
    a2.set_title("Training: throughput (mean policy)", loc="left", fontweight="bold", color=INK)
    a2.set_xlabel("CEM iteration", color=INK2)
    a1.legend(frameon=False, fontsize=8.5)

    for r in val:
        is_def = r["policy"] == "default"
        i = 0 if is_def else [f"C={C:g}" for C in pens].index(r["policy"])
        col = DEFAULT if is_def else SERIES[i]
        a3.scatter(r["throughput"], r["collisions"], s=140 if r["policy"] == chosen else 70, color=col,
                   edgecolors=INK if r["policy"] == chosen else SURFACE, linewidths=2, zorder=3)
        a3.annotate(f"{r['policy']}\nF2 {r['f_beta']:.2f}", (r["throughput"], r["collisions"]),
                    xytext=(8, 4), textcoords="offset points", fontsize=8.5, color=INK)
    a3.set_title("Validation: collisions vs throughput", loc="left", fontweight="bold", color=INK)
    a3.set_xlabel("throughput (1.0 = never slowed)", color=INK2)
    a3.set_ylabel("collisions (held-out encounters)", color=INK2)
    xs = [r["throughput"] for r in val]
    a3.set_xlim(min(xs) - 0.03, max(xs) + 0.06)
    cs = [r["collisions"] for r in val]
    a3.set_ylim(min(cs) - 3, max(cs) + 4)
    for ax in (a1, a2, a3):
        ax.set_facecolor(SURFACE)
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(colors=INK2, length=0)
        for sp in ax.spines.values():
            sp.set_visible(False)
    n = val[0]["episodes"]
    fig.text(0.01, 0.01, f"Cross-Entropy Method over 10 policy parameters; reward = -C·collision - seconds lost - 0.5·false alarm. "
             f"Validation: {n} held-out encounters with randomised noise, latency and loss. Outlined = chosen.",
             color=INK2, fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=170, facecolor=SURFACE)
    print("saved", out)


if __name__ == "__main__":
    main(*sys.argv[1:])
