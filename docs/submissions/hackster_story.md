# EdgeGuard: Stop Forklift Accidents Before They Happen with oneM2M and ETSI MEC

*Predict worker–forklift collisions 1–3 seconds ahead on the network edge, tell people exactly what to do, and keep protecting them when the network fails, all built on standard oneM2M resources.*

**Team EdgeGuard (Sejong University) · 2026 oneM2M International Hackathon**

![EdgeGuard architecture](https://raw.githubusercontent.com/ljw22112/Edgeguard/main/docs/img/architecture_en.png)

---

## Things used in this project

**Hardware components**

- **ESP32 development board (ESP32-WROOM DevKit)**: Qty: 2; Role: worker tag, forklift module
- **Qorvo DWM1000 UWB module (or an ESP32 UWB board)**: Qty: 2+; Role: positioning, device-to-device ranging
- **Coin vibration motor + NPN transistor (2N2222) + diode (1N4148) + 1 kΩ resistor**: Qty: 1 set; Role: the tag's haptic cue
- **LEDs + 220 Ω resistors**: Qty: 2; Role: tag WAIT light, forklift beacon
- **Small DC motor + driver (L298N or MOSFET module)**: Qty: 1; Role: stands in for the forklift drive, so the speed limit is visible
- **Smartphone (optional)**: Qty: 1; Role: a worker tag without any hardware (vibration, screen)

**Software apps and online services**

- [oneM2M](https://www.onem2m.org) CSEs: [ACME CSE](https://github.com/ankraft/ACME-oneM2M-CSE) (IN-CSE and zone MN-CSEs) and [KETI Mobius](https://github.com/IoTKETI/Mobius)
- [ETSI MEC](https://www.etsi.org/technologies/multi-access-edge-computing) Location (MEC 013) and RNIS (MEC 012) on the ETSI MEC Sandbox and a self-hosted AdvantEDGE
- Python 3.11 (FastAPI, NumPy), Arduino IDE (ESP32 core 3.x, ArduinoJson), Docker Compose
- [Eclipse Mosquitto](https://mosquitto.org) (oneM2M MQTT binding over TLS), OpenSSL (demo site CA)
- Model Context Protocol (MCP) for the AI safety agent; Claude (optional) for free questions

---

## Story

### The problem: people and forklifts share the same aisles

Korea recorded **2,559 forklift accident casualties in 2021–2022** (KOSHA). One workplace injury costs about **USD 116,000** once indirect costs are included (NSC Injury Facts, OSHA 3885). Proximity alarms exist, but they have three weaknesses:

1. **Safe or productive, not both.** A distance alarm also fires on every forklift that will pass safely. Set wide (6 m warning / 3 m stop), it prevented every collision in our simulation but cut forklift throughput to **48 %** of nominal; narrowed to 4 m / 2 m to stop the nuisance, it let **49 collisions** through in 3,617 conflicts.
2. **One buzz says "danger", not "what now".** In our first version, the remaining collisions came from workers who stopped at the buzz and then walked back into the lane before the forklift had passed.
3. **No server, no safety.** When the network or the server fails, server-based systems go silent exactly when they are needed.

### Our solution in one sentence

Tags and forklift modules publish their positions into **oneM2M**. An **ETSI MEC** application next to the CSE predicts collision courses. Each worker gets **WAIT → GO**, or **STEP ASIDE** when standing in the lane, and the forklift keeps its speed as long as it can still stop short of the person, braking on its own for a **stop point** when it cannot. On 1,000 fresh simulated episodes: **0 collisions at 2.0× the throughput of a UWB proximity alarm**, and 0 in 34,644 conflicts under bad network, server restart, low compliance and noisy positioning.

### How it works

1. **Sense:** UWB worker tags and forklift modules publish their position up to 10 times per second (2 Hz when nothing is near): as an UPDATE of their own SDT device twin on ACME, or as a contentInstance on any CSE (Mobius, and the ESP32 firmware today).
2. **Notify:** the edge CSE notifies the EdgeGuard MEC app through subscriptions. No polling and no custom broker.
3. **Predict:** Kalman tracking, a turning model for forklifts (CTRV), or the forklift's planned route when the fleet system shares it.
4. **Decide:** a **collision-course test** borrowed from missile guidance. If the bearing stays constant while the range closes (line-of-sight rate ≈ 0) and the closest point of approach is inside the safety radius, the two will meet. A forklift that will pass by never raises an alert.
5. **Cue:** an alert contentInstance goes back through oneM2M. The tag shows **WAIT** until the forklift has passed and then **GO**, or **STEP ASIDE**. The forklift module enforces the smallest speed limit that avoids contact. Each device confirms what it did in its own `status` container.

---

## oneM2M resource design

Each device is **its own AE**, so the originator is the device. The MEC app's decisions are oneM2M resources too, which means any oneM2M application can subscribe to them. The tree below shows the SDT data model on a zone MN-CSE (illustrative; the same tree runs on the IN-CSE in the single-CSE demos).

```
/cse-mn-a (zone MN-CSE on the MEC host)
├─ worker_01                AE, originator SWorker01, lbl egs:role/worker
│   ├─ tag                  flexContainer egs:wrkTg (device class "workerTag")
│   │   ├─ kinematics       egs:kinSt  posX, posY, speed, heading, sampleTime   (mni 100: history)
│   │   ├─ cue              egs:wrkCe  cueState IDLE | WAIT | ASIDE | GO
│   │   ├─ battery          cod:bat    standard oneM2M module class
│   │   └─ smd              semanticDescriptor (SAREF, RDF/Turtle)
│   ├─ relay · status       containers: D2D relay, actuator confirmations
│   └─ acp_worker_01        ACP
├─ forklift_01              AE, originator SForklift01
│   ├─ module               egs:frkMe: kinematics, speedLimit (egs:spdLt), battery, smd
│   └─ acp_forklift_01
└─ EdgeGuard                AE of the MEC app: risk · alert · control · nearmiss (mni 2000) · mec_lease
```

### A standard data model: SDT flexContainers (TS-0023 style)

Instead of opaque JSON in contentInstances, device state uses **flexContainer specializations** from our own SDT domain `org.edgeguard.safety`. The device classes `workerTag` and `forkliftModule` combine three new module classes with the **standard** `battery` module class from `org.onem2m.common`. The domain is a single file that the CSE loads ([`config/onem2m/edgeguard.fcp`](https://github.com/ljw22112/Edgeguard/blob/main/config/onem2m/edgeguard.fcp)):

```json
{ "type": "egs:kinSt", "lname": "kinematicState", "sdttype": "moduleclass",
  "cnd":  "org.edgeguard.safety.moduleclass.kinematicState",
  "attributes": [
    { "sname": "posX",  "lname": "positionX",  "type": "float",   "car": "1" },
    { "sname": "posY",  "lname": "positionY",  "type": "float",   "car": "1" },
    { "sname": "speed", "lname": "speed",      "type": "float",   "car": "01" },
    { "sname": "smpTe", "lname": "sampleTime", "type": "integer", "car": "1" } ] }
```

With the SDT data model (ACME), a position sample is a single UPDATE of the kinematics module. The CSE keeps the history (`fcied`, `mni`) and notifies the subscribers. Mobius deployments and the current ESP32 firmware use plain contentInstances; the MEC app accepts both:

```http
PUT /cse-mn-a/forklift_01/module/kinematics
X-M2M-Origin: SForklift01
{"egs:kinSt": {"posX": 3.5, "posY": 2.1, "speed": 1.8, "headg": 0.0, "smpTe": 1791617040123}}
```

### Discoverability: labels and semantics

- **Labels:** every resource carries `egs:site/…`, `egs:role/…`, `egs:id/…`, `egs:module/…`. The MEC app finds every kinematics module with **one discovery request**, `GET /cse?fu=1&ty=28&lbl=egs:module/kinematics`. A tag that registers itself is onboarded automatically, without a device list; in CI this takes about 9 s.
- **Semantics:** each twin has a **SAREF** description in a `semanticDescriptor`. A **semantic query** answers questions like "which forklifts control their drive speed?" and returns oneM2M paths an application can subscribe to:

```sparql
PREFIX saref: <https://saref.etsi.org/core/>  PREFIX egs: <https://edgeguard.example/ns#>
SELECT ?d ?path WHERE { ?d a saref:Device ; egs:role "forklift" ;
                           saref:controlsProperty egs:DriveSpeed ; egs:resource ?path . }
```

### Security and privacy: least privilege per device

- **One ACP per device AE:** the device has full rights, the MEC app and the MEC-IPE may read, discover and subscribe, and every other device gets nothing.
- **CREATE limited by child type:** with `accessControlObjectDetails` (`chty: [23]`), the MEC app may create **subscriptions only** and cannot write data into a device's twin.
- **Checked on every commit:** CI runs 8 access checks against a real Mobius (a forged write from another device is refused) and checks on ACME that another device cannot update a twin (403).
- **Encrypted, authenticated transport:** devices use MQTT over TLS, and applications use HTTPS. In CI, plaintext HTTP and MQTT, an untrusted certificate, a wrong password, a device sending as another device, and another device reading the forklift's data are all refused (10/10).
- **Privacy by placement:** worker trajectories stay in the zone's edge CSE; only alerts, risk summaries and near-miss records (event positions, not trajectories) leave the site. Device-to-device frames are signed with an HMAC.

```json
{"m2m:acp": {"rn": "acp_forklift_01", "pv": {"acr": [
   {"acor": ["SForklift01"], "acop": 63},
   {"acor": ["SEdgeGuard", "SMecIpe"], "acop": 51, "acod": [{"chty": [23]}]} ]}}}
```

### Protocols: each link uses what fits

- **Device → CSE**: Protocol: oneM2M **MQTT binding over TLS**, in the firmware too (`M2M_MQTT=1`; device certificate on the mutual-TLS listener); Why: one open connection, no inbound port; broker password and an ACL that lets a device speak only as itself
- **MEC app ↔ CSE**: Protocol: Mca over **HTTPS**, subscriptions / notifications; Why: the CSE pushes every sample to the app; the CSE certificate is checked against the site CA
- **Tags behind NAT**: Protocol: `<pollingChannel>`; Why: the tag long-polls; zone alerts reach it without an inbound connection
- **Zone MN-CSE ↔ IN-CSE**: Protocol: **Mcc**; Why: edge to cloud, announcement of device AEs
- **Device ↔ device**: Protocol: ESP-NOW + HMAC, UWB ranging; Why: works with no access point and no CSE: the fallback when the network fails
- **MEC services**: Protocol: ETSI MEC REST (MEC 013, MEC 012); Why: brought into oneM2M by a MEC-IPE

---

## ETSI MEC integration

- **MEC services through oneM2M:** a MEC Interworking Proxy Entity (MEC-IPE) polls the **Location** and **RNIS** APIs and writes new values as oneM2M resources (`location/<ue>`, `rnis/<cell>`). The MEC app subscribes to MEC data exactly as it subscribes to a device. Location supplies positions for people without a UWB fix, and RNIS cell load sets the reporting rate and the alert priority.
- **Deployment:** the MEC app runs as a Docker container next to the CSE on the MEC host, as an active-standby pair (takeover in **0.73 s**). It ran live against the public **ETSI MEC Sandbox** (try-mec.etsi.org) and in a custom warehouse scenario on a self-hosted **AdvantEDGE** (70 alerts in 2 minutes).
- **Event-driven and bidirectional:** a second MEC-IPE subscribes to MEC 013 **zone events** and MEC 012 **per-UE measurement reports** (RSRP / RSRQ). It writes them into oneM2M as SDT twins (`egs:mecUe` with `egs:ueLoc` and `egs:rdLnk`), and it executes MEC requests that oneM2M applications post into `MEC-IPE/requests` (zone_subscribe, radio_subscribe, location, unsubscribe). Zone event → oneM2M resource: median 15–45 ms.
- **Zone broadcast:** one oneM2M `<group>` per zone. A DANGER alert is **one request** to `<group>/fopt`, and the CSE creates it in the inbox of every tag in that zone (p50 8–19 ms including the tag's polling channel).
- **Latency:** the median alert latency on the edge is **25 ms**, against 85 ms for a cloud-only path (measured with an injected 25 ms one-way WAN delay).

---

## Service continuity: CSE handover between MEC zones

A large warehouse has several zones, each with its own MEC host and MN-CSE. When a forklift drives from zone A to zone B, its oneM2M presence moves with it, **make-before-break** ([`edgeguard/handover.py`](https://github.com/ljw22112/Edgeguard/blob/main/edgeguard/handover.py)):

1. **Trigger:** the forklift's position is 1 m inside zone B (hysteresis against ping-pong), or the serving CSE stops answering (availability).
2. **Prepare in the background** while samples keep flowing to zone A:
   - state: the module values (speed limit, kinematics, battery) are read from the source and restored on the target
   - security: the AE, twin and ACP are rebuilt with the same rules
   - subscriptions: every subscription on the twin is re-created with the same notification URIs. This works because subscribers attach the device's ACP to their subscription, which lets the device read and carry it.
   - announcement: the new AE is announced to the IN-CSE, whose AEAnnc `lnk` points at the serving CSE
3. **Switch:** the next sample goes to zone B.
4. **Home record:** `<IN-CSE>/<device>/serving` is updated, so applications can resolve or subscribe to the device's current CSE.
5. **Release:** the AE on zone A is deleted after a short grace period.

**Measured (CI, every commit):**

- **Location A → B**: Prepared in: ≈ 115–140 ms (in the background); Service interruption: **3–11 ms**; Samples lost: **0**
- **Availability: zone B's CSE killed → back to A**: Prepared in: ≈ 80 ms after detection; Service interruption: ≈ 306 ms; Samples lost: 3 (the detection window)

The subscribed application never re-subscribed. It kept receiving notifications, now sent by zone B's CSE (`/id-mn-b`).

**Triggered by the network.** In ESTIMED terms, the trigger authority can also be the MEC network. The MEC platform sees the forklift attach to zone B's small cell and emits `ENTERING_AREA_EVENT zoneB`. The MEC-IPE writes the event into oneM2M, and the forklift, subscribed to it, starts the handover. In the CI run (A → B → A at 4 m/s), interruption was 1.5–8 ms and no sample was lost. At the boundary, the RSRP of both cells crosses over at about −90 dBm.

![Mobility map: zones, handover, signal strength](https://raw.githubusercontent.com/ljw22112/Edgeguard/main/docs/img/mobility_map.png)

---

## When the network fails: graceful degradation

If a device hears no heartbeat from the MEC app for 2 s, it switches to local decisions: UWB ranging between devices, direct state exchange over ESP-NOW (HMAC-signed), and alert relay to neighbours in coverage holes. It stops only when nothing else is known.

- **Total network outage (180 encounters that would collide)**: Collisions: **2** (v0.7 hold-then-stop: 180); Forklift throughput: 57 % (stop-everything approach: 18 %)
- **Worker or forklift in a coverage hole**: Collisions: **0 / 0** (was 16 / 19); Forklift throughput: —

Two layers sit on the devices themselves, independent of the network and the MEC app:
- **Tag GO check:** a WAIT that runs out without a word from the MEC app (for example after a restart) ends only if walking on at the worker's last pace would not meet a truck, judged from the device-to-device state broadcast alone.
- **Always-on emergency brake** on the forklift module: a person on a collision course within 1.5 s stops the truck, and the truck **stays stopped while that person is in front of it**.

Both run identically in the Python reference and the ESP32 firmware (equivalence tests in CI). Results under exceptional conditions are under Results below.

---

## Federated learning across sites (oneM2M TR-0084)

Worker trajectories are personal data. To learn how people really walk (decelerating into stops and turns, which constant velocity misses), each site trains a small worker-motion model on its own data, and **only weights travel through oneM2M** ([`edgeguard/fl.py`](https://github.com/ljw22112/Edgeguard/blob/main/edgeguard/fl.py)):

- **Coordinator (IN-AE):** a `task` flexContainer (`egs:flTsk`: model, rounds, clients per round, quorum, timeout, status, model version), a `rounds` container (selection per round) and a `models` container (every version with its parent and participants: model lineage).
- **Clients (one AE per site):** a `participant` flexContainer (`egs:flPrt`: sample count, availability, compute score, last round) and an `updates` container.
- **Dynamic selection:** participants are found by label. The coordinator picks available clients with enough data, preferring those that waited longest. If a round reaches its quorum before the timeout, it is aggregated with FedAvg.

In the CI run, Incheon's MEC host fails in the middle of round 3, and the round is still aggregated from the other two sites. Daejeon registers before round 4 and is selected immediately.

- **Constant velocity (what the risk engine assumed)**: 0.604 m
- **Each site training alone**: 0.521 m
- **Federated global model**: **0.486 m**

**Aggregation is not delivery.** Each site's model manager subscribes to the model repository and handles every new version in three steps:
1. **Canary:** the version is evaluated on the site's own held-out data and must beat the active model.
2. **Activate:** it is activated in the risk engine (`guidance_fl`).
3. **Monitor:** the previous version is shadow-evaluated on live windows, and the manager rolls back if it wins three times in a row.

In CI, an untrained v0 and a corrupted v2 are rejected, and a Busan-specialised v3 is activated. After a layout change, v3 is rolled back to the global v1. Each step is recorded in `egs:mdlDp`.

*The study ran on ACME. The design follows the ESTIMED proof of concept and is meant to run on the ESTIMED VM.*

---

## Swarm and orchestration (TR-0077 7.4 and 7.1)

**Swarm.** Forklifts in a zone form a swarm: a `<group>` of their `plan` containers. Each forklift publishes its route through the intersections with arrival times and reads every member's plan with one request (`<group>/fopt/la`, ≈ 6 ms). It then computes the same conflict-free schedule as everyone else: loaded forklifts first, then the earliest arrival, then a 4 s headway at shared intersections. No coordinator is needed, and every participant keeps local authority. In the demo, conflicts drop from 4 to 0, at 14.5 s of total delay compared with 23.5 s for braking at each intersection.

**Orchestration.** MEC hosts register themselves (`egs:mecHs`: zone, free CPU and memory, RTT, lifecycle API, a one-second heartbeat). An operator deploys EdgeGuard by creating a single `egs:depIn` intent, for example "risk engine, zone A, 2 CPU, ≤ 10 ms". The orchestrator then:
1. discovers hosts by label and selects one against the constraints
2. deploys through the host's lifecycle API
3. waits for the instance to register its own AE
4. provisions it by extending the device ACPs and writing its configuration

The engine runs ≈ 0.75 s after the intent. When the zone A host crashes, the engine is running again on the second zone A host ≈ 2.3–2.7 s later, and the old instance's access is revoked.

See [docs/estimed-mapping.md](https://github.com/ljw22112/Edgeguard/blob/main/docs/estimed-mapping.md) for how each feature maps to TR-0077 clause 7 and the ESTIMED deployment continuum (EdgeGuard is option C per zone, with an IN-CSE in the cloud).

---

## AI safety agent with MCP

A safety manager wants a shift report, not raw resources. Our agent ([`agent/`](https://github.com/ljw22112/Edgeguard/blob/main/agent)) talks to **four MCP servers**: one oneM2M server per CSE (the IN-CSE and both zone MN-CSEs) and one for ETSI MEC. It runs a multi-step workflow:

1. Read its own state from oneM2M, so only new near misses are processed.
2. Build the device inventory with SAREF semantic queries on every CSE.
3. Find near-miss hotspots and classify them: blind corner, unalerted, fast traffic, or crossing.
4. Add MEC context: how many people are near each hotspot right now (Location) and the radio load (RNIS).
5. For every forklift involved, look up its **serving CSE** in the home record and route the query to that zone's MCP server for the live speed limit.
6. Validate the totals and check that the data did not change mid-run, then persist the report, the cursor and a step log in oneM2M.

If a CSE is down, the agent writes a **partial** report, records the error, and keeps the cursor so those records are read again on the next run. Its writes are limited to its own AE (a server-side guardrail), and its oneM2M identity is still bound by the ACPs.

Sample recommendation from the CI run:

> (12, 4) m, 9 near misses: Blind corner: add the rack to the site map / install a convex mirror - 3 people within 6 m right now
> (-7, 0) m, 6 near misses: Fast forklift traffic: declare a speed-limited zone - forklift_02 currently without a speed limit - 1 person within 6 m right now

---

## Hardware build

- **Tag**: Pin: GPIO 25; Connection: 1 kΩ → transistor base; vibration motor on the collector (other end 3.3 V); diode across the motor
- **Tag**: Pin: GPIO 2; Connection: 220 Ω → LED → GND (WAIT light)
- **Forklift**: Pin: GPIO 27; Connection: motor driver PWM / EN; driver powered from a power bank
- **Forklift**: Pin: GPIO 26; Connection: 220 Ω → LED → GND (beacon)

![Worker tag schematic](https://raw.githubusercontent.com/ljw22112/Edgeguard/main/docs/img/schematic_tag.png)

![Forklift module schematic](https://raw.githubusercontent.com/ljw22112/Edgeguard/main/docs/img/schematic_forklift.png)

*Status: the board kit and wiring are ready and the board demo is scheduled before the final; the CI evidence today is firmware-in-the-loop.* The firmware ([`firmware/`](https://github.com/ljw22112/Edgeguard/blob/main/firmware)) registers the device's own AE at boot and receives alerts as oneM2M notifications. It drives the outputs and writes confirmations to `<device>/status`, which appear on the dashboard as **HW ✓**. **Firmware-in-the-loop:** the same sketches compile unmodified for a PC, and CI runs them against a real CSE on every commit (6 of 6 checks). A phone can act as the tag: open `http://<MEC host>:9090/tag?worker=worker_01`.

![Firmware-in-the-loop and a phone as the worker tag](https://raw.githubusercontent.com/ljw22112/Edgeguard/main/docs/img/sil_phone.png)

---

## Results (closed-loop simulation)

All results come from a closed-loop simulator of a warehouse floor (8 workers and 4 forklifts per 25 s episode, randomised network delay and loss, UWB noise). The policy was trained and selected on separate seeds; **every number below is on fresh episodes that were never used to train, select or tune it**, with 95 % confidence intervals ([`sim/large_eval.py`](https://github.com/ljw22112/Edgeguard/blob/main/sim/large_eval.py)).

### Against what warehouses use today (1,000 episodes, 3,617 conflicts, nobody looks out)

![Systems used on sites today vs EdgeGuard](https://raw.githubusercontent.com/ljw22112/Edgeguard/main/docs/img/large_eval.png)

- **No system**: Collisions (per 1,000 conflicts): 2,621 (725); Forklift throughput: 99.9 %; Alarms per episode: 0
- **Speed zoning 5 km/h**: Collisions (per 1,000 conflicts): 2,088 (577); Forklift throughput: 75.1 %; Alarms per episode: 0
- **UWB proximity alarm, 6 m / 3 m**: Collisions (per 1,000 conflicts): 0 (< 1.1); Forklift throughput: 48.3 %; Alarms per episode: 37.6
- **UWB proximity alarm, 4 m / 2 m**: Collisions (per 1,000 conflicts): 49 (13.5); Forklift throughput: 60.3 %; Alarms per episode: 25.7
- **EdgeGuard**: Collisions (per 1,000 conflicts): **0 (< 1.1)**; Forklift throughput: **97.3 % [96.9–97.7]**; Alarms per episode: **7.0**

- **As safe as the wide proximity alarm, at 2.0× its throughput**, with 81 % fewer alarms and half the worker waiting (2.1 s instead of 4.3 s per episode).
- Against the narrowed alarm sites choose to cut nuisance alarms: **0 collisions instead of 49, and +37 points of throughput**.
- With an attentive driver (brakes after 1 s for a person in front): EdgeGuard 0 collisions, 96.0 %; narrowed alarm 20 collisions.

The proximity alarm follows commercial UWB systems: slow to walking speed in the warning zone, stop in the danger zone, vibrate the worker's tag ([comparison details](https://github.com/ljw22112/Edgeguard/blob/main/docs/site-compare.md)).

### When things go wrong (8,000 episodes, 34,644 conflicts)

The same fresh episodes under eight conditions: normal, 85 % and 70 % of alerts obeyed, bad network (300–600 ms, up to 40 % loss), the MEC app restarting and losing its state, noisy UWB (0.35–0.6 m), a dense floor (12 workers, 6 forklifts) and attentive drivers.

![Policies under exceptional conditions](https://raw.githubusercontent.com/ljw22112/Edgeguard/main/docs/img/large_eval_robust.png)

- **Previous policy**: Collisions (per 1,000 conflicts, 95 % CI): 30 (0.87 [0.61–1.24]); Close passes < 1.5 m: 190; Throughput, per scenario: 83.0–91.6 %
- **EdgeGuard v3.1**: Collisions (per 1,000 conflicts, 95 % CI): **0 (0 [0–0.11])**; Close passes < 1.5 m: **141**; Throughput, per scenario: **90.6–97.3 %**

Each collision we found on the way was traced to its cause and fixed in both the Python reference and the firmware, then checked again on new seeds: stop points that crept with position noise, a sidestep that led into a second truck, a WAIT lost in a server restart, an emergency stop released while the person still stood in front of the truck ([robustness](https://github.com/ljw22112/Edgeguard/blob/main/docs/robustness.md)). Why it stays safe, hazard by hazard, with the tests that are the evidence: [safety case](https://github.com/ljw22112/Edgeguard/blob/main/docs/safety-case.md).

### How it got here

- **v1.0, vibration-only alert (many-to-many site, 750 conflicts)**: Collisions: 100; Throughput: 61.7 %
- **WAIT → GO and STEP ASIDE**: Collisions: 4; Throughput: 86.0 %
- **+ learned policy, truck priority, stop points (1,000 episodes, 3,617 conflicts)**: Collisions: 0; Throughput: 97.3 %

*Limits: walkers and drivers follow models (nobody looks out unless stated), and the proximity-alarm settings are typical, not one product's. A board demo and a user study are planned; the CI evidence today is the simulator plus firmware-in-the-loop.*

---

## Why oneM2M, and why we would keep using it

- **A hub, not a database:** subscriptions replaced the broker and polling code we would otherwise have written.
- **Open by design:** alerts and near misses are standard resources. A WMS, a reporting tool or a camera vendor can subscribe without any integration work.
- **Security comes built in:** per-device ACPs with child-type restrictions gave us least privilege without writing an authentication layer.
- **One model from the device to the cloud:** SDT flexContainers, labels and SAREF semantics make devices discoverable (on ACME), and the same application code runs on Mobius and ACME.
- **Mobility as a service feature:** announcement, home records and portable subscriptions let a device change CSEs while applications keep receiving data.

Along the way we found and documented **7 interoperability issues** between CSEs, including a Content-Type parsing fix for ACME ([interoperability notes](https://github.com/ljw22112/Edgeguard/blob/main/docs/interop-notes.md)).

---

## Try it yourself

```bash
git clone https://github.com/ljw22112/Edgeguard && cd Edgeguard
pip install -r requirements.txt
scripts/acme.sh start in mn-a mn-b              # IN-CSE + two zone MN-CSEs with the EdgeGuard SDT domain
scripts/run_live_demo.sh                        # live demo, dashboard at http://localhost:9090/
python tools/handover_demo.py --failover        # CSE handover between zones
python tools/fl_demo.py                         # federated learning through oneM2M
python tools/agent_demo.py                      # AI safety agent over MCP
python tools/mobility_demo.py                   # MEC zone events -> network-triggered handover, signal strength
python tools/orchestration_demo.py              # deploy by intent across MEC hosts
python tools/swarm_demo.py                      # forklift swarm
python tools/model_delivery_demo.py             # canary, activate, roll back federated models
python tools/zone_demo.py                       # group fan-out + pollingChannel
python tools/sil_run.py                         # firmware-in-the-loop
```

Full Docker stack with Mobius: `cd deploy && docker compose --profile demo up -d`.

## Links

- Article on hackster.io: https://www.hackster.io/ahind012/edgeguard-stop-forklift-accidents-before-they-happen-e07309
- Code: https://github.com/ljw22112/Edgeguard
- Video: https://youtu.be/P2JI5ZG6PIg · narrated 3 min 31 s cut with the large-scale results: `results/edgeguard_final.mp4`
- Demo videos in the repository: `results/edgeguard_final.mp4`, `results/edgeguard_demo_v1.3.mp4`, `results/edgeguard_firmware_in_the_loop.mp4`
- oneM2M: https://www.onem2m.org · [oneM2M specifications](https://www.onem2m.org/technical/published-specifications) (TS-0001 architecture, TS-0004 protocols, TS-0023 SDT)
- ACME CSE: https://github.com/ankraft/ACME-oneM2M-CSE · KETI Mobius: https://github.com/IoTKETI/Mobius
- ETSI MEC: https://www.etsi.org/technologies/multi-access-edge-computing · ETSI MEC Sandbox: https://try-mec.etsi.org
