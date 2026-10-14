# EdgeGuard on the MEC platform APIs: Mp1, AMS, geofences

[← README](../README.md) · [한국어](ko/mec-platform.md) · [Mobility](mobility.md) · [TR-0077 mapping](estimed-mapping.md)

Besides Location (MEC 013) and RNIS (MEC 012), a MEC application talks to its platform. EdgeGuard uses three more ETSI MEC APIs. The clients are in [`edgeguard/mec_platform.py`](../edgeguard/mec_platform.py) and the MEC-IPE ([`edgeguard/mobility.py`](../edgeguard/mobility.py)); the platform side is in [`mec_mock/platform.py`](../mec_mock/platform.py).

| API | What EdgeGuard does with it |
|---|---|
| **MEC 011 Mp1**: app enablement, service management | Each instance confirms `READY` and registers the `edgeguard-safety` service. Its `transportInfo.implSpecificInfo.oneM2M` names the zone's CSE and the AE, so a MEC app that only speaks Mp1 finds the oneM2M resources. The MEC-IPE is pointed at the **Location service it discovers over Mp1**, not at a hard-coded URL. Service availability notifications report other instances coming and going. |
| **MEC 021 AMS**: application mobility | Each zone's instance registers the forklifts it serves (`APP_MOBILITY_PERMITTED_WITH_CONTEXT_TRANSFER`) and subscribes to mobility procedures. AMS becomes a **trigger authority for the oneM2M CSE handover**, next to device location, CSE availability and MEC zone events. |
| **MEC 013 area and distance subscriptions** | Requested by oneM2M applications through `MEC-IPE/requests` (`area_subscribe`, `distance_subscribe`). Events go to `MEC-IPE/geoEvents` as `{kind, ue / ues, event, mec_ts, ipe_ts}`. Area = a circular geofence (e.g. a loading dock). Distance = "worker and forklift within 5 m", computed by the network from its own positioning, independent of the tags. |

## AMS-driven handover

```
forklift_01 crosses into zone B (MEC host mep-b)
 AMS ──INTERHOST_MOVEOUT_TRIGGERED(target edgeguard-b, commInterface)──▶ edgeguard-a
 edgeguard-a ──safety context (last sample, risk state)──▶ edgeguard-b          (target's commInterface)
 edgeguard-a ──network_trigger("B", reason=ams)──▶ oneM2M twin: make-before-break to MN-CSE B
 edgeguard-a ──PUT USER_CONTEXT_TRANSFER_COMPLETED──▶ AMS
 AMS ──INTERHOST_MOVEOUT_COMPLETED──▶ edgeguard-a
```

The application context (MEC side) and the device twin (oneM2M side) move together, in one procedure, at the moment the platform decides the UE has moved hosts.

## Demo (CI on every commit)

```bash
scripts/acme.sh start in mn-a mn-b
python tools/mec_platform_demo.py     # 10 checks -> results/mec_platform.json
```

Scenario: [`edgeguard-two-zones.yaml`](../scenarios/edgeguard-two-zones.yaml) with `MEC_MOCK_HOSTS=zoneA=mep-a,zoneB=mep-b`. The forklift drives A → B → A at 4 m/s and passes worker_01 twice.

| Check | Result |
|---|---|
| Mp1: both instances READY, `edgeguard-safety` discoverable on both hosts with CSE ID and AE | pass |
| Mp1: Location and AMS services discovered; the IPE uses the discovered Location endpoint | pass |
| Mp1: availability notifications ADDED × 2, REMOVED on deregistration | pass |
| AMS: move-out A → B, then B → A, each to the other host's instance | pass |
| AMS: safety context delivered to the target's commInterface (≈ 2–20 ms) | pass |
| AMS as trigger: oneM2M twin moved A → B → A, reason `ams` | pass |
| AMS: `INTERHOST_MOVEOUT_COMPLETED` after the transfer report | pass |
| Area: ENTERING inside / LEAVING outside the 6 m geofence, within one GIS update (2 m at 4 m/s) | pass (4.4 m / 7.6 m from centre) |
| Distance: worker_01 and forklift_01 within 5 m; ground-truth gap 3.8–4.0 m | pass |
| MEC 013 subscriptions removed through oneM2M | pass |

Geofence and distance events reach oneM2M about 10 ms after the platform raises them.

Unit tests: [`tests/test_mec_platform.py`](../tests/test_mec_platform.py) (Mp1 filters, AMS same-host moves, instance filters, edge crossing).

## Limits

- The platform is `mec_mock`, a subset of the ETSI data models. The AMS procedure follows MEC 021 (registration, `MobilityProcedureNotification`, `contextTransferState`), but context transfer between instances is EdgeGuard's own small JSON. MEC 021 leaves that format to the application.
- Mp1 runs without the platform's OAuth; a real MEC platform would issue tokens at instantiation.
- These subscription paths have not been run on the ETSI MEC Sandbox yet; [`tools/mec_events_check.py`](../tools/mec_events_check.py) checks the zone-event path on a real platform.
