"""Type-check the ESP32 sketches on a PC (real ArduinoJson + small ESP32 API stubs).

Catches syntax and type errors before anyone flashes a board.  Needs g++ and the
ArduinoJson sources: set ARDUINOJSON_SRC to its `src` directory (CI clones it).
"""
import filecmp
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AJ = os.environ.get("ARDUINOJSON_SRC", "/tmp/claude-0/arduinojson/src")


def test_d2d_header_copies_in_sync():
    for sk in ("worker_tag", "forklift_module"):
        assert filecmp.cmp(os.path.join(ROOT, "firmware", "common", "d2d.h"),
                           os.path.join(ROOT, "firmware", sk, "d2d.h"), shallow=False)


@pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler")
def test_d2d_neighbours_and_inbox(tmp_path):
    """Relay bookkeeping: who is offline, for how long; inbox order and overflow."""
    src = tmp_path / "t.cpp"
    src.write_text(r'''
#include <cstdio>
#include "d2d.h"
int main() {
  d2d::Neighbours nb; d2d::Frame f; d2d::setId(f, "worker_01"); f.mecOk = 0;
  nb.seen(f, 10.0f);
  int a = nb.offline("worker_01", 10.5f), b = nb.offline("worker_01", 11.2f), c = nb.offline("worker_02", 10.5f);
  f.mecOk = 1; nb.seen(f, 10.6f);
  int d = nb.offline("worker_01", 10.7f);               // still within 1 s of the last mecOk = 0
  d2d::Inbox in; uint8_t raw[sizeof(d2d::Frame)];
  int pushed = 0;
  for (int i = 0; i < 12; i++) { d2d::Frame g; g.x = (float)i; memcpy(raw, &g, sizeof g); in.push(raw); pushed++; }
  d2d::Frame o; int n = 0; float first = -1;
  while (in.pop(o)) { if (n == 0) first = o.x; n++; }
  std::printf("%d %d %d %d %d %.0f %d\n", a, b, c, d, n, first, (int)sizeof(d2d::Frame));
}
''')
    exe = tmp_path / "t"
    subprocess.run(["g++", "-std=c++17", "-Wall", "-I", os.path.join(ROOT, "firmware", "common"), str(src), "-o", str(exe)],
                   check=True)
    a, b, c, d, n, first, size = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.split()
    assert (a, b, c, d) == ("1", "0", "0", "1")
    assert n == "7" and first == "0"                     # 8-slot ring keeps 7, drops the overflow
    assert int(size) <= 250


def test_uwb_header_copy_in_sync():
    assert filecmp.cmp(os.path.join(ROOT, "firmware", "common", "uwb_position.h"),
                       os.path.join(ROOT, "firmware", "worker_tag", "uwb_position.h"), shallow=False)


@pytest.mark.skipif(shutil.which("g++") is None or not os.path.isdir(AJ), reason="needs g++ and ArduinoJson")
@pytest.mark.parametrize("sketch", ["worker_tag", "forklift_module"])
def test_sketch_type_checks(sketch):
    d = os.path.join(ROOT, "firmware", sketch)
    r = subprocess.run(["g++", "-std=c++17", "-fsyntax-only", "-Wall", "-Wextra", "-Werror", "-x", "c++",
                        "-include", "Arduino.h", "-I", os.path.join(ROOT, "tests", "firmware", "stubs"),
                        "-I", AJ, "-I", d, os.path.join(d, f"{sketch}.ino")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-3000:]
