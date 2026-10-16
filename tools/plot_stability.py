"""Before / after chart of the MEC app soak test: results/soak_before.json, results/soak.json -> docs/img/stability.png

    python tools/plot_stability.py
"""
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    b = json.load(open(os.path.join(ROOT, "results", "soak_before.json")))
    a = json.load(open(os.path.join(ROOT, "results", "soak.json")))
    window = round(b["minutes"] * 60 - b["recovery"]["reset"]["fault_end_s"])   # what was left of the run
    never = b["recovery"]["reset"].get("alerts_s") is None
    rows = [
        ("Alerts reach the tags again\nafter the CSE lost its state (s)",
         b["recovery"]["reset"].get("alerts_s", window), a["recovery"]["reset"]["alerts_s"], never),
        ("Device data back\nafter the CSE lost its state (s)", b["recovery"]["reset"]["feed_s"], a["recovery"]["reset"]["feed_s"], False),
        ("Slowest /health answer\n(ms, incl. 2,000-message burst)", b["health_ms_max"], a["health_ms_max"], False),
        ("Threads at peak", b["threads_max"], a["threads_max"], False),
    ]
    fig, axs = plt.subplots(1, 4, figsize=(13, 3.9))
    for ax, (title, vb, va, inf) in zip(axs, rows):
        bars = ax.bar(["before", "after"], [vb, va], color=["#9aa0a6", "#e2ad00"], edgecolor="#15181b", linewidth=0.8)
        if inf:
            bars[0].set_hatch("xx")
            ax.text(0, vb, f"never\n(> {window} s)", ha="center", va="bottom", fontsize=8.5, color="#8a2f24")
        else:
            ax.text(0, vb, f"{vb:g}", ha="center", va="bottom", fontsize=8.5)
        ax.text(1, va, f"{va:g}", ha="center", va="bottom", fontsize=8.5)
        ax.set_title(title, fontsize=9)
        ax.set_ylim(0, max(vb, va) * 1.3)
        ax.spines[["top", "right"]].set_visible(False)
    nb, na = sum(map(bool, b["checks"].values())), sum(map(bool, a["checks"].values()))
    fig.suptitle(f"MEC app soak test with faults ({a['minutes']:g} min, 6 tags + 3 forklifts at {a['devices']['hz']:g} Hz): "
                 f"checks passed {nb}/{len(b['checks'])} before, {na}/{len(a['checks'])} after", fontsize=10.5)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(os.path.join(ROOT, "docs", "img", "stability.png"), dpi=150)
    print("docs/img/stability.png")


if __name__ == "__main__":
    main()
