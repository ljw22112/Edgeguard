"""MCP server for a oneM2M CSE: an AI agent reads (and, within a guarded scope, writes) oneM2M resources.

    python -m agent.onem2m_mcp --name in --base-url http://127.0.0.1:8080 --cse-rn cse-in --origin SEdgeGuardAgent

One server per CSE (IN-CSE, each zone MN-CSE); the agent routes a request to the right one.  Tools:
  cse_info              the CSEBase (CSE-ID, type, supported resource types)
  discover              resource paths by label and/or type (oneM2M discovery)
  retrieve              one resource
  latest                the newest contentInstance of a container
  history               the last n contentInstances of a container (oldest first)
  find_devices          SAREF semantic query: devices by role / zone / what they actuate
  semantic_query        any SPARQL query over the CSE's semanticDescriptors
  serving_cse           where a device is served now (its home record, IN-CSE)
  write_content         create a contentInstance - only below the agent's own AE (guardrail)
The originator's ACPs still apply: the server can do no more than its oneM2M identity is allowed to.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp.server.fastmcp import FastMCP                 # noqa: E402

from edgeguard import sdt                              # noqa: E402
from edgeguard.onem2m import OneM2MClient, OneM2MError, decode_con  # noqa: E402


def build(name, base_url, cse_rn, origin, write_scope):
    c = OneM2MClient(base_url, cse_rn, origin, timeout=3.0)
    mcp = FastMCP(f"onem2m-{name}", log_level="WARNING")

    def guard(fn):
        @functools.wraps(fn)                             # keeps the signature FastMCP builds the schema from
        def wrapped(*a, **kw):
            try:
                return fn(*a, **kw)
            except OneM2MError as e:
                return {"error": f"oneM2M {e.status}", "rsc": e.rsc, "detail": str(e)[:300]}
            except Exception as e:                       # unreachable CSE etc.: the agent decides what to do
                return {"error": type(e).__name__, "detail": str(e)[:300]}
        return wrapped

    @mcp.tool()
    @guard
    def cse_info() -> dict:
        """The CSEBase of this CSE: CSE-ID, CSE type, supported resource types."""
        cb = (c.request("GET", "") or {}).get("m2m:cb", {})
        return {"server": name, "csi": cb.get("csi"), "cst": cb.get("cst"), "srt": cb.get("srt"), "rn": cb.get("rn")}

    @mcp.tool()
    @guard
    def discover(label: str = "", resource_type: int = 0, parent: str = "") -> list[str]:
        """Paths of resources below `parent` with this label and/or resource type (28 = flexContainer,
        3 = container, 2 = AE, 23 = subscription)."""
        params = {"fu": 1}
        if label:
            params["lbl"] = label
        if resource_type:
            params["ty"] = resource_type
        res = c.request("GET", parent, params=params) or {}
        return [c._rel(u) for u in res.get("m2m:uril") or []]

    @mcp.tool()
    @guard
    def retrieve(path: str) -> dict:
        """One resource (all attributes)."""
        return c.request("GET", path) or {}

    @mcp.tool()
    @guard
    def latest(container: str) -> dict:
        """Content of the newest contentInstance of a container."""
        return {"content": c.latest(container)}

    @mcp.tool()
    @guard
    def history(container: str, n: int = 50) -> list[dict]:
        """Contents of the last n contentInstances of a container, oldest first."""
        res = c.request("GET", container, params={"rcn": 4}) or {}      # attributes + child resources
        cins = next(iter(res.values()), {}).get("m2m:cin", []) if res else []
        cins = sorted(cins, key=lambda x: (x.get("ct", ""), x.get("ri", "")))[-max(1, min(n, 2000)):]
        return [{"ct": x.get("ct"), "content": decode_con(x.get("con"))} for x in cins]

    @mcp.tool()
    @guard
    def find_devices(role: str = "", zone: str = "", actuates: str = "") -> list[dict]:
        """Devices from their SAREF descriptions (semantic query): role worker|forklift, zone, and what they
        actuate (WorkerCue | DriveSpeed).  Returns the RDF node, the oneM2M path of the twin and the role."""
        return c.semantic_query(sdt.query_devices(role or None, zone or None, actuates or None))

    @mcp.tool()
    @guard
    def semantic_query(sparql: str) -> list[dict]:
        """Run a SPARQL SELECT over this CSE's semantic descriptors (SAREF)."""
        return c.semantic_query(sparql)

    @mcp.tool()
    @guard
    def serving_cse(device: str) -> dict:
        """Which CSE serves a device now (its home record <dev>/serving on the IN-CSE, kept by CSE handover)."""
        return c.latest(f"{device}/serving")

    @mcp.tool()
    @guard
    def write_content(container: str, content: str) -> dict:
        """Create a contentInstance (content = JSON text).  Guardrail: only below the agent's own AE."""
        if not any(container == s or container.startswith(s + "/") for s in write_scope):
            return {"error": "forbidden", "detail": f"writes are limited to {write_scope}"}
        res = c.create_cin(container, json.loads(content))
        return {"created": (res or {}).get("m2m:cin", {}).get("rn")}

    return mcp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="in")
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--cse-rn", default="cse-in")
    ap.add_argument("--origin", default="SEdgeGuardAgent")
    ap.add_argument("--write-scope", default="EdgeGuardAgent", help="comma-separated path prefixes")
    a = ap.parse_args()
    build(a.name, a.base_url, a.cse_rn, a.origin, [s for s in a.write_scope.split(",") if s]).run("stdio")


if __name__ == "__main__":
    main()
