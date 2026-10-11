# Mobility through ETSI MEC: zone events, signal strength, network-triggered handover

[← README](../README.md) · [한국어](ko/mobility.md) · [TR-0077 mapping](estimed-mapping.md)

The polling MEC-IPE ([`tools/mec_ipe.py`](../tools/mec_ipe.py)) copies UE positions into the CSE. The event-driven MEC-IPE in [`edgeguard/mobility.py`](../edgeguard/mobility.py) works in both directions.

**MEC → oneM2M.** It subscribes to MEC 013 zone / user location events and MEC 012 MeasRepUe reports, and writes them into oneM2M as they happen:
- zone events become `contentInstance`s in `MEC-IPE/zoneEvents`
- each UE's location and radio link are kept in SDT flexContainers, with history

**oneM2M → MEC.** A oneM2M application creates a `contentInstance` in `MEC-IPE/requests`:
- `zone_subscribe`
- `radio_subscribe`
- `location`
- `unsubscribe`

The IPE calls the MEC API and answers in `MEC-IPE/responses` with the same `rqi`. Applications get MEC services without speaking the MEC APIs or holding MEC credentials.

```
MEC-IPE                    AE (IN-CSE)
  requests                 CNT        readers may only create contentInstances (chty 4)
  responses                CNT        readers read / subscribe
  zoneEvents               CNT        {ue, zone, event ENTERING/LEAVING, poa, mec_ts, ipe_ts}
  ue_<address>             egs:mecUe  lbl egs:mec/ue, egs:id/<address>
    location               egs:ueLoc  lat, lon, accuracy, zoneId, accessPointId, time   (mni 50)
    radio                  egs:rdLnk  servingCell, rsrp, rsrq, neighbourCell, neighbourRsrp, time (mni 100)
```

The SDT classes are defined in [`config/onem2m/edgeguard.fcp`](../config/onem2m/edgeguard.fcp), next to the device classes ([data-model.md](data-model.md)). RSRP and RSRQ use the 3GPP TS 36.133 reporting indices (dBm = index − 141).

## Network-triggered handover

A [`HandoverClient`](../edgeguard/handover.py) with `trigger="network"` ignores its own position and follows the MEC platform instead:
1. The MEC platform reports "forklift_01 ENTERING_AREA_EVENT zoneB".
2. The MEC-IPE writes it into `MEC-IPE/zoneEvents`.
3. The device, subscribed to that container, calls `network_trigger("B")`.
4. The twin is prepared on zone B's MN-CSE in the background and switched on the next sample, with the same make-before-break procedure as [location handover](handover.md).

This is the ESTIMED trigger authority "MEC network or radio system".

## Demo and measurements (CI on every commit)

```bash
scripts/acme.sh start in mn-a mn-b
python tools/mobility_demo.py       # 10 checks -> results/mobility.json
python tools/mobility_map.py        # docs/img/mobility_map.html (+ .png)
```

The scenario is [`scenarios/edgeguard-two-zones.yaml`](../scenarios/edgeguard-two-zones.yaml), in the AdvantEDGE layout:
- two zones, each with one 5G small cell and one MN-CSE
- forklift_01 drives A → B → A at 4 m/s

`mec_mock` plays it with a 0.25 s GIS period, detects zone changes and sends the notifications. RSRP uses log-distance path loss (−44 dBm at 1 m, exponent 3.5).

| | CI run |
|---|---|
| Handovers | A → B, then B → A, both triggered by the network |
| Service interruption | 1.5–8 ms per handover |
| Samples lost | 0 |
| MEC zone event → contentInstance in oneM2M | median 15–45 ms |
| MEC request through oneM2M (subscribe) | ≈ 20 ms round trip |
| Radio at the handover | the new cell is received at least as strongly as the old one (≈ −90 dBm each at the boundary) |

**Checks:**
- zone subscription via oneM2M (2 MEC subscriptions)
- location via oneM2M
- ENTERING zoneB, then zoneA, in oneM2M
- handovers A → B → A by the network
- 0 lost
- interruption < 300 ms
- serving cell cellA → cellB → cellA in `egs:rdLnk`
- new cell at least as strong at each handover
- MEC twins discoverable by label
- MEC subscriptions removed through oneM2M

![mobility map](img/mobility_map.png)

The map (HTML, with a time slider) shows the forklift on the floor plan, its serving CSE, the last MEC zone event, the RSRP of both cells and the handovers. The RSRP chart below it shows the cross-over at the zone boundary.
