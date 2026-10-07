import filecmp
import os
import random
import shutil
import subprocess

import pytest

from edgeguard.device_policy import CREEP_MPS, ForkliftLimit, ReportRate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_lost_clear_is_lifted_while_mec_alive():
    fl = ForkliftLimit()
    fl.on_alert(0.0, "raise", 1.2)
    assert fl.effective(1.0) == 1.2
    for t in range(1, 7):
        fl.on_heartbeat(float(t))
        if t <= 5:
            assert fl.effective(float(t)) == 1.2     # hold the plan between refreshes
    assert fl.effective(6.0) is None         # no refresh for 5 s, but MEC heard: the clear was lost


def test_silence_never_lifts_the_limit():
    fl = ForkliftLimit()
    fl.on_alert(0.0, "raise", 1.2)
    assert fl.effective(1.8) == 1.2          # MEC silent (restarting): hold the plan
    assert fl.effective(2.1) == 0.0          # silent > 2 s: stop
    assert fl.effective(60.0) == 0.0         # MEC down: stop, never lift
    legacy = ForkliftLimit("legacy")
    legacy.on_alert(0.0, "raise", 1.2)
    assert legacy.effective(60.0) is None    # v0.6 behaviour: lifted after 5 s
    creep = ForkliftLimit("failsafe_creep")
    creep.on_alert(0.0, "raise", 1.2)
    assert creep.effective(1.5) == CREEP_MPS
    fl.on_alert(61.0, "refresh", 0.3)        # MEC back with a tighter limit
    assert fl.effective(61.5) == 0.3
    fl.on_alert(62.0, "clear", None)
    assert fl.effective(62.1) is None


def test_rate_command_falls_back_to_full_rate():
    r = ReportRate()
    assert r.current(0.0) == 10.0
    r.on_command(1.0, 2.0)
    assert r.current(5.0) == 2.0
    assert r.current(7.5) == 10.0


@pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler")
def test_firmware_header_matches_python(tmp_path):
    """Random alert / heartbeat / rate-command sequences through device_policy.py and the
    firmware header must give the same limit and rate at every query."""
    exe = tmp_path / "policy"
    subprocess.run(["g++", "-std=c++17", "-O1", "-I", os.path.join(ROOT, "firmware", "common"),
                    os.path.join(ROOT, "tests", "firmware", "policy_driver.cpp"), "-o", str(exe)], check=True)
    rng = random.Random(7)
    for _ in range(40):
        fl, rr, lines, expect, t = ForkliftLimit(), ReportRate(), [], [], 0.0
        for _ in range(60):
            t += rng.choice((0.1, 0.3, 0.5, 1.0, 2.0, 4.0))          # events on a 0.1 s grid
            k = rng.random()
            if k < 0.35:
                clear = rng.random() < 0.2
                lim = round(rng.uniform(0.0, 2.5), 2)
                fl.on_alert(t, "clear" if clear else "refresh", None if clear else lim)
                lines.append(f"A {t:.2f} {int(clear)} {lim}")
            elif k < 0.6:
                fl.on_heartbeat(t)
                lines.append(f"H {t:.2f}")
            elif k < 0.75:
                hz = rng.choice((2.0, 10.0))
                rr.on_command(t, hz)
                lines.append(f"R {t:.2f} {hz}")
            q = t + 0.05 + rng.choice((0.0, 0.5, 1.0, 1.5, 2.5, 5.0, 7.0))   # never on a threshold
            lim = fl.effective(q)
            expect.append((-1.0 if lim is None else lim, rr.current(q)))
            lines.append(f"Q {q:.2f}")
        out = subprocess.run([str(exe)], input="\n".join(lines), capture_output=True, text=True, check=True)
        got = [tuple(map(float, ln.split())) for ln in out.stdout.split("\n") if ln]
        assert got == [pytest.approx(e, abs=1e-3) for e in expect]


def test_firmware_header_copies_in_sync():
    src = os.path.join(ROOT, "firmware", "common", "device_policy.h")
    for sk in ("worker_tag", "forklift_module"):
        assert filecmp.cmp(src, os.path.join(ROOT, "firmware", sk, "device_policy.h"), shallow=False)
