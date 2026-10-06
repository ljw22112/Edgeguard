import math
import os
import random
import shutil
import subprocess

import pytest

from edgeguard.uwb import locate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = [(0, 0, 3), (20, 0, 3), (20, 12, 3), (0, 12, 3)]
TZ = 1.2


def ranges(x, y, noise=0.0, rng=None):
    return [math.sqrt((x - ax) ** 2 + (y - ay) ** 2 + (TZ - az) ** 2) + (rng.gauss(0, noise) if rng else 0)
            for ax, ay, az in A]


def test_clean_and_noisy_fix():
    f = locate(A, ranges(7.3, 5.1), TZ)
    assert f.ok and f.x == pytest.approx(7.3, abs=1e-3) and f.y == pytest.approx(5.1, abs=1e-3)
    rng = random.Random(3)
    errs = [math.hypot(*(lambda f: (f.x - x, f.y - y))(locate(A, ranges(x, y, 0.1, rng), TZ)))
            for x in range(1, 20, 3) for y in range(1, 12, 3)]
    assert sum(errs) / len(errs) < 0.15


def test_nlos_anchor_rejected():
    d = ranges(6, 4)
    d[2] += 1.5
    f = locate(A, d, TZ)
    assert f.rejected == 2 and math.hypot(f.x - 6, f.y - 4) < 0.05


@pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler")
def test_firmware_header_on_host(tmp_path):
    exe = tmp_path / "t_uwb"
    subprocess.run(["g++", "-std=c++17", "-O2", "-I", os.path.join(ROOT, "firmware", "common"),
                    os.path.join(ROOT, "tests", "firmware", "test_uwb_position.cpp"), "-o", str(exe)], check=True)
    out = subprocess.run([str(exe)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout
