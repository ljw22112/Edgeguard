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
