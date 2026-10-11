# EdgeGuard and ESTIMED (TR-0077 clause 7)

[← README](../README.md) · [한국어](ko/estimed-mapping.md)

ETSI STF 685 **ESTIMED** integrates oneM2M and ETSI MEC so that standard IoT services can be deployed, orchestrated and consumed in MEC edge environments. oneM2M TR-0077 clause 7 lists the gaps the project works on, and the ESTIMED PoC (TDE-2026-0052) demonstrates them. EdgeGuard is a warehouse version of that PoC loop, **sense → coordinate → learn → deploy → improve**. Each feature below runs on ACME CSEs in CI on every commit.

## Deployment continuum: option C, with an IN-CSE in the cloud

ESTIMED accepts four couplings of oneM2M and MEC:
- **A**: cloud oneM2M with edge MEC
- **B**: separate edge nodes
- **C**: the same physical edge node
- **D**: deep integration

EdgeGuard is **option C** per zone. Each zone's MEC host runs:
- the zone **MN-CSE**
- the EdgeGuard MEC app
- the MEC-IPE

The **IN-CSE** in the cloud or the site data centre provides global context, the home records and the announcements. That cloud tier is option A. Option B is also covered: the MEC app runs unchanged against a CSE on another node, which is the `sil.yaml` and ETSI Sandbox setup.

```
          IN-CSE (cloud / site DC): home records, announcements, FL coordinator, orchestrator, AI agent
             │ Mcc
   ┌─────────┴──────────┐
 MEC host zone A      MEC host zone B           each: MN-CSE + MEC app + MEC-IPE (option C)
 MN-CSE · MEC app     MN-CSE · MEC app
   │ Mca                 │ Mca
 tags, forklift modules (UEs on the zone's 5G small cell / Wi-Fi AP)
```

## TR-0077 clause 7 → EdgeGuard

| Clause | ESTIMED feature | EdgeGuard | Code · demo (CI) |
|---|---|---|---|
| **7.1 Interworking** | MEC Location services in oneM2M, SDT models for MEC APIs | Event-driven, bidirectional MEC-IPE: MEC 013 zone events become `contentInstance`s; MEC 012 MeasRepUe and MEC 013 fixes become SDT twins (`egs:mecUe`, `egs:ueLoc`, `egs:rdLnk`). oneM2M apps request MEC services through `<MEC-IPE>/requests` | [`mobility.py`](../edgeguard/mobility.py) · `mobility_demo.py` 10/10 |
| 7.1 | Orchestration of MEC apps: discover → select → deploy → register → provision | Hosts self-register (`egs:mecHs`); an operator creates one `egs:depIn` intent. The orchestrator places, deploys via the host lifecycle API, waits for registration, grants device ACPs, configures, monitors and re-places after a host crash | [`orchestration.py`](../edgeguard/orchestration.py) · `orchestration_demo.py` 11/11 |
| **7.2 Handover** | Continuity bundle: AE identity, handover states, serving MN-CSE resolution. Trigger authority: MEC network / radio system | Make-before-break twin migration (state, ACP, portable subscriptions, announcement, home record). Triggers: device location, CSE availability, or the **MEC network** (zone event) | [`handover.py`](../edgeguard/handover.py) · `handover_demo.py` 10/10 + 8/8, `mobility_demo.py` |
| **7.3 Federated learning** | Discover, select, train, aggregate, infer. Model lineage, activation, rollback ("aggregation ≠ operational model delivery") | TR-0084 roles over oneM2M: participants found by label, dropout and late join, FedAvg. Then **delivery**: canary on the site's held-out data, activation in the risk engine (`guidance_fl`), shadow monitoring, rollback; status in `egs:mdlDp` | [`fl.py`](../edgeguard/fl.py), [`model_delivery.py`](../edgeguard/model_delivery.py) · `fl_demo.py` 8/8, `model_delivery_demo.py` 8/8 |
| **7.4 Swarm computing** | Membership, context, coordination, recommendations; participants keep local authority | Swarm membership is a `<group>` of plan containers. The shared context is read with one fan-out request. Each forklift computes the same conflict-free schedule itself, with no coordinator | [`swarm.py`](../edgeguard/swarm.py) · `swarm_demo.py` 9/9 |
| Supporting | Group communication, devices behind NAT | Zone broadcast through `<group>/fopt` to tags that poll a `<pollingChannel>` | [`zones.py`](../edgeguard/zones.py) · `zone_demo.py` 9/9 |
| Supporting | Secure transport | Devices on the oneM2M MQTT binding over TLS (broker passwords, per-originator ACL); CSE and apps on HTTPS | [`mqtt_binding.py`](../edgeguard/mqtt_binding.py) · `secure_transport_demo.py` 10/10 |
| Supporting | AI over the integrated system | Shift safety agent over MCP servers: oneM2M IN plus zone MN-CSEs, and ETSI MEC | [`agent/`](../agent) · `agent_demo.py` 9/9 |

## The PoC's mobility slide, for a warehouse

The PoC asks for a slide that shows mobility: moving around the map, the handover, and another MEC service (signal strength). [`docs/img/mobility_map.html`](img/mobility_map.html) is that view, built from a real run (`tools/mobility_demo.py` → `tools/mobility_map.py`):
- the forklift drives zone A → B → A
- the MEC platform detects each zone change and the MEC-IPE writes it into oneM2M
- the forklift's twin moves to that zone's MN-CSE
- RSRP of both cells is shown as it crosses over

![mobility map](img/mobility_map.png)

## What is still a stand-in

- The MEC platform here is `mec_mock`. It serves the MEC 013 / 012 data models EdgeGuard uses, plus subscriptions, and plays AdvantEDGE scenarios. The polling path was verified against the ETSI MEC Sandbox ([mec-sandbox.md](mec-sandbox.md)); the subscription path has not been run on the Sandbox yet.
- MEC host lifecycle: a simplified MEC 010-2-style API (instantiate, query, terminate) on simulated hosts. Deployed instances are real oneM2M applications that register, are provisioned and process live data, but they run as threads, not containers.
- Notifications to MQTT-registered AEs: ACME's current MQTT binding fails on outgoing requests, so applications receive notifications over HTTPS ([transport-security.md](transport-security.md)).
