"""Safety agent (agent/safety_agent.py): workflow logic against a fake MCP hub (no CSE needed)."""
import asyncio

from agent.safety_agent import SafetyAgent, hotspots


def ev(x, y, f="forklift_01", occ=False, alerted=True, speed=1.0, ct="20261011T080000"):
    return {"ct": ct, "content": {"x": x, "y": y, "forklift": f, "worker": "worker_01", "occluded": occ,
                                  "alerted": alerted, "forklift_speed": speed}}


class FakeHub:
    def __init__(self, near, serving=None, down=()):
        self.params = {"in": 1, "mn-b": 1, "mec": 1}
        self.near, self.serving, self.down, self.log, self.writes = near, serving, set(down), [], []

    async def call(self, server, tool, **a):
        self.log.append((server, tool, a))
        if server in self.down:
            return {"error": "server unavailable"}
        if tool == "latest":
            return {"content": {"cursor": "", "runs": 0}}
        if tool == "find_devices":
            return [{"d": "x#forklift_01", "path": "forklift_01/module", "role": "forklift"}] if server == "mn-b" else []
        if tool == "history":
            return self.near
        if tool == "all_ue_locations":
            return {"ues": [{"x": 12.2, "y": 4.1}, {"x": 40, "y": 40}]}
        if tool == "cell_load":
            return {"max_load_pct": 50}
        if tool == "serving_cse":
            return self.serving or {"error": "oneM2M 404"}
        if tool == "retrieve":
            return {"egs:spdLt": {"limit": 1.5, "maxSd": 2.5}}
        if tool == "write_content":
            self.writes.append(a["container"])
            return {"created": "cin_1"}
        return {}


def test_hotspot_classification():
    evs = [ev(12.3, 4.2, occ=True)["content"]] * 3 + [ev(-6.5, 0.2, speed=2.6)["content"]] * 2
    hs = hotspots(evs)
    assert (hs[0]["x"], hs[0]["y"], hs[0]["advice"], hs[0]["count"]) == (12, 4, "blind_corner", 3)
    assert hs[1]["advice"] == "speed"


def test_report_routes_to_serving_cse_and_persists():
    hub = FakeHub([ev(12.3, 4.2, occ=True)] * 4, serving={"zone": "B"})
    rep = asyncio.run(SafetyAgent(hub).shift_report())
    assert rep["status"] == "complete" and rep["forklifts"]["forklift_01"]["server"] == "mn-b"
    assert ("mn-b", "retrieve", {"path": "forklift_01/module/speedLimit"}) in hub.log
    assert rep["hotspots"][0]["people_now"] == 1 and rep["hotspots"][0]["radio_load_pct"] == 50
    assert hub.writes == ["EdgeGuardAgent/reports", "EdgeGuardAgent/state", "EdgeGuardAgent/runs"]


def test_partial_run_keeps_the_cursor():
    hub = FakeHub([ev(12.3, 4.2, occ=True)] * 2, serving={"zone": "B"}, down={"mn-b"})
    rep = asyncio.run(SafetyAgent(hub).shift_report())
    assert rep["status"] == "partial" and rep["forklifts"]["forklift_01"]["status"] == "unreachable"
    assert "EdgeGuardAgent/state" not in hub.writes and "EdgeGuardAgent/reports" in hub.writes
