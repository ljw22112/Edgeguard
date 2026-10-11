"""EdgeGuard safety agent: orchestrates several MCP servers (oneM2M IN-CSE, zone MN-CSEs, ETSI MEC).

    python -m agent.safety_agent report                # the shift safety report workflow
    python -m agent.safety_agent ask "Why did forklift_01 slow down?"   # free question, needs ANTHROPIC_API_KEY

Shift report workflow (structured agent, every step a tool call through MCP):
  1  state         its own last run from oneM2M (<IN>/EdgeGuardAgent/state): only new near misses are read
  2  inventory     devices from their SAREF descriptions, on every oneM2M server (semantic query)
  3  near misses   new records from <IN>/EdgeGuard/nearmiss
  4  hotspots      1 m grid cells, classified (blind corner / unalerted / speed / crossing)
  5  context       per hotspot: people around now (MEC Location), radio load (MEC RNIS); per forklift involved:
                   its serving CSE (home record) -> the MN-CSE MCP server of that zone -> live speed limit
  6  validate      totals add up, the snapshot did not change meanwhile (re-count), every forklift resolved
  7  persist       report -> <IN>/EdgeGuardAgent/reports, cursor -> state, step log -> runs
Errors (a CSE or the MEC platform unreachable, a tool error) are recorded and the run continues with what
it has; the report is then marked partial and the cursor stays, so the next run covers those records again.  Writes go only below the agent's own AE (MCP server guardrail).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.nearmiss import ADVICE                 # noqa: E402

AGENT_AE = "EdgeGuardAgent"


def default_servers(origin="SEdgeGuardAgent", mec_url="http://127.0.0.1:8085"):
    py = sys.executable
    one = lambda n, url, rn: StdioServerParameters(command=py, cwd=ROOT, args=[      # noqa: E731
        "-m", "agent.onem2m_mcp", "--name", n, "--base-url", url, "--cse-rn", rn, "--origin", origin])
    return {"in": one("in", "http://127.0.0.1:8080", "cse-in"),
            "mn-a": one("mn-a", "http://127.0.0.1:8081", "cse-mn-a"),
            "mn-b": one("mn-b", "http://127.0.0.1:8082", "cse-mn-b"),
            "mec": StdioServerParameters(command=py, cwd=ROOT, args=["-m", "agent.mec_mcp", "--mec-url", mec_url])}


class MCPHub:
    """Several MCP servers behind one call(server, tool, **args), with the tool catalogue and a call log."""

    def __init__(self, servers: dict):
        self.params, self.sessions, self.tools, self.log = servers, {}, {}, []
        self.stack = AsyncExitStack()

    async def __aenter__(self):
        for name, p in self.params.items():
            try:
                read, write = await self.stack.enter_async_context(stdio_client(p))
                s = await self.stack.enter_async_context(ClientSession(read, write))
                await s.initialize()
                self.sessions[name] = s
                self.tools[name] = [t for t in (await s.list_tools()).tools]
            except Exception as e:
                self.log.append({"server": name, "tool": "connect", "error": f"{type(e).__name__}: {str(e)[:200]}"})
        return self

    async def __aexit__(self, *exc):
        await self.stack.aclose()

    async def call(self, server, tool, **args):
        t0 = time.time()
        if server not in self.sessions:
            out = {"error": "server unavailable", "detail": server}
        else:
            try:
                r = await asyncio.wait_for(self.sessions[server].call_tool(tool, args), timeout=15)
                out = self._result(r)
            except Exception as e:
                out = {"error": type(e).__name__, "detail": str(e)[:200]}
        self.log.append({"server": server, "tool": tool, "args": args, "ms": round((time.time() - t0) * 1000, 1),
                         "error": out.get("error") if isinstance(out, dict) else None})
        return out

    @staticmethod
    def _result(r):
        if getattr(r, "isError", False):
            return {"error": "tool error", "detail": " ".join(getattr(c, "text", "") for c in r.content)[:300]}
        if getattr(r, "structuredContent", None):
            sc = r.structuredContent
            return sc["result"] if set(sc) == {"result"} else sc
        texts = [c.text for c in r.content if getattr(c, "type", "") == "text"]
        if len(texts) == 1:
            try:
                return json.loads(texts[0])
            except ValueError:
                return {"text": texts[0]}
        return [json.loads(t) for t in texts] if texts else {}


def err(x):
    return isinstance(x, dict) and "error" in x


def hotspots(events, cell=1.0, n=5):
    cells = {}
    for e in events:
        k = (math.floor(e["x"] / cell) * cell, math.floor(e["y"] / cell) * cell)
        c = cells.setdefault(k, {"count": 0, "occluded": 0, "unalerted": 0, "speed": 0.0, "forklifts": set()})
        c["count"] += 1
        c["occluded"] += bool(e.get("occluded"))
        c["unalerted"] += not e.get("alerted", True)
        c["speed"] += float(e.get("forklift_speed") or 0.0)
        c["forklifts"].add(e.get("forklift"))
    out = []
    for (x, y), c in sorted(cells.items(), key=lambda kv: -kv[1]["count"])[:n]:
        n_ = c["count"]
        why = ("blind_corner" if c["occluded"] / n_ >= 0.5 else "unalerted" if c["unalerted"] / n_ >= 0.3
               else "speed" if c["speed"] / n_ > 2.0 else "crossing")
        out.append({"x": x, "y": y, "count": n_, "advice": why, "text": ADVICE[why],
                    "forklifts": sorted(f for f in c["forklifts"] if f)})
    return out


class SafetyAgent:
    def __init__(self, hub: MCPHub, near_container="EdgeGuard/nearmiss", people_radius=6.0):
        self.hub, self.near, self.radius = hub, near_container, people_radius
        self.steps = []

    def step(self, name, **info):
        self.steps.append({"step": name, "t": round(time.time(), 3), **info})

    async def route(self, device):
        """The MCP server of the CSE that serves `device` now (home record on the IN-CSE), else the IN-CSE."""
        rec = await self.hub.call("in", "serving_cse", device=device)
        if err(rec) or not isinstance(rec, dict) or not rec.get("zone"):
            return "in", None
        server = f"mn-{rec['zone'].lower()}"
        return (server if server in self.hub.params else "in"), rec

    async def shift_report(self):
        t0, errors = time.time(), []
        self.steps = []
        # 1 state
        st = await self.hub.call("in", "latest", container=f"{AGENT_AE}/state")
        state = st.get("content") if isinstance(st, dict) and isinstance(st.get("content"), dict) else {}
        cursor, runs = state.get("cursor", ""), state.get("runs", 0)      # creation time of the last record read
        self.step("state", cursor=cursor, runs=runs)
        # 2 inventory (every oneM2M server)
        inventory = {}
        for srv in [s for s in self.hub.params if s != "mec"]:
            devs = await self.hub.call(srv, "find_devices")
            if err(devs):
                errors.append({"step": "inventory", "server": srv, **devs})
                continue
            for d in devs:
                inventory[d["d"].rsplit("#", 1)[-1]] = {"role": d.get("role"), "server": srv, "path": d.get("path")}
        self.step("inventory", devices=len(inventory))
        # 3 near misses (only the new ones)
        hist = await self.hub.call("in", "history", container=self.near, n=2000)
        if err(hist):
            errors.append({"step": "near misses", **hist})
            hist = []
        events = [h["content"] for h in hist if isinstance(h.get("content"), dict)]
        new = [h["content"] for h in hist if isinstance(h.get("content"), dict) and (h.get("ct") or "") > cursor]
        last_ct = max([h.get("ct") or "" for h in hist] + [cursor])
        self.step("near misses", total=len(events), new=len(new))
        # 4 hotspots
        hs = hotspots(new)
        self.step("hotspots", n=len(hs))
        # 5 context
        ues = await self.hub.call("mec", "all_ue_locations")
        if err(ues):
            errors.append({"step": "context", "server": "mec", **ues})
            ues = None
        else:
            ues = ues.get("ues", [])
        load = await self.hub.call("mec", "cell_load")
        if err(load):
            errors.append({"step": "context", "server": "mec", **load})
            load = None
        forklifts = {}
        for h in hs:
            if ues is not None:
                h["people_now"] = sum(1 for u in ues if u.get("x") is not None and
                                      math.hypot(u["x"] - h["x"], u["y"] - h["y"]) <= self.radius)
            if load is not None:
                h["radio_load_pct"] = load.get("max_load_pct")
            for f in h["forklifts"]:
                if f in forklifts:
                    continue
                server, rec = await self.route(f)
                twin = (inventory.get(f) or {}).get("path") or f"{f}/module"
                lim = await self.hub.call(server, "retrieve", path=f"{twin}/speedLimit")
                if err(lim):
                    errors.append({"step": "context", "device": f, "server": server, **lim})
                    forklifts[f] = {"server": server, "zone": (rec or {}).get("zone"), "speed_limit": None,
                                    "status": "unreachable"}
                else:
                    sl = lim.get("egs:spdLt", {})
                    forklifts[f] = {"server": server, "zone": (rec or {}).get("zone"), "status": "ok",
                                    "speed_limit": sl.get("limit"), "max_speed": sl.get("maxSd")}
        self.step("context", forklifts=len(forklifts), people=ues is not None, rnis=load is not None)
        # 6 validate
        recount = await self.hub.call("in", "history", container=self.near, n=2000)
        stable = not err(recount) and len(recount) == len(events)
        checks = {"hotspot counts within total": sum(h["count"] for h in hs) <= len(new),
                  "snapshot unchanged during the run": stable,
                  "every forklift in a hotspot resolved": all(f in forklifts for h in hs for f in h["forklifts"])}
        self.step("validate", **checks)
        recs = []
        for h in hs:
            r = f"({h['x']:.0f}, {h['y']:.0f}) m, {h['count']} near misses: {h['text']}"
            if h["advice"] == "speed":
                fl = [f for f in h["forklifts"] if forklifts.get(f, {}).get("speed_limit") is None]
                if fl:
                    r += f" - {', '.join(fl)} currently without a speed limit"
            if h.get("people_now"):
                r += f" - {h['people_now']} people within {self.radius:.0f} m right now"
            recs.append(r)
        report = {"generated_ms": int(time.time() * 1000), "status": "partial" if errors else "complete",
                  "near_misses_new": len(new), "near_misses_total": len(events),
                  "unalerted": sum(1 for e in new if not e.get("alerted", True)),
                  "devices": len(inventory), "hotspots": hs, "forklifts": forklifts, "recommendations": recs,
                  "validation": checks, "errors": errors}
        # 7 persist
        w1 = await self.hub.call("in", "write_content", container=f"{AGENT_AE}/reports", content=json.dumps(report))
        if not err(w1) and all(checks.values()) and not errors:   # a partial run does not consume the records:
                                                                  # the next run reads them again
            await self.hub.call("in", "write_content", container=f"{AGENT_AE}/state",
                                content=json.dumps({"cursor": last_ct, "runs": runs + 1,
                                                    "last_run_ms": report["generated_ms"]}))
        await self.hub.call("in", "write_content", container=f"{AGENT_AE}/runs", content=json.dumps(
            {"steps": self.steps, "tool_calls": len(self.hub.log), "errors": len(errors),
             "duration_ms": round((time.time() - t0) * 1000)}))
        self.step("persist", report=w1)
        return report


async def ask(hub: MCPHub, question: str, model=None, max_turns=12):
    """Free question answered by Claude using every MCP tool of the hub (tool names server__tool)."""
    import anthropic
    client = anthropic.Anthropic()
    tools, index = [], {}
    for srv, ts in hub.tools.items():
        for t in ts:
            name = f"{srv.replace('-', '_')}__{t.name}"
            index[name] = (srv, t.name)
            tools.append({"name": name, "description": f"[{srv}] {t.description or ''}"[:1000],
                          "input_schema": t.inputSchema or {"type": "object", "properties": {}}})
    system = ("You are the safety assistant of a warehouse running EdgeGuard (worker-forklift collision "
              "prediction on oneM2M and ETSI MEC). Use the tools: 'in' is the IN-CSE, 'mn_a'/'mn_b' the zone MN-CSEs "
              "(use in__serving_cse to find where a device is served), 'mec' the ETSI MEC services. Check numbers "
              "against the data before stating them.")
    msgs = [{"role": "user", "content": question}]
    for _ in range(max_turns):
        r = client.messages.create(model=model or os.environ.get("EDGEGUARD_AGENT_MODEL", "claude-sonnet-5"),
                                   max_tokens=2000, system=system, tools=tools, messages=msgs)
        msgs.append({"role": "assistant", "content": r.content})
        calls = [b for b in r.content if b.type == "tool_use"]
        if not calls:
            return "".join(b.text for b in r.content if b.type == "text")
        results = []
        for b in calls:
            srv, tool = index[b.name]
            out = await hub.call(srv, tool, **(b.input or {}))
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out)[:20000]})
        msgs.append({"role": "user", "content": results})
    return "(stopped after max_turns)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["report", "ask", "tools"])
    ap.add_argument("question", nargs="?")
    ap.add_argument("--mec-url", default="http://127.0.0.1:8085")
    a = ap.parse_args()

    async def run():
        async with MCPHub(default_servers(mec_url=a.mec_url)) as hub:
            if a.command == "tools":
                return {s: [t.name for t in ts] for s, ts in hub.tools.items()}
            if a.command == "ask":
                return await ask(hub, a.question or "Summarise today's near misses.")
            return await SafetyAgent(hub).shift_report()
    out = asyncio.run(run())
    print(out if isinstance(out, str) else json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
