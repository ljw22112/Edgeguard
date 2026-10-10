# AI safety agent with MCP

[← README](../README.md) · [한국어](ko/ai-agent.md)

A safety manager wants a shift report, not raw resources. The EdgeGuard agent ([`agent/`](../agent/)) works through **Model Context Protocol (MCP)** servers, so the same tools serve our workflow and any MCP client (Claude Desktop, Claude Code, …).

## MCP servers

| Server | Tools |
|---|---|
| `agent/onem2m_mcp.py`, one per CSE (IN-CSE, zone A, zone B) | `cse_info`, `discover` (label / type), `retrieve`, `latest`, `history`, `find_devices` (SAREF semantic query), `semantic_query`, `serving_cse` (home record), `write_content` (guarded) |
| `agent/mec_mcp.py` | `ue_location`, `all_ue_locations` (MEC 013 Location), `cell_load` (MEC 012 RNIS) |

The oneM2M server acts with its own originator (`SEdgeGuardAgent`), so the CSE's ACPs still apply. `write_content` additionally refuses anything outside the agent's own AE.

## Shift report workflow

`python -m agent.safety_agent report`

| Step | Tool calls |
|---|---|
| 1 state | `in.latest(EdgeGuardAgent/state)`: the cursor (creation time of the last near miss read) |
| 2 inventory | `find_devices` on every oneM2M server |
| 3 near misses | `in.history(EdgeGuard/nearmiss)`, keeping only records newer than the cursor |
| 4 hotspots | 1 m grid cells, classified as blind corner, unalerted, fast traffic or crossing |
| 5 context | `mec.all_ue_locations` (people near each hotspot now), `mec.cell_load`; for each forklift involved, `in.serving_cse` → **route** to that zone's server → `retrieve(<twin>/speedLimit)` |
| 6 validate | hotspot counts within the total, snapshot unchanged (re-count), every forklift resolved |
| 7 persist | report → `EdgeGuardAgent/reports`, cursor → `state`, step log → `runs` |

**Errors.** When a CSE or the MEC platform is unreachable or a tool fails, the error is recorded and the run continues. The report is marked **partial** and the cursor stays, so the next run covers those records again.

**Free questions (optional).** With `ANTHROPIC_API_KEY` set and `pip install anthropic`, run `python -m agent.safety_agent ask "Why did forklift_01 slow down?"`. Claude answers using every MCP tool of the hub.

## Demo (CI)

```bash
scripts/acme.sh start in mn-a mn-b
python tools/agent_demo.py          # 9 checks; results/agent.json
```

The demo seeds a shift:
- twins on the IN-CSE, and forklift_01 attached to zone B through a CSE handover client
- 25 near misses with three hotspots
- people and radio load in the MEC mock

**Run 1:** complete, 16 tool calls.
> (12, 4) m, 9 near misses: Blind corner: add the rack to the site map / install a convex mirror - 3 people within 6 m right now
> (-7, 0) m, 6 near misses: Fast forklift traffic: declare a speed-limited zone - forklift_02 currently without a speed limit

**Run 2:** five new near misses arrive and zone B's MN-CSE goes down. The agent reads only the 5 new records and writes a partial report, recording that forklift_01 was unreachable.

**Checks:**
- tools found on 4 servers
- workflow validated
- forklift_01 routed to zone B's server
- blind corner is the top hotspot
- the forklift without a speed limit is named
- MEC context present
- persistent state (5 new records only)
- partial report saved
- guardrail refuses writes outside the agent's AE

## Using the servers from an MCP client

```json
{"mcpServers": {
  "edgeguard-in":  {"command": "python", "args": ["-m", "agent.onem2m_mcp", "--name", "in", "--base-url", "http://127.0.0.1:8080", "--cse-rn", "cse-in"], "cwd": "/path/to/Edgeguard"},
  "edgeguard-mec": {"command": "python", "args": ["-m", "agent.mec_mcp", "--mec-url", "http://127.0.0.1:8085"], "cwd": "/path/to/Edgeguard"}}}
```
