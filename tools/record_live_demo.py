"""Record the v1.3 demo video: reacting devices on a real CSE, captioned in English.

    EDGEGUARD_CONFIG=config/site.yaml EDGEGUARD_OVERRIDES=config/local-acme.yaml,config/live-demo.yaml \\
        python tools/record_live_demo.py --out results/edgeguard_demo_v1.3.mp4

Needs the CSE, the MEC app and the oneM2M resources (tools/setup_resources.py) - the devices'
alert subscriptions point at the device_sim port this script's devices listen on, so start
setup after the devices (scripts/run_live_demo.sh does all of it).  Playwright + ffmpeg.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTRO = [
    ("EdgeGuard - MEC-based worker-forklift collision prevention on oneM2M", 5),
    ("Every tag and forklift is its own oneM2M AE; the MEC app subscribes and writes alerts to its AE", 6),
]
SCENES = [
    ("crossing", "1/3  Worker crossing: the tag says WAIT, the forklift passes, then GO"),
    ("head_on", "2/3  Worker in the forklift's lane: STEP ASIDE, the forklift waits, then passes"),
    ("two_trucks", "3/3  Two forklifts: the worker gets GO only after both have passed"),
]
OUTRO = ("Simulation results: collisions -96 % (8 workers x 4 forklifts), forklift throughput 61.7 -> 86.0 %", 6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/edgeguard_demo_v1.3.mp4")
    ap.add_argument("--dashboard", default="http://localhost:9090/")
    ap.add_argument("--seconds", type=float, default=20.0)
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    tmp = tempfile.mkdtemp(prefix="eglive_")
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1600, "height": 900}, record_video_dir=tmp,
                            record_video_size={"width": 1600, "height": 900}, color_scheme="dark")
        page = ctx.new_page()
        page.goto(a.dashboard)
        time.sleep(1.5)
        page.evaluate("""() => { const d = document.createElement('div'); d.id = 'eg-caption';
            d.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:92vw;' +
              'background:rgba(0,0,0,.78);color:#fff;font:600 22px system-ui,sans-serif;text-align:center;' +
              'padding:12px 22px;border-radius:10px;z-index:99';
            document.body.appendChild(d); }""")
        caption = lambda t: page.evaluate("t => document.getElementById('eg-caption').textContent = t", t)  # noqa: E731
        for text, secs in INTRO:
            caption(text)
            time.sleep(secs)
        # one device process for all scenes (its alert listener must stay up), captions follow its marks
        marks = os.path.join(tmp, "marks.jsonl")
        proc = subprocess.Popen([sys.executable, "devices/live_devices.py", "--scene", "all",
                                 "--seconds", str(a.seconds), "--marks", marks],
                                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        texts, shown = dict(SCENES), None
        while proc.poll() is None:
            try:
                last = open(marks).read().strip().splitlines()[-1]
                name = json.loads(last)["scene"]
            except (OSError, IndexError, ValueError):
                name = None
            if name and name != shown:
                caption(texts[name])
                shown = name
            time.sleep(0.2)
        caption(OUTRO[0])
        time.sleep(OUTRO[1])
        ctx.close()
        b.close()
    webm = glob.glob(os.path.join(tmp, "*.webm"))[0]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", webm, "-vf", "pad=1920:1080:160:90:color=0x0f1318",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-movflags", "+faststart", a.out], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("saved", a.out)


if __name__ == "__main__":
    main()
