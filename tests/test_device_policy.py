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


def test_local_fallback_only_while_mec_silent():
    fl = ForkliftLimit("failsafe_local_ttc")
    fl.on_heartbeat(0.0)
    for k in range(6):                                   # worker 2.5 m away, closing at 1 m/s
        fl.on_range(0.5 + 0.1 * k, "w", 3.0 - 0.1 * k)
    assert fl.effective(1.0) is None                     # MEC heard: local rule off
    for k in range(6):
        fl.on_range(2.5 + 0.1 * k, "w", 3.0 - 0.1 * k)
    assert fl.effective(3.0) == 0.0                      # silent 3 s, 2.5 m and closing: stop
    assert fl.vibrate_local(3.0)
    fl.on_heartbeat(3.1)
    assert fl.effective(3.2) is None                     # heard again: back to the MEC plan


def test_local_fallback_ttc_slows_before_the_zone():
    ttc, zone = ForkliftLimit("failsafe_local_ttc"), ForkliftLimit("failsafe_local_zone")
    for fl in (ttc, zone):
        for k in range(6):                               # 9 m away, closing at 3 m/s -> TTC 3 s
            fl.on_range(10.0 + 0.1 * k, "w", 10.5 - 0.3 * k)
    assert ttc.effective(10.6) == 1.0                    # time-to-collision < 4 s: slow
    assert zone.effective(10.6) is None                  # 9 m: outside the distance zones
    assert ForkliftLimit("failsafe").local_limit(10.6) is None


def test_coop_cpa_ignores_a_worker_walking_past():
    """D2D state: a worker 4 m away walking parallel is no reason to stop (range-rate would slow)."""
    fl = ForkliftLimit("coop")
    fl.on_heartbeat(0.0)
    fl.on_own_state(5.0, 0.0, 0.0, 2.0, 0.0)                 # forklift east at 2 m/s
    fl.on_peer_state(5.0, "w", 0.0, 4.0, 2.0, 0.0)            # worker 4 m north, same velocity
    assert fl.effective(5.1) is None
    fl.on_own_state(5.2, 0.0, 0.0, 2.0, 0.0)
    fl.on_peer_state(5.2, "w", 5.0, -1.0, 0.0, 1.0)           # crossing 5 m ahead: closest 1.3 m in 2.2 s
    assert fl.effective(5.3) == 0.0
    assert fl.vibrate_local(5.3)


def test_coop_falls_back_to_range_when_d2d_is_stale():
    fl = ForkliftLimit("coop")
    fl.on_own_state(1.0, 0, 0, 0, 0)
    fl.on_peer_state(1.0, "w", 20, 0, 0, 0)
    for k in range(6):
        fl.on_range(4.0 + 0.1 * k, "w", 2.5)                  # D2D silent since 1.0 s, UWB says 2.5 m
    assert fl.effective(4.6) == 0.0


@pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler")
def test_firmware_coop_matches_python(tmp_path):
    """D2D own / peer states + ranges + heartbeats in random order: same caps in C++ and Python."""
    exe = tmp_path / "policy"
    subprocess.run(["g++", "-std=c++17", "-O1", "-I", os.path.join(ROOT, "firmware", "common"),
                    os.path.join(ROOT, "tests", "firmware", "policy_driver.cpp"), "-o", str(exe)], check=True)
    rng = random.Random(23)
    for _ in range(300):
        fl, lines, expect, t = ForkliftLimit("coop"), ["M 1", "C 1"], [], 0.0
        own = [0.0, 0.0, rng.uniform(-2.5, 2.5), rng.uniform(-2.5, 2.5)]
        peers = {tg: [rng.uniform(-12, 12), rng.uniform(-12, 12), rng.uniform(-1.5, 1.5), rng.uniform(-1.5, 1.5)]
                 for tg in (1, 2)}
        for _ in range(60):
            t = round(t + rng.choice((0.1, 0.1, 0.2, 0.7)), 3)
            if rng.random() < 0.06:
                fl.on_heartbeat(t)
                lines.append(f"H {t:.3f}")
            own[0] += own[2] * 0.1
            own[1] += own[3] * 0.1
            if rng.random() < 0.9:
                o = [round(v, 3) for v in own]
                fl.on_own_state(t, *o)
                lines.append(f"O {t:.3f} {o[0]} {o[1]} {o[2]} {o[3]}")
            for tg, p in peers.items():
                p[0] += p[2] * 0.1
                p[1] += p[3] * 0.1
                tr = round(t + 0.011 * tg, 3)
                if rng.random() < 0.7:
                    q = [round(v, 3) for v in p]
                    fl.on_peer_state(tr, str(tg), *q)
                    lines.append(f"P {tr:.3f} {tg} {q[0]} {q[1]} {q[2]} {q[3]}")
                if rng.random() < 0.6:
                    d = round(((p[0] - own[0]) ** 2 + (p[1] - own[1]) ** 2) ** 0.5, 3)
                    fl.on_range(tr, str(tg), d)
                    lines.append(f"D {tr:.3f} {tg} {d}")
            q = round(t + 0.037, 3)
            lim = fl.effective(q)
            expect.append(-1.0 if lim is None else lim)
            lines.append(f"Q {q:.3f}")
        out = subprocess.run([str(exe)], input="\n".join(lines), capture_output=True, text=True, check=True)
        got = [float(ln.split()[0]) for ln in out.stdout.split("\n") if ln]
        assert got == [pytest.approx(e, abs=1e-3) for e in expect]


@pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler")
def test_firmware_local_fallback_matches_python(tmp_path):
    """Local UWB fallback: random heartbeats / alerts / direct ranges, same answers in C++."""
    exe = tmp_path / "policy"
    subprocess.run(["g++", "-std=c++17", "-O1", "-I", os.path.join(ROOT, "firmware", "common"),
                    os.path.join(ROOT, "tests", "firmware", "policy_driver.cpp"), "-o", str(exe)], check=True)
    rng = random.Random(11)
    for _ in range(300):
        fl, lines, expect, t = ForkliftLimit("failsafe_local_ttc"), ["M 1"], [], 0.0
        d = {1: rng.uniform(1, 12), 2: rng.uniform(1, 12)}
        v = {1: rng.uniform(-3, 1), 2: rng.uniform(-0.45, -0.05)}     # tag 2 near the 0.2 m/s gate
        for _ in range(80):
            t = round(t + rng.choice((0.1, 0.1, 0.1, 0.4, 1.5)), 3)
            k = rng.random()
            if k < 0.08:
                fl.on_heartbeat(t)
                lines.append(f"H {t:.3f}")
            elif k < 0.12:
                lim = round(rng.uniform(0.0, 2.5), 2)
                fl.on_alert(t, "refresh", lim)
                lines.append(f"A {t:.3f} 0 {lim}")
            for tag in (1, 2):
                if rng.random() < 0.8:
                    d[tag] = max(0.2, d[tag] + v[tag] * 0.1 + rng.gauss(0, 0.05))
                    tr = round(t + 0.013 * tag, 3)
                    fl.on_range(tr, str(tag), round(d[tag], 3))
                    lines.append(f"D {tr:.3f} {tag} {round(d[tag], 3)}")
            q = round(t + 0.031, 3)
            lim = fl.effective(q)
            expect.append(-1.0 if lim is None else lim)
            lines.append(f"Q {q:.3f}")
        out = subprocess.run([str(exe)], input="\n".join(lines), capture_output=True, text=True, check=True)
        got = [float(ln.split()[0]) for ln in out.stdout.split("\n") if ln]
        assert got == [pytest.approx(e, abs=1e-3) for e in expect]


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


def test_stop_point_brakes_from_own_position():
    from edgeguard.device_policy import ForkliftLimit
    fl = ForkliftLimit("coop")
    fl.on_heartbeat(0.0)
    fl.on_pose(0.0, 0.0, 1.0, 0.0)
    fl.on_alert(0.0, "raise", None, "w1", stop_at=(5.0, 0.0))
    v5 = fl.effective(0.1)
    fl.on_pose(3.0, 0.0, 1.0, 0.0)                       # closer: tighter, without any new message
    v2 = fl.effective(0.2)
    assert 0 < v2 < v5
    fl.on_pose(5.2, 0.0, 1.0, 0.0)
    assert fl.effective(0.3) == 0.0                      # at / past the point: stop
    fl.on_alert(0.4, "clear", None, "w1")
    assert fl.effective(0.5) is None


def test_stop_point_survives_silence():
    from edgeguard.device_policy import ForkliftLimit
    fl = ForkliftLimit("coop")
    fl.on_heartbeat(0.0)
    fl.on_pose(0.0, 0.0, 1.0, 0.0)
    fl.on_alert(0.0, "raise", None, "w1", stop_at=(6.0, 0.0))
    assert fl.effective(1.5) is not None and fl.effective(1.5) > 0      # MEC restarting: the point is held
    assert fl.effective(7.0) == 0.0                                       # MEC down: stop


def test_firmware_stop_point_matches_python(tmp_path):
    import random
    from edgeguard.device_policy import ForkliftLimit
    exe = tmp_path / "drv"
    subprocess.run(["g++", "-std=c++17", "-O1", "-I", os.path.join(ROOT, "firmware", "common"),
                    os.path.join(ROOT, "tests", "firmware", "policy_driver.cpp"), "-o", str(exe)], check=True)
    rng = random.Random(5)
    for _ in range(20):
        fl = ForkliftLimit("coop")
        lines, expect, t = ["M 0", "C 0"], [], 0.0
        fl.ranges, fl.peers = {}, {}
        x = 0.0
        for _ in range(40):
            t = round(t + rng.uniform(0.05, 0.6), 2)
            k = rng.random()
            if k < 0.25:
                lim = rng.choice([-1.0, round(rng.uniform(0, 3), 2)])
                sx = round(x + rng.uniform(-1, 12), 2)
                src = rng.choice(["w1", "w2"])
                fl.on_alert(t, "refresh", None if lim < 0 else lim, src, stop_at=(sx, 0.0))
                lines.append(f"S {t} {src} {lim} {sx} 0")
            elif k < 0.35:
                src = rng.choice(["w1", "w2"])
                fl.on_alert(t, "clear", None, src)
                lines.append(f"K {t} {src}")
            elif k < 0.55:
                fl.on_heartbeat(t)
                lines.append(f"H {t}")
            elif k < 0.75:
                x = round(x + rng.uniform(0, 1.5), 2)
                fl.on_pose(x, 0.0, 1.0, 0.0)
                lines.append(f"X {x} 0 1 0")
            else:
                v = fl.effective(t)
                expect.append(-1.0 if v is None else v)
                lines.append(f"Q {t}")
        out = subprocess.run([str(exe)], input="\n".join(lines), capture_output=True, text=True, check=True)
        got = [float(ln.split()[0]) for ln in out.stdout.split("\n") if ln]
        assert got == [pytest.approx(e, abs=2e-3) for e in expect]
