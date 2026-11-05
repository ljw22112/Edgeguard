"""A community MCP server for oneM2M, on EdgeGuard's resources.

`onem2m-mcp` (Rostan Technologies, BSD-3-Clause, PyPI) is a generic oneM2M MCP gateway: it registers as an
AE on any CSE and offers 17 MCP tools.  This check starts it against the CSE that holds EdgeGuard's twins and,
as a plain MCP client, finds and reads them with the gateway's own tools, so any MCP-capable agent can use
EdgeGuard's data without our MCP servers.

    python -m venv /tmp/mcpv && /tmp/mcpv/bin/pip install onem2m-mcp      # its own venv (mcp >= 2)
    scripts/acme.sh start in && python tools/setup_resources.py           # EdgeGuard twins on ACME
    /tmp/mcpv/bin/python tools/onem2m_mcp_check.py                        # -> results/onem2m_mcp_check.json
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSE, CSE_RN, PORT = os.environ.get("CSE", "http://127.0.0.1:8080"), os.environ.get("CSE_RN", "cse-in"), 8383


def _m2m(method, path, body=None):
    import urllib.request
    req = urllib.request.Request(f"{CSE}/{CSE_RN}/{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-M2M-Origin": "CAdmin", "X-M2M-RI": "mcp-check", "X-M2M-RVI": "3",
                                          "Accept": "application/json", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read() or b"{}")


def _grant_read(acp, owner, agent):
    """The operator adds RETRIEVE + DISCOVERY for the agent to a device's ACP (nothing else)."""
    a = _m2m("GET", f"{owner}/{acp}")["m2m:acp"]
    acr = [r for r in a["pv"]["acr"] if agent not in r.get("acor", [])] + [{"acor": [agent], "acop": 2 + 32}]
    _m2m("PUT", f"{owner}/{acp}", {"m2m:acp": {"pv": {"acr": acr}}})


def _revoke_read(acp, owner, agent):
    a = _m2m("GET", f"{owner}/{acp}")["m2m:acp"]
    _m2m("PUT", f"{owner}/{acp}", {"m2m:acp": {"pv": {"acr": [r for r in a["pv"]["acr"] if agent not in r.get("acor", [])]}}})


def _text(res):
    return "\n".join(getattr(c, "text", "") for c in res.content)


async def run():
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client as streamablehttp_client

    out = {"tools": [], "calls": [], "agent": os.environ.get("MCP_AGENT", "CmcpAgent")}
    async with streamablehttp_client(f"http://127.0.0.1:{PORT}/mcp") as streams:
        r, w = streams[0], streams[1]
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            out["tools"] = sorted(t.name for t in tools)
            schema = {t.name: (getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}) for t in tools}

            async def call(name, **args):
                res = await s.call_tool(name, args)
                txt = _text(res)
                out["calls"].append({"tool": name, "args": args, "error": bool(getattr(res, "is_error", getattr(res, "isError", False))), "result": txt[:600]})
                print(f"{"ERR " if getattr(res, "is_error", getattr(res, "isError", False)) else "ok  "}{name}({args}) -> {txt[:160]!r}")
                return txt, getattr(res, "is_error", getattr(res, "isError", False))

            await call("cse_info")
            props = (schema.get("discover_resources") or {}).get("properties", {})
            label_key = next((k for k in ("labels", "label", "lbl") if k in props), "label")
            rprops = (schema.get("retrieve_resource") or {}).get("properties", {})
            rkey = next((k for k in ("resource_id", "path", "resource_path", "id") if k in rprops), "resource_id")
            target = f"{CSE_RN}/worker_01/tag/kinematics"

            found, err = await call("discover_resources", **{label_key: "egs:module/kinematics"})
            out["before_grant_found"] = (not err) and "kinematics" in found       # least privilege: expected False
            _grant_read("acp_worker_01", "worker_01", out["agent"])            # the site operator lets this agent read
            found, err = await call("discover_resources", **{label_key: "egs:module/kinematics"})
            out["found_twin"] = (not err) and "kinematics" in found
            got, err = await call("retrieve_resource", **{rkey: target})
            out["read_twin"] = (not err) and "kinematics" in got
            _revoke_read("acp_worker_01", "worker_01", out["agent"])
    return out


def main():
    env = dict(os.environ, ACME_MCP_CSE_URL=CSE, ACME_MCP_CSE_RN=CSE_RN, ACME_MCP_PORT=str(PORT))
    gw = subprocess.Popen([sys.executable, "-m", "onem2m_mcp.gateway"], env=env, stdin=subprocess.DEVNULL,
                          stdout=open(os.path.join(ROOT, "results", "onem2m_mcp_gateway.log"), "w"), stderr=subprocess.STDOUT)
    try:
        time.sleep(4)
        out = asyncio.run(run())
    finally:
        gw.terminate()
    out["package"] = "onem2m-mcp 0.4.1 (BSD-3-Clause)"
    with open(os.path.join(ROOT, "results", "onem2m_mcp_check.json"), "w") as f:
        json.dump(out, f, indent=1)
    ok = out.get("found_twin") and out.get("read_twin") and not out.get("before_grant_found")
    print(f"{len(out['tools'])} MCP tools; before the operator's grant the agent sees no twin: {not out.get('before_grant_found')}; "
          f"after it, found by label: {out.get('found_twin')}, read: {out.get('read_twin')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
