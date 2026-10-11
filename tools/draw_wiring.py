"""Draw docs/img/wiring.png: wiring of the worker tag and the forklift module.

Pins come from the firmware (worker_tag.ino, forklift_module.ino) and docs/hardware-demo.md.
DWM1000 uses the ESP32 default SPI bus (SCK 18, MISO 19, MOSI 23).
Run: python tools/draw_wiring.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "docs" / "img" / "wiring.png"

INK = "#1f2933"
MUTED = "#52606d"
ESP = "#e8f0fe"
PART = "#fff4e5"
UWB = "#e6f6ec"
WIRE = {"spi": "#2f6fdf", "ctl": "#c2410c", "pwr": "#b91c1c", "gnd": "#334155"}


def box(ax, x, y, w, h, fill, title, sub=None):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc=fill, ec=INK, lw=1.4))
    ax.text(x + w / 2, y + h - 0.22, title, ha="center", va="top", fontsize=10.5, weight="bold", color=INK)
    if sub:
        ax.text(x + w / 2, y + h - 0.62, sub, ha="center", va="top", fontsize=8, color=MUTED)


def pin(ax, x, y, label, side):
    ax.plot([x], [y], marker="o", ms=4, color=INK)
    # label sits inside the box, next to its edge
    ha = "left" if side == "left" else "right"
    dx = 0.15 if side == "left" else -0.15
    ax.text(x + dx, y, label, ha=ha, va="center", fontsize=8.5, color=INK, family="monospace")


def wire(ax, pts, kind, label=None, lx=None, ly=None):
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=WIRE[kind], lw=1.8, solid_capstyle="round")
    if label:
        ax.text(lx, ly, label, fontsize=8, color=WIRE[kind], ha="center", va="bottom")


def esp32(ax, x, y, left, right, title):
    h = 1.0 + 0.42 * max(len(left), len(right))
    box(ax, x, y, 3.4, h, ESP, title, "ESP32 DevKit")
    lp, rp = {}, {}
    for i, name in enumerate(left):
        py = y + h - 1.15 - 0.42 * i
        pin(ax, x, py, name, "left")
        lp[name] = (x, py)
    for i, name in enumerate(right):
        py = y + h - 1.15 - 0.42 * i
        pin(ax, x + 3.4, py, name, "right")
        rp[name] = (x + 3.4, py)
    return lp, rp


def dwm1000(ax, x, y, pins):
    h = 1.0 + 0.42 * len(pins)
    box(ax, x, y, 2.6, h, UWB, "DWM1000", "UWB ranging (SPI)")
    p = {}
    for i, name in enumerate(pins):
        py = y + h - 1.15 - 0.42 * i
        pin(ax, x + 2.6, py, name, "right")
        p[name] = (x + 2.6, py)
    return p


def spi_block(ax, uwb, lp, names):
    for k, (u, e) in enumerate(names):
        ux, uy = uwb[u]
        ex, ey = lp[e]
        mid = ux + 0.7 + 0.06 * k
        kind = "pwr" if u == "VCC" else "gnd" if u == "GND" else "spi"
        wire(ax, [(ux, uy), (mid, uy), (mid, ey), (ex, ey)], kind)


def main():
    fig, ax = plt.subplots(figsize=(17, 8.2), dpi=150)
    ax.set_xlim(0, 34)
    ax.set_ylim(0, 15.2)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(0.3, 14.9, "EdgeGuard wiring", fontsize=16, weight="bold", color=INK, va="top")
    ax.text(0.3, 14.25, "Pins as used by firmware/worker_tag and firmware/forklift_module. "
            "The DWM1000 uses the ESP32 default SPI bus. With HIL_MODE 1 the boards run without the DWM1000.",
            fontsize=9.5, color=MUTED, va="top")

    # ---- worker tag (left half) ----
    ax.text(0.6, 13.1, "Worker tag", fontsize=13, weight="bold", color=INK)
    spi_pins = ["VCC", "GND", "SCK", "MISO", "MOSI", "CS", "IRQ", "RST"]
    uwb = dwm1000(ax, 0.6, 7.0, spi_pins)
    lp, rp = esp32(ax, 4.9, 7.0,
                   ["3V3", "GND", "GPIO18", "GPIO19", "GPIO23", "GPIO4", "GPIO34", "GPIO27"],
                   ["GPIO25", "GPIO2", "3V3 ", "GND "], "Worker tag")
    spi_block(ax, uwb, lp, list(zip(spi_pins, ["3V3", "GND", "GPIO18", "GPIO19", "GPIO23", "GPIO4", "GPIO34", "GPIO27"])))

    # vibration motor driver: GPIO25 -> 1k -> NPN base; motor between 3.3 V and collector; diode across motor
    gx, gy = rp["GPIO25"]
    box(ax, 10.9, 9.7, 4.8, 3.4, PART, "Vibration cue", "coin motor, 2N2222, 1N4148")
    wire(ax, [(gx, gy), (9.6, gy), (9.6, 10.6), (10.9, 10.6)], "ctl", "1 kΩ", 8.95, gy + 0.05)
    ax.text(13.3, 11.9, "GPIO25 → 1 kΩ → NPN base\n3V3 → motor → NPN collector\n1N4148 across the motor\nNPN emitter → GND",
            ha="center", va="top", fontsize=8.5, color=INK)
    lx, ly = rp["GPIO2"]
    box(ax, 10.9, 7.0, 4.8, 1.9, PART, "WAIT LED", "220 Ω → LED → GND")
    wire(ax, [(lx, ly), (9.1, ly), (9.1, 7.6), (10.9, 7.6)], "ctl")

    # ---- forklift module (right half) ----
    ax.text(17.6, 13.1, "Forklift module", fontsize=13, weight="bold", color=INK)
    uwb2 = dwm1000(ax, 17.6, 7.0, spi_pins)
    lp2, rp2 = esp32(ax, 21.9, 7.0,
                     ["3V3", "GND", "GPIO18", "GPIO19", "GPIO23", "GPIO5", "GPIO34", "GPIO17"],
                     ["GPIO27", "GPIO26", "GND "], "Forklift module")
    spi_block(ax, uwb2, lp2, list(zip(spi_pins, ["3V3", "GND", "GPIO18", "GPIO19", "GPIO23", "GPIO5", "GPIO34", "GPIO17"])))

    px, py = rp2["GPIO27"]
    box(ax, 27.9, 9.7, 5.4, 3.4, PART, "Drive (speed limit)", "L298N or MOSFET module")
    wire(ax, [(px, py), (26.6, py), (26.6, 10.6), (27.9, 10.6)], "ctl", "PWM", 25.95, py + 0.05)
    ax.text(30.6, 11.9, "GPIO27 → driver EN (PWM)\nSmall DC motor on the driver output\npower bank supply, common GND",
            ha="center", va="top", fontsize=8.5, color=INK)
    bx, by = rp2["GPIO26"]
    box(ax, 27.9, 7.0, 5.4, 1.9, PART, "Beacon LED", "220 Ω → LED → GND")
    wire(ax, [(bx, by), (26.1, by), (26.1, 7.6), (27.9, 7.6)], "ctl")

    # ---- pin table ----
    rows = [
        ("Board", "Signal", "ESP32 pin", "Firmware constant"),
        ("Tag", "Vibration motor (via NPN)", "GPIO25", "MOTOR_PIN"),
        ("Tag", "WAIT LED", "GPIO2", "LED_PIN"),
        ("Tag", "DWM1000 CS / IRQ / RST", "GPIO4 / 34 / 27", "PIN_SS / PIN_IRQ / PIN_RST"),
        ("Forklift", "Motor driver PWM", "GPIO27", "MOTOR_PWM_PIN"),
        ("Forklift", "Beacon LED", "GPIO26", "BEACON_PIN"),
        ("Forklift", "DWM1000 CS / IRQ / RST", "GPIO5 / 34 / 17", "PIN_SS / PIN_IRQ / PIN_RST"),
        ("Both", "DWM1000 SCK / MISO / MOSI", "GPIO18 / 19 / 23", "default SPI"),
    ]
    cols = [0.6, 3.6, 10.6, 16.4]
    for r, row in enumerate(rows):
        y = 5.9 - 0.62 * r
        for c, cell in enumerate(row):
            ax.text(cols[c], y, cell, fontsize=9, color=INK, va="center",
                    weight="bold" if r == 0 else "normal",
                    family="monospace" if c in (2, 3) and r else None)
    ax.plot([0.6, 24.5], [5.58, 5.58], color=MUTED, lw=0.8)

    # legend
    for i, (k, t) in enumerate([("spi", "SPI / UWB"), ("ctl", "control output"), ("pwr", "3.3 V"), ("gnd", "GND")]):
        x = 27.0
        y = 5.9 - 0.62 * i
        ax.plot([x, x + 0.8], [y, y], color=WIRE[k], lw=2.2)
        ax.text(x + 1.0, y, t, fontsize=9, va="center", color=INK)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, bbox_inches="tight", facecolor="white")
    print(OUT)


if __name__ == "__main__":
    main()
