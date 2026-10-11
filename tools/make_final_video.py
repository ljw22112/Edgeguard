"""Final hackathon video (about 2.5 min, 1920x1080, no audio track): title and result cards, the live demo,
firmware-in-the-loop, and the mobility map playing a real run.

    python tools/mobility_map.py                 # docs/img/mobility_map.html from results/mobility.json
    python tools/make_final_video.py             # results/edgeguard_final.mp4 (+ .srt, narration in docs/video-script.md)

Needs Playwright (Chromium) and ffmpeg.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H, FPS = 1920, 1080, 25

CSS = """
*{box-sizing:border-box;margin:0}body{width:1920px;height:1080px;background:#121C26;color:#F3F1EA;
font-family:'DejaVu Sans',Arial,sans-serif;padding:120px 140px;display:flex;flex-direction:column;gap:40px;overflow:hidden}
.k{font-size:30px;font-weight:700;color:#F2A900;letter-spacing:3px;text-transform:uppercase}
h1{font-size:120px;line-height:1.05}h2{font-size:68px;line-height:1.12;color:#FBFAF6}
p{font-size:38px;line-height:1.4;color:#B8C2CC}.row{display:flex;gap:36px}.c{flex:1;background:#1B2733;border-radius:22px;padding:40px 44px;display:flex;flex-direction:column;gap:14px}
.n{font-size:76px;font-weight:700;color:#F2A900;line-height:1}.l{font-size:30px;line-height:1.35;color:#B8C2CC}
table{border-collapse:collapse;font-size:34px}td{padding:20px 22px;border-bottom:2px solid #2B3946;vertical-align:top;color:#DCE3EA}
td.h{color:#FBFAF6;font-weight:700;white-space:nowrap}td.m{color:#F2A900;white-space:nowrap}
.foot{position:absolute;left:140px;bottom:70px;font-size:28px;color:#8D99A6}
.bands{position:absolute;right:0;top:0;height:1080px;display:flex}.bands div{width:110px;height:1080px}
"""

CARDS = {
    "title": """<div class="bands"><div style="background:#C62828"></div><div style="background:#B84A06"></div><div style="background:#2E7D32"></div></div>
<div style="margin-top:220px;display:flex;flex-direction:column;gap:36px;width:1300px">
<p class="k">2026 oneM2M International Hackathon</p><h1>EdgeGuard</h1>
<p style="font-size:44px;color:#DCE3EA">Stop forklift accidents before they happen,<br>with oneM2M and ETSI MEC</p></div>
<p class="foot">Team EdgeGuard · Sejong University</p>""",
    "problem": """<p class="k">The problem</p><h2>People and forklifts share the same aisles</h2>
<div class="row" style="margin-top:30px"><div class="c"><div class="n">2,559</div><div class="l">forklift accident casualties in Korea, 2021–2022 (KOSHA)</div></div>
<div class="c"><div class="n">85 %</div><div class="l">of alerts from a 5 m proximity alarm are false, so people stop listening (our simulation baseline)</div></div>
<div class="c"><div class="n">1 buzz</div><div class="l">says "danger" but not what to do, and server-based systems go silent when the network fails</div></div></div>""",
    "solution": """<p class="k">EdgeGuard</p><h2>Predict the collision 1–3 s ahead on the MEC edge, and tell each person what to do</h2>
<div class="row" style="margin-top:30px"><div class="c" style="border-top:10px solid #C62828"><div class="n" style="color:#FBFAF6">WAIT</div><div class="l">a forklift is coming: hold until it has passed</div></div>
<div class="c" style="border-top:10px solid #B84A06"><div class="n" style="color:#FBFAF6">STEP ASIDE</div><div class="l">you are in its lane: move to the edge</div></div>
<div class="c" style="border-top:10px solid #2E7D32"><div class="n" style="color:#FBFAF6">GO</div><div class="l">clear: go ahead. The forklift slows only as much as needed</div></div></div>""",
    "arch": """<p class="k">Architecture</p><h2 style="font-size:56px">oneM2M + ETSI MEC: one MN-CSE and MEC app per zone, IN-CSE in the cloud</h2>
<img src="file://{root}/docs/img/architecture_en.png" style="height:660px;width:auto;max-width:1640px;object-fit:contain;align-self:center;border-radius:14px;background:#fff">""",
    "label_demo": """<div style="margin-top:330px"><p class="k">Live demo</p><h2 style="font-size:84px">Devices → oneM2M CSE → MEC app → WAIT / STEP ASIDE / GO</h2></div>""",
    "label_fw": """<div style="margin-top:330px"><p class="k">Firmware in the loop</p><h2 style="font-size:84px">The ESP32 firmware, unmodified, against a real oneM2M CSE, with a phone as the worker tag</h2></div>""",
    "label_mob": """<div style="margin-top:330px"><p class="k">Mobility via ETSI MEC</p><h2 style="font-size:84px">The MEC network sees the forklift enter zone B, and its oneM2M twin follows</h2></div>""",
    "clause7": """<p class="k">ESTIMED · oneM2M TR-0077 clause 7 · measured in CI on every commit</p><h2 style="font-size:60px">Every clause 7 gap runs as an EdgeGuard feature</h2>
<table><tr><td class="h">7.1 Interworking</td><td>bidirectional MEC-IPE with SDT models; deploy by one intent across MEC hosts</td><td class="m">re-placed in ≈ 2.5 s</td></tr>
<tr><td class="h">7.2 Handover</td><td>twin, ACP and subscriptions follow the forklift; triggered by a MEC zone event</td><td class="m">1.5–11 ms, 0 lost</td></tr>
<tr><td class="h">7.3 Federated learning</td><td>TR-0084 roles as resources; canary, activation in the risk engine, rollback</td><td class="m">0.604 → 0.486 m</td></tr>
<tr><td class="h">7.4 Swarm</td><td>forklift plans in a group; every member computes the same schedule</td><td class="m">conflicts 4 → 0</td></tr></table>""",
    "onem2m": """<p class="k">Why oneM2M</p><h2 style="font-size:60px">The CSE does the work our own server would otherwise do</h2>
<div class="row"><div class="c"><div class="l" style="font-size:34px;color:#FBFAF6"><b>SDT twins + SAREF</b></div><div class="l">devices onboard by label discovery; semantic queries</div></div>
<div class="c"><div class="l" style="font-size:34px;color:#FBFAF6"><b>group + pollingChannel</b></div><div class="l">one request alerts every tag in a zone, even behind NAT</div></div>
<div class="c"><div class="l" style="font-size:34px;color:#FBFAF6"><b>ACP + TLS</b></div><div class="l">MQTT/TLS devices, HTTPS apps; 6 attacks refused in CI</div></div></div>
<div class="row"><div class="c"><div class="l" style="font-size:34px;color:#FBFAF6"><b>Announcement + Mcc</b></div><div class="l">zone MN-CSEs under one IN-CSE; home records</div></div>
<div class="c"><div class="l" style="font-size:34px;color:#FBFAF6"><b>AI agent over MCP</b></div><div class="l">shift safety reports from 4 MCP servers, state kept in oneM2M</div></div>
<div class="c"><div class="l" style="font-size:34px;color:#FBFAF6"><b>Vendor-neutral</b></div><div class="l">same code on ACME and KETI Mobius</div></div></div>""",
    "results": """<p class="k">Results (closed-loop simulation; baseline: our v1.0 vibration alert)</p><h2 style="font-size:60px">Fewer collisions, more throughput, still safe when the network fails</h2>
<div class="row" style="margin-top:20px"><div class="c"><div class="n">100 → 4</div><div class="l">collisions, 8 workers · 4 forklifts, 750 conflicts</div></div>
<div class="c"><div class="n">61.7 → 86.0 %</div><div class="l">forklift throughput, same site</div></div></div>
<div class="row"><div class="c"><div class="n">180 → 2</div><div class="l">collisions during a total network outage (D2D fallback)</div></div>
<div class="c"><div class="n">25 ms</div><div class="l">median alert latency on the edge (cloud only: 85 ms)</div></div></div>""",
    "closing": """<div class="bands"><div style="background:#C62828"></div><div style="background:#B84A06"></div><div style="background:#2E7D32"></div></div>
<div style="margin-top:250px;display:flex;flex-direction:column;gap:34px;width:1350px"><h1 style="font-size:96px">EdgeGuard</h1>
<p style="font-size:44px;color:#DCE3EA">Sense → coordinate → learn → deploy → improve,<br>on standard oneM2M resources at the MEC edge</p>
<p style="font-size:36px;color:#F2A900">github.com/ljw22112/Edgeguard</p></div>
<p class="foot">Team EdgeGuard · Sejong University · thank you</p>""",
}

# (kind, source, seconds or (start, end, speed), caption for the .srt)
TIMELINE = [
    ("card", "title", 4, "EdgeGuard: stop forklift accidents before they happen, with oneM2M and ETSI MEC."),
    ("card", "problem", 6, "People and forklifts share aisles; proximity alarms are mostly false and do not say what to do."),
    ("card", "solution", 6, "EdgeGuard predicts the collision 1 to 3 seconds ahead and tells each worker WAIT, STEP ASIDE or GO."),
    ("card", "arch", 7, "Each zone has a MEC host with an MN-CSE and the EdgeGuard MEC app; an IN-CSE in the cloud ties them together."),
    ("card", "label_demo", 2.5, "Live demo."),
    ("clip", "results/edgeguard_demo_v1.3.mp4", (8.0, 98.0, 1.5), "Crossing, a worker in the lane, and two forklifts: the tag says WAIT, STEP ASIDE, then GO."),
    ("card", "label_fw", 2.5, "Firmware in the loop."),
    ("clip", "results/edgeguard_firmware_in_the_loop.mp4", (2.0, 27.0, 1.5), "The ESP32 firmware runs unmodified against a real oneM2M CSE; a phone is the worker tag."),
    ("card", "label_mob", 2.5, "Mobility via ETSI MEC."),
    ("mobility", "docs/img/mobility_map.html", 17, "A MEC zone event moves the forklift's twin to zone B's MN-CSE: 1.5 to 8 ms interruption, no sample lost; RSRP of both cells cross at the boundary."),
    ("card", "clause7", 10, "All four TR-0077 clause 7 gaps run as EdgeGuard features, measured in CI on every commit."),
    ("card", "onem2m", 8, "oneM2M does the work: SDT twins, group fan-out, pollingChannel, access control with TLS, announcement, and an AI agent over MCP."),
    ("card", "results", 7, "In simulation: collisions 100 to 4, throughput 61.7 to 86 percent, and 180 to 2 collisions during a network outage."),
    ("card", "closing", 5, "EdgeGuard. Thank you."),
]


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def enc(extra_in, vf, out, dur=None):
    cmd = ["ffmpeg", "-y", *extra_in, "-vf", f"{vf},fps={FPS},format=yuv420p", "-an", "-c:v", "libx264", "-preset", "medium",
           "-crf", "20", "-r", str(FPS)]
    if dur:
        cmd += ["-t", f"{dur:.2f}"]
    run(cmd + [out])


def main():
    from playwright.sync_api import sync_playwright
    tmp = tempfile.mkdtemp(prefix="egvideo")
    parts, srt, t = [], [], 0.0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for i, (kind, src, spec, cap) in enumerate(TIMELINE):
            out = os.path.join(tmp, f"{i:02d}.mp4")
            if kind == "card":
                html = os.path.join(tmp, f"{src}.html")
                open(html, "w").write(f"<!doctype html><meta charset=utf-8><style>{CSS}</style><body>{CARDS[src].replace('{root}', ROOT)}</body>")
                png = html.replace(".html", ".png")
                pg = b.new_page(viewport={"width": W, "height": H})
                pg.goto("file://" + html)
                pg.wait_for_timeout(200)
                pg.screenshot(path=png)
                pg.close()
                fade = min(0.4, spec / 4)
                enc(["-loop", "1", "-i", png], f"fade=t=in:d={fade},fade=t=out:st={spec - fade}:d={fade}", out, spec)
                dur = spec
            elif kind == "clip":
                a, z, sp = spec
                dur = (z - a) / sp
                enc(["-ss", str(a), "-to", str(z), "-i", os.path.join(ROOT, src)],
                    f"setpts=PTS/{sp},scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x121C26", out, dur)
            else:                                             # record the mobility map playing
                ctx = b.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5,
                                    record_video_dir=tmp, record_video_size={"width": 1280, "height": 720}, color_scheme="light")
                pg = ctx.new_page()
                pg.goto(f"file://{os.path.join(ROOT, src)}?autoplay=1&step=55")
                pg.wait_for_timeout(int(spec * 1000))
                vid = pg.video.path()
                ctx.close()
                dur = spec - 0.5
                enc(["-ss", "0.5", "-i", vid], f"scale={W}:{H}:flags=lanczos", out, dur)
            parts.append(out)
            srt.append((t, t + dur, cap))
            t += dur
        b.close()
    lst = os.path.join(tmp, "list.txt")
    open(lst, "w").write("".join(f"file '{x}'\n" for x in parts))
    out = os.path.join(ROOT, "results", "edgeguard_final.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out])

    def ts(x):
        return f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d},{int(round((x % 1) * 1000)):03d}"
    with open(out.replace(".mp4", ".srt"), "w") as f:
        for k, (a, z, c) in enumerate(srt, 1):
            f.write(f"{k}\n{ts(a)} --> {ts(z)}\n{c}\n\n")
    print(f"wrote {out} ({t:.1f} s) and {out.replace('.mp4', '.srt')}")


if __name__ == "__main__":
    sys.exit(main())
