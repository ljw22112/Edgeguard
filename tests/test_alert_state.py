import importlib
import os
import sys


def _alert_state():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return importlib.import_module("mec_app.app").AlertState


def test_debounce_raise_refresh_clear():
    A = _alert_state()
    a = A(debounce=2, refresh_s=1.0, hold_s=1.0)
    assert a.step(2, 0.0) is None          # first WARNING frame: debounced
    assert a.step(2, 0.1) == "raise"
    assert a.step(2, 0.5) is None
    assert a.step(3, 0.6) == "raise"       # escalation fires at once
    assert a.step(2, 1.7) == "refresh"     # still dangerous, periodic refresh
    assert a.step(0, 1.8) is None          # hold before clearing
    assert a.step(0, 2.9) == "clear"


def test_danger_fires_immediately():
    a = _alert_state()()
    assert a.step(3, 0.0) == "raise"
