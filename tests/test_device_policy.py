from edgeguard.device_policy import CREEP_MPS, ForkliftLimit, ReportRate


def test_lost_clear_is_lifted_while_mec_alive():
    fl = ForkliftLimit()
    fl.on_alert(0.0, "raise", 1.2)
    assert fl.effective(1.0) == 1.2
    for t in range(1, 7):
        fl.on_heartbeat(float(t))
        if t <= 5:
            assert fl.effective(float(t)) == 1.2     # hold the plan between refreshes
    assert fl.effective(6.0) is None         # no refresh for 5 s, but MEC heard: the clear was lost


def test_silence_never_lifts_the_limit():
    fl = ForkliftLimit()
    fl.on_alert(0.0, "raise", 1.2)
    assert fl.effective(2.5) == 1.2          # MEC silent (restarting): hold the plan
    assert fl.effective(60.0) == 0.0         # MEC down: stop, never lift
    legacy = ForkliftLimit("legacy")
    legacy.on_alert(0.0, "raise", 1.2)
    assert legacy.effective(60.0) is None    # v0.6 behaviour: lifted after 5 s
    creep = ForkliftLimit("failsafe_creep")
    creep.on_alert(0.0, "raise", 1.2)
    assert creep.effective(1.5) == CREEP_MPS
    fl.on_alert(61.0, "refresh", 0.3)        # MEC back with a tighter limit
    assert fl.effective(61.5) == 0.3
    fl.on_alert(62.0, "clear", None)
    assert fl.effective(62.1) is None


def test_rate_command_falls_back_to_full_rate():
    r = ReportRate()
    assert r.current(0.0) == 10.0
    r.on_command(1.0, 2.0)
    assert r.current(5.0) == 2.0
    assert r.current(7.5) == 10.0
