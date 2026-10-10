"""Summarise the user study (tools/user_study.py) and turn it into simulation inputs.

    python tools/study_report.py [results/user_study] [--out results/user_study_summary.json]

Per trial, from the cue time and the observer's taps:
  stop reaction   first "stopped" after the cue
  premature walk  WAIT / STEP ASIDE: "walking" before GO;  BUZZ: "walking" before the forklift has
                  passed (HAZARD_S after the cue) - i.e. back into the lane while the truck is there
  GO response     first "walking" after GO (WAIT / STEP ASIDE)
  aside correct   STEP ASIDE trials with an "aside" tap
The WAIT compliance (1 - premature rate) is what sim/worker_cue_eval.py and sim/multi_sim.py assume
(Mover.COMPLY); the report prints the command to re-run the evaluation with the measured value.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.user_study import HAZARD_S        # noqa: E402

LIKERT_N = 5


def trials_of(session):
    ev = sorted(session["events"], key=lambda e: e["t"])
    cues = [e for e in ev if e["type"] == "cue"]
    out = []
    for i, c in enumerate(cues):
        t_end = cues[i + 1]["t"] if i + 1 < len(cues) else float("inf")
        win = [e for e in ev if c["t"] <= e["t"] < t_end]
        go = next((e["t"] for e in win if e["type"] == "go"), None)
        obs = [(e["t"], e["what"]) for e in win if e["type"] == "obs"]
        stop = next((t for t, w in obs if w in ("stopped", "aside")), None)
        safe_at = go if c["cue"] != "BUZZ" else c["t"] + HAZARD_S
        premature = stop is not None and safe_at is not None and any(
            w == "walking" and stop < t < safe_at for t, w in obs)
        go_rt = next((t - go for t, w in obs if w == "walking" and go is not None and t >= go), None)
        out.append({"condition": c["condition"], "cue": c["cue"],
                    "stop_rt": None if stop is None else round(stop - c["t"], 2),
                    "stopped": stop is not None, "premature": premature,
                    "go_rt": None if go_rt is None else round(go_rt, 2),
                    "aside_ok": any(w == "aside" for _, w in obs) if c["cue"] == "ASIDE" else None})
    return out


def summarise(sessions):
    rows = [dict(t, participant=s["participant"]) for s in sessions for t in trials_of(s)]
    res = {"participants": len(sessions), "trials": len(rows), "by_condition": {}}
    for cond in ("BUZZ", "WAITGO"):
        r = [x for x in rows if x["condition"] == cond]
        if not r:
            continue
        rts = [x["stop_rt"] for x in r if x["stop_rt"] is not None]
        gos = [x["go_rt"] for x in r if x["go_rt"] is not None]
        aside = [x["aside_ok"] for x in r if x["aside_ok"] is not None]
        res["by_condition"][cond] = {
            "trials": len(r), "stopped_rate": round(sum(x["stopped"] for x in r) / len(r), 3),
            "premature_rate": round(sum(x["premature"] for x in r) / len(r), 3),
            "stop_rt_median_s": round(statistics.median(rts), 2) if rts else None,
            "go_rt_median_s": round(statistics.median(gos), 2) if gos else None,
            "aside_correct_rate": round(sum(aside) / len(aside), 3) if aside else None}
    quiz = [s["quiz"] for s in sessions if s.get("quiz")]
    if quiz:
        key = {"q1": "wait", "q2": "go", "q3": "aside"}
        res["quiz_correct_rate"] = round(sum(q.get(k) == v for q in quiz for k, v in key.items()) / (3 * len(quiz)), 3)
    surveys = [s["survey"] for s in sessions if s.get("survey")]
    if surveys:
        items = [i["item"] for i in surveys[0]["likert"]]
        res["likert_mean"] = {it: round(statistics.mean([sv["likert"][k]["score"] for sv in surveys
                                                         if sv["likert"][k]["score"]] or [0]), 2)
                              for k, it in enumerate(items)}
    w = res["by_condition"].get("WAITGO")
    if w:
        res["sim_comply"] = round(1 - w["premature_rate"], 3)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default="results/user_study")
    ap.add_argument("--out", default="results/user_study_summary.json")
    a = ap.parse_args()
    sessions = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(a.dir, "*.json")))]
    if not sessions:
        sys.exit(f"no sessions in {a.dir}")
    res = summarise(sessions)
    json.dump(res, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(f"participants {res['participants']}, trials {res['trials']}")
    print(f"{'condition':8s} {'stopped':>8s} {'premature':>10s} {'stop RT':>8s} {'GO RT':>7s} {'aside ok':>9s}")
    for c, r in res["by_condition"].items():
        aside = "-" if r["aside_correct_rate"] is None else f"{r['aside_correct_rate']:.0%}"
        print(f"{c:8s} {r['stopped_rate']:8.0%} {r['premature_rate']:10.0%} {r['stop_rt_median_s'] or '-':>8} "
              f"{r['go_rt_median_s'] or '-':>7} {aside:>9}")
    if "quiz_correct_rate" in res:
        print(f"quiz correct {res['quiz_correct_rate']:.0%}")
    if "sim_comply" in res:
        print(f"\nmeasured WAIT compliance {res['sim_comply']:.2f} -> re-run the evaluation with it:")
        print(f"  python -m sim.failsafe_eval --modes coop --ux hold --comply {res['sim_comply']}")


if __name__ == "__main__":
    main()
