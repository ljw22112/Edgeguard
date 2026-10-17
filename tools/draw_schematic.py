"""Draw the electronic schematics of the worker tag and the forklift module.

    python tools/draw_schematic.py        # docs/img/schematic_tag.{png,svg}, docs/img/schematic_forklift.{png,svg}

Pins come from the firmware (firmware/worker_tag/worker_tag.ino, firmware/forklift_module/forklift_module.ino):
  both  DWM1000 UWB on the ESP32 VSPI bus: SCK 18, MISO 19, MOSI 23; IRQ 34 (input-only pin)
  tag   DWM1000 SS 4, RST 27; vibration motor GPIO 25 (2N2222 low side); WAIT LED GPIO 2
  fork  DWM1000 SS 5, RST 17; MPU-6050 I2C SDA 21, SCL 22 (address 0x68, AD0 low);
        drive motor PWM GPIO 27 (20 kHz, logic-level MOSFET low side); beacon LED GPIO 26
Parts follow docs/hardware-demo.md.  The ESP32 DevKit's own regulator supplies 3.3 V (DWM1000 draws up to
~150 mA in receive: within the AMS1117's budget); the forklift's drive motor runs from a separate 5 V supply
with a common ground.
"""
from pathlib import Path

import schemdraw
import schemdraw.elements as elm

OUT = Path(__file__).resolve().parent.parent / "docs" / "img"


def esp32(pins_left, pins_right):
    return elm.Ic(pins=[elm.IcPin(name="3V3", side="top", slot="1/3"), elm.IcPin(name="VIN (5V)", side="top", slot="3/3"),
                        elm.IcPin(name="GND", side="bottom", slot="2/3")]
                  + [elm.IcPin(name=n, side="left") for n in pins_left]
                  + [elm.IcPin(name=n, side="right") for n in pins_right],
                  edgepadW=1.2, edgepadH=1.0, pinspacing=1.1, leadlen=0.9, lsize=12) \
        .label("U1  ESP32-WROOM-32 DevKit", "bottom", ofst=(3.4, -0.6), fontsize=12)


def dwm1000(name="U2"):
    return elm.Ic(pins=[elm.IcPin(name="VDD 3V3", side="top"), elm.IcPin(name="GND", side="bottom")]
                  + [elm.IcPin(name=n, side="right") for n in ("SPICLK", "SPIMISO", "SPIMOSI", "SPICSn", "IRQ", "RSTn")],
                  edgepadW=0.9, edgepadH=1.0, pinspacing=1.1, leadlen=0.9, lsize=12) \
        .label(f"{name}  DWM1000 UWB", "bottom", ofst=(-2.4, -0.6), fontsize=12)


SPI = [("SPICLK", "GPIO18 SCK"), ("SPIMISO", "GPIO19 MISO"), ("SPIMOSI", "GPIO23 MOSI")]


def uwb_block(d, u1, ss, rst):
    """DWM1000 to the left of U1 with SPI, IRQ, reset, supply and decoupling."""
    u2 = d.add(dwm1000().at((u1.absanchors["GPIO18 SCK"][0] - 7.0, u1.absanchors["GPIO18 SCK"][1])).anchor("SPICLK"))
    for a, b in SPI + [("SPICSn", ss), ("IRQ", "GPIO34 IRQ"), ("RSTn", rst)]:
        d.add(elm.Wire("-").at(u2.absanchors[a]).to(u1.absanchors[b]))
    return u2


def supply(d, at, label="3V3"):
    return d.add(elm.Vdd().at(at).label(label, fontsize=11))


def ground(d, at):
    return d.add(elm.Ground().at(at))


def decoupling(d, at):
    """100 nF + 10 uF from a 3V3 node to ground, to the left of `at`, above the module."""
    d.add(elm.Line().at(at).left(1.6))
    p = d.here
    d.add(elm.Capacitor().down(1.5).label("C1\n100 nF", loc="top", fontsize=10))
    ground(d, d.here)
    d.add(elm.Line().at(p).left(2.0))
    d.add(elm.Capacitor(polar=True).down(1.5).label("C2\n10 µF", loc="top", fontsize=10))
    ground(d, d.here)


def tag():
    with schemdraw.Drawing(show=False) as d:
        d.config(fontsize=12, unit=2.2, lw=1.4)
        u1 = d.add(esp32(["GPIO18 SCK", "GPIO19 MISO", "GPIO23 MOSI", "GPIO4 SS", "GPIO34 IRQ", "GPIO27 RST"],
                         ["GPIO2 LED", "GPIO25 MOTOR"]))
        u2 = uwb_block(d, u1, "GPIO4 SS", "GPIO27 RST")
        # supplies
        d.add(elm.Line().at(u1.absanchors["3V3"]).up(1.2))
        supply(d, d.here)
        d.add(elm.Line().at(u1.absanchors["VIN (5V)"]).up(1.2))
        d.add(elm.Vdd().label("5V USB /\npower bank", fontsize=10))
        ground(d, u1.absanchors["GND"])
        d.add(elm.Line().at(u2.absanchors["VDD 3V3"]).up(3.4))
        top = d.here
        supply(d, top)
        decoupling(d, (top[0], top[1] - 0.4))
        ground(d, u2.absanchors["GND"])
        # vibration motor: GPIO25 -> 1k -> 2N2222 base, motor from 3V3 to collector, 1N4148 across the motor
        m = u1.absanchors["GPIO25 MOTOR"]
        d.add(elm.Resistor().at(m).right(2.6).label("R1 1 kΩ", fontsize=11))
        q = d.add(elm.BjtNpn(circle=True).anchor("base").label("Q1\n2N2222", loc="right", ofst=(0.2, 0), fontsize=11))
        ground(d, q.emitter)
        d.add(elm.Line().at(q.collector).up(0.8))
        node = d.here
        d.add(elm.Motor().up(2.2).label("M1 coin\nvibration motor", loc="top", ofst=0.6, fontsize=10))
        mtop = d.here
        d.add(elm.Line().up(0.6))
        supply(d, d.here)
        d.add(elm.Line().at(node).right(1.8))
        d.add(elm.Diode().up(2.2).label("D1\n1N4148", loc="right", fontsize=10))   # cathode to 3V3
        d.add(elm.Line().left(1.8).to(mtop))
        # WAIT LED: GPIO2 -> 220R -> LED -> GND
        d.add(elm.Line().at(u1.absanchors["GPIO2 LED"]).right(1.2))
        d.add(elm.Resistor().down(2.2).label("R2\n220 Ω", loc="bottom", fontsize=10))
        d.add(elm.LED().down(1.8).label("D2 red\nWAIT LED", loc="bottom", fontsize=10))
        ground(d, d.here)
        d.add(elm.Label().at((u2.absanchors["GND"][0] - 1.5, u2.absanchors["GND"][1] - 3.6)).label(
            "EdgeGuard worker tag - all grounds common; DWM1000 IRQ on GPIO34 (input only, no pull-up needed: push-pull)",
            fontsize=10, halign="left"))
        d.save(OUT / "schematic_tag.svg")
        d.save(OUT / "schematic_tag.png", dpi=170)


def forklift():
    with schemdraw.Drawing(show=False) as d:
        d.config(fontsize=12, unit=2.2, lw=1.4)
        u1 = d.add(esp32(["GPIO18 SCK", "GPIO19 MISO", "GPIO23 MOSI", "GPIO5 SS", "GPIO34 IRQ", "GPIO17 RST"],
                         ["GPIO26 BEACON", "GPIO21 SDA", "GPIO22 SCL", "GPIO27 PWM"]))
        u2 = uwb_block(d, u1, "GPIO5 SS", "GPIO17 RST")
        d.add(elm.Line().at(u1.absanchors["3V3"]).up(1.2))
        supply(d, d.here)
        d.add(elm.Line().at(u1.absanchors["VIN (5V)"]).up(1.2))
        d.add(elm.Vdd().label("5V logic\npower bank", fontsize=10))
        ground(d, u1.absanchors["GND"])
        d.add(elm.Line().at(u2.absanchors["VDD 3V3"]).up(3.4))
        top = d.here
        supply(d, top)
        decoupling(d, (top[0], top[1] - 0.4))
        ground(d, u2.absanchors["GND"])
        # MPU-6050 on I2C (breakout with 4.7k pull-ups on board), AD0 low -> 0x68
        sda = u1.absanchors["GPIO21 SDA"]
        u3 = d.add(elm.Ic(pins=[elm.IcPin(name="SDA", side="left"), elm.IcPin(name="SCL", side="left"),
                                elm.IcPin(name="VCC", side="top"), elm.IcPin(name="GND", side="bottom"),
                                elm.IcPin(name="AD0", side="right")],
                          edgepadW=0.8, edgepadH=0.8, pinspacing=1.1, leadlen=0.9, lsize=12)
                   .label("U3  MPU-6050 (0x68)", "top", ofst=(0, 0.2), fontsize=12).theta(0).at((sda[0] + 8.0, sda[1])).anchor("SDA"))
        d.add(elm.Wire("-").at(sda).to(u3.absanchors["SDA"]))
        d.add(elm.Wire("-").at(u1.absanchors["GPIO22 SCL"]).to(u3.absanchors["SCL"]))
        d.add(elm.Line().at(u3.absanchors["VCC"]).up(0.8))
        supply(d, d.here)
        ground(d, u3.absanchors["GND"])
        d.add(elm.Line().at(u3.absanchors["AD0"]).right(0.6))
        d.add(elm.Line().down(0.6))
        ground(d, d.here)
        d.add(elm.Label().at((u3.absanchors["SDA"][0] - 4.5, u3.absanchors["SDA"][1] - 0.5)).label(
            "4.7 kΩ pull-ups on the breakout", fontsize=9, halign="left"))
        # drive motor: GPIO27 PWM (20 kHz) -> 100R gate, 10k pull-down, IRLZ44N low side; 1N5819 across the motor
        p = u1.absanchors["GPIO27 PWM"]
        d.add(elm.Line().at(p).right(0.8))
        d.add(elm.Line().up(2.4))
        d.add(elm.Resistor().right(2.6).label("R3 100 Ω", loc="top", fontsize=11))
        g = d.here
        d.add(elm.Line().right(1.4))
        q = d.add(elm.NFet(bulk=True).theta(0).reverse().anchor("gate"))
        d.add(elm.Label().at((q.drain[0] + 0.4, (q.drain[1] + q.source[1]) / 2)).label(
            "Q2 IRLZ44N\n(logic-level)", fontsize=10, halign="left"))
        ground(d, q.source)
        d.add(elm.Resistor().at(g).down(1.6).label("R4\n10 kΩ", loc="bottom", fontsize=10))
        ground(d, d.here)
        d.add(elm.Line().at(q.drain).up(0.8))
        node = d.here
        d.add(elm.Motor().up(2.2).label("M2 drive\nmotor", loc="top", ofst=0.6, fontsize=10))
        mtop = d.here
        d.add(elm.Line().up(0.6))
        d.add(elm.Vdd().label("+5V motor supply\n(separate, common GND)", fontsize=10))
        d.add(elm.Line().at(node).right(1.8))
        d.add(elm.Diode().up(2.2).label("D3\n1N5819", loc="right", fontsize=10))   # cathode to +5V
        d.add(elm.Line().left(1.8).to(mtop))
        # beacon LED
        d.add(elm.Line().at(u1.absanchors["GPIO26 BEACON"]).right(1.2))
        d.add(elm.Resistor().down(2.2).label("R5\n220 Ω", loc="bottom", fontsize=10))
        d.add(elm.LED().down(1.8).label("D4 amber\nbeacon", loc="bottom", fontsize=10))
        ground(d, d.here)
        d.add(elm.Label().at((u2.absanchors["GND"][0] - 1.5, u2.absanchors["GND"][1] - 3.6)).label(
            "EdgeGuard forklift module - all grounds common; L298N instead of Q2: GPIO27 -> ENA, IN1 high, IN2 low",
            fontsize=10, halign="left"))
        d.save(OUT / "schematic_forklift.svg")
        d.save(OUT / "schematic_forklift.png", dpi=170)


if __name__ == "__main__":
    tag()
    forklift()
    print("docs/img/schematic_tag.png, docs/img/schematic_forklift.png")
