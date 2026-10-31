"""Final hackathon video (about 3 min, 1920x1080): title and result cards, the live demo,
firmware-in-the-loop, the mobility map playing a real run, and a spoken narration.

    python tools/mobility_map.py                 # docs/img/mobility_map.html from results/mobility.json
    python tools/make_final_video.py             # results/edgeguard_final.mp4 (+ .srt)

Needs Playwright (Chromium) and ffmpeg. Narration: Piper TTS (`pip install piper-tts`) with a voice model in
$EG_VOICE (an .onnx file, e.g. en_US-lessac-high from rhasspy/piper-voices); without it the video is silent.
Each card lasts at least as long as its narration; a clip's narration must fit the clip.
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
<div class="c"><div class="n">48 %</div><div class="l">forklift throughput left by a wide UWB proximity alarm (6 m / 3 m)</div></div>
<div class="c"><div class="n">49</div><div class="l">collisions let through when the alarm is narrowed to 4 m / 2 m (3,617 conflicts, simulation)</div></div></div>""",
    "solution": """<p class="k">EdgeGuard</p><h2>Predict the collision 1–3 s ahead on the MEC edge, and tell each person what to do</h2>
<div class="row" style="margin-top:30px"><div class="c" style="border-top:10px solid #C62828"><div class="n" style="color:#FBFAF6">WAIT</div><div class="l">a forklift is coming: hold until it has passed</div></div>
<div class="c" style="border-top:10px solid #B84A06"><div class="n" style="color:#FBFAF6">STEP ASIDE</div><div class="l">you are in its lane: move to the edge</div></div>
<div class="c" style="border-top:10px solid #2E7D32"><div class="n" style="color:#FBFAF6">GO</div><div class="l">clear: go ahead. The forklift keeps its speed while it can still stop short of you</div></div></div>""",
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
    "layers": """<p class="k">When things fail</p><h2 style="font-size:60px">No server, still safe: four layers on the devices and the edge</h2>
<table><tr><td class="h">MEC app</td><td>collision course, WAIT / GO / STEP ASIDE, speed plans; standby takeover</td><td class="m">0.73 s</td></tr>
<tr><td class="h">Stop points</td><td>the truck brakes for its point from its own position, every cycle</td><td class="m">no radio delay</td></tr>
<tr><td class="h">Device-to-device</td><td>signed state broadcast; the tag checks GO itself when the MEC app is silent</td><td class="m">ESP-NOW</td></tr>
<tr><td class="h">Emergency brake</td><td>a person on a collision course within 1.5 s stops the truck, held while he is in front</td><td class="m">always on</td></tr></table>""",
    "site": """<p class="k">Results · same 1,000 fresh simulated episodes for every system</p><h2 style="font-size:60px">As safe as the wide proximity alarm, at 2.0× its throughput</h2>
<img src="file://{root}/docs/img/large_eval.png" style="width:1640px;height:auto;align-self:center;border-radius:14px;background:#fff">
<p style="font-size:34px">0 collisions in 3,617 conflicts · 97.3 % throughput vs 48.3 % · 81 % fewer alarms</p>""",
    "robust": """<p class="k">Results · 8,000 episodes on bad days</p><h2 style="font-size:60px">30 collisions to 0 under eight exceptional conditions</h2>
<img src="file://{root}/docs/img/large_eval_robust.png" style="width:1640px;height:auto;align-self:center;border-radius:14px;background:#fff">
<p style="font-size:34px">0 collisions in 34,644 conflicts · +4.8 to +9.9 points of throughput</p>""",
    "closing": """<div class="bands"><div style="background:#C62828"></div><div style="background:#B84A06"></div><div style="background:#2E7D32"></div></div>
<div style="margin-top:250px;display:flex;flex-direction:column;gap:34px;width:1350px"><h1 style="font-size:96px">EdgeGuard</h1>
<p style="font-size:44px;color:#DCE3EA">Safe and productive, not one or the other,<br>on standard oneM2M resources at the MEC edge</p>
<p style="font-size:36px;color:#F2A900">github.com/ljw22112/Edgeguard</p></div>
<p class="foot">Team EdgeGuard · Sejong University · thank you</p>""",
}

# (kind, source, seconds or (start, end, speed), narration = caption for the .srt)
TIMELINE = [
    ("card", "title", 4, "This is EdgeGuard. It stops forklift accidents before they happen, with oneM2M and ETSI MEC."),
    ("card", "problem", 6, "Workers and forklifts share the same aisles. In Korea there were over two thousand five hundred forklift casualties in two years. Proximity alarms make sites choose: set wide, trucks lose half their throughput; narrowed, collisions get through."),
    ("card", "solution", 6, "EdgeGuard predicts the collision course one to three seconds ahead, on the MEC edge. It tells each worker WAIT, STEP ASIDE, or GO, and the forklift keeps its speed as long as it can still stop short of the person."),
    ("card", "arch", 7, "Each warehouse zone has a MEC host, running a oneM2M MN-CSE and our MEC app. Tags and forklift modules register their own AEs. An IN-CSE in the cloud ties the zones together."),
    ("card", "label_demo", 2.5, "Here it is, live."),
    ("clip", "results/edgeguard_demo_v1.3.mp4", (8.0, 98.0, 1.5), "The worker crossing gets WAIT, until the forklift has passed, then GO. A worker standing in the lane is told to step aside. With two forklifts, GO comes only after both have passed. Every position, and every alert, is a oneM2M resource."),
    ("card", "label_fw", 2.5, "Firmware in the loop."),
    ("clip", "results/edgeguard_firmware_in_the_loop.mp4", (2.0, 27.0, 1.5), "The ESP32 firmware runs unmodified against a real oneM2M CSE, and a phone acts as the worker tag. CI checks this on every commit."),
    ("card", "label_mob", 2.5, "Mobility, through ETSI MEC."),
    ("mobility", "docs/img/mobility_map.html", 17, "The MEC platform sees the forklift enter zone B. Our MEC-IPE writes the event into oneM2M, and the forklift's twin moves to zone B's CSE, with a few milliseconds of interruption, and no sample lost."),
    ("card", "clause7", 10, "All four ESTIMED gaps run as features: MEC interworking and orchestration, handover, federated learning with model delivery and rollback, and forklift swarm coordination."),
    ("card", "onem2m", 8, "oneM2M does the work: SDT twins with SAREF, group fan-out, polling channels, access control with TLS, and an AI agent over MCP."),
    ("card", "layers", 8, "If the network or the MEC app fails, protection is layered: stop points the truck brakes for on its own, device-to-device state, a tag that checks GO by itself, and an always-on emergency brake."),
    ("card", "site", 8, "On one thousand fresh simulated episodes, EdgeGuard had zero collisions, like the wide proximity alarm, at twice its throughput, with eighty-one percent fewer alarms."),
    ("card", "robust", 8, "And on eight thousand episodes with a bad network, server restarts, low compliance and noisy positioning: zero collisions in thirty-four thousand conflicts, down from thirty."),
    ("card", "closing", 5, "EdgeGuard. Safe and productive. Thank you."),
]
VOICE = os.environ.get("EG_VOICE", "")


def speak(text, wav):
    """Narration for one segment with Piper; returns its length in seconds, or 0 without a voice."""
    if not VOICE or not os.path.exists(VOICE):
        return 0.0
    subprocess.run([sys.executable, "-m", "piper", "-m", VOICE, "-f", wav, "--sentence-silence", "0.25"],
                   input=text.encode(), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", wav],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


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
    parts, srt, voice, t = [], [], [], 0.0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for i, (kind, src, spec, cap) in enumerate(TIMELINE):
            out = os.path.join(tmp, f"{i:02d}.mp4")
            wav = os.path.join(tmp, f"{i:02d}.wav")
            said = speak(cap, wav)
            if kind == "card":
                spec = max(spec, said + 0.9) if said else spec
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
            if said > dur:
                print(f"warning: narration of segment {i} ({said:.1f} s) is longer than its picture ({dur:.1f} s)")
            parts.append(out)
            voice.append((wav, said, dur))
            srt.append((t, t + dur, cap))
            t += dur
        b.close()
    lst = os.path.join(tmp, "list.txt")
    open(lst, "w").write("".join(f"file '{x}'\n" for x in parts))
    out = os.path.join(ROOT, "results", "edgeguard_final.mp4")
    silent = os.path.join(tmp, "silent.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", silent])
    if any(said for _, said, _ in voice):
        pieces = []                                   # each segment's narration, 0.3 s in, padded to its length
        for k, (wav, said, dur) in enumerate(voice):
            seg = os.path.join(tmp, f"a{k:02d}.wav")
            if said:
                run(["ffmpeg", "-y", "-i", wav, "-af", f"adelay=300|300,apad,atrim=0:{dur:.3f}", "-ar", "22050", "-ac", "1", seg])
            else:
                run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", f"{dur:.3f}", seg])
            pieces.append(seg)
        alst = os.path.join(tmp, "alist.txt")
        open(alst, "w").write("".join(f"file '{x}'\n" for x in pieces))
        track = os.path.join(tmp, "voice.wav")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", alst, "-c", "copy", track])
        run(["ffmpeg", "-y", "-i", silent, "-i", track, "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest",
             "-movflags", "+faststart", out])
    else:
        run(["ffmpeg", "-y", "-i", silent, "-c", "copy", "-movflags", "+faststart", out])

    def ts(x):
        return f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d},{int(round((x % 1) * 1000)):03d}"
    with open(out.replace(".mp4", ".srt"), "w") as f:
        for k, (a, z, c) in enumerate(srt, 1):
            f.write(f"{k}\n{ts(a)} --> {ts(z)}\n{c}\n\n")
    print(f"wrote {out} ({t:.1f} s) and {out.replace('.mp4', '.srt')}")


if __name__ == "__main__":
    sys.exit(main())
