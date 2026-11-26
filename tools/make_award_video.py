"""Award-ceremony video (about 3 min, silent, captioned cards): played while the team speaks over it.

    python tools/mobility_map.py && python tools/make_award_video.py   # results/edgeguard_award.mp4

Same building blocks as tools/make_final_video.py, with a "why" and a "how we built it" card and no narration
(the team talks over it; script in docs/award-ceremony.md).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_final_video as v  # noqa: E402

v.CARDS["award_title"] = """<div class="bands"><div style="background:#C62828"></div><div style="background:#B84A06"></div><div style="background:#2E7D32"></div></div>
<div style="margin-top:220px;display:flex;flex-direction:column;gap:36px;width:1300px">
<p class="k">2026 oneM2M · ETSI MEC AIoT Hackathon</p><h1>EdgeGuard</h1>
<p style="font-size:44px;color:#DCE3EA">Worker–forklift collision prediction<br>on oneM2M and ETSI MEC</p></div>
<p class="foot">Jeongwon Lee · Kihwan Kim · Sejong University</p>"""
v.CARDS["why"] = """<p class="k">Why this topic</p><h2>Today a site has to choose: safe, or productive</h2>
<div class="row" style="margin-top:30px"><div class="c"><div class="n">2,559</div><div class="l">forklift accident casualties in Korea in two years (KOSHA, 2021–2022)</div></div>
<div class="c"><div class="n">2 s</div><div class="l">is all a walker has when a forklift appears from behind a rack</div></div>
<div class="c"><div class="n">48 % / 49</div><div class="l">a distance alarm: wide, trucks keep 48 % of their work; narrowed, 49 collisions get through</div></div></div>
<p style="margin-top:10px">The question we asked: not "how close?", but "will they meet?"</p>"""
v.CARDS["how"] = """<p class="k">How we built it</p><h2 style="font-size:60px">Trace every collision, fix the cause, test again on new episodes</h2>
<table><tr><td class="h">v1.0</td><td>a vibration alert on the worker's tag</td><td class="m">100 collisions · 62 %</td></tr>
<tr><td class="h">WAIT · GO · STEP ASIDE</td><td>tell each person what to do, not just "danger"</td><td class="m">4 collisions · 86 %</td></tr>
<tr><td class="h">Learned policy</td><td>forklift priority and stop points the truck brakes for by itself</td><td class="m">0 · 97 %</td></tr>
<tr><td class="h">Bad days</td><td>network loss, server restarts, people who ignore alerts or drift and hesitate</td><td class="m">30 → 1 · 0 moving</td></tr>
<tr><td class="h">Real stack</td><td>oneM2M CSEs, ETSI MEC APIs, the ESP32 firmware run against a real CSE in CI</td><td class="m">every commit</td></tr></table>"""
v.CARDS["award_close"] = """<div class="bands"><div style="background:#C62828"></div><div style="background:#B84A06"></div><div style="background:#2E7D32"></div></div>
<div style="margin-top:280px;display:flex;flex-direction:column;gap:34px;width:1350px"><h1 style="font-size:110px">Thank you</h1>
<p style="font-size:44px;color:#DCE3EA">Safe and productive, not one or the other,<br>on standard oneM2M and ETSI MEC</p>
<p style="font-size:36px;color:#F2A900">github.com/ljw22112/Edgeguard</p></div>
<p class="foot">Team EdgeGuard · Sejong University</p>"""

v.TIMELINE = [
    ("card", "award_title", 6, "EdgeGuard: worker–forklift collision prediction on oneM2M and ETSI MEC."),
    ("card", "why", 24, "Why: forklift accidents, and alarms that make sites choose between safety and productivity."),
    ("card", "solution", 9, "Predict the collision course on the MEC edge, and tell each person WAIT, STEP ASIDE or GO."),
    ("card", "how", 26, "How we built it: every collision traced, fixed and tested again."),
    ("card", "arch", 8, "A MEC host per zone, oneM2M CSEs, and the EdgeGuard MEC app."),
    ("card", "label_demo", 2.5, "Live demo."),
    ("clip", "results/edgeguard_demo_v1.3.mp4", (8.0, 98.0, 2.0), "WAIT until the forklift has passed, then GO; STEP ASIDE in the lane; two forklifts."),
    ("card", "label_fw", 2.5, "Firmware in the loop."),
    ("clip", "results/edgeguard_firmware_in_the_loop.mp4", (2.0, 27.0, 1.5), "The ESP32 firmware against a real oneM2M CSE, a phone as the worker tag."),
    ("card", "label_mob", 2.5, "Mobility through ETSI MEC."),
    ("mobility", "docs/img/mobility_map.html", 14, "A MEC zone event moves the forklift's twin to zone B's CSE."),
    ("card", "site", 7, "As safe as the wide alarm, at twice the throughput."),
    ("card", "robust", 7, "On bad days: 30 collisions to 1, and no moving truck touching anyone."),
    ("card", "award_close", 6, "Thank you."),
]
v.VOICE = ""
os.environ.setdefault("EG_VIDEO_OUT", os.path.join(v.ROOT, "results", "edgeguard_award.mp4"))

if __name__ == "__main__":
    sys.exit(v.main())
