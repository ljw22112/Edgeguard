# Site features

Blind-corner awareness, D2D frame authentication, monitoring, near-miss analysis, camera node, access control, dashboard and safety report.

[← README](../README.md) · [한국어](ko/site-features.md)

## Blind-corner awareness (site map)
When `sitemap.obstacles` (rectangles such as racks) is set in `config/site.yaml`, the MEC app checks line of sight for every pair
(`edgeguard/sitemap.py`, Liang–Barsky line clipping). Pairs that cannot see each other get a +0.5 m safety radius and a debounce of 1, so they are alerted earlier,
and the dashboard draws them with a "no line of sight" line. 320 simulation runs including the effect of people avoiding each other once they are in view (12 m sight range)
(`sim/occlusion_eval.py` → `results/occlusion_eval.json`):

| 80 blind-corner cases | Collisions | False alarms |
|---|---|---|
| No map | 17 | 39 |
| Map: time margin +1 s | 22 | 48 |
| **Map: radius +0.5 m, debounce 1** | **11** | 57 |

Results in open areas are unchanged (7 collisions), and the extra false alarms occur only at blind corners. The time-margin approach made things worse, so it was not adopted.

## D2D frame authentication (HMAC)
Each ESP-NOW frame (66 B, limit 250 B) carries an 8-byte HMAC-SHA256 tag and a per-sender sequence number
(`firmware/common/d2d_auth.h`, SHA-256 with no external library). The receiver checks the tag with a constant-time comparison and
drops numbers outside the latest 50 for that sender as well as numbers already received — blocking forged "release stop" frames and replayed stale alerts.
Relays repeat the signed original 3 times unchanged, so relay devices do not need the key (the site key is pre-distributed with the firmware).
The C++ implementation is cross-checked byte for byte against the Python reference implementation (`edgeguard/d2d_auth.py`) (`tests/test_d2d_auth.py`).

## Monitoring (Prometheus + Grafana)
Prometheus scrapes the MEC app's `/metrics` (samples · alerts · CSE write success/failure/drop · queue · input errors · congestion · near misses · HA leader) every 2 s,
and the dashboard is provisioned in Grafana automatically. Five operator alert rules: CSE write failures, sample gaps, no leader, near miss without alert, queue backlog.
```
docker compose --profile monitoring up -d         # Grafana http://localhost:3000 · Prometheus http://localhost:9095
```
CI verifies scraping, rule loading and dashboard provisioning (`deploy/check_monitoring.py`). Even on a laptop (8 GB) the two containers together use only a few hundred MB.

## Near-miss analysis
Alerts are *predictions*; near misses are *what actually happened*. An approach in which the measured distance between a moving forklift and a worker falls below 2 m counts as one near miss,
recorded at the moment of closest approach (`edgeguard/nearmiss.py`). Whether an alert was issued beforehand (`alerted`) is stored along with a 1 m grid heat map,
and cells with many events get cause-specific recommendations — blind corner (add to map · convex mirror), high-speed traffic (speed-limit zone), close approach without alert (check tags · anchors),
frequent crossings (separate walkways). Viewable via `<AE>/nearmiss` (oneM2M), the `/nearmiss` API, the dashboard heat map and `tools/safety_report.py`.
"Near misses without an alert" are gaps in the system, so they are counted separately and also raised as operator alerts.

## Camera node (untagged workers)

`devices/camera_node.py`: detects people with YOLOv8n, converts the foot position (bottom centre of the box) to floor coordinates (m) via homography, and
writes them to `camera_01/detect`. The MEC app treats detections within 1.5 m of a tag track as the same person and turns the rest into `untagged_N` tracks,
issuing forklift slowdown and beacon-light alerts (vibration is skipped since there is no tag to send it to).

- Inference time (2-core CPU, YOLOv8n): 113 ms at 640 px, 39 ms at 320 px → 5 Hz feasible. Faster on Jetson.
- In scenarios with workers visible only to the camera (no tag), first-alert lead times were 2.27 s and 1.67 s.
- Run: `EDGEGUARD_YOLO=yolov8n.pt python devices/camera_node.py --source 0` (calibration points in `camera.calib_points`).

## Access control (per-device ACP)

Each device registers its own AE (v1.3), and that AE's ACP allows only the device itself and the MEC app (retrieve · subscribe).
`risk` · `alert` · `control` · `nearmiss` are written only by the MEC app; devices can only read them. On every commit, CI verifies the following against Mobius (`deploy/check_acl.py`, 8/8 passing):

| Attempt | Result |
|---|---|
| SWorker01 → write own `worker_01/location` | Allowed |
| SWorker01 → write `forklift_01/motion` (spoofing) | Denied 403 / 4103 |
| SWorker01 → write `alert` (fake alert) | Denied 403 / 4103 |
| Unregistered SIntruder → write `worker_01/location` | Denied 403 / 4103 |
| Device AEs · MEC AE · MEC subscriptions exist | Confirmed |

## Safety report and demo video

- `python tools/safety_report.py --config config/site.yaml` → `results/safety_report.html`:
  builds a 1 m risk-zone heat map, the zones and pairs with the most alerts, and improvement suggestions from the alert history stored in the CSE.
- `python tools/record_demo.py --config config/site.yaml` → `results/edgeguard_demo.mp4`:
  opens the dashboard and records while replaying 4 scenes (crossing collision, turning forklift, untagged worker, UWB coverage hole + Location API).

## Control dashboard

Start the MEC app and open `http://<mec-host>:9090/` in a browser.
It refreshes every 0.2 s with worker and forklift positions, 3-second predicted paths, predicted closest-approach points (✕ with time remaining), safety radii, per-pair risk metrics and the alert log.
Each worker's tag state (**WAIT** red · **STEP ASIDE** orange · **GO** green) is shown on the map. It follows the tag by running the same state machine as the tag (`edgeguard/worker_cue.py`) on the signals the MEC app sent to it.
