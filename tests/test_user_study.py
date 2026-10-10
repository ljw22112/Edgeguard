"""User-study kit: trial scoring and the simulation input it produces."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.study_report import summarise, trials_of   # noqa: E402


def session():
    ev = [
        # WAIT trial: stops after 0.9 s, waits for GO (4 s), walks 0.6 s after GO
        {"t": 10.0, "type": "cue", "condition": "WAITGO", "cue": "WAIT", "trial": 0},
        {"t": 10.9, "type": "obs", "what": "stopped"}, {"t": 14.0, "type": "go", "trial": 0},
        {"t": 14.6, "type": "obs", "what": "walking"},
        # STEP ASIDE trial done right
        {"t": 20.0, "type": "cue", "condition": "WAITGO", "cue": "ASIDE", "trial": 1},
        {"t": 21.0, "type": "obs", "what": "aside"}, {"t": 24.0, "type": "go", "trial": 1},
        {"t": 24.5, "type": "obs", "what": "walking"},
        # BUZZ trial: stops, walks on after 2 s - before the truck has passed (4 s)
        {"t": 30.0, "type": "cue", "condition": "BUZZ", "cue": "BUZZ", "trial": 2},
        {"t": 30.8, "type": "obs", "what": "stopped"}, {"t": 32.8, "type": "obs", "what": "walking"},
    ]
    return {"participant": "P01", "events": ev, "quiz": {"q1": "wait", "q2": "go", "q3": "back"},
            "survey": {"likert": [{"item": "a", "score": 5}], "free": ""}}


def test_trial_scoring():
    t = trials_of(session())
    assert t[0]["stop_rt"] == 0.9 and not t[0]["premature"] and t[0]["go_rt"] == 0.6
    assert t[1]["aside_ok"] and not t[1]["premature"]
    assert t[2]["premature"]


def test_summary_and_sim_input():
    s = summarise([session()])
    assert s["by_condition"]["WAITGO"]["premature_rate"] == 0.0
    assert s["by_condition"]["BUZZ"]["premature_rate"] == 1.0
    assert s["sim_comply"] == 1.0 and abs(s["quiz_correct_rate"] - 2 / 3) < 1e-3
