"""Record a demo video of the live dashboard while scripted scenarios play.

    python tools/record_demo.py --config config/site.yaml --out results/edgeguard_demo.mp4

Needs: the CSE and MEC app running (with mec_services pointing at mec_mock if the
Location-API scene is included), Playwright with Chromium, and ffmpeg.
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENES = [
    ("Crossing paths: guidance geometry predicts the collision 2+ s ahead",
     ["--scenario", "crossing_conflict", "--seed", "5"]),
    ("Forklift turning into an aisle: CTRV prediction + slow-down command",
     ["--scenario", "turn_into_worker", "--seed", "3"]),
    ("Worker without a tag: camera detection still stops the forklift",
     ["--scenario", "crossing_conflict", "--seed", "8", "--untagged"]),
    ("UWB tag shadowed: ETSI MEC Location API keeps tracking the worker",
     ["--scenario", "crossing_conflict", "--seed", "6", "--uwb-dropout", "2.5,6.5",
      "--mec-mock", "http://localhost:8085"]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default="results/edgeguard_demo.mp4")
    ap.add_argument("--dashboard", default="http://localhost:9090/")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    tmp = tempfile.mkdtemp(prefix="egdemo_")
    marks = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1600, "height": 900},
                            record_video_dir=tmp, record_video_size={"width": 1600, "height": 900},
                            color_scheme="dark")
        page = ctx.new_page()
        t0 = time.time()
        page.goto(a.dashboard)
        time.sleep(2)
        page.evaluate("""() => { const d = document.createElement('div'); d.id = 'eg-caption';
            d.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);' +
              'background:rgba(0,0,0,.72);color:#fff;font:600 22px system-ui,sans-serif;' +
              'padding:12px 22px;border-radius:10px;z-index:99;white-space:nowrap';
            document.body.appendChild(d); }""")
        for i, (caption, args) in enumerate(SCENES):
            # the caption lives in the page, so it is always in sync with the recorded frames
            page.evaluate("t => document.getElementById('eg-caption').textContent = t",
                          f"{i + 1}/{len(SCENES)}  {caption}")
            start = time.time() - t0
            subprocess.run([sys.executable, "devices/device_sim.py", "--config", a.config, "--quiet"] + args,
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
            time.sleep(2.5)                       # tracks expire between scenes
            marks.append((start, time.time() - t0, caption))
        ctx.close()
        b.close()
    webm = glob.glob(os.path.join(tmp, "*.webm"))[0]
    filters = ["pad=1920:1080:160:90:color=0x0f1318"]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", webm, "-vf", ",".join(filters),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "22", "-movflags", "+faststart", a.out],
                   check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("saved", a.out, [(round(s, 1), round(e, 1)) for s, e, _ in marks])


if __name__ == "__main__":
    main()
