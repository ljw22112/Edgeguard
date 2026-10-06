"""Render results/evaluation.json as a report figure (results/evaluation.png)."""
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
BASE, OURS = "#b9b8b2", "#2a78d6"


def main(path="results/evaluation.json", out="results/evaluation.png"):
    d = json.load(open(path))["summary"]
    methods = list(d)[::-1]
    colors = [OURS if m.startswith("Guidance") else BASE for m in methods]
    panels = [("Timely detection (higher is better)", "timely_detection"),
              ("False alarm rate (lower is better)", "false_alarm_rate")]

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), facecolor=SURFACE, sharey=True)
    for ax, (title, key) in zip(axes, panels):
        vals = [d[m][key] * 100 for m in methods]
        bars = ax.barh(methods, vals, color=colors, height=0.55, edgecolor=SURFACE, linewidth=2)
        for b, v in zip(bars, vals):
            ax.text(v + 1.5, b.get_y() + b.get_height() / 2, f"{v:.0f}%",
                    va="center", color=INK, fontsize=9.5)
        ax.set_xlim(0, 112)
        ax.set_title(title, loc="left", color=INK, fontsize=11, fontweight="bold")
        ax.set_facecolor(SURFACE)
        ax.xaxis.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(colors=INK2, length=0)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.set_xticklabels([f"{x}%" for x in [0, 25, 50, 75, 100]])
    s = json.load(open(path))["settings"]
    fig.text(0.01, 0.01,
             f"Simulated warehouse encounters: 8 scenario types x {s['n_per_scenario']} episodes, "
             f"UWB noise {s['pos_noise_m']} m. Timely = alarm >= {s['lead_required_s']:.0f} s before "
             f"contact (distance < {s['r_safe_m']} m).", color=INK2, fontsize=8.5)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    print("saved", out)


if __name__ == "__main__":
    main(*sys.argv[1:])
