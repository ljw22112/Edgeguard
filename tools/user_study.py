"""User validation of the worker cue (WAIT / STEP ASIDE / GO vs a single vibration).

    python tools/user_study.py --port 9300
    observer (laptop):      http://<laptop-ip>:9300/observer
    participant (phone):    http://<laptop-ip>:9300/tag

The simulations assume how people react to the tag (stop after ~0.8 s, keep waiting until GO,
step aside when told).  This kit measures it with real people in a corridor (docs/user-study.md):
each participant walks back and forth; the observer page fires cues at random moments and the
observer taps what the participant actually does.  Two conditions, counterbalanced:
  BUZZ   : one 0.6 s vibration + red flash (a conventional proximity tag); the hidden forklift passes
           HAZARD_S after the cue - resuming before that counts as "walked back into the lane"
  WAITGO : EdgeGuard cue - WAIT (red, pulse every second) until GO (green, two short pulses) at HAZARD_S;
           some trials start with STEP ASIDE
Results: results/user_study/<session>.json; summary: python tools/study_report.py
"""
from __future__ import annotations

import argparse
import json
import os
import random
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results", "user_study")
HAZARD_S = 4.0                 # the (imagined) forklift has passed this long after the cue
TRIALS = {"BUZZ": ["BUZZ"] * 5, "WAITGO": ["WAIT"] * 3 + ["ASIDE"] * 2}

app = FastAPI(title="EdgeGuard user study")
lock = threading.Lock()
S = {"session": None}          # current session


def now():
    return time.time()


def save():
    s = S["session"]
    if s:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, f"{s['id']}.json"), "w") as fh:
            json.dump(s, fh, indent=1, ensure_ascii=False)


@app.post("/api/start")
async def start(req: Request):
    """New participant: conditions in counterbalanced order, trials shuffled within a condition."""
    b = await req.json()
    pid = str(b.get("participant", "P01"))
    n = int("".join(ch for ch in pid if ch.isdigit()) or 0)
    order = ["BUZZ", "WAITGO"] if n % 2 else ["WAITGO", "BUZZ"]
    rng = random.Random(pid)
    plan = []
    for cond in order:
        trials = TRIALS[cond][:]
        rng.shuffle(trials)
        plan += [{"condition": cond, "cue": c} for c in trials]
    with lock:
        S["session"] = {"id": f"{pid}_{int(now())}", "participant": pid, "order": order, "plan": plan,
                        "trial": -1, "cue": {"state": "WALK", "t": now(), "seq": 0}, "events": [],
                        "quiz": None, "survey": None, "started": now()}
        save()
    return {"order": order, "trials": len(plan)}


@app.post("/api/next")
def next_trial():
    """Fire the next trial's cue now (the observer page calls this at a random moment)."""
    with lock:
        s = S["session"]
        if not s or s["trial"] + 1 >= len(s["plan"]):
            return {"done": True}
        s["trial"] += 1
        tr = s["plan"][s["trial"]]
        t = now()
        state = {"BUZZ": "BUZZ", "WAIT": "WAIT", "ASIDE": "ASIDE"}[tr["cue"]]
        s["cue"] = {"state": state, "t": t, "seq": s["cue"]["seq"] + 1, "trial": s["trial"]}
        s["events"].append({"t": t, "type": "cue", "trial": s["trial"], **tr})
        save()
    if tr["cue"] != "BUZZ":                       # EdgeGuard: GO once the forklift has passed
        threading.Timer(HAZARD_S, _go, args=(s["id"], s["trial"])).start()
    return {"trial": s["trial"], **tr, "hazard_s": HAZARD_S}


def _go(sid, trial):
    with lock:
        s = S["session"]
        if s and s["id"] == sid and s["trial"] == trial:
            t = now()
            s["cue"] = {"state": "GO", "t": t, "seq": s["cue"]["seq"] + 1, "trial": trial}
            s["events"].append({"t": t, "type": "go", "trial": trial})
            save()


@app.post("/api/observe")
async def observe(req: Request):
    """Observer taps what the participant does: stopped | walking | aside."""
    b = await req.json()
    with lock:
        s = S["session"]
        if s:
            s["events"].append({"t": now(), "type": "obs", "what": b.get("what"), "trial": s["trial"]})
            save()
    return {"ok": True}


@app.post("/api/quiz")
async def quiz(req: Request):
    b = await req.json()
    with lock:
        if S["session"]:
            S["session"]["quiz"] = b
            save()
    return {"ok": True}


@app.post("/api/survey")
async def survey(req: Request):
    b = await req.json()
    with lock:
        if S["session"]:
            S["session"]["survey"] = b
            save()
    return {"ok": True}


@app.get("/api/cue")
def cue():
    with lock:
        s = S["session"]
        return s["cue"] if s else {"state": "IDLE", "seq": 0}


@app.get("/api/state")
def state():
    with lock:
        s = S["session"]
        if not s:
            return JSONResponse({"session": None})
        return {"session": s["id"], "trial": s["trial"], "trials": len(s["plan"]), "cue": s["cue"],
                "plan": s["plan"], "events": s["events"][-8:]}


TAG = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EdgeGuard tag</title><style>
html,body{margin:0;height:100%;font-family:system-ui,sans-serif;background:#111;color:#fff}
#s{height:100%;display:flex;align-items:center;justify-content:center;flex-direction:column;font-weight:800;font-size:15vw;text-align:center}
#s small{font-size:5vw;font-weight:500;opacity:.8;margin-top:2vh}
button{font-size:6vw;padding:3vw 6vw;border-radius:3vw;border:0;margin:1vw}
.q{font-size:5vw;padding:5vw} .q label{display:block;margin:2vw 0}
</style></head><body><div id="s"><button id="go">시작 / Start</button><small>버튼을 누르면 진동이 켜집니다</small></div>
<script>
const s = document.getElementById('s'); let last = 0, pulse = null, ctx = null;
function beep(ms){ try{ ctx = ctx || new AudioContext(); const o = ctx.createOscillator(); o.connect(ctx.destination);
  o.frequency.value = 880; o.start(); setTimeout(()=>o.stop(), ms);}catch(e){} }
function buzz(p){ if(navigator.vibrate) navigator.vibrate(p); beep(Array.isArray(p)?p[0]:p); }
function show(bg, big, small){ s.style.background = bg; s.innerHTML = big + (small?`<small>${small}</small>`:''); }
function stopPulse(){ if(pulse){ clearInterval(pulse); pulse = null; } }
async function poll(){
  try{ const c = await (await fetch('/api/cue',{cache:'no-store'})).json();
    if(c.seq !== last){ last = c.seq; stopPulse();
      if(c.state==='BUZZ'){ buzz(600); show('#c62828','!',''); setTimeout(()=>show('#111','',''), 600); }
      else if(c.state==='WAIT'){ buzz(600); show('#c62828','WAIT','기다리세요'); pulse = setInterval(()=>buzz(150), 1000); }
      else if(c.state==='ASIDE'){ buzz(1500); show('#ef6c00','STEP<br>ASIDE','옆으로 비켜서 기다리세요'); pulse = setInterval(()=>buzz(150), 1000); }
      else if(c.state==='GO'){ buzz([80,80,80]); show('#2e7d32','GO','지나가세요'); setTimeout(()=>show('#111','',''), 1500); }
      else { show('#111','',''); }
    }}catch(e){}
  setTimeout(poll, 150);
}
document.getElementById('go').onclick = () => { buzz(50); show('#111','',''); poll(); };
</script></body></html>"""

OBSERVER = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EdgeGuard study - observer</title><style>
body{font-family:system-ui,sans-serif;max-width:860px;margin:20px auto;padding:0 16px;background:#f5f6f8;color:#16202b}
button{font-size:20px;padding:14px 22px;border-radius:10px;border:1px solid #c9d1da;margin:6px;background:#fff;cursor:pointer}
.big{font-size:26px;padding:22px 30px} .stop{background:#ffd9d6} .walk{background:#d9f2df} .aside{background:#ffe7c7}
#st{font:15px ui-monospace,monospace;white-space:pre;background:#fff;border:1px solid #d5dbe2;border-radius:8px;padding:10px}
input{font-size:18px;padding:8px;width:120px}
</style></head><body>
<h2>EdgeGuard 사용자 검증 — 관찰자 화면</h2>
<p>참가자 번호 <input id="pid" value="P01"> <button onclick="start()">세션 시작</button>
<button onclick="auto()">다음 시행 (2–6초 뒤 자동 신호)</button></p>
<p>참가자가 실제로 한 행동을 바로 누르세요:</p>
<p><button class="big stop" onclick="obs('stopped')">멈춤</button>
<button class="big walk" onclick="obs('walking')">다시 걸음</button>
<button class="big aside" onclick="obs('aside')">옆으로 비켜섬</button></p>
<div id="st">세션 없음</div>
<script>
async function post(u, b){ return (await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})})).json(); }
async function start(){ const r = await post('/api/start',{participant:document.getElementById('pid').value}); alert('순서: '+r.order.join(' → ')+' / 시행 '+r.trials); }
function auto(){ const d = 2000 + Math.random()*4000; document.getElementById('st').textContent += '\n신호 대기 '+(d/1000).toFixed(1)+' s...';
  setTimeout(async ()=>{ const r = await post('/api/next'); if(r.done) alert('모든 시행 완료 — 참가자에게 설문을 진행하세요 (/survey)'); }, d); }
async function obs(w){ await post('/api/observe',{what:w}); }
async function refresh(){ try{ const s = await (await fetch('/api/state',{cache:'no-store'})).json();
  if(s.session){ const tr = s.plan[s.trial] || {}; document.getElementById('st').textContent =
    `세션 ${s.session}\n시행 ${s.trial+1} / ${s.trials}  조건 ${tr.condition||'-'}  신호 ${tr.cue||'-'}\n현재 태그 상태: ${s.cue.state}\n` +
    s.events.map(e=>`${new Date(e.t*1000).toLocaleTimeString()}  ${e.type} ${e.cue||e.what||''}`).join('\n'); } }catch(e){}
  setTimeout(refresh, 400); }
refresh();
</script></body></html>"""

SURVEY = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EdgeGuard study - survey</title><style>body{font-family:system-ui,sans-serif;max-width:640px;margin:16px auto;padding:0 16px;font-size:18px}
fieldset{border:1px solid #ccd;border-radius:10px;margin:12px 0;padding:10px 14px} label{display:block;margin:6px 0}
button{font-size:20px;padding:12px 20px;border-radius:10px}</style></head><body>
<h2>사용 후 설문</h2>
<fieldset><legend>1. 빨간 화면 + 1초마다 짧은 진동은 무슨 뜻이었나요?</legend>
<label><input type="radio" name="q1" value="wait"> 지게차가 지나갈 때까지 기다린다</label>
<label><input type="radio" name="q1" value="stop2s"> 잠깐 멈췄다가 바로 간다</label>
<label><input type="radio" name="q1" value="run"> 빨리 지나간다</label></fieldset>
<fieldset><legend>2. 초록 화면 + 짧은 진동 두 번은?</legend>
<label><input type="radio" name="q2" value="go"> 이제 지나가도 된다</label>
<label><input type="radio" name="q2" value="danger"> 위험이 커졌다</label>
<label><input type="radio" name="q2" value="battery"> 배터리가 부족하다</label></fieldset>
<fieldset><legend>3. 주황 화면 + 긴 진동은?</legend>
<label><input type="radio" name="q3" value="aside"> 통로 가장자리로 비켜서서 기다린다</label>
<label><input type="radio" name="q3" value="back"> 왔던 길로 돌아간다</label>
<label><input type="radio" name="q3" value="go"> 계속 걷는다</label></fieldset>
<fieldset><legend>4~8. 동의하는 정도 (1 전혀 아니다 – 5 매우 그렇다)</legend>
<div id="lk"></div></fieldset>
<fieldset><legend>9. 자유 의견</legend><textarea id="free" rows="3" style="width:100%"></textarea></fieldset>
<button onclick="send()">제출</button>
<script>
const items = ["진동 한 번보다 WAIT/GO 신호가 언제 움직여야 할지 더 분명했다", "WAIT 신호가 너무 길거나 답답했다",
  "실제 작업 중에도 이 신호를 따를 것 같다", "STEP ASIDE 신호를 보고 어디로 가야 할지 알았다", "이 장치를 현장에서 쓰고 싶다"];
document.getElementById('lk').innerHTML = items.map((t,i)=>`<p>${i+4}. ${t}<br>` +
  [1,2,3,4,5].map(v=>`<label style="display:inline;margin-right:14px"><input type="radio" name="l${i}" value="${v}"> ${v}</label>`).join('') + '</p>').join('');
async function send(){ const v = n => (document.querySelector(`input[name=${n}]:checked`)||{}).value || null;
  await fetch('/api/quiz',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({q1:v('q1'),q2:v('q2'),q3:v('q3')})});
  await fetch('/api/survey',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({likert:items.map((t,i)=>({item:t,score:+v('l'+i)||null})),free:document.getElementById('free').value})});
  document.body.innerHTML = '<h2>감사합니다!</h2>'; }
</script></body></html>"""


@app.get("/tag")
def tag_page():
    return HTMLResponse(TAG)


@app.get("/observer")
def observer_page():
    return HTMLResponse(OBSERVER)


@app.get("/survey")
def survey_page():
    return HTMLResponse(SURVEY)


def main():
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9300)
    a = ap.parse_args()
    print(f"observer: http://<this-pc>:{a.port}/observer   participant phone: http://<this-pc>:{a.port}/tag")
    uvicorn.run(app, host="0.0.0.0", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
