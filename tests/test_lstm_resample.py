"""edgeguard.learned.resample: 10 Hz grid by time, refuses short or gappy histories."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from edgeguard.learned import HIST, MAX_GAP_S, resample   # noqa: E402


def test_regular_samples_pass_through():
    h = [(0.1 * k, 0.1 * k, 0.0) for k in range(25)]
    r = resample(h)
    assert len(r) == HIST and abs(r[-1][0] - 2.4) < 1e-9 and abs(r[0][0] - 0.5) < 1e-9


def test_2hz_samples_are_interpolated_by_time():
    h = [(0.5 * k, 1.0 * 0.5 * k, 0.0) for k in range(6)]          # 1 m/s, reported at 2 Hz
    r = resample(h)
    steps = [b[0] - a[0] for a, b in zip(r, r[1:])]
    assert all(abs(s - 0.1) < 1e-9 for s in steps)                  # 0.1 m per 0.1 s = 1 m/s


def test_short_or_gappy_history_is_refused():
    assert resample([(0.1 * k, 0, 0) for k in range(10)]) is None    # only 0.9 s
    g = MAX_GAP_S + 0.2
    h = [(0.0, 0, 0), (0.1, 0, 0), (0.1 + g, 0, 0)] + [(0.1 + g + 0.1 * k, 0, 0) for k in range(1, 5)]
    assert resample(h) is None
