"""Software-in-the-loop test: the real ESP32 firmware, compiled for a PC, on a real oneM2M CSE.

    python tools/sil_run.py                      # local ACME (scripts/run_local_demo.sh starts it)
    python tools/sil_run.py --scene head_on

The worker tag and forklift module sketches (HIL_MODE 1) are built against tests/firmware/sil/sil_core.cpp
(Arduino API with real HTTP client / server, actuator pins logged as JSON).  They register their own oneM2M
AEs, receive the MEC app's alerts through subscriptions, drive their outputs and confirm in <device>/status -
the same code that runs on the boards.  Positions come from devices/live_devices.py.  Checks:
  registration   both AEs exist and were created by the firmware itself
  worker tag     vibration motor pulses and LED on while WAIT, then off after GO
  forklift       drive PWM reduced under the speed limit and restored, beacon blinking meanwhile
  confirmation   the MEC app received the firmware's status confirmations
Result: results/sil_run.json (timeline of every actuator change).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
AJ = os.environ.get("ARDUINOJSON_SRC", "/tmp/claude-0/arduinojson/src")
DEVICES = {"worker_tag": ("worker_01", 19001), "forklift_module": ("forklift_01", 19002)}
PINS = {"worker_01": {25: "vibration", 2: "led"}, "forklift_01": {27: "drive_pwm", 26: "beacon"}}


def mqtt_settings():
    """Broker password and site CA from scripts/certs.sh (the broker runs with scripts/mqtt.sh)."""
    env = dict(line.strip().split("=", 1) for line in open(os.path.join(ROOT, ".certs", "mqtt.env")) if "=" in line)
    return env["MQTT_DEV_PW"], open(os.path.join(ROOT, ".certs", "ca.crt")).read()


def build(out_dir, cse_url, transport="http"):
    os.makedirs(out_dir, exist_ok=True)
    extra, libs = [], []
    if transport == "mqtt":                          # oneM2M MQTT binding over TLS (firmware/common/m2m_mqtt.h)
        pw, ca = mqtt_settings()
        hdr = os.path.join(out_dir, "sil_mqtt.h")
        open(hdr, "w").write("#define MQTT_CA_PEM " + json.dumps(ca) + "\n")
        extra = ["-DM2M_MQTT=1", "-DSIL_MQTT", '-DSIL_MQTT_HOST="127.0.0.1"', f'-DSIL_MQTT_PASS="{pw}"', "-include", hdr]
        libs = ["-lmosquitto"]
    for sketch, (_, port) in DEVICES.items():
        d = os.path.join(ROOT, "firmware", sketch)
        subprocess.run(["g++", "-std=c++17", "-O1", "-w", "-DHIL_MODE=1", f"-DHTTP_PORT={port}",
                        f'-DSIL_CSE_URL="{cse_url}"', *extra, "-I", os.path.join(ROOT, "tests", "firmware", "stubs"),
                        "-I", AJ, "-I", d, "-x", "c++", "-include", "Arduino.h", os.path.join(d, f"{sketch}.ino"),
                        "-x", "none", *[x for x in extra if x.startswith("-D")],
                        os.path.join(ROOT, "tests", "firmware", "sil", "sil_core.cpp"),
                        "-o", os.path.join(out_dir, sketch), "-lpthread", *libs], check=True)


def record(a, live):
    """Dashboard (with the firmware's FW check marks) and the phone tag page, recorded side by side in one
    page (two iframes), so both views share one clock."""
    import glob
    import tempfile
    from playwright.sync_api import sync_playwright
    tmp = tempfile.mkdtemp(prefix="egsil_")
    html = os.path.join(tmp, "both.html")
    open(html, "w").write("""<!doctype html><html><body style="margin:0;background:#0f1318;display:flex;gap:16px;
        align-items:center;justify-content:center;height:100vh">
      <iframe id="d" src="http://localhost:9090/" style="width:1280px;height:900px;border:0"></iframe>
      <iframe id="p" src="http://localhost:9090/tag?worker=worker_01" allow="autoplay; vibrate"
              style="width:390px;height:900px;border:0;border-radius:18px"></iframe>
      <div style="position:fixed;left:50%;bottom:28px;transform:translateX(-50%);background:rgba(0,0,0,.78);
        color:#fff;font:600 19px system-ui,sans-serif;padding:10px 18px;border-radius:10px;text-align:center;max-width:1500px">
        Firmware in the loop: the ESP32 firmware runs unmodified on a PC, registers its oneM2M AE, obeys the alerts
        and confirms (FW check marks). Right: a phone as the worker tag.</div></body></html>""")
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1920, "height": 1080}, color_scheme="dark",
                            record_video_dir=tmp, record_video_size={"width": 1920, "height": 1080})
        pg = ctx.new_page()
        pg.goto("file://" + html)
        pg.frame_locator("#p").locator("#go").click()
        live.wait(timeout=a.seconds + 30)
        time.sleep(1.0)
        ctx.close()
        b.close()
    v = glob.glob(os.path.join(tmp, "*.webm"))[0]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", v, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "23", "-movflags", "+faststart", a.record], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("saved", a.record)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cse", default="http://127.0.0.1:8080/cse-in")
    ap.add_argument("--scene", default="crossing")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--out", default="results/sil_run.json")
    ap.add_argument("--build-dir", default="/tmp/edgeguard_sil")
    ap.add_argument("--record", help="also record the dashboard + a phone tag side by side to this .mp4")
    ap.add_argument("--transport", choices=("http", "mqtt"), default="http",
                    help="device -> CSE: HTTP, or the oneM2M MQTT binding over TLS (needs scripts/mqtt.sh and "
                         "ACME_MQTT=1 scripts/acme.sh start in)")
    a = ap.parse_args()
    if shutil.which("g++") is None or not os.path.isdir(AJ):
        sys.exit("::error title=sil_run::needs g++ and ArduinoJson (ARDUINOJSON_SRC)")
    build(a.build_dir, a.cse, a.transport)
    broker_log = os.path.join(ROOT, ".mqtt", "mosquitto.log")
    log_start = os.path.getsize(broker_log) if a.transport == "mqtt" and os.path.exists(broker_log) else 0
    env = dict(os.environ, EDGEGUARD_CONFIG="config/site.yaml",
               EDGEGUARD_OVERRIDES="config/local-acme.yaml,config/live-demo.yaml,config/sil.yaml")
    subprocess.run(["bash", "scripts/mec.sh", "restart"], cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)

    timeline, procs, t0 = [], [], time.time()

    def reader(dev, proc):
        for line in proc.stdout:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            what = PINS[dev].get(e["pin"])
            if what:
                timeline.append({"t": round(time.time() - t0, 2), "device": dev, "output": what, "value": e["value"]})

    for sketch, (dev, _) in DEVICES.items():
        p = subprocess.Popen([os.path.join(a.build_dir, sketch)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, cwd=ROOT)
        procs.append(p)
        threading.Thread(target=reader, args=(dev, p), daemon=True).start()
    live = subprocess.Popen([sys.executable, "devices/live_devices.py", "--scene", a.scene, "--seconds", str(a.seconds),
                             "--start-delay", "6"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.0)                                   # firmware registered its AEs, listeners are up
    subprocess.run([sys.executable, "tools/setup_resources.py", "--reset"], cwd=ROOT, env=env, check=True,
                   stdout=subprocess.DEVNULL)
    for p in procs:                                   # re-register after the reset, as a rebooted board would
        p.terminate()
    procs.clear()
    for sketch, (dev, _) in DEVICES.items():
        p = subprocess.Popen([os.path.join(a.build_dir, sketch)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, cwd=ROOT)
        procs.append(p)
        threading.Thread(target=reader, args=(dev, p), daemon=True).start()
    acks, seen = {}, []                                # confirmations as the MEC app saw them

    def poll_acks():
        while live.poll() is None:
            try:
                for dev, ack in json.load(urllib.request.urlopen("http://localhost:9090/state", timeout=3)).get("acks", {}).items():
                    if ack.get("hw") == "sil" and (dev, ack.get("state")) not in [(d, s_) for d, s_, _ in seen]:
                        seen.append((dev, ack.get("state"), round(time.time() - t0, 2)))
                    acks[dev] = ack
            except Exception:
                pass
            time.sleep(0.3)
    threading.Thread(target=poll_acks, daemon=True).start()
    if a.record:
        record(a, live)
    live.wait(timeout=a.seconds + 30)
    time.sleep(0.5)
    for p in procs:
        p.terminate()

    def series(dev, out):
        return [e for e in timeline if e["device"] == dev and e["output"] == out]
    vib, led = series("worker_01", "vibration"), series("worker_01", "led")
    pwm, beacon = series("forklift_01", "drive_pwm"), series("forklift_01", "beacon")
    led_on = [e["t"] for e in led if e["value"] == 1]
    led_off_after = [e["t"] for e in led if e["value"] == 0 and led_on and e["t"] > led_on[0]]
    wait_s = round(led_off_after[0] - led_on[0], 2) if led_on and led_off_after else None
    base = max((e["value"] for e in pwm), default=0)
    checks = {
        "worker tag: WAIT (LED on >= 2 s, vibration pulses)": bool(wait_s and wait_s >= 2.0
                                                              and sum(e["value"] == 1 for e in vib) >= 3),
        "worker tag: GO (LED off after the WAIT)": bool(led_off_after),
        "forklift: drive PWM reduced under the limit": any(0 <= e["value"] < base for e in pwm) if base else False,
        "forklift: drive PWM restored after the clear": bool(pwm) and pwm[-1]["value"] == base,
        "forklift: beacon blinking during the alert": sum(e["value"] == 1 for e in beacon) >= 2,
        "MEC app received the firmware's confirmations (WAIT and a speed limit)":
            any(d == "worker_01" and st in ("WAIT", "STEP ASIDE") for d, st, _ in seen)
            and any(d == "forklift_01" and st.startswith("limit") for d, st, _ in seen),
    }
    if a.transport == "mqtt":
        # the firmware's requests went over the broker: its TLS sessions as SWorker01 / SForklift01 in the broker
        # log, and every resource it created exists in the CSE (registration was over MQTT)
        log = open(broker_log).read()[log_start:] if os.path.exists(broker_log) else ""
        users = {u: log.count(f"u'{u}'") for u in ("SWorker01", "SForklift01")}
        checks["firmware connected to the broker over TLS as its own originator (both devices)"] = all(users.values())
        try:
            from edgeguard.onem2m import OneM2MClient
            c = OneM2MClient(a.cse.rsplit("/", 1)[0], a.cse.rsplit("/", 1)[1], "CAdmin")
            st = [c.request("GET", f"{dev}/status")["m2m:cnt"]["cni"] for dev in ("worker_01", "forklift_01")]
            checks["confirmations written over MQTT reached the CSE"] = all(n > 0 for n in st)
        except Exception:
            checks["confirmations written over MQTT reached the CSE"] = False
    out = {"scene": a.scene, "cse": a.cse, "transport": a.transport, "wait_s": wait_s, "drive_pwm_min": min((e["value"] for e in pwm), default=None),
           "drive_pwm_base": base, "checks": checks,
           "acks_seen_by_mec": [{"device": d, "state": s_, "t": t} for d, s_, t in seen], "timeline": timeline}
    json.dump(out, open(os.path.join(ROOT, a.out), "w"), indent=1)
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + " title=sil_run::" +
          json.dumps({"passed": sum(checks.values()), "total": len(checks), "wait_s": wait_s}))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"::error title=sil_run::step failed: {' '.join(map(str, e.cmd))[:300]} (exit {e.returncode})")
        raise
