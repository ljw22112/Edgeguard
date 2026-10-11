# CSE handover between MEC zones

[← README](../README.md) · [한국어](ko/handover.md)

A large warehouse has several zones, each with a MEC host running an **MN-CSE** next to the EdgeGuard MEC app. The MN-CSEs register with the **IN-CSE** over Mcc. A forklift module or worker tag keeps its SDT twin on the MN-CSE of the zone it is in, and moves it when it changes zones. Code: [`edgeguard/handover.py`](../edgeguard/handover.py).

## Procedure (make-before-break)

| Step | What happens |
|---|---|
| Trigger | **location**: the position is `hysteresis` (1 m) inside another zone · **availability**: `fail_limit` (3) failed publishes in a row → nearest zone whose CSE answers |
| Prepare (background) | samples keep going to the source while: module values are read from the source twin (**state**) · AE, twin and ACP are rebuilt on the target (**security context**) · every subscription on the twin is re-created with the same `nu` (**subscriptions**) · the new AE is announced to the IN-CSE (`at`), whose AEAnnc `lnk` points at the serving CSE |
| Switch | the next sample goes to the target |
| Home record | `<IN-CSE>/<dev>/serving` gets `{zone, cse_id, poa, reason, prep_ms, subscriptions}`, which applications read or subscribe to |
| Release | the source AE is deleted after `grace_s` (0.5 s) |

**Portable subscriptions.** In ACME a subscription is readable only by its creator. A subscriber that wants to follow a moving device therefore attaches the device's ACP to its subscription (`create_subscription(..., acpi=[<device ACP>])`). The device can then read the subscription and carry it to the target CSE.

**Availability failover.** The source can no longer be read. The twin is rebuilt from the device's own last state, and the configured subscribers (`handover.subscribers`) are subscribed on the target. Applications also see the change through the home record.

A target whose preparation failed is not retried for 5 s.

## Measured (CI on every commit)

```bash
scripts/acme.sh start in mn-a mn-b          # IN-CSE :8080, zone A :8081, zone B :8082
python tools/handover_demo.py               # location: 10 checks
python tools/handover_demo.py --failover    # + zone B's CSE killed: 8 checks (5 location + 3 availability)
```

| Handover | Prepared in | Service interruption | Samples lost |
|---|---|---|---|
| Location A → B | ≈ 115–140 ms (in the background) | **3–11 ms** | **0** |
| Availability (zone B down) → A | ≈ 80 ms after detection | ≈ 306 ms | 3 (the detection window: 3 failed publishes) |

Interruption is the largest gap between notifications at the subscribed application, minus the 100 ms sample period. Lost samples are those the device sent that never reached the application.

**Checks:**
- location trigger (A → B)
- no sample lost
- interruption < 300 ms
- speed limit restored on the target
- subscription restored on the target
- another device refused on the target (ACP)
- announcement at the IN-CSE links to zone B
- source AE deleted
- the application kept receiving, now from zone B (notification origin `/id-mn-b`), without re-subscribing
- home record followed the device
- the `--failover` run has 8 checks: 5 of the location checks, then availability trigger B → A, notifications resume, home record shows the failover

Results: `results/handover.json`, `results/handover_failover.json`.

## Files

| File | Contents |
|---|---|
| `scripts/acme-mn-a.ini`, `scripts/acme-mn-b.ini` | zone MN-CSE configuration (register with the IN-CSE) |
| `scripts/acme.sh` | starts and stops `in`, `mn-a`, `mn-b` with the SDT domain installed |
| `edgeguard/handover.py` | `HandoverClient` (attach, publish, triggers, prepare, switch, release), `setup_home` |
| `tools/handover_demo.py` | demo and measurement |

## Limits

- The trigger uses the device's own position. Triggering from MEC Location zone events is a possible extension.
- The availability path loses the samples sent during detection (≈ 0.3 s at 10 Hz). D2D local decisions cover that window on real devices.
