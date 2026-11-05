# EdgeGuard and the TR-0086 developer guide

[← README](../README.md) · [한국어](ko/tr0086-mapping.md) · [ESTIMED / TR-0077 mapping](estimed-mapping.md)

The TR-0086 developer guide (oneM2M + ETSI MEC deployment, shared with the hackathon teams in late October 2026) walks through a co-deployed platform: pick a deployment option, bring the platform up (5.2), register devices (5.3), run an AE as a MEC app (5.4), and, as optional extras, handover (5.5) and location-aware devices (5.6), with oneM2M building blocks in Annex A. EdgeGuard was built before the guide was released; this page maps each step to where EdgeGuard does it, and what is checked in CI.

## Deployment option (5.2.2): C, per zone

| Option | In the guide | EdgeGuard |
|---|---|---|
| A | MEC-IPE as a MEC app, registered directly to the cloud IN-CSE | the cloud tier: home records, announcements, federated-learning coordinator, orchestrator, AI agent |
| B | MN-CSE as a MEC app on a separate edge node + MEC-IPE | also runs: the MEC app works unchanged against a CSE on another node (`sil.yaml`, ETSI Sandbox runs) |
| **C** | **MN-CSE as a MEC app, co-located on the MEC host** | **adopted**: each zone's MEC host runs the zone MN-CSE (ACME), the EdgeGuard MEC app and the MEC-IPE |
| D | MN-CSE as a MEC service | not used |

**Why C:** a collision warning has a 1-3 s budget. With the CSE, the decision and the MEC data on the same host, the median alert latency is 25 ms (85 ms cloud-only), worker trajectories never leave the zone, and each zone keeps working on its own if the link to the cloud fails.

**Where it runs (5.2.4.2):** we did not install the local MEC Sandbox (STF_685 branch). The MN-CSEs are our own ACME instances (the guide's "your own MN-CSE" path), MEC 013 / 012 / 011 / 021 come from `mec_mock` playing AdvantEDGE-style scenarios, and the polling path also ran against the public ETSI MEC Sandbox ([mec-sandbox.md](mec-sandbox.md)).

## Steps

| TR-0086 | What the guide asks for | EdgeGuard | Checked |
|---|---|---|---|
| **5.2** Platform bring-up | IN-CSE up; MEC platform and MEC 011 API verified; MN-CSE / MEC-IPE started and registered | `scripts/acme.sh start in mn-a mn-b`: IN-CSE + two zone MN-CSEs, each MN-CSE registered over Mcc (`registrarCse*` keys in `scripts/acme-mn-*.ini`). MEC 011 Mp1: service registration and discovery ([mec-platform.md](mec-platform.md)) | CI on every commit; `mec_platform_demo.py` 10/10 |
| **5.3** Device registration | onboard a device / AE to the option's CSE, publish telemetry | each tag and forklift module registers its own AE with an ACP; telemetry as an SDT flexContainer twin (`egs:wrkTg`, `egs:frkMe`) or contentInstances; discovery by label onboards a new tag without a device list ([data-model.md](data-model.md)) | ≈ 9 s onboarding in CI; 8/8 access checks on Mobius; unmodified ESP32 firmware over HTTP, MQTT and mutual TLS |
| **5.4** AE as a MEC app | package and run the AE as a managed MEC application | the EdgeGuard MEC app is a container (`deploy/edge-app`), deployed by one oneM2M intent resource: discover host → select → deploy → Mp1 registration → device ACPs → monitor → re-place on host crash ([orchestration.md](orchestration.md)) | `orchestration_demo.py` 11/11; re-placed in ≈ 2-3 s |
| **5.5** Handover *(optional)* | move a device between MN-CSEs without losing continuity (MEC 012 RNIS) | make-before-break twin migration with state, ACP, portable subscriptions, announcement and home record; triggered by a MEC 013 zone event, by RNIS signal strength (RSRP / RSRQ in `egs:rdLnk`) or by MEC 021 AMS ([handover.md](handover.md), [mobility.md](mobility.md)) | `handover_demo.py` 10/10 + 8/8; zone-event handover 1.5-8 ms, 0 samples lost |
| **5.6** Location-aware devices *(optional)* | network location (MEC 013) or device position | both: MEC 013 fixes and zone / area / distance events as oneM2M resources (`egs:ueLoc`, `MEC-IPE/geoEvents`), and the device's own UWB position in its twin | `mobility_demo.py` 10/10; geofence / distance event → oneM2M ≈ 10 ms |

## Annex A building blocks

| Building block | EdgeGuard |
|---|---|
| containers | per-device data, alerts, near misses (`maxNrOfInstances` bounds the history) |
| ACPs | one per device AE; the MEC app may only create subscriptions in a twin (`chty`) |
| subscriptions | positions → MEC app, alerts → tags and forklift modules, MEC events → apps |
| groups | one per zone: a DANGER alert is one request to `<group>/fopt`; forklift swarm plans |
| telemetry | positions up to 10 Hz (2 Hz when nothing is near) |
| latest retrieval | `<container>/la` ([`edgeguard/onem2m.py`](../edgeguard/onem2m.py)) |
| downlink commands | WAIT / STEP ASIDE / GO to the tag; speed plans and stop points to the forklift module, each confirmed in the device's `status` container |

## Beyond the guide

TR-0077 clause 7 items the guide does not cover step by step, all in CI: federated learning over oneM2M (TR-0084) with model delivery and rollback, a forklift swarm (7.4), MEC 021 application mobility, and an AI agent over MCP ([estimed-mapping.md](estimed-mapping.md)).
