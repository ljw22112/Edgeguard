import math

import pytest

from edgeguard.learned import available, LSTMPredictor, HIST
from edgeguard.tracking import Track

pytestmark = pytest.mark.skipif(not available(), reason="torch or model weights missing")


def test_lstm_follows_straight_walk():
    w, f = Track("w", "worker"), Track("f", "forklift")
    for i in range(HIST):
        t = i * 0.1
        w.update(t, 1.0 * t, 0.0)                      # walking +x at 1 m/s
        f.update(t, -10.0, 8.0, speed=0.0, heading=0.0, yaw_rate=0.0)
    x, y = LSTMPredictor(w, f).positions([2.0])[0]
    # roughly 2 m further along +x after 2 s
    assert x == pytest.approx(1.9 + 2.0, abs=0.6)
    assert abs(y) < 0.6
    assert math.isfinite(x) and math.isfinite(y)
