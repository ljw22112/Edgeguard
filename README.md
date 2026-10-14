# EdgeGuard

[![ci](https://github.com/ljw22112/Edgeguard/actions/workflows/ci.yml/badge.svg)](https://github.com/ljw22112/Edgeguard/actions/workflows/ci.yml)

**English** | [한국어](README.ko.md) · **[Judge site](site/index.html)** · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

**MEC-based AIoT safety service that predicts worker–forklift collisions**
2026 oneM2M International Hackathon · Team EdgeGuard (Sejong University)

EdgeGuard collects worker-tag and forklift sensor data through **oneM2M** and predicts collisions 1–3 seconds ahead on an **ETSI MEC** edge.
When there is a risk, the worker's tag says **WAIT → GO** (the forklift has passed) and the forklift slows down only as much as needed.
If the network or the server fails, the devices talk to each other directly (D2D) and keep protecting people.

## At a glance

| | v1.0 (vibration alert) | **Now (v1.5)** |
|---|---|---|
| Collisions, many-to-many site (8 workers · 4 forklifts, 750 conflict pairs) | 100 | **4 (−96 %)** |
| Forklift throughput (many-to-many) | 61.7 % | **86.0 %** |
| Collisions, one-to-one encounters (1,207 conflicts) | 145 | **1** |
| Collisions inside coverage holes (worker / forklift, 180 runs) | 16 / 19 | **0 / 0** |

> The figures come from simulation. Device behaviour is tested on every commit by running **the board firmware unmodified on a PC** against a real oneM2M CSE (CI, 6/6 checks), and a phone serves as the worker tag ([hardware demo](docs/hardware-demo.md)).
> **Article: [hackster.io](https://www.hackster.io/ahind012/edgeguard-stop-forklift-accidents-before-they-happen-e07309)** · **Final video: [YouTube](https://youtu.be/P2JI5ZG6PIg)** (2 min 34 s) · Demo videos: **`results/edgeguard_final.mp4`** (final, 2 min 34 s, captions; [storyboard](docs/video-script.md)) · `results/edgeguard_demo_v1.3.mp4` (live demo, 3 scenes, about 1 min 50 s) · `results/edgeguard_firmware_in_the_loop.mp4` (firmware + phone tag, about 30 s).

![Live demo: worker tag on WAIT, oneM2M resource panel](docs/img/demo_wait.png)

## How it works

![EdgeGuard architecture: zone MEC hosts with MN-CSEs, IN-CSE, federated learning and the AI agent](docs/img/architecture_en.png)

```
 Worker tag · forklift module (ESP32 + UWB)
        │ position · velocity (oneM2M CIN)          ▲ WAIT / GO / STEP ASIDE · speed limit
        ▼                                           │
   oneM2M CSE (Mobius) ── Notify ──▶ MEC app: tracking → path prediction → collision-course test → alert
        ▲                                ▲
        │ (network / server failure)     └─ ETSI MEC Location / RNIS APIs
 Device-to-device (D2D): state exchange · local decision · alert relay
```

1. **Sense** — UWB positioning (worker tags · forklifts), optionally cameras and the MEC Location API.
2. **Predict** — Kalman tracking + forklift turn prediction (CTRV); when the forklift's planned route is shared, prediction follows that route.
3. **Decide** — a **collision-course test** (line-of-sight rate · closest point of approach) instead of distance, so passing traffic does not trigger alerts.
4. **Alert** — worker: WAIT (hold) → GO; if he is standing in the forklift's lane, STEP ASIDE (to the lane edge).
   Forklift: slows only as much as needed to avoid contact. In a standoff one side goes first, so both never start at once.
5. **On failure** — graceful degradation: MEC prediction → device-to-device UWB ranging and D2D state exchange → stop; neighbours relay alerts to devices in coverage holes.

## oneM2M in EdgeGuard

**Why oneM2M.** The CSE does the work our own server would otherwise have to do:

- **A hub, not a database** — devices and apps never talk directly; subscriptions push positions to the MEC app and alerts to the tags, so there is no custom broker or polling code.
- **Open to other applications** — alerts and near misses are standard resources; a WMS, a reporting tool or a camera vendor can subscribe without integration work.
- **Access control built in** — one ACP per device AE gives least privilege; CI checks on every commit, on Mobius, that a forged write from another device is rejected (8/8).
- **Vendor-neutral, edge to cloud** — the same code runs on KETI Mobius 3.0.1 and ACME; the edge MN-CSE registers with a cloud IN-CSE over Mcc. 7 interoperability issues documented.

| oneM2M feature | Used for | Status |
|---|---|---|
| AE · container · contentInstance | per-device data (originator = device), MEC app decisions | in use |
| subscription / notify | positions → MEC app, alerts → tags and dashboards | in use |
| accessControlPolicy | one ACP per device AE, least privilege ([resource tree](docs/deployment.md#onem2m-resource-tree)) | in use |
| maxNrOfInstances | bounded history (near misses 2,000, HA lease 20) | in use |
| Mcc registration | edge MN-CSE ↔ cloud IN-CSE | in use |
| flexContainer (SDT, TS-0023 style) + labels + discovery | device twins from our SDT domain `org.edgeguard.safety` + the standard `cod:bat`; devices onboarded by label, no device list ([data model](docs/data-model.md)) | in use |
| semanticDescriptor (SAREF) + semantic query | "forklifts that control their drive speed in zone A" → oneM2M paths | in use |
| accessControlObjectDetails (chty) | the MEC app may create subscriptions only in a device's twin | in use |
| announcement · CSE handover | device AE moves between zone MN-CSEs with state, ACP and subscriptions; AEAnnc at the IN-CSE ([handover](docs/handover.md)) | in use |
| group (fanOutPoint) · pollingChannel | one DANGER alert to every tag in a zone; tags behind NAT poll their channel ([zone broadcast](docs/transport-security.md)) · swarm context read in one request | in use |
| MQTT binding · TLS | devices on MQTT over TLS (password + per-originator broker ACL), CSE and apps on HTTPS ([secured transport](docs/transport-security.md)) | in use |

**ETSI MEC.** A MEC-IPE brings MEC 013 Location and MEC 012 RNIS into the CSE, so the MEC app consumes MEC services through oneM2M. The event-driven IPE also turns MEC zone events and per-UE signal strength into oneM2M resources (SDT classes for MEC data). It lets oneM2M applications request MEC services, and its zone events trigger the CSE handover ([mobility](docs/mobility.md)). On the platform side, instances use **MEC 011 Mp1** (service registration and discovery), **MEC 021 AMS** (application mobility as a handover trigger, with context transfer) and **MEC 013 area / distance** subscriptions ([MEC platform](docs/mec-platform.md)). EdgeGuard follows ESTIMED deployment option C: the MN-CSE, MEC app and IPE share each zone's MEC host ([TR-0077 clause 7 mapping](docs/estimed-mapping.md)). Live on the public ETSI MEC Sandbox (try-mec.etsi.org); 70 alerts in a warehouse scenario on a self-hosted AdvantEDGE.

**Learn more:** [oneM2M](https://www.onem2m.org) · [oneM2M specifications](https://www.onem2m.org/technical/published-specifications) (TS-0001 architecture, TS-0004 protocols) · [ACME CSE](https://github.com/ankraft/ACME-oneM2M-CSE) · [KETI Mobius](https://github.com/IoTKETI/Mobius) · [ETSI MEC](https://www.etsi.org/technologies/multi-access-edge-computing)

## Beyond the edge: ESTIMED / TR-0077 clause 7

| | What | Measured (CI on every commit) |
|---|---|---|
| [CSE handover](docs/handover.md) | a forklift's oneM2M presence follows it between zone MN-CSEs, make-before-break; failover when a zone's CSE dies | location: **3–11 ms** interruption, **0** samples lost · failover ≈ 0.3 s |
| [Federated learning](docs/federated-learning.md) | sites train a worker-motion model on their own data; task, participants, rounds and model versions are oneM2M resources (TR-0084) | 2 s error 0.604 → **0.486 m**; dropout and late join handled |
| [AI safety agent](docs/ai-agent.md) | shift safety reports through MCP servers for the IN-CSE, both zone MN-CSEs and ETSI MEC; state kept in oneM2M | 15 tool calls, validated; partial report when a zone is down |
| [Data model](docs/data-model.md) | SDT flexContainer twins, labels, SAREF semantics | self-registered device onboarded in ≈ 9 s (CI run) |
| [MEC platform APIs](docs/mec-platform.md) (7.1, 7.2) | Mp1 service registration / discovery with a oneM2M pointer; AMS move-out moves app context and oneM2M twin together; geofence and worker–forklift distance from the network | 10/10: AMS A → B → A, context ≈ 2–20 ms; geofence / distance events → oneM2M ≈ 10 ms |
| [Mobility via MEC](docs/mobility.md) (7.1, 7.2) | MEC zone events and RNIS signal strength into oneM2M; MEC requests from oneM2M apps; handover triggered by the MEC network | A → B → A by zone events: **1.5–8 ms** interruption, **0** lost; event → oneM2M 15–45 ms |
| [App orchestration](docs/orchestration.md) (7.1) | one intent resource → discover, select, deploy, register, provision across MEC hosts, one container per instance; re-placed on host crash | host crash → running again in a new container in ≈ 2–3 s |
| [Model delivery](docs/swarm-and-model-delivery.md) (7.3) | canary → activate in the risk engine → shadow monitoring → rollback | untrained and corrupted versions rejected, regression rolled back |
| [Swarm](docs/swarm-and-model-delivery.md) (7.4) | forklifts share plans through a group; each computes the same conflict-free schedule | conflicts → 0; 14.5 s total delay vs 23.5 s reacting |
| [Zone broadcast · secured transport](docs/transport-security.md) | group fan-out to tags behind NAT; firmware on MQTT/TLS with per-device certificates (mutual TLS, CRL), HTTPS apps | one request to 3 tags, p50 8–19 ms; unmodified firmware passes over HTTP, MQTT and mutual TLS; revoked / foreign / missing certificates refused |

## Key results

### Safety

| Metric | Result | Baseline |
|---|---|---|
| Timely detection (1 s before contact) | **100 %**, median lead time 2.4 s | 5 m proximity alarm: 76 % |
| False alarm rate | **30 %** | 5 m proximity alarm: 85 % |
| Further false alarm reduction (v1.2) | 622 → 570 → **400** of 993 (stillness check → route sharing) | — |
| Blind corners (site map) | collisions 17 → **11** of 80 | no map |
| Worker WAIT compliance 85 / 70 / 50 % | collisions 12 / 27 / 42 of 1,207 | v1.0: 145 |

### Productivity

| Metric | Result | Baseline |
|---|---|---|
| Forklift throughput (many-to-many) | **86.0 %**, loss per forklift 11.2 → 5.7 s | v1.0: 61.7 % |
| Forklift throughput (one-to-one) | **86.4 %** (89.0 % with route sharing) | v1.0: 77.3 % |
| Worker time lost per encounter | one-to-one 2.07 → 3.16 s, many-to-many 2.5 → 2.7 s | the cost of the WAIT cue |

### Failures and reliability

| Metric | Result | Baseline |
|---|---|---|
| Total network outage | collisions 180 → **2**, throughput 57 % | stop-everything approach: 18 % |
| MEC app down for 8 s | collisions 85 → **11** of 180 | v0.7 |
| MEC app takeover (HA) | **0.73 s**, heartbeat gap 1.0 s | forklift local fallback threshold: 2 s |
| Median alert latency | **25 ms** (edge), 58 ms on the team laptop | cloud only: 85 ms · none during an outage |
| Scale (40 devices) | alert latency p95 1,642 → **256 ms** | fixed reporting interval |

### Cost and business

| Item | Details |
|---|---|
| Market | Global forklift collision avoidance systems: USD 1.18 billion (2024) → USD 5.11 billion (2034), CAGR 10.9 % |
| Deployment cost (10,000 m² warehouse · 50 workers · 10 forklifts) | about USD 15,100 (KRW 21 million) up front (low-cost ESP32 + UWB devices, two edge servers for HA) |
| Payback | 1.3–4 years from forklift time savings alone; immediate if one injury (about USD 116,000) is prevented |
| Business model | hardware kit + subscription software (KRW 30,000 ≈ USD 21 per forklift and KRW 5,000 ≈ USD 3.6 per worker per month) + MEC partnerships with mobile network operators |

Details: [Cost, market and business model](docs/business.md)

## What is different

| | Existing approach | EdgeGuard |
|---|---|---|
| Decision | distance threshold → frequent false alarms, alarm fatigue | **collision course** (missile-guidance LOS rate · CPA) |
| Cue to the person | one vibration → stops briefly, then walks on | **WAIT → GO**; **STEP ASIDE** when standing in the lane |
| Forklift control | stop, or a fixed low speed | slows only as much as needed; standoffs resolved one side at a time |
| Network failure | server down = no alerts | **graceful degradation + D2D** (like autonomous cars in a tunnel) |
| Many-to-many | no separate per-pair plans | forklifts keep a plan per worker, tags keep a hold per forklift |
| Standards | proprietary protocol and server | per-device oneM2M AEs + ETSI MEC APIs — any oneM2M app can subscribe to alerts and near misses |
| Operations | — | HA · monitoring · near-miss heatmap · D2D authentication |

## Quick start

```bash
cd deploy
docker compose --profile demo up -d                     # Mobius + MEC app + virtual devices (4 encounters)
python3 check_demo.py out/devices.json http://localhost:9090/health
# Dashboard: http://localhost:9090/  (WAIT / STEP ASIDE / GO per worker)

MEC_HA=1 docker compose --profile ha up -d              # + standby MEC app (HA)
# Reactive live demo (local ACME): scripts/run_live_demo.sh   · with real boards: HW=1 scripts/run_live_demo.sh
docker compose --profile monitoring up -d               # + Prometheus :9095 · Grafana :3000
```

| To do this | Run |
|---|---|
| Local demo without Docker | `pip install -r requirements.txt && scripts/run_local_demo.sh crossing_conflict` |
| Tests | `python -m pytest` |
| ACME CSEs with the EdgeGuard SDT domain | `scripts/acme.sh start in mn-a mn-b` (IN-CSE :8080, zone MN-CSEs :8081 / :8082) |
| Data model checks (twins, labels, SAREF, onboarding) | `python deploy/check_sdt.py --onboard` (with the live demo running) |
| CSE handover between zones | `python tools/handover_demo.py [--failover]` |
| Federated learning through oneM2M | `python tools/fl_demo.py` |
| AI safety agent over MCP | `python tools/agent_demo.py` · `python -m agent.safety_agent report` |
| Reactive live demo / record the demo video | `scripts/run_live_demo.sh` / `scripts/run_live_demo.sh record` |
| Firmware-in-the-loop (SIL, same as CI) | `python tools/sil_run.py` · `--scene head_on` |
| A phone as the worker tag | while the MEC app runs, open `http://<host>:9090/tag?worker=worker_01` on the phone |
| Hardware demo (two ESP32 boards) | [Hardware demo guide](docs/hardware-demo.md) |
| User study (phone tag) | `python tools/user_study.py` → [User study](docs/user-study.md) |
| Many-to-many simulation | `python -m sim.multi_sim` |
| One-to-one · compliance evaluation | `python -m sim.worker_cue_eval` |
| False alarm evaluation | `python -m sim.false_alarm_eval` |
| Failure-condition evaluation | `python -m sim.failsafe_eval --modes coop` |

## Components

| Area | Contents |
|---|---|
| Risk engine | Kalman tracking; CV · CTRV · route · LSTM prediction; collision-course test (CPA/TCPA · LOS rate · collision cone · VO slow-down); learned alert policy |
| Alert policy | WAIT hold cue, GO safety check, standoff resolution (one side first), STEP ASIDE, blind-corner compensation |
| MEC app | FastAPI: notifications in → risk / alert / control out, priority send queue, dashboard, phone tag, `/health` · `/metrics` · `/nearmiss` |
| Device firmware | ESP32 + DW1000 (worker tag · forklift module): UWB positioning, WAIT/GO cues, per-pair speed plans, local rules, ESP-NOW D2D + HMAC |
| Integration | oneM2M Mobius / ACME, ETSI MEC Location · RNIS (MEC-IPE), cloud copy sync, camera node (YOLOv8n) |
| Deployment · CI | Docker Compose (demo · ha · monitoring · sandbox); GitHub Actions: tests → firmware-in-the-loop (SIL) → stack end-to-end · restart · takeover · monitoring tests → GHCR |

## Documentation

| Document | Contents |
|---|---|
| [Risk engine and evaluation](docs/risk-and-evaluation.md) | v1.2 many-to-many · standoff resolution · stepping aside · false alarms; v1.1 WAIT/GO; collision-course test; comparison experiments; LSTM; policy learning |
| [Resilience](docs/resilience.md) | graceful degradation (v0.8), D2D cooperation (v0.9), HA (v1.0), scale · restart · server hardening |
| [Site features](docs/site-features.md) | blind corners, D2D authentication, monitoring, near-miss analysis, camera, access control, dashboard · reports |
| [Deployment](docs/deployment.md) | Compose stack, local demo, deployment architecture (measured), oneM2M resource tree, firmware · CI |
| [ETSI MEC integration · Sandbox](docs/mec-sandbox.md) | MEC API integration, live public Sandbox, self-hosted Sandbox ([setup](deploy/sandbox-host/README.md)) |
| [Cost, market and business model](docs/business.md) | problem size, market, deployment cost, payback, revenue model, scalability, oneM2M ecosystem contribution |
| [Adoption barriers](docs/adoption.md) | why similar systems did not spread on sites, and how EdgeGuard responds |
| [Interoperability notes](docs/interop-notes.md) | issues found in cross-CSE testing and their fixes |
| [Data model](docs/data-model.md) | SDT flexContainer twins, labels and discovery, SAREF semantic descriptors, ACPs |
| [CSE handover](docs/handover.md) | zone MN-CSEs, make-before-break handover, failover, portable subscriptions, measurements |
| [Federated learning](docs/federated-learning.md) | TR-0084 roles as oneM2M resources, selection, dropout, late join, results |
| [AI safety agent](docs/ai-agent.md) | MCP servers (oneM2M per CSE, ETSI MEC), shift report workflow, routing, persistent state |
| [ESTIMED / TR-0077 mapping](docs/estimed-mapping.md) | deployment continuum (option C), clause 7.1–7.4 → EdgeGuard features and demos, stand-ins |
| [MEC platform APIs](docs/mec-platform.md) | MEC 011 Mp1, MEC 021 AMS handover trigger, MEC 013 area / distance subscriptions |
| [Mobility via MEC](docs/mobility.md) | event-driven bidirectional MEC-IPE, MEC SDT classes, network-triggered handover, mobility map |
| [App orchestration](docs/orchestration.md) | host registration, deployment intents, lifecycle, provisioning, re-placement |
| [Swarm and model delivery](docs/swarm-and-model-delivery.md) | group-based swarm coordination; canary, activation, monitoring and rollback of federated models |
| [Zone broadcast · secured transport](docs/transport-security.md) | group fan-out, pollingChannel, MQTT binding over TLS, HTTPS, broker ACL |
| [hackster.io article](https://www.hackster.io/ahind012/edgeguard-stop-forklift-accidents-before-they-happen-e07309) ([source](docs/hackster-article.md)) | the project story for the hackathon article, published on hackster.io |
| [Interview Q&A](docs/interview-qa.md) | 16 expected questions with answers and their evidence |
| [Final video storyboard](docs/video-script.md) | timeline and narration of `results/edgeguard_final.mp4` |
| [Hardware demo](docs/hardware-demo.md) | firmware-in-the-loop (SIL, CI) · phone tag · ESP32 boards (parts · wiring · checklist) |
| [User study](docs/user-study.md) | cue-response experiment with a phone tag, safety manager interviews, feeding results back into the simulation |

Korean versions of all documents: [docs/ko/](docs/ko/).

## Repository layout

```
edgeguard/   risk engine · tracking · prediction · alert policy · worker cues · device rules · site map · near misses · HA · oneM2M/MEC clients
mec_app/     MEC app (FastAPI) + dashboard + phone tag + Dockerfile
firmware/    ESP32 sketches (worker_tag, forklift_module) + shared headers (UWB positioning, device rules, WAIT/GO, D2D, HMAC)
deploy/      Docker Compose stack, monitoring config, Sandbox host install scripts, end-to-end test scripts
sim/         scenarios · one-to-one / many-to-many closed-loop simulation · failure · false alarm evaluation · policy/LSTM training
tools/       resource setup · MEC-IPE · Sandbox integration/checks · firmware-in-the-loop · load/config tests · safety reports
results/     evaluation results (JSON · figures) · devices/ mec_mock/ scenarios/ models/ scripts/ tests/ docs/
```

## Version history

| Version | Highlights |
|---|---|
| v0.6–0.7 | collision-course test · learned alert policy (collisions 32 → 15 of 180, throughput +14 %), adaptive reporting rate, restart failsafe, cloud copy |
| v0.8 | graceful degradation on network failure (MEC silent for 2 s → local device-to-device UWB decision) |
| v0.9 | device-to-device cooperation (D2D): state exchange · local closest-approach test · alert relay to devices in coverage holes, server hardening |
| v1.0 | blind-corner site map, D2D frame authentication, MEC app HA, monitoring, near-miss analysis |
| v1.1 | worker WAIT → GO cue (cause of the remaining accidents: workers walking on after the vibration) |
| v1.2 | many-to-many validation · per-pair plans, standoff resolution, STEP ASIDE, fewer false alarms (stillness check · route sharing), WAIT/GO on the dashboard |
| v1.4 | SDT flexContainer data model (labels, discovery onboarding, SAREF semantics, chty ACPs), CSE handover between zone MN-CSEs, federated learning through oneM2M, AI safety agent over MCP, hackster.io article draft |
| v1.5 | ESTIMED / TR-0077 clause 7: event-driven bidirectional MEC-IPE with MEC SDT classes, network-triggered handover and mobility map; MEC app orchestration across hosts; forklift swarm; federated model delivery (canary, rollback) into the risk engine; zone broadcast via group + pollingChannel; MQTT/TLS devices and HTTPS |
| v1.3 | per-device oneM2M AEs · ACPs (forged writes rejected, verified in CI), cost · market · business model, reactive live demo · new demo video, firmware-in-the-loop (SIL, CI) · phone tag, hardware demo kit (HIL), user study kit, English documentation |

## Roadmap to the final (Nov 20)

| By | Adds | Hackathon criteria |
|---|---|---|
| ~~Oct 20~~ done | flexContainer data model, labels, discovery, SAREF semantics | Data interoperability |
| ~~Nov 10~~ done | CSE handover between zone MN-CSEs with failover | CSE handover |
| ~~Nov 17~~ done | MCP servers and safety agent; federated learning | AI agents and MCP, federated learning |
| ~~Oct 31~~ done | group, pollingChannel; MQTT for devices; TLS | Innovative use of oneM2M, protocols, security |
| ~~Nov 10~~ done | MEC zone events → handover trigger; bidirectional MEC–oneM2M; multi-host orchestration; swarm; model delivery | Geolocation, MEC services, deployment |
| Nov 20 | ESP32 board demo, user study, hackster.io article published, final video, public repository | Article, video, GitHub, promotion |

## Validation scope and limitations

**How it was validated** — online and fast closed-loop simulation, real Mobius / ACME CSEs, and the ETSI MEC Sandbox.
The firmware is compiled unmodified for a PC and exchanges real messages with a CSE (SIL) on every commit in CI. A demo on physical ESP32 boards is planned by the team.

**Models of people and sites**
- Worker behaviour (stopping on vibration, WAIT compliance, stepping aside) is modelled. Sensitivity is shown for 50–100 % compliance, but the real value needs a site trial.
- The step-aside direction is "the nearer lane edge" and does not consider other forklifts. The tag shows no direction.
- False alarms remain when workers stop on their own before an aisle (people slow down only in the last second).
- The site map is hand-entered rectangular obstacles, and blind-corner compensation raises false alarms in those areas (39 → 57 of 80).

**Learning and agent**
- Federated learning uses walking data from a per-site simulator. The delivered model drives the risk engine's worker prediction (`guidance_fl`) in the delivery demo; the live demo configuration still uses `guidance_ctrv`.
- The agent's workflow is deterministic; Claude is used only for free questions (`ask`, needs an API key).

**System**
- Route sharing is an optional feature that needs a forklift fleet system (WMS) or driver tablet integration.
- Real UWB error and firmware timing were replaced by simulation and sensitivity tests. The official MEC-IPE (TR-0086) is not yet public, so `tools/mec_ipe.py` and `edgeguard/mobility.py` play that role. MEC zone events, RNIS reports and the host lifecycle API come from `mec_mock` and simulated hosts.
- Scale tests ran on a single 2-core PC that also ran the load generator, so results vary with hardware. The cloud path was compared only by injecting latency.
- The D2D key is a site-wide pre-shared key (no per-device keys, no automatic rotation).
- HA covers up to two MEC apps sharing one CSE; a CSE failure is handled by the devices' local rules and D2D.

## License

EdgeGuard code is under the [MIT](LICENSE) license. Licenses of the open-source software used (Mobius, ACME, AdvantEDGE, YOLOv8, etc.) are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
