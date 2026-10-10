# Resilience: network failures, high availability and scale

How the safety function keeps working when the network drops or a server dies, with measured results (v0.7 → v1.0).

[← README](../README.md) · [한국어](ko/resilience.md)

## v1.0: MEC app high availability (active-standby)
Two MEC app instances each receive the same samples through their own subscriptions and keep their tracking state warm, but **only the leader** writes alerts, heartbeats and risk summaries.
Leadership is decided by a lease at `<AE>/mec_lease` on the CSE (renewed every 0.2 s; if renewal stops for 0.6 s, the standby takes over), and the new leader sends a
heartbeat immediately (`edgeguard/ha.py`). Each instance judges lease expiry on its own monotonic clock, so device clocks do not need to agree.
```
MEC_HA=1 docker compose --profile ha up -d        # mec(9090) + mec2(9092)
python3 deploy/check_ha.py                        # kill the leader; measure takeover time and heartbeat gap
```
On every run, CI kills the leader and checks that the heartbeat gap stays below the forklift's threshold for switching to local rules (2 s).
CI measurement (GitHub runner): **takeover 0.73 s, maximum heartbeat gap 1.0 s** (the same as the normal period) — when the leader dies, devices never notice a loss of MEC.

## v0.9: device-to-device cooperation (D2D) — like autonomous cars in a tunnel

Just as autonomous cars in a tunnel talk to each other, devices exchange data directly when the network drops or some of them enter a radio coverage hole (behind metal racks).

1. **State broadcast**: every device broadcasts its own state `{x, y, vx, vy, mecOk}` directly over ESP-NOW at each reporting interval (no access point needed, a few ms).
   Position keeps coming from the UWB anchors independently of the network, so broadcasting continues when the network is down. On a real 5G site the same frame goes over sidelink (PC5).
2. **Local 2D prediction**: when MEC has been silent for more than 2 s and the peer's state is fresh (within 0.5 s), the device decides using
   the **constant-velocity closest point of approach (CPA)** instead of v0.8's distance and closing speed. A worker walking alongside is no reason to stop; only a worker on a crossing path is. If peer state stops arriving, the device falls back to the v0.8 rules.
3. **Relay (partial failure)**: a device that can still hear MEC forwards MEC alerts and heartbeats to a neighbour that has announced `mecOk = 0` (1 hop, repeated 3 times),
   and uploads that neighbour's position to the CSE on its behalf. A device in a coverage hole behaves as if it were connected.

`sim/failsafe_eval.py` (180 true collisions, with per-device link and coverage-hole conditions added; `results/failsafe_eval.json`, figure `results/failsafe_eval.png`):

| Behaviour under failure (collisions · throughput) | Normal | MEC down 8 s | Network cut | Forklift in dead zone 8 s | Worker in dead zone 8 s |
|---|---|---|---|---|---|
| v0.7: hold → stop | 20 / 77 % | 85 / 68 % | 180 / 100 % | 52 / 68 % | 66 / 83 % |
| Reference: stop all forklifts | 10 / 67 % | 25 / 42 % | 2 / 18 % | 5 / 43 % | 52 / 72 % |
| v0.8: local UWB | 19 / 77 % | 40 / 59 % | 3 / 54 % | 34 / 60 % | 51 / 82 % |
| D2D state exchange only (no relay) | 23 / 76 % | 35 / 59 % | 2 / 57 % | 39 / 60 % | 38 / 81 % |
| **v0.9: D2D + relay (adopted)** | **23 / 76 % | 35 / 59 % | 2 / 57 % | 19 / 76 % | 16 / 76 %** |

- Adding **v1.1 (worker WAIT/GO)** on the same encounters gives normal 23 → 0, MEC down 8 s 36 → 11, forklift / worker dead zone 17 · 16 → 1 · 1
  ([Risk engine and evaluation](risk-and-evaluation.md), "v1.1", `results/failsafe_eval_hold.json`). The table below shows results up to v1.0.
- **Biggest difference in dead zones**: worker dead zone 66 → 16 and forklift dead zone 52 → 19, while throughput stays at 76 %, the same as normal (stopping all forklifts gives 43 %).
  Without the relay (state exchange only) the counts are 38 and 39, so most of the gain comes from the relay.
- Under a full network cut or MEC outage it is similar to or slightly better than v0.8 (2 vs 3, 35 vs 40). Differences under normal conditions and short restarts are within sampling error.
- **When the D2D link degrades** (`sim/d2d_sensitivity.py`, `results/d2d_sensitivity.json`, collisions / 180):

| D2D condition | Forklift dead zone | Worker dead zone | MEC down 8 s | Network cut |
|---|---|---|---|---|
| assumed (10 % loss, 40 m) | 19 | 16 | 35 | 2 |
| 30 % frame loss | 21 | 19 | 34 | 2 |
| 60 % frame loss | 26 | 20 | 34 | 3 |
| range 15 m | 19 | 20 | 36 | 2 |
| 60 % loss + 15 m | 24 | 17 | 36 | 4 |

  At first, relay frames were sent only once, and at 60 % frame loss the forklift dead zone gave 48 collisions — **worse than with no relay at all (34)**
  (sporadic heartbeats kept local decisions switched off while alerts were missed). Repeating relay frames 3 times fixed it (26).
- The rules live in both `edgeguard/device_policy.py` and `firmware/common/device_policy.h` (`cpaCap`) and are checked with cross-implementation and mutation tests.
  The frame format and relay bookkeeping are in `firmware/common/d2d.h` (size ≤ 250 B; reception is handed off to a queue from the Wi-Fi task),
  and both sketches include ESP-NOW send/receive and relay (they pass PC type checks). A device in a coverage hole attempts direct transmission only every 2 s so that HTTP does not block the loop.
- Limitations: ESP-NOW must use the same channel as the AP, and real radio loss and range must be verified on hardware. Message authentication (forged frames triggering stops) is not addressed.

## v0.8: fallback for network failure — graceful degradation (MEC prediction → local UWB → stop)

The v0.7 failsafe only protected pairs **MEC had already alerted on**. A worker who appeared while MEC or the network was down was seen by no one,
so if the network was down for the whole encounter, all 180 true collisions happened. v0.8 moves the decision down to the forklift during failures.

1. **Normal: MEC prediction** — sees the whole site and predicts when a collision will happen (few false alarms, long lead time).
2. **MEC silent for 2 s or more: local UWB** — the forklift module ranges directly to the worker tag over UWB (the DW1000 two-way ranging it does with anchors, now aimed at the tag),
   and decides using distance and **TTC computed from closing speed (rate of change of distance)**: stop if within 3 m or TTC below 2 s; 1 m/s if within 6 m or TTC below 4 s.
   Two-way ranging gives both sides the distance, so **the worker tag also vibrates under the same rule** and the worker stops.
3. **Restricted and MEC still silent: stop** (v0.7 rule kept). As soon as MEC is heard again, control returns to MEC prediction.

`sim/failsafe_eval.py`, 330 high-speed closed-loop encounters (180 true collisions), same encounters and same network conditions (`results/failsafe_eval.json`, figure `results/failsafe_eval.png`; re-measured with the v0.9 simulator):

| Behaviour when silent (collisions · throughput) | Normal | Restart 1.7 s | Restart + 20 % loss | MEC down 8 s | Network cut (whole encounter) |
|---|---|---|---|---|---|
| v0.7: hold → stop after 2 s if restricted | 20 / 77 % | 40 / 75 % | 41 / 74 % | 85 / 68 % | 180 / 100 % |
| Reference: stop all forklifts after 2 s of silence | 10 / 67 % | 28 / 66 % | 31 / 64 % | 25 / 42 % | 2 / 18 % |
| Local distance zones only | 20 / 77 % | 43 / 75 % | 43 / 73 % | 62 / 60 % | 37 / 62 % |
| Local distance + closing speed (TTC) | 19 / 77 % | 43 / 74 % | 41 / 72 % | 60 / 59 % | 30 / 60 % |
| **v0.8: local TTC + tag vibration** | **19 / 77 % | 43 / 74 % | 43 / 72 % | 40 / 59 % | 3 / 54 %** |

- **Even with the network completely cut, collisions drop 180 → 3**, and forklifts keep working at 54 % (MEC down 8 s: 85 → 40). "Stop all forklifts" gives 2 collisions but throughput falls to 18 %.
- Under normal conditions and short restarts the difference from v0.7 is within sampling error (local rules only engage when MEC has been silent for more than 2 s).
  We swept the engagement time over 1.3 / 2.0 / 3.0 s and chose 2.0 s.
- Using closing speed always beat distance-only zones (the commercial UWB approach), and vibrating the worker tag as well always beat stopping only the forklift.
- The rules live in both `edgeguard/device_policy.py` and `firmware/common/device_policy.h` (`LocalGuard`), and a test compares the two implementations
  on random distance and heartbeat sequences (mutation tests confirm it catches constant changes).
- **Direct ranging with no extra protocol**: the forklift module's DW1000 is brought up as a *moving anchor* (short address `0x20NN`). In its usual
  anchor ranging round, the worker tag also ranges to the forklift anchor, and because the ranging is two-way the forklift learns the same distance
  (`firmware/forklift_module` `onPeerRange`, `firmware/worker_tag` `onNewRange`). The tag does not use this distance for positioning, only for the local rules.
  arduino-dw1000 ranges to at most 4 devices by default, so `MAX_DEVICES` is raised to 8 (4 fixed anchors + 4 forklifts). The forklift's own position comes from a separate tag board
  (one DW1000 cannot act as anchor and tag at the same time).
- **Robustness when assumptions get worse** (`sim/peer_ranging_sensitivity.py`, `results/peer_ranging_sensitivity.json`, collisions / 180 true collisions; v0.7 gives 75 / 180):

| Direct ranging condition | MEC down 8 s | Network cut |
|---|---|---|
| assumed (10 Hz, 10 % miss, 0.1 m, 30 m) | 31 | 3 |
| 5 Hz (crowded channel) | 31 | 4 |
| 2 Hz (very crowded) | 41 | 7 |
| 40 % missed rounds (NLOS) | 31 | 2 |
| noise 0.3 m | 28 | 3 |
| NLOS bias +0.5 m | 34 | 5 |
| max range 12 m | 28 | 3 |
| all bad (5 Hz, 40 %, 0.3 m, +0.5 m, 12 m) | 47 | 23 |

  To stay usable even when the ranging rate drops to 2 Hz (many tags crowding the channel), the closing-speed window is set to 1.5 s and range validity to 1.2 s
  (with 0.6 / 0.5 s, network-cut collisions at 2 Hz were 41 → 7). Even with every condition bad at once, collisions are far fewer than v0.7 (180): 23.
- Remaining limitation: the radio ranging itself must be verified on hardware (ranging rate, multi-tag collisions, NLOS from metal racks).

## v0.7: resilience and scale

### Scale: adaptive reporting rate
Every sample costs one write on the CSE plus one notification to the MEC app, so the total sample count across the site is what limits scale.
`edgeguard/rate_control.py`: only devices with a peer nearby or approaching report at 10 Hz; the rest report at 2 Hz.
The test is `d < 8 m + 2 s × (sum of both speeds + 0.5)` or `reaches within 5 s at the actual closing speed`, with a 3 s hold and 20 % margin applied only when slowing down.
Commands go to `<ae>/control` and the full table is resent every 1 s, so lost commands self-heal. A device returns to 10 Hz if it receives no command for 6 s.

Online simulation (`results/online_robustness.json`, conservative setup with devices, Mobius, DB and MEC app all on one 2-core PC):

| Case | Devices | Collisions (without → with) | Timely detection | Alert latency p50 / p95 | Samples sent |
|---|---|---|---|---|---|
| Baseline | 16 | 8 → 0 | 100 % | 58 / 79 ms | 5,744 |
| Baseline + adaptive | 16 | 8 → 1 | 100 % | 57 / 78 ms | 5,750 |
| Design load | 24 | 8 → 0 | 100 % | 74 / 95 ms | 5,760 |
| 40 devices (all in encounters) | 40 | 13 → 3 | 100 % | 352 / 1,044 ms | 8,979 |
| 40 devices (half working apart) | 40 | 11 → 2 | 100 % | 459 / 1,642 ms | 13,292 |
| **Same + adaptive** | 40 | 11 → 1 | 100 % | **94 / 256 ms** | **11,573 (−13 %)** |

The 40-device test is sensitive to PC load. Across three runs, without adaptive rate the p95 latency was 0.46–3.4 s and collisions 11 → 1–9; with adaptive rate it was 0.21–1.1 s and 11 → 1 every time (the table shows the latest run, after an alert-state bug fix).
Under baseline load no device is slowed down, so results are identical. That is why `rate_control.enabled: true` is the default.
The MEC app's output queue is prioritised (alert > control > risk summary), so alerts never wait behind other writes.

### MEC app restart and forklift failsafe
Even if the MEC app is killed and restarted mid-encounter, alerts resume within 1.2–2.2 s (`mec_restart` case: collisions 5 → 0–1, timely detection 100 %).
What the forklift should do while MEC is silent was decided by measurement (`sim/failsafe_eval.py`, 330 high-speed closed-loop encounters, same encounters and same network conditions):

| Behaviour when silent (collisions / 180 true collisions) | Normal | Restart 1.7 s | Restart + 20 % alert loss | MEC down 8 s |
|---|---|---|---|---|
| v0.6: hold last restriction, release after 5 s | 19 | 30 | 43 | 93 |
| Slow down immediately on silence (0.5 m/s) | 20 | 42 | 60 | 94 |
| Stop immediately on silence | 20 | 34 | 52 | 60 |
| **Hold → stop if silent for more than 2 s (adopted)** | **19** | **27** | **42** | **78** |

- Slowing or stopping on short silences actually increased collisions. The deceleration plan is built so the forklift either clears the crossing point first or stops before it,
  and a slowed forklift stays in the conflict zone longer. When MEC stays absent, stopping is clearly better.
- We swept the stop threshold over 1.3–3.0 s and chose 2.0 s (`results/failsafe_stop_sweep.json`). It is equal to or better than v0.6 under every condition.
- MEC sends a heartbeat to `<ae>/control` every 1 s. Heartbeats have lower priority than alerts, so a heartbeat arriving also means no alerts are backed up.
  If MEC is alive but there has been no update for 5 s, the "clear" alert is assumed lost and the restriction is released. Silence alone never releases a restriction.
- The rules are identical in `edgeguard/device_policy.py` (reference implementation) and `firmware/common/device_policy.h` (firmware),
  and a test feeds random event sequences to both and checks that the results match.

### Server hardening (v0.9)

Issues found in code review and the fixes (`tests/test_server_hardening.py`):

| Issue | Impact | Fix |
|---|---|---|
| **Late samples reset the track** — when network jitter reorders samples, it is treated as a "device restart" and velocity is discarded | 50 ms jitter: 178 resets in 300 s, velocity error 0.26 m/s (80 ms jitter: 420 resets, 0.45 m/s) | Drop samples up to 1 s late and keep the track → 0 resets, error 0.08 m/s |
| **Backed-up heartbeats delivered late** — when the CSE slows down, they pile up in the output queue and later report "MEC alive" | Forklift notices the failure late | Queue items expire: alerts after 1.5 s, heartbeats and risk summaries after 1 s (alerts are refreshed every 1 s) |
| **Track and pair tables grow forever** — camera `untagged_N` tracks, departed devices | Memory and evaluation cost grow in long-running operation | Prune tracks silent for 30 s and their pairs (every 10 s) |
| **500 responses to bad notifications** — broken JSON, non-numeric coordinates | The CSE may delete a subscription after repeated failures | Always respond 2000; just count bad input |
| **Risk evaluation blocks the event loop** | Delays in handling concurrent notifications | Run evaluation in a thread pool |
| **Device clock drift breaks the timeline** (NTP failure) | Track resets, wrong latency calculation | Use receive time if it differs by more than 5 s |
| **Input stops silently if a subscription disappears** (e.g. a CSE restored without its DB) | No one notices that alerts have stopped | Check and restore subscriptions on device containers every 60 s |
| **State not visible from outside** | Hard to diagnose failures in operation | Added `degraded` (CSE writes failing for more than 5 s), output queue and input errors to `/health`, plus `/metrics` (Prometheus format) |

### Cloud copy: store and forward
`edgeguard/cloud_sync.py`: alerts and risk summaries bound for the cloud are queued in order and retried with exponential backoff on failure.
When the queue fills, risk summaries are dropped first and alerts are kept to the end. On-site alerts take a separate path and are unaffected.
`python tools/outage_replay_test.py` — cuts the WAN proxy for 25 s mid-run, then restores it (`results/outage_replay.json`):

| Alerts issued by MEC | Max queue during outage | Alerts in cloud after recovery | Duplicates | Dropped |
|---|---|---|---|---|
| 56 | 43 | **56 (all)** | 0 | 0 |
