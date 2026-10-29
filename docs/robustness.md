# Normal and exceptional conditions

[← README](../README.md) · [한국어](ko/robustness.md) · [comparison with site practice](site-compare.md)

A safety system is judged by its bad days. [`sim/robust_eval.py`](../sim/robust_eval.py) runs the many-to-many floor (8 workers, 4 forklifts, 25 s) under eight conditions; every condition uses the same episodes, only the condition changes.

| Scenario | What changes |
|---|---|
| normal | randomised network (40-220 ms, up to 20 % / 10 % loss), UWB noise 0.1-0.35 m |
| comply 85 % / 70 % | workers ignore 15 % / 30 % of the alerts (stop ~2 s on the buzz and walk on) |
| bad network | 300-600 ms latency, 20-40 % uplink and 15-30 % downlink loss |
| MEC restart | the MEC app is silent for 2.5 s at a random moment and comes back **without** its alert state |
| noisy UWB | 0.35-0.6 m position noise |
| dense | 12 workers and 6 forklifts |
| attentive driver | drivers brake for someone right in front (1 s reaction) |

## Results on the test seeds (5000+, 150 episodes per scenario), robust policy v1

| Scenario | Collisions: previous / **robust** | Close passes < 1.5 m | Forklift throughput: previous / **robust** |
|---|---|---|---|
| normal | 0 / **0** | 0 / 0 | 91.1 % / **96.6 %** |
| comply 85 % | 0 / **0** | 2 / 2 | 86.1 % / **94.7 %** |
| comply 70 % | 0 / **0** | 3 / 2 | 82.2 % / **90.8 %** |
| bad network | 0 / **0** | 15 / 6 | 82.9 % / **90.8 %** |
| MEC restart | **3** / **0** | 14 / 8 | 85.9 % / **93.8 %** |
| noisy UWB | 0 / **1** | 1 / 4 | 82.7 % / **90.6 %** |
| dense | 0 / **0** | 6 / 2 | 87.2 % / **95.1 %** |
| attentive driver | 0 / **0** | 2 / 0 | 90.2 % / **95.4 %** |
| **all 1,200 episodes** | **3 / 1** | **43 / 24** | |

Both rows run with the same devices (D2D fall-back and emergency brake, below). "Previous" is the learned policy before truck priority ([`results/policy_previous.json`](../results/policy_previous.json)). The robust policy is better on every throughput line and in total collisions and close passes; it still had **one collision in 1,200 episodes, under 0.35-0.6 m UWB noise** (see Limits).

## Robust policy v2 (glide), on two test sets

v2 adds the glide plan and lifts a stop point as soon as the worker has left the path ([site-compare.md](site-compare.md#truck-priority-stop-points-robust-training)); refined by robust training and picked with no collision on 2,000 validation episodes (seeds 13,000+ / 15,000+). Tested on the seeds above and on a second, fresh test set (17,000+), 8 scenarios x 150 episodes each:

| | Collisions (5000+ / 17000+) | Close passes < 1.5 m | Mean throughput over the 8 scenarios |
|---|---|---|---|
| Previous policy | 3 / 5 | 43 / 29 | 86.0 % / 86.6 % |
| Robust v1 | 1 / 1 | 24 / 27 | 93.5 % / 94.1 % |
| **Robust v2** | **2 / 0** | 35 / 29 | **94.1 % / 94.4 %** |

Safety stays at v1's level (2 collisions in 2,400 stressed episodes each, against 8 for the previous policy; none in the normal scenario), with 0.3-0.6 points more throughput; v2 has somewhat more close passes on the first test set. Its two collisions were after a MEC restart. Results: [`results/robust_eval.json`](../results/robust_eval.json), [`results/robust_eval_test2.json`](../results/robust_eval_test2.json).

## Large-scale test: 8,000 fresh episodes per policy, with confidence intervals

Counts of 0-5 in 1,200 episodes cannot separate policies. [`sim/large_eval.py`](../sim/large_eval.py) runs every policy on the **same 1,000 fresh episodes per scenario** (seeds 23,000+, never used to train, pick or tune any policy): 8,000 episodes and 34,644 conflicts each. Intervals: Wilson 95 % for collisions per 1,000 conflicts, bootstrap 95 % for throughput.

![Policies under exceptional conditions](img/large_eval_robust.png)

| Scenario | Collisions: previous / v2 / **v3** | Throughput: previous / v2 / **v3** |
|---|---|---|
| normal | 0 / 0 / **0** | 91.6 % / 97.3 % / **97.3 %** |
| comply 85 % | 0 / 0 / **0** | 87.4 % / 94.7 % / **94.7 %** |
| comply 70 % | 1 / 0 / **0** | 83.0 % / 90.6 % / **90.7 %** |
| bad network | 9 / 1 / **0** | 83.4 % / 91.0 % / **91.2 %** |
| MEC restart | 9 / 4 / **2** | 87.6 % / 94.6 % / **94.6 %** |
| noisy UWB | 3 / 0 / **0** | 83.2 % / 93.1 % / **93.1 %** |
| dense (12 workers, 6 forklifts) | 6 / 0 / **0** | 87.4 % / 95.1 % / **95.1 %** |
| attentive driver | 2 / 0 / **0** | 90.7 % / 95.5 % / **95.5 %** |
| **all 34,644 conflicts** | **30 / 5 / 2** | |
| per 1,000 conflicts (95 % CI) | 0.87 [0.61-1.24] / 0.14 [0.06-0.34] / **0.06 [0.02-0.21]** | |

- **v3 vs previous policy: 93 % fewer collisions** (intervals do not overlap) and **+4.8 to +9.9 points of throughput in every scenario**.
- **v3 vs v2:** 2 collisions instead of 5, throughput unchanged (within ±0.2 points). The intervals overlap: v3 is at least as safe, and its two collisions are in the one scenario it was built for, MEC restart (4 -> 2).
- Seven of the eight scenarios had no collision in 1,000 episodes each; for these the 95 % upper bound is about 1 collision per 1,000 conflicts (0.46 on the dense floor).

Raw per-episode data: [`results/large_eval.json`](../results/large_eval.json), summary [`results/large_eval_report.txt`](../results/large_eval_report.txt).

## What failed, and what changed (Python reference and firmware)

Each row was found by tracing a collision of the scenario set ([`sim/collision_audit.py`](../sim/collision_audit.py) style traces), fixed, and checked again on fresh seeds.

| Found | Change |
|---|---|
| A stop point (the position the truck must stop short of) crept away with position noise, and was dropped while DANGER | Within an encounter a stop point only moves closer, or farther once the worker has moved more than 1 m; DANGER and "worker first" keep it |
| A STEP ASIDE for one truck walked a worker into another truck, or across the truck's own path | The sidestep must keep clear of every truck; never across the path |
| After a MEC restart the tag's WAIT timed out (no message for 2.5 s) while a truck passed; the restarted app needed a moment to raise its alerts again | A tag keeps WAIT through MEC silence while its own D2D rule sees a truck close (max 20 s); the local D2D rule stays on 1.5 s after a silence ends |
| Bad network: speed plans and stop points to the truck were lost | The forklift reports the plan it applies in every motion sample; the MEC app re-sends a plan that is not reported within `ack_s` |
| A late "clear" overtook a newer "raise" (jitter) | Tags and forklift modules drop a message older than the last one applied for the pair (`mec_tx_ts`) |
| A worker walking into the truck's path was a stop point where he stood | ... at the middle of the path (`env_walk_in`) |
| The rare case none of the above covers | **Always-on D2D emergency brake**: from the peer-to-peer state broadcast alone, a worker on a collision course within 1.5 s (closest approach < 1.3 m) stops the truck, whether or not the MEC app and the network work |

## Policy v3: the tag checks GO itself

The large-scale test below found v2's weak spot: 4 of its 5 collisions in 8,000 episodes came after a MEC restart. Tracing them (and one on the dense floor) gave three mechanisms:

| Found | Change (v3) |
|---|---|
| The restarted MEC app had lost the WAIT it had given. Nobody checked GO: the WAIT ran out after 2.5 s unheard, and the worker walked into a truck that was still coming | **Tag GO check** (`tag_walk_check`): before a WAIT ends on its own, the tag checks, from the D2D state broadcast alone, whether walking on at the pace and heading the worker had before the WAIT would bring a truck onto a collision course. If it would, the WAIT is kept, up to 20 s |
| The same thing on the dense floor: a worker waiting for one truck was released when that WAIT ran out, while a second truck - passing him quietly under the stopping envelope, which trusts a waiting worker - was 4 m away | the same check, for every WAIT that runs out unheard |
| After a restart, the rebuilt alert state cleared a pair (GO) while the truck was just pulling away next to the worker | the GO check also applies to the clear / release of a WAIT given before an MEC silence (an "orphaned" WAIT) |
| A truck standing before a person in its path had its plan lifted ("no faster than you are going" is no limit at 0 m/s) and crept up to him | a truck standing before someone in its path stays stopped (`env_keep_stop`) |

The walking velocity is taken only while the worker clearly walks (> 0.6 m/s; at 0.3 m/s the velocity noise of a standing worker overwrote it). Python reference [`edgeguard/device_policy.py`](../edgeguard/device_policy.py) (`truck_near_if_walk`, `orphaned`), firmware [`firmware/common/device_policy.h`](../firmware/common/device_policy.h) and [`worker_cue.h`](../firmware/common/worker_cue.h), the same results in [`tests/test_device_policy.py`](../tests/test_device_policy.py).

Variants compared on development seeds 62,000+ (8 scenarios x 150 episodes; mean over the scenarios):

| | Collisions | Close passes | Mean throughput | Worker time lost |
|---|---|---|---|---|
| v2 | 2 | 23 | 95.0 % | 2.56 s |
| GO check for orphaned WAITs only (+ keep-stop) | 1 | 16 | 95.0 % | 2.56 s |
| GO check on every GO, also the MEC app's own | 0 | 16 | 95.1 % | **3.19 s** |
| GO check when a WAIT runs out | 0 | 15 | 95.1 % | 2.57 s |
| **v3: ... and on the clear of an orphaned WAIT** | **0** | **15** | **95.0 %** | **2.58 s** |

Checking every GO is as safe but makes workers wait 25 % longer: the MEC app's own GO check already covers the trucks it knows about, and the tag then also holds for trucks merely passing nearby. The variant that only checks WAITs running out had one collision on the validation seeds 11,000+ (the clear after a restart); v3 had none there (8 x 150 episodes, mean throughput 94.7 %, worker time 2.56 s). Raw output: [`results/tag_go_check_dev_val.txt`](../results/tag_go_check_dev_val.txt).

Rejected after validation (kept as options, off): STEP ASIDE only after 0.6 s of standing (`aside_still_s`, more collisions and less throughput), narrowing STEP ASIDE to workers inside r_safe (`aside_reach`, fixed the noisy-UWB case but added three elsewhere), buzzing a walker on an envelope alert (`env_buzz_walker`) and a worst-case GO direction (`go_unknown_worst`), no measurable effect.

## Tried on top of v2, not adopted (development seeds 60000+, 8 scenarios x 100 episodes)

| | Collisions | Normal throughput | Worker time lost (normal) | Alarms per episode (normal) |
|---|---|---|---|---|
| v2 | 0 | 98.4 % | 1.99 s | 7.1 |
| + green wave (slow the truck early so it reaches a crossing after the walker) | 1 | 96.9 % | 2.21 s | 6.1 |
| + green wave, gentler (at most 20 % slower) | 0-1 | 97.6 % | 2.21 s | 6.6-6.8 |
| + alert state restored after a MEC restart | 0 | 98.4 % | 1.99 s | 7.1 |

- **Green wave** cut alarms by 7-14 % but cost throughput and worker time and added a collision. Under truck priority a WAIT for the worker is cheap, so slowing the truck for a crossing the WAIT would have resolved moves the cost to the truck; the walker's path 6-8 s ahead is uncertain (people turn and stop); and the quiet slow-down holds the pair's alert at WARNING, so a real collision course that follows is no longer a new alert and the worker is not buzzed - a safety gap that would need its own alert channel.
- **Restoring the alert state** after a MEC restart (read back from the CSE) changed little here (MEC restart: close passes 6 -> 5, throughput +0.2 points): the devices' own layers (tag WAIT kept while a truck is near, local D2D rule, emergency brake) already cover the restart. Its costs: a CSE write per alert change, a stale state after a long outage (needs an age limit), and consistency with an active-standby pair.

Raw output: [`results/green_wave_state_restore_dev.txt`](../results/green_wave_state_restore_dev.txt).

A second round (same seeds; mean over the 8 scenarios, 800 episodes each):

| | Collisions | Close passes | Mean throughput | Worker time lost | Alarms per episode |
|---|---|---|---|---|---|
| v2 | 0 | 26 | 94.7 % | 2.52 s | 9.2 |
| + entry gate (WAIT a walker before he steps into the path) | 0 | 27 | 94.8 % | 2.53 s | 9.3 |
| + tag UWB + IMU fusion (assumed 40 % less worker position error) | 3 | 26 | 95.5 % | 2.24 s | 7.6 |
| + learned walking prediction (LSTM) | 2 | 19 | 94.8 % | 2.42 s | 8.4 |
| + all three | 1 | 17 | 95.7 % | 2.23 s | 7.6 |

- **Entry gate**: almost never fires - the collision-course warning already comes early enough for most walkers to stop outside the path; no gain, more rules.
- **UWB + IMU fusion**: the best single gain in efficiency (worker time -11 %, alarms -17 %, +0.8 points) but 3 collisions: the policy's margins were learned for UWB-only noise, and with sharper positions the truck passes closer - a sensor change needs a re-trained, re-validated policy. The 40 % is an assumption (the sim models Gaussian noise, not NLOS outliers), and it needs an IMU on every tag, calibration and drift handling near steel racks.
- **LSTM**: fewer close passes (-27 %) and alarms (-9 %), but 2 collisions under 0.35-0.6 m UWB noise: trained on cleaner tracks, it extrapolates noisy ones badly (the one-pair evaluation found the same trade). It also needs 2 s of history, PyTorch on the MEC host and is harder to explain for a safety case.
- **All three**: +1.0 point throughput, -12 % worker time, -17 % alarms, -35 % close passes, 1 collision (dense floor). Promising, but adoptable only after the policy is re-trained with them and passes validation with no collision.

Raw output: [`results/entry_gate_fusion_lstm_dev.txt`](../results/entry_gate_fusion_lstm_dev.txt).

A third round (same seeds, 800 episodes each):

| | Collisions | Close passes | Mean throughput | Worker time lost |
|---|---|---|---|---|
| v2 | 0 | 21 | 94.7 % | 2.51 s |
| + early GO (release the worker once the truck is past) | 1 | 24 | 94.5 % | 2.38 s |
| + adaptive stop-point margin (k x estimated position error) | 2 | 26 | 94.4 % | 2.58 s |
| + green wave on a truck-only channel | 2 | 18 | 93.7 % | 2.37 s |
| + all three | 4 | 40 | 93.5 % | 2.17 s |

- **Early GO** saves workers 5 % of their waiting but sends some out while a truck that has only just passed is still close; one collision (attentive driver).
- **Adaptive margin**: the innovation also contains a walker's own manoeuvres, so the margin grows in normal operation (less throughput) without growing enough when it matters.
- **Green wave on its own channel** fixes the masked-alert gap but still costs a point of throughput: under truck priority the worker's WAIT is cheaper than the truck's slow-down.
- Together they trade truck throughput for worker time and add collisions. v2 stays. [`results/release_margin_greenwave2_dev.txt`](../results/release_margin_greenwave2_dev.txt).

**Re-trained with all three** (`sim/train_multi.py --mode plus --robust`, 7 CEM generations; the LSTM makes a generation ~3 x slower): the best candidate had no collision on validation seeds 13,000+ (mean throughput 95.6 % vs v2's 94.3 % on the same episodes) but **2 collisions on validation seeds 15,000+** (after a MEC restart and on the dense floor; v2 had none there, 94.8 % vs 93.4 %). It fails the gate and is not adopted ([`results/policy_plus_rejected.json`](../results/policy_plus_rejected.json)): about 1.3 points of throughput for a safety record that does not hold on fresh episodes, plus an IMU on every tag and PyTorch on the MEC host.

## How the policy was chosen

1. Training ([`sim/train_multi.py`](../sim/train_multi.py) `--mode priority --robust`): CEM over 20 parameters, every candidate scored on 144 episodes, half normal and half exceptional (85 / 70 % compliance, bad network, MEC restart, noisy UWB, dense), seeds 80,000+, a collision costing 2 episodes' output.
2. Selection on validation seeds 7,000+ and 9,000+ (8 scenarios × 250 episodes): the only candidate without a collision ([`results/policy_robust.json`](../results/policy_robust.json)).
3. Test on seeds 5,000+ (this page and [site-compare.md](site-compare.md)).

## Limits

- Simulation. One collision in 1,200 stressed test episodes is not zero; with counts this small, 1 vs 3 is not a significant difference - what the table shows is that the new policy is not less safe while being 5-9 points faster in every condition.
- The noisy-UWB collision: a sidestep planned from a position 0.4-0.6 m off. Positioning quality is a deployment requirement (anchor layout, NLOS mitigation), not something the policy can fully make up for.
- The plan confirmation and message ordering need the devices' plan report and the alert's `mec_tx_ts`; the emergency brake needs the D2D state broadcast (ESP-NOW / sidelink) on both devices.

Reproduce: `python -m sim.robust_eval --episodes 150 --offset 5000 --policy current --policy results/policy_previous_eval.json` (about 25 minutes on 2 cores).
