# EdgeGuard and the wider oneM2M / ETSI MEC ecosystem

[← README](../README.md) · [한국어](ko/ecosystem.md)

Three checks that run EdgeGuard against other people's work, all in CI on every commit.

## 1. A third CSE: tinyIoT

[tinyIoT](https://github.com/seslabSJU/tinyIoT) is a lightweight oneM2M CSE in C by the Software Engineering and Security Lab of Sejong University (BSD-3-Clause), listed by oneM2M among the open-source platforms and recommended in the ESTIMED developer materials. A compact MN-CSE is what a MEC host of TR-0086 option C needs.

| | ACME | tinyIoT |
|---|---|---|
| oneM2M tutorial ([`tools/tutorial_safety_app.py`](../tools/tutorial_safety_app.py), 5 checks) | 5/5 | **5/5**, with three documented fallbacks |
| EdgeGuard features ([`tools/cse_probe.py`](../tools/cse_probe.py)) | 13/13 | 9/13 |
| missing on tinyIoT | — | JSON objects as content, ACP `chty`, pollingChannel, semanticDescriptor |

The differences and what EdgeGuard does about each are interoperability issues 8 to 11 in [interop-notes.md](interop-notes.md). With ACME, KETI Mobius and tinyIoT, the same application code now runs on three independent CSE implementations.

## 2. EdgeGuard's MEC traffic against the official ETSI OpenAPI definitions

[`tools/mec_conformance.py`](../tools/mec_conformance.py) runs the MEC platform stand-in with the two-zone scenario, drives EdgeGuard's own clients (MEC-IPE: MEC 013 zone, area and distance subscriptions, location query, MEC 012 radio subscription; Mp1: MEC 011 READY, service registration, discovery, availability subscription; MEC 021 AMS registration, subscription, context transfer) and validates every exchange with [openapi-core](https://github.com/python-openapi/openapi-core) against the ETSI Forge definitions (MEC 013 3.1.1, MEC 012 2.2.1, MEC 011 3.1.1, MEC 021 2.2.1; copies with their BSD-3-Clause licence in [`third_party/etsi-mec/`](../third_party/etsi-mec/)).

| | Before | After |
|---|---|---|
| Requests and responses conforming | 13 of 19 | **19 of 19** |
| Notifications conforming (6 types) | 0 of 77 (a shorter run) | **160 of 160** |

What it found and what changed:
- MEC 013 v3 `callbackReference` is a URI string, not `{notifyURL}` (the v2 form); distance criteria are `AllWithinDistance`, not `ALL_WITHIN_DISTANCE`.
- MEC 012 and MEC 021 encode `AssociateId.type`, the report trigger and `mobilityStatus` as integers.
- Notifications carry `_links`; MEC 013 user records in distance notifications are full `UserInfo`; ServiceInfo carries `_links` and a transport `security` block.

EdgeGuard now sends the ETSI form and still reads the older names ([`edgeguard/mec_codes.py`](../edgeguard/mec_codes.py)); the MEC platform and mobility demos pass 10/10 as before.

Defects in the published definition files are fixed in the validator and listed in the report rather than worked around in EdgeGuard: `type` next to `$ref` in RniAPI.yaml (80 places, left from the 3.0 to 3.1 conversion), the MEC 021 AssociateId placeholder, no success response for MEC 011 `confirm_ready`, and the `SEE_DESCRIPTION` placeholder enum of `changeType`. The definitions also name older base paths (`location/v2`, `mec_app_support/v1`) than the ETSI MEC Sandbox serves (`location/v3`, `mec_app_support/v2`); EdgeGuard uses the Sandbox paths.

## 3. A community MCP server for oneM2M

[onem2m-mcp](https://pypi.org/project/onem2m-mcp/) (Rostan Technologies, BSD-3-Clause) is a generic MCP gateway for any CSE with 17 tools. [`tools/onem2m_mcp_check.py`](../tools/onem2m_mcp_check.py) starts it against the CSE that holds EdgeGuard's twins and, as an ordinary MCP client:

1. discovers the kinematics twins by label: **nothing**, because each device's ACP admits only the device, the MEC app and the MEC-IPE;
2. the site operator adds RETRIEVE and DISCOVERY for the agent's originator to one device's ACP;
3. the agent finds the twin by label and reads it (`egs:kinSt`), then the grant is removed.

So any MCP-capable agent can use EdgeGuard's data through a standard gateway, without our own MCP servers, and only as far as the operator allows.

Reproduce: `python tools/cse_probe.py --cse <url> --rn <cse>`, `python tools/mec_conformance.py`, `/tmp/mcpv/bin/python tools/onem2m_mcp_check.py` (see each file's header).
