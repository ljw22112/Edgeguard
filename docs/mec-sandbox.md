# ETSI MEC integration and Sandbox

Integration with the MEC service APIs (013/012), a live connection to the public ETSI MEC Sandbox, and our warehouse scenario on a self-hosted Sandbox (AdvantEDGE).

[← README](../README.md) · [한국어](ko/mec-sandbox.md)

## ETSI MEC service integration

`edgeguard/mec_services.py` (client), `mec_mock/server.py` (test MEC platform, a subset of the ETSI data models).
Enabled via `mec_services` in `config/site.yaml`.

- **Location API (MEC 013)**: when a worker's UWB tag drops out for 0.5 s or more (a coverage hole behind a rack), the network-based
  location is fed to the tracker with noise as large as its reported accuracy. The dashboard shows it as a dashed circle labelled "MEC Location API".
- **RNIS (MEC 012)**: when PRB utilisation of the site cell is 80% or higher, the alert decision horizon is extended by 0.5 s and alert updates are sent twice as often.

Four collision scenarios, lead time of the first alert before contact (`results/mec_services.json`):

| Condition | Lead time (s) |
|---|---|
| UWB normal | 2.48, 2.37, 2.37, 2.27 |
| UWB dropout 3.0–6.5 s, no fallback | 2.07, 2.37, **0.87**, 2.27 |
| UWB dropout + Location API fallback | 2.38, 2.37, 2.28, 2.28 |
| Cell congestion (RNIS 90%) | 2.86, 2.77, 2.97, 3.17 |

Without the fallback, one run missed the 1 s target; with the fallback enabled, lead times returned to normal levels.

## Self-hosted MEC Sandbox + warehouse scenario (AdvantEDGE v1.9.2)

The public Sandbox only offers its built-in scenarios, so we installed AdvantEDGE v1.9.2, the open-source base of the ETSI MEC Sandbox, on a Hyper-V VM
on a team PC (Ubuntu 22.04, Kubernetes 1.27) and deployed **our own warehouse scenario** (`scenarios/edgeguard-warehouse.json`).
The installation procedure and fixes for image paths that are broken as of 2026 are in `deploy/sandbox-host/` (README and scripts).

Path: AdvantEDGE Location API → MEC-IPE → Mobius resource → subscription notification → MEC app → alert (`results/sandbox_selfhosted_live.json`)

| Item | Result (2026-10-08, 2 min) |
|---|---|
| Verdict | **CONNECTED** |
| UE classification (by peak speed) | 2 forklifts · 4 workers — matches the scenario |
| Location updates received | 828, 6.0 /s, 0 unregistered UEs |
| Worker–forklift pairs evaluated | 8 |
| **Alerts** | **70** |

## Live ETSI MEC Sandbox integration (try-mec.etsi.org)

From a team laptop (Galaxy Book2 Pro, 8 GB RAM, Windows 11, Docker Desktop) we deployed a network scenario on the public ETSI MEC Sandbox and connected the EdgeGuard stack.
Path: **Sandbox Location API → MEC-IPE → Mobius resource → subscription notification → MEC app** (the app does not call the MEC API directly).

```
cd deploy
docker compose up -d --build
docker compose run --rm sandbox-setup https://try-mec.etsi.org/<sbx-id>/mep1/location/v3   # discover API and UEs → sandbox/overrides.yaml
docker compose --profile sandbox up -d --force-recreate                                   # start MEC-IPE, MEC app in Sandbox mode
docker compose run --rm sandbox-check                                                     # sandbox/report.json, CONNECTED verdict
```

| Item | Result (2026-10-07) |
|---|---|
| Verdict | **CONNECTED** |
| UE / cell containers created by MEC-IPE | 3 / 10 |
| MEC app subscriptions to IPE | 13 |
| Location updates received | 32, 2.0 /s, 0 unregistered UEs |
| UEs being tracked | 2 |

- The dashboard lists the Location API as v2, but only `location/v3` actually responds. `sandbox_probe` tries both versions.
- Sandbox UEs move at city scale (hundreds of metres apart), so no worker–forklift pair came within evaluation range, hence 0 alerts.
  Collision-risk performance is evaluated with our own warehouse scenario below.
- This scenario provides no cell load (layer2_meas), so the congestion margin adjustment stayed off.
- To leave Sandbox mode: delete `deploy/sandbox/overrides.yaml`, then `docker compose up -d --force-recreate mec`.

## Alignment with the hackathon MEC Sandbox (via oneM2M resources, MEC-IPE)

Organiser guidance (2026-10-06): for an AE connected to a CSE, the CSE handles MEC host registration on its behalf; UE locations are
written **as CSE resources by the MEC-IPE**; and going through oneM2M resources is recommended over calling MEC APIs directly. Teams are also encouraged to **build their own scenario** with their own maps and trajectories.
Changes made accordingly:

- **Location source = CSE (default)**: `mec_services.location_source: cse`. The MEC app periodically discovers (`fu=1&ty=3`) and subscribes to the
  `<ipe.root>/location/*` and `<ipe.root>/rnis/*` containers, and uses the notification content (MEC 013 UserInfo / MEC 012 cellInfo) as is.
  `direct` (calling the API directly) is kept as an option for comparison and exploration. No app registration (MEC 011) is performed.
- **MEC-IPE stand-in** `tools/mec_ipe.py`: since TR-0086 is not yet published, it fills the same role — reading the MEC APIs and writing to the CSE — in the same format.
  The resource structure is configurable, so once the real IPE is published only the paths need to be matched.
- **Sandbox scenario** `scenarios/edgeguard-warehouse.yaml` (`tools/sandbox_scenario.py`): a 40×24 m warehouse, 2 private 5G small cells, 1 MEC host,
  2 forklifts and 4 workers moving along GeoJSON paths at constant speed and meeting periodically. Passes AdvantEDGE 1.8.0 data model schema validation.
  `mec_mock` replays the same scenario (`MEC_MOCK_SCENARIO=...`).
- **UWB is the primary source, MEC location is secondary**: when tag data arrives within 0.5 s the MEC location is discarded; when the tag drops out, MEC location is accepted with noise as large as its accuracy.
  As the results below show, 1 Hz, metre-level network location alone is insufficient for collision avoidance, so we consider devices writing their own location to fall under the "exception" described in the guidance.
- Fixed alert debouncing to be time-based (0.2 s) so it works with sparse locations such as 1 Hz (10 Hz results unchanged: closed loop 19/180).

End-to-end test `python tools/sandbox_e2e.py` — scenario → MEC → (IPE → Mobius) → MEC app → alert, 120 s, scored against ground truth from the scenario trajectories, 16 contacts:

| Location source | Update | Location error / reported accuracy | Alert ≥1 s before | Median lead time | False alarms | Location→alert p50 |
|---|---|---|---|---|---|---|
| CSE (MEC-IPE) | 1 s | 0 / 1 m | 62.5 % | 1.26 s | 4 | 114 ms |
| MEC API direct | 1 s | 0 / 1 m | 62.5 % | 1.44 s | 4 | 169 ms |
| CSE (MEC-IPE) | 1 s | 0 / 0.3 m | 93.8 % | 2.03 s | 2 | 156 ms |
| CSE (MEC-IPE) | 1 s | 1 m / 1 m | 68.8 % | 2.23 s | 7 | 119 ms |
| CSE (MEC-IPE) | 1 s | 3 m / 3 m | 43.8 % | 4.05 s | 12 | 178 ms |
| CSE (MEC-IPE) | 0.1 s | 0 / 1 m | 93.8 % | 2.13 s | 5 | 87 ms |
| *(reference) UWB tag* | *0.1 s* | *0.15 m* | *100 % (online sim)* | | | *~70 ms* |

- Going through the CSE and calling the API directly give the same detection rate with similar latency → using the recommended path (CSE) by default costs nothing.
- Performance is determined not by the path but by **location update rate and accuracy**. With realistic network errors of 1–3 m, detection drops from 69 to 44 % and false alarms increase,
  so the safety function needs UWB (0.1 s, 0.15 m), and MEC location is best suited to filling tag coverage holes and zone-level decisions.
