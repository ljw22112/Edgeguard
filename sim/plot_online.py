"""Figure for the online closed-loop simulation (results/online_sim.png)."""
import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
BASE, OURS, REF = "#b9b8b2", "#2a78d6", "#d03b3b"
LABELS = {
    "baseline": "Baseline", "noise_high": "UWB noise 0.35 m", "uplink_loss_10": "Uplink loss 10%",
    "uplink_loss_30": "Uplink loss 30%", "downlink_loss_20": "Alert loss 20%",
    "wifi_latency": "Wi-Fi latency 60±30 ms", "rate_5hz": "Sample rate 5 Hz",
    "clock_skew": "Clock skew ±300 ms", "uwb_shadow": "UWB shadow 3 s",
    "odd_behaviour": "Running / zigzag / reversing", "crowded_aisle": "Crowded aisle (6+6)",
    "worst_combined": "Worst case combined", "proximity_5m": "Proximity 5 m (baseline system)",
}


def main(path="results/online_sim.json", out="results/online_sim.png"):
    rs = json.load(open(path))["results"][::-1]
    names = [LABELS.get(r["case"], r["case"]) for r in rs]
    y = range(len(rs))
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9.5})
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(14, 0.42 * len(rs) + 1.6), facecolor=SURFACE,
                                     sharey=True, gridspec_kw={"width_ratios": [1.3, 1, 1]})
    h = 0.36
    wo = [r["collisions_without_system"] for r in rs]
    wi = [r["collisions_with_system"] for r in rs]
    a1.barh([i + h / 2 for i in y], wo, h, color=BASE, edgecolor=SURFACE, linewidth=1.5, label="no safety system")
    a1.barh([i - h / 2 for i in y], wi, h, color=OURS, edgecolor=SURFACE, linewidth=1.5, label="with the system (closed loop)")
    for i, (a, b) in enumerate(zip(wo, wi)):
        a1.text(max(a, b) + 0.15, i, f"{a} → {b}", va="center", color=INK, fontsize=9)
    a1.set_title("Collisions (centre distance < 1.0 m)", loc="left", fontweight="bold", color=INK)
    a1.legend(loc="upper right", frameon=False, fontsize=8.5, bbox_to_anchor=(1.0, 1.0))
    a1.set_xlim(0, max(wo) * 1.35)
    a1.set_yticks(list(y))
    a1.set_yticklabels(names)

    lead = [r["median_lead_s"] or 0 for r in rs]
    a2.barh(list(y), lead, 0.55, color=[OURS if r["case"] != "proximity_5m" else BASE for r in rs],
            edgecolor=SURFACE, linewidth=1.5)
    a2.axvline(1.0, color=REF, linewidth=1.2, linestyle="--")
    a2.text(1.03, len(rs) - 0.4, "required 1 s", color=REF, fontsize=8)
    for i, (v, r) in enumerate(zip(lead, rs)):
        td = r["timely_detection"]
        a2.text(v + 0.05, i, f"{v:.1f} s  ({td:.0%} timely)" if td is not None else "-", va="center",
                color=INK, fontsize=8.5)
    a2.set_title("Median warning lead time", loc="left", fontweight="bold", color=INK)
    a2.set_xlim(0, max(lead) * 1.75)

    lost = [r["forklift_time_lost_s_per_episode"] for r in rs]
    a3.barh(list(y), lost, 0.55, color=[OURS if r["case"] != "proximity_5m" else BASE for r in rs],
            edgecolor=SURFACE, linewidth=1.5)
    for i, (v, r) in enumerate(zip(lost, rs)):
        fa = r["false_alarm_rate"]
        a3.text(v + 0.05, i, f"{v:.1f} s  (FA {fa:.0%})" if fa is not None else f"{v:.1f} s", va="center",
                color=INK, fontsize=8.5)
    a3.set_title("Forklift time lost per encounter", loc="left", fontweight="bold", color=INK)
    a3.set_xlim(0, max(lost) * 1.9)
    for ax in (a1, a2, a3):
        ax.set_facecolor(SURFACE)
        ax.xaxis.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(colors=INK2, length=0)
        for sp in ax.spines.values():
            sp.set_visible(False)
    eps = rs[0]["episodes"]
    fig.text(0.01, 0.01, f"Online closed-loop simulation through Mobius + MEC app; {eps} encounters per case "
             "(8 concurrent worker/forklift pairs x 3 rounds; crowded aisle: 6+6 sharing one area). "
             "FA = false-alarm rate on encounters that would not have collided.", color=INK2, fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=170, facecolor=SURFACE)
    print("saved", out)


if __name__ == "__main__":
    main(*sys.argv[1:])
