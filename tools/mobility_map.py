"""Mobility map: the forklift moving across the two zones, its serving CSE, the MEC zone events, the
signal strength of both cells and the handovers - from results/mobility.json (tools/mobility_demo.py).

    python tools/mobility_map.py            # docs/img/mobility_map.html (+ .png when Playwright is installed)

The HTML is self-contained (data embedded, no libraries): a time slider / play button over the run.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EdgeGuard mobility map</title>
<style>
:root{--bg:#F3F1EA;--card:#FBFAF6;--ink:#18212B;--mute:#5A6573;--a:#2F6FD0;--b:#C98A00;--fk:#E0504A;--wk:#2E9E4A;--line:#D9D5CA}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#121C26;--card:#1B2733;--ink:#F3F1EA;--mute:#9AA6B2;--line:#2B3946}}
:root[data-theme="dark"]{--bg:#121C26;--card:#1B2733;--ink:#F3F1EA;--mute:#9AA6B2;--line:#2B3946}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:20px 16px}
h1{font-size:22px;margin:0 0 4px}p.sub{margin:0 0 14px;color:var(--mute)}
.grid{display:grid;grid-template-columns:2fr 1fr;gap:14px}@media(max-width:820px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border-radius:12px;padding:14px}
svg{width:100%;height:auto;display:block}
.k{font-size:12px;color:var(--mute);text-transform:uppercase;letter-spacing:.06em}
.v{font-size:26px;font-weight:700}
.bar{height:14px;border-radius:7px;background:var(--line);overflow:hidden;margin:4px 0 10px}.bar>i{display:block;height:100%}
.ctl{display:flex;gap:10px;align-items:center;margin-top:10px}input[type=range]{flex:1}
button{border:0;border-radius:8px;padding:6px 12px;background:var(--a);color:#fff;font-weight:600;cursor:pointer}
ul{margin:6px 0 0;padding-left:18px}li{margin:2px 0}li.on{font-weight:700}
</style></head><body><main>
<h1>Forklift handover between zone MN-CSEs, triggered by the network</h1>
<p class="sub">ETSI MEC zone events and RNIS signal strength reach oneM2M through the MEC-IPE; the forklift's twin moves to the zone's MN-CSE when the network sees it attach to that zone's cell.</p>
<div class="grid">
 <div class="card"><svg id="map" viewBox="-4 -6 88 40"></svg>
  <div class="ctl"><button id="play">Play</button><input id="t" type="range" min="0" step="1" value="0"><span id="tt"></span></div></div>
 <div class="card">
  <div class="k">Serving CSE</div><div class="v" id="cse"></div>
  <div class="k" style="margin-top:8px">MEC zone (last event)</div><div class="v" id="zone" style="font-size:20px"></div>
  <div class="k" style="margin-top:10px">Signal strength (RSRP)</div>
  <div id="ra"></div><div class="bar"><i id="ba" style="background:var(--a)"></i></div>
  <div id="rb"></div><div class="bar"><i id="bb" style="background:var(--b)"></i></div>
  <div class="k">Handovers</div><ul id="hos"></ul>
 </div>
 <div class="card" style="grid-column:1/-1"><div class="k">RSRP of both cells over the run, handovers marked</div><svg id="chart" viewBox="0 0 1000 220"></svg></div>
</div></main>
<script>
const D = __DATA__;
const TL = D.timeline, svgNS = "http://www.w3.org/2000/svg";
const el = (n, a, p) => { const e = document.createElementNS(svgNS, n); for (const k in a) e.setAttribute(k, a[k]); (p||map).appendChild(e); return e; };
const map = document.getElementById("map"), Y = y => 30 - y;
const zc = {A: "var(--a)", B: "var(--b)"};
for (const [n, z] of Object.entries(D.zones)) {
  const [x0, y0, x1, y1] = z.rect;
  el("rect", {x: x0, y: Y(y1), width: x1 - x0, height: y1 - y0, fill: zc[n], "fill-opacity": .10, stroke: zc[n], "stroke-width": .3});
  el("text", {x: x0 + 1, y: Y(y1) - 1.2, "font-size": 2.2, fill: zc[n], "font-weight": 700}).textContent = `Zone ${n} · MN-CSE ${z.cse}`;
}
for (const [n, p] of Object.entries(D.poas)) {
  const c = p.cell === "cellA" ? "var(--a)" : "var(--b)";
  el("circle", {cx: p.xy[0], cy: Y(p.xy[1]), r: 1, fill: c});
  el("text", {x: p.xy[0] + 1.4, y: Y(p.xy[1]) + .7, "font-size": 1.8, fill: c}).textContent = `${n} (${p.cell})`;
}
for (const [n, xy] of Object.entries(D.workers)) {
  el("circle", {cx: xy[0], cy: Y(xy[1]), r: .8, fill: "var(--wk)"});
  el("text", {x: xy[0] + 1.1, y: Y(xy[1]) + .6, "font-size": 1.6, fill: "var(--wk)"}).textContent = n;
}
el("polyline", {points: TL.map(r => `${r.x},${Y(r.y)}`).join(" "), fill: "none", stroke: "var(--fk)", "stroke-width": .25, "stroke-dasharray": ".8 .6", opacity: .6});
for (const h of D.handovers) {
  const r = TL.reduce((a, b) => Math.abs(b.t - h.t) < Math.abs(a.t - h.t) ? b : a);
  const up = h.to !== "A";
  el("path", {d: up ? `M${r.x},${Y(r.y) - 1.4} l-1,-1.6 h2 z` : `M${r.x},${Y(r.y) + 1.4} l-1,1.6 h2 z`, fill: "var(--fk)"});
  el("text", {x: r.x - 4, y: up ? Y(r.y) - 3.6 : Y(r.y) + 5, "font-size": 1.6, fill: "var(--ink)"}).textContent = `${h.from}→${h.to} ${h.interruption_ms} ms`;
}
const fk = el("g", {});
el("rect", {x: -1.6, y: -1, width: 3.2, height: 2, rx: .4, fill: "var(--fk)"}, fk);
const fkl = el("text", {x: -1.8, y: -1.6, "font-size": 1.7, fill: "var(--fk)", "font-weight": 700}, fk); fkl.textContent = "forklift_01";
const link = el("line", {stroke: "var(--fk)", "stroke-width": .2, "stroke-dasharray": ".5 .4"});
const hosEl = document.getElementById("hos");
D.handovers.forEach((h, i) => { const li = document.createElement("li"); li.id = "h" + i;
  li.textContent = `t=${h.t}s ${h.from}→${h.to} (${h.reason}): prep ${h.prep_ms} ms, gap ${h.interruption_ms} ms, lost ${h.samples_lost}`; hosEl.appendChild(li); });
const pct = d => d == null ? 0 : Math.max(0, Math.min(100, (d + 120) / 60 * 100));
const slider = document.getElementById("t"); slider.max = TL.length - 1;
function show(i) {
  const r = TL[i]; fk.setAttribute("transform", `translate(${r.x},${Y(r.y)})`);
  const poa = Object.values(D.poas).find(p => p.cell === r.cell);
  if (poa) { link.setAttribute("x1", r.x); link.setAttribute("y1", Y(r.y)); link.setAttribute("x2", poa.xy[0]); link.setAttribute("y2", Y(poa.xy[1])); }
  document.getElementById("cse").textContent = r.serving_cse ? `Zone ${r.serving_cse}${r.pending ? " (preparing…)" : ""}` : "–";
  document.getElementById("cse").style.color = zc[r.serving_cse] || "";
  document.getElementById("zone").textContent = r.mec_zone || "–";
  const a = r.cell === "cellA" ? r.rsrp_dbm : r.nb_rsrp_dbm, b = r.cell === "cellB" ? r.rsrp_dbm : r.nb_rsrp_dbm;
  document.getElementById("ra").textContent = `cellA ${a ?? "–"} dBm${r.cell === "cellA" ? " · serving" : ""}`;
  document.getElementById("rb").textContent = `cellB ${b ?? "–"} dBm${r.cell === "cellB" ? " · serving" : ""}`;
  document.getElementById("ba").style.width = pct(a) + "%"; document.getElementById("bb").style.width = pct(b) + "%";
  document.getElementById("tt").textContent = `t = ${r.t.toFixed(1)} s`;
  D.handovers.forEach((h, k) => document.getElementById("h" + k).className = r.t >= h.t ? "on" : "");
  cursor.setAttribute("x1", cx(r.t)); cursor.setAttribute("x2", cx(r.t));
}
// chart
const ch = document.getElementById("chart"), T = TL[TL.length - 1].t;
const cx = t => 50 + t / T * 930, cy = d => 200 - (d + 120) / 60 * 190;
for (let d = -120; d <= -60; d += 20) { el("line", {x1: 50, x2: 980, y1: cy(d), y2: cy(d), stroke: "var(--line)"}, ch);
  el("text", {x: 4, y: cy(d) + 4, "font-size": 12, fill: "var(--mute)"}, ch).textContent = d + " dBm"; }
for (const [cell, col] of [["cellA", "var(--a)"], ["cellB", "var(--b)"]]) {
  const pts = TL.map(r => [r.t, r.cell === cell ? r.rsrp_dbm : r.nb_rsrp_dbm]).filter(p => p[1] != null);
  el("polyline", {points: pts.map(p => `${cx(p[0])},${cy(p[1])}`).join(" "), fill: "none", stroke: col, "stroke-width": 2.5}, ch);
  const l = pts[Math.floor(pts.length * 0.12)]; if (l) el("text", {x: cx(l[0]), y: cy(l[1]) - 8, "font-size": 13, fill: col, "font-weight": 700}, ch).textContent = cell;
}
for (const h of D.handovers) { el("line", {x1: cx(h.t), x2: cx(h.t), y1: 5, y2: 200, stroke: "var(--fk)", "stroke-dasharray": "4 3"}, ch);
  el("text", {x: cx(h.t) + 4, y: 16, "font-size": 12, fill: "var(--fk)"}, ch).textContent = `handover ${h.from}→${h.to}`; }
const cursor = el("line", {y1: 5, y2: 200, stroke: "var(--ink)", "stroke-width": 1, opacity: .5}, ch);
slider.oninput = () => show(+slider.value);
let timer = null;
document.getElementById("play").onclick = e => {
  if (timer) { clearInterval(timer); timer = null; e.target.textContent = "Play"; return; }
  e.target.textContent = "Pause";
  timer = setInterval(() => { slider.value = (+slider.value + 1) % TL.length; show(+slider.value); }, 100);
};
const start = new URLSearchParams(location.search).get("t");
const i0 = start ? TL.findIndex(r => r.t >= +start) : 0; slider.value = Math.max(0, i0); show(+slider.value);
const q = new URLSearchParams(location.search);
if (q.get("autoplay")) {                 // ?autoplay=1&step=50 : play once (video recording)
  const step = +(q.get("step") || 100);
  document.getElementById("play").textContent = "Pause";
  timer = setInterval(() => { if (+slider.value >= TL.length - 1) { clearInterval(timer); return; }
    slider.value = +slider.value + 1; show(+slider.value); }, step);
}
</script></body></html>
"""


def main():
    data = json.load(open(os.path.join(ROOT, "results", "mobility.json")))
    keep = {k: data[k] for k in ("zones", "poas", "workers", "handovers", "timeline")}
    out = os.path.join(ROOT, "docs", "img", "mobility_map.html")
    open(out, "w").write(PAGE.replace("__DATA__", json.dumps(keep, separators=(",", ":"))))
    print("wrote", out)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return
    t = data["handovers"][0]["t"] + 1.0 if data["handovers"] else 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1240, "height": 820}, device_scale_factor=2, color_scheme="light")
        pg.goto(f"file://{out}?t={t}")
        pg.wait_for_timeout(300)
        pg.screenshot(path=out.replace(".html", ".png"), full_page=True)
        b.close()
    print("wrote", out.replace(".html", ".png"))


if __name__ == "__main__":
    sys.exit(main())
