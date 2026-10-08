"""D2D authentication: C++ (firmware) and Python agree byte for byte; tampering and replays fail."""
import os
import random
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard import d2d_auth   # noqa: E402

KEY = b"edgeguard-test-site-key"


@pytest.fixture(scope="module")
def drv(tmp_path_factory):
    if shutil.which("g++") is None:
        pytest.skip("no C++ compiler")
    exe = tmp_path_factory.mktemp("d2d") / "auth"
    subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-O1", "-I", os.path.join(ROOT, "firmware", "common"),
                    os.path.join(ROOT, "tests", "firmware", "d2d_auth_driver.cpp"), "-o", str(exe)], check=True)
    return exe


def test_cpp_frames_match_python(drv):
    rng = random.Random(5)
    frames, lines = [], []
    for i in range(50):
        fr = {"id": rng.choice(["worker_01", "forklift_01", "w9"]), "short": rng.randrange(65536), "kind": rng.randrange(2),
              "mecOk": rng.randrange(2), "x": round(rng.uniform(-50, 50), 2), "y": round(rng.uniform(-50, 50), 2),
              "vx": round(rng.uniform(-3, 3), 2), "vy": round(rng.uniform(-3, 3), 2), "clear": rng.randrange(2),
              "vibrate": rng.randrange(2), "beacon": rng.randrange(2), "level": rng.randrange(3),
              "limit": round(rng.uniform(-1, 3), 2), "src": rng.choice(["forklift_01", "worker_02"]),
              "seq": rng.randrange(1 << 32), "type": rng.randrange(1, 4)}
        frames.append(fr)
        lines.append("S {id} {short} {kind} {mecOk} {x} {y} {vx} {vy} {clear} {vibrate} {beacon} {level} {limit} {src} {seq} {type}".format(**fr))
    out = subprocess.run([str(drv)], input="\n".join(lines), capture_output=True, text=True, check=True).stdout.split()
    for fr, hx in zip(frames, out):
        assert bytes.fromhex(hx) == d2d_auth.sign(KEY, fr)


def test_tamper_and_wrong_key_fail(drv):
    good = d2d_auth.sign(KEY, {"id": "worker_01", "x": 1.0, "seq": 7})
    bad = bytearray(good)
    bad[20] ^= 1                                          # flip one bit of x
    other = d2d_auth.sign(b"another-site", {"id": "worker_01", "x": 1.0, "seq": 7})
    out = subprocess.run([str(drv)], input=f"V {good.hex()}\nV {bytes(bad).hex()}\nV {other.hex()}",
                         capture_output=True, text=True, check=True).stdout.split()
    assert out == ["1", "0", "0"]
    assert d2d_auth.verify(KEY, good) and not d2d_auth.verify(KEY, bytes(bad))


def test_replay_guard(tmp_path):
    if shutil.which("g++") is None:
        pytest.skip("no C++ compiler")
    src = tmp_path / "r.cpp"
    src.write_text(r'''
#include <cstdio>
#include "d2d_auth.h"
int main() {
  d2d::ReplayGuard g;
  int r[6];
  r[0] = g.accept("worker_01", 1000, 1000);   // fresh
  r[1] = g.accept("worker_01", 1000, 1001);   // same seq again: replay
  r[2] = g.accept("worker_01", 999, 1001);    // older: replay
  r[3] = g.accept("worker_01", 1001, 1001);   // newer: ok
  r[4] = g.accept("worker_02", 900, 1001);    // 10 s old: stale
  r[5] = g.accept("worker_02", 1300, 0);      // receiver clock unsynced: monotonic only
  for (int i = 0; i < 6; i++) std::printf("%d", r[i]);
}
''')
    exe = tmp_path / "r"
    subprocess.run(["g++", "-std=c++17", "-Wall", "-I", os.path.join(ROOT, "firmware", "common"), str(src), "-o", str(exe)], check=True)
    assert subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout == "100101"
