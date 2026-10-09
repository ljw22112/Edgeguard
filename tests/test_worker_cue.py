"""Worker WAIT / GO cue (edgeguard/worker_cue.py, firmware/common/worker_cue.h) and the MEC side
(alerting.decide: WAIT keep-alive, GO check; forklift ignores worker-only cues)."""
import os
import random
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.worker_cue import WaitCue, HOLD_IDLE_S          # noqa: E402
from edgeguard.alerting import AlertState, decide              # noqa: E402
from edgeguard.device_policy import ForkliftLimit              # noqa: E402
from edgeguard.risk import RiskConfig, assess                  # noqa: E402
from edgeguard.tracking import Track                           # noqa: E402


def test_wait_until_go_and_idle_timeout():
    c = WaitCue()
    c.on_alert(0.0, "raise", vibrate=True, danger=False)
    assert c.led(0.1) and c.motor(0.1)                 # burst
    assert c.led(2.0)                                  # still waiting (< HOLD_IDLE_S)
    c.on_alert(2.0, "wait")                            # keep-alive
    assert c.led(4.0)
    c.on_alert(4.2, "release")
    assert not c.led(4.25) and c.motor(4.25)           # GO pulse
    assert not c.motor(5.0)
    c.on_alert(6.0, "raise", vibrate=True)
    assert not c.led(6.0 + HOLD_IDLE_S + 0.01)         # nothing heard: gives up the hold
    c.on_alert(10.0, "refresh", vibrate=False)         # no vibrate, not waiting: nothing
    assert not c.led(10.1)


@pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler")
def test_cpp_cue_matches_python(tmp_path):
    exe = tmp_path / "cue"
    subprocess.run(["g++", "-std=c++17", "-Wall", "-I", os.path.join(ROOT, "firmware", "common"),
                    os.path.join(ROOT, "tests", "firmware", "cue_driver.cpp"), "-o", str(exe)], check=True)
    rng = random.Random(3)
    for _ in range(100):
        py, lines, expect, t = WaitCue(), [], [], 0.013
        for _ in range(60):
            t = round(t + rng.choice([0.051, 0.097, 0.313, 0.709, 1.103, 2.917]), 3)   # off the cue's boundaries
            if rng.random() < 0.35:
                ev = rng.choice(["raise", "refresh", "wait", "clear", "release", "hb"])
                vb, dg = rng.random() < 0.6, rng.random() < 0.3
                py.on_alert(t, ev, vb, dg)
                lines.append(f"A {t:.3f} {ev} {int(vb)} {int(dg)}")
            else:
                expect.append(f"{int(py.motor(t))} {int(py.led(t))}")
                lines.append(f"Q {t:.3f}")
        out = subprocess.run([str(exe)], input="\n".join(lines), capture_output=True, text=True, check=True)
        assert out.stdout.split("\n")[:-1] == expect


def test_forklift_ignores_worker_only_cues():
    fl = ForkliftLimit("failsafe")
    fl.on_alert(0.0, "raise", 0.8)
    fl.on_alert(0.5, "wait", None)
    fl.on_alert(0.6, "release", None)
    assert fl.effective(0.7) == 0.8


def _track(oid, kind, pts, speed=None, heading=None):
    tr = Track(oid, kind)
    for t, (x, y) in pts:
        kw = {} if speed is None else {"speed": speed, "heading": heading, "yaw_rate": 0.0}
        tr.update(t, x=x, y=y, **kw)
    return tr


def test_keepalive_and_go_check():
    cfg = RiskConfig(wait_keepalive=True, go_check=True)
    st = AlertState(debounce=cfg.debounce)
    # worker walking +y toward the forklift lane (y = 0), forklift along +x
    w = _track("w", "worker", [(k * 0.1, (0.0, -4.0 + 1.2 * k * 0.1)) for k in range(6)])
    f = _track("f", "forklift", [(k * 0.1, (-6.5 + 2.0 * k * 0.1, 0.0)) for k in range(6)], 2.0, 0.0)
    evs = []
    for k in range(3):
        r = assess(w, f, cfg)
        evs.append(decide(st, r, w, f, cfg, 0.5 + 0.1 * k)[0])
    assert "raise" in evs and st.intent is not None
    # the worker has stopped 2.5 m short of the lane: no conflict now, but walking on would cross
    w2 = _track("w", "worker", [(1.0 + k * 0.1, (0.0, -2.5)) for k in range(8)])
    f2 = _track("f", "forklift", [(1.0 + k * 0.1, (-5.0 + 2.0 * k * 0.1, 0.0)) for k in range(8)], 2.0, 0.0)
    r = assess(w2, f2, cfg)
    assert r.level < 2
    ev, acts = decide(st, r, w2, f2, cfg, 2.0)
    assert r.hold and r.level == 2 and "still to pass" in r.reason
    # keep-alive: nothing else to send for a second -> `wait` for the worker only
    st.last_any = 0.0
    st.last_sent = 10.0
    r = assess(w2, f2, cfg)
    ev, acts = decide(st, r, w2, f2, cfg, 3.5)
    assert ev in ("refresh", "wait")
    if ev == "wait":
        assert set(acts) == {"w"}
