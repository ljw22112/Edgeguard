"""Safety report from the alert history stored in the CSE.

Reads every alert contentInstance under <AE>/alert, groups the WARNING/DANGER
events, and writes a self-contained HTML report with a near-miss heatmap
(1 m cells over the site plan), the busiest worker/forklift pairs and the
daily timeline.

    python tools/safety_report.py --config config/site.yaml --out results/safety_report.html
"""
from __future__ import annotations

import argparse
import base64
import collections
import datetime as dt
import html
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard import config                      # noqa: E402
from edgeguard.onem2m import decode_con           # noqa: E402

INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"


def fetch_alerts(c, path):
    """Return alert payloads (oldest first) from a container."""
    res = c.request("GET", f"{path}?fu=1&ty=4")
    uris = res.get("m2m:uril", []) if res else []
    out = []
    for u in uris:
        rel = u.split("/", 1)[1] if u.startswith(c.cse_rn) or u.startswith("/" + c.cse_rn) else u
        rel = rel.lstrip("/")
        if rel.startswith(c.cse_rn + "/"):
            rel = rel[len(c.cse_rn) + 1:]
        try:
            cin = c.request("GET", rel)["m2m:cin"]
        except Exception:
            continue
        a = decode_con(cin.get("con"))
        if isinstance(a, dict) and "level" in a:
            out.append(a)
    out.sort(key=lambda a: a.get("mec_tx_ts", 0))
    return out


def heatmap_png(points_w, points_d, extent):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    x0, x1, y0, y1 = extent
    bins = [np.arange(x0, x1 + 1, 1.0), np.arange(y0, y1 + 1, 1.0)]
    allp = points_w + points_d
    H, xe, ye = np.histogram2d([p[0] for p in allp], [p[1] for p in allp], bins=bins)
    fig, ax = plt.subplots(figsize=(9, 9 * (y1 - y0) / (x1 - x0) + 0.6), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    masked = np.ma.masked_where(H.T == 0, H.T)
    im = ax.imshow(masked, origin="lower", extent=(x0, x1, y0, y1), cmap="Oranges",
                   vmin=0, interpolation="nearest")
    if points_d:
        ax.scatter([p[0] for p in points_d], [p[1] for p in points_d], s=22, c="#d03b3b",
                   edgecolors=SURFACE, linewidths=1, label="DANGER (slow-down sent)", zorder=3)
    ax.set_xticks(range(int(x0), int(x1) + 1, 5))
    ax.set_yticks(range(int(y0), int(y1) + 1, 5))
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.tick_params(colors=INK2, labelsize=8, length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xlabel("site x (m)", color=INK2, fontsize=9)
    ax.set_ylabel("site y (m)", color=INK2, fontsize=9)
    from matplotlib.ticker import MaxNLocator
    cb = fig.colorbar(im, ax=ax, shrink=0.7, pad=0.02, ticks=MaxNLocator(integer=True))
    cb.set_label("WARNING + DANGER events per 1 m cell", color=INK2, fontsize=8)
    cb.ax.tick_params(labelsize=8, colors=INK2)
    if points_d:
        ax.legend(loc="upper left", fontsize=8, frameon=False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--out", default="results/safety_report.html")
    a = ap.parse_args()
    cfg = config.load(a.config)
    c = config.client(cfg)
    p = config.paths(cfg)
    alerts = fetch_alerts(c, p["alert"])
    raises = [x for x in alerts if x.get("event") == "raise"]
    events = [x for x in raises if x.get("level") in ("WARNING", "DANGER")]

    def mid(x):
        pos = x.get("pos") or {}
        w, f = pos.get(x["worker"]), pos.get(x["forklift"])
        if not w or not f:
            return None
        return ((w[0] + f[0]) / 2, (w[1] + f[1]) / 2)
    pw = [m for x in events if x["level"] == "WARNING" and (m := mid(x))]
    pd = [m for x in events if x["level"] == "DANGER" and (m := mid(x))]
    pts = pw + pd
    if pts:
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        extent = (min(0, min(xs) - 3), max(xs) + 3, min(0, min(ys) - 3), max(ys) + 3)
        img = heatmap_png(pw, pd, extent)
    else:
        img = None

    by_level = collections.Counter(x["level"] for x in events)
    pairs = collections.Counter((x["worker"], x["forklift"]) for x in events)
    cells = collections.Counter((int(q[0] // 5) * 5, int(q[1] // 5) * 5) for q in pts)
    untagged = sum(1 for x in events if x["worker"].startswith("untagged_"))
    slow = [x["metrics"].get("speed_scale") for x in events if x["level"] == "DANGER"
            and x.get("metrics")]
    t_first = dt.datetime.fromtimestamp(alerts[0]["mec_tx_ts"] / 1000) if alerts else None
    t_last = dt.datetime.fromtimestamp(alerts[-1]["mec_tx_ts"] / 1000) if alerts else None

    rows = "".join(f"<tr><td>{html.escape(w)}</td><td>{html.escape(f)}</td><td class=n>{n}</td></tr>"
                   for (w, f), n in pairs.most_common(8))
    hot = "".join(f"<tr><td>x {x}–{x + 5} m, y {y}–{y + 5} m</td><td class=n>{n}</td></tr>"
                  for (x, y), n in cells.most_common(5))
    period = f"{t_first:%Y-%m-%d %H:%M} – {t_last:%H:%M}" if t_first else "no data"
    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>EdgeGuard 안전 리포트</title>
<style>
body{{font:15px/1.55 system-ui,"Noto Sans KR",sans-serif;color:{INK};background:{SURFACE};margin:0}}
main{{max-width:980px;margin:0 auto;padding:28px 18px 48px}}
h1{{font-size:26px;margin:0 0 4px}} h2{{font-size:17px;margin:28px 0 10px}}
.sub{{color:{INK2};margin:0 0 20px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}
.k{{border:1px solid {GRID};border-radius:10px;padding:12px 14px;background:#fff}}
.k b{{display:block;font:700 26px ui-monospace,Menlo,monospace}} .k span{{color:{INK2};font-size:13px}}
table{{border-collapse:collapse;width:100%;background:#fff}} td,th{{border-bottom:1px solid {GRID};padding:7px 10px;text-align:left}}
th{{font-size:12px;color:{INK2};text-transform:uppercase;letter-spacing:.6px}} .n{{text-align:right;font-family:ui-monospace,Menlo,monospace}}
img{{max-width:100%;border:1px solid {GRID};border-radius:10px}}
.two{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}
.note{{color:{INK2};font-size:13px}}
</style></head><body><main>
<h1>EdgeGuard 안전 리포트</h1>
<p class="sub">기간 {period} · 데이터: CSE <code>{html.escape(p['alert'])}</code> 의 경보 기록 {len(alerts)}건</p>
<div class="kpis">
<div class="k"><b>{len(events)}</b><span>아차사고 경보 (WARNING 이상)</span></div>
<div class="k"><b>{by_level.get('DANGER', 0)}</b><span>DANGER · 지게차 감속 명령</span></div>
<div class="k"><b>{by_level.get('WARNING', 0)}</b><span>WARNING · 작업자 진동</span></div>
<div class="k"><b>{untagged}</b><span>태그 없이 카메라로 감지</span></div>
<div class="k"><b>{(sum(slow) / len(slow)) if slow else 0:.2f}</b><span>DANGER 시 평균 속도 명령 (×)</span></div>
</div>
<h2>위험 구역 히트맵</h2>
{'<img alt="near-miss heatmap" src="data:image/png;base64,' + img + '">' if img else '<p class="note">경보가 없습니다.</p>'}
<p class="note">각 칸은 1 m × 1 m, 값은 경보 시점의 작업자–지게차 중간 위치입니다. 붉은 점은 감속 명령까지 나간 DANGER 경보입니다.</p>
<div class="two">
<div><h2>경보가 많은 구역 (5 m 단위)</h2><table><tr><th>구역</th><th class=n>경보</th></tr>{hot}</table></div>
<div><h2>경보가 많은 작업자–지게차 쌍</h2><table><tr><th>작업자</th><th>지게차</th><th class=n>경보</th></tr>{rows}</table></div>
</div>
<h2>개선 제안</h2>
<ul>
{''.join(f'<li>x {x}–{x + 5} m, y {y}–{y + 5} m 구역: 경보 {n}건. 교차로 반사경·바닥 표시, 지게차 서행 구간 지정을 검토하세요.</li>' for (x, y), n in cells.most_common(2)) or '<li>특이 구역이 없습니다.</li>'}
{f'<li>태그 없이 카메라로만 감지된 경보가 {untagged}건 있습니다. 태그 착용 점검이 필요합니다.</li>' if untagged else ''}
</ul>
<p class="note">EdgeGuard MEC app · tools/safety_report.py 로 생성</p>
</main></body></html>"""
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    open(a.out, "w").write(page)
    print(f"{len(alerts)} alerts, {len(events)} near-miss events -> {a.out}")


if __name__ == "__main__":
    main()
