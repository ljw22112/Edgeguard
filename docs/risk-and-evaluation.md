# Risk engine and evaluation

Many-to-many · deadlock resolution · stepping aside · false alarm reduction (v1.2), worker WAIT/GO cues (v1.1), guidance-geometry risk assessment, method comparison, LSTM trajectory prediction, online closed-loop simulation, policy learning.

[← README](../README.md) · [한국어](ko/risk-and-evaluation.md)

## v1.2: many-to-many sites · deadlock resolution · stepping aside · false alarm reduction

Up to v1.1 the simulation had one worker and one forklift. We built a simulator where many workers and forklifts meet at once, as in a real warehouse
(`sim/multi_sim.py`: 36 × 24 m, 3 aisles × 3 cross aisles, 8 workers · 4 forklifts, 25 s × 200 runs, randomised network conditions),
and fixed the problems it exposed one by one.

| Problem (found in many-to-many) | Fix |
|---|---|
| Devices remembered only one plan: worker A's `clear` lifted a forklift speed limit imposed because of worker B, and forklift A's release sent off a worker that forklift B was approaching | Forklifts keep a **per-worker speed plan** (the strictest value applies); tags keep a **per-forklift WAIT** (GO only when all are released) — in both Python and C++ (`device_policy`, `worker_cue`) |
| **Release race**: the forklift had stopped and the worker was waiting; the moment the alert cleared, both set off at once and collided | Release **one side first**: if the forklift's path is clear, the forklift goes first at pass-through speed (worker WAIT held); if the worker is on the forklift's path, the worker goes first (forklift held at 0 m/s, then worker GO) |
| The GO decision assumed the forklift kept its "current speed": it underestimated stopped or accelerating forklifts | Check every speed up to the pre-stop speed, including a 1 m/s² acceleration phase |
| The GO decision only looked at the forklift in the alert pair: GO while another forklift was approaching | Confirm GO safety against every forklift nearby (25 m) (v1.3; measured difference is small — many-to-many collisions 4 vs 4, throughput +0.3 pp — but logically required) |
| Head-on or turning entry in the same aisle: if the worker waits on the forklift's path, nobody can pass (the largest source of forklift time loss) | **STEP ASIDE**: tell a worker standing on the forklift's predicted path to step to the nearer aisle edge (r_safe + 0.8 m from the path) and wait there → the forklift passes |
| UWB noise made standing pickers "walk", causing false alarms | Workers below 0.4 m/s are predicted as stationary |
| CTRV predicted a forklift about to turn as going straight (false alarm), and warned workers in the aisle it was turning into too late | (Optional) **Route sharing**: if a planned route is available from fleet management, the WMS or a driver tablet, predict along that route (`RoutePredictor`) |

**Many-to-many results** (`results/multi_sim.json`, 750 collision-risk pairs):

| Method | Collisions | Forklift throughput | Forklift loss / vehicle | Worker loss / person |
|---|---|---|---|---|
| v1.0 vibration only | 100 | 61.7 % | 11.2 s | 2.5 s |
| v1.1 WAIT/GO | 22 | 61.7 % | 11.1 s | 3.1 s |
| **v1.2** | **4** | **86.0 %** | **5.7 s** | 2.7 s |
| v1.2 without stepping aside | 3 | 60.0 % | 11.5 s | 3.2 s |
| v1.2 without per-worker plans | 7 | 86.1 % | 5.6 s | 2.4 s |

- Collisions **down 96 %** (100 → 4), forklift throughput **+39 %** (61.7 → 86.0 %). Almost all of the throughput gain comes from STEP ASIDE (60 % without it).
- The rule that turns speed commands below 0.3 m/s into a stop had no measurable effect after the other fixes (collisions 4 vs 2, within noise),
  but we keep it because a plan that crawls at a few cm/s is meaningless.

**1:1 results** (`results/worker_cue_eval.json`, 2,200 encounters · 1,207 collision risks): v1.0 145 → v1.1 8 → **v1.2 1**,
forklift throughput 77.3 → 81.6 → **86.4 %**, forklift loss 2.76 → 1.62 s, worker loss 2.07 → 3.16 s.
At worker WAIT compliance rates of 85 / 70 / 50 %, collisions are 12 / 27 / 42 (v1.0: 145).

**Failure conditions** (`results/failsafe_eval_hold.json`, 180 real collisions): normal 0, MEC restart 6, restart + 20 % loss 12, MEC down 8 s 11, network outage 2,
forklift · worker coverage holes **0 · 0**, normal throughput 85 %.

**False alarms** (`results/false_alarm_eval.json`, 993 encounters with no collision risk):

| | False alarms | Collisions | Throughput |
|---|---|---|---|
| No stationary detection | 622 | 2 | 86.0 % |
| + stationary detection (v1.2 default) | 570 | 1 | 86.4 % |
| + route sharing (optional) | **400** (−36 %) | 2 | **89.0 %** |

- False alarms from forklifts turning away 136 → 3; from pickers beside the aisle 126 → 47.
- Half of the remaining false alarms are workers who stop on their own in front of the aisle (200 / 200). People decelerate within the last second, so at alert time the case cannot be distinguished.

**Control dashboard**: the MEC app mirrors each worker tag's state (a `WaitCue` copy) and shows **WAIT (red) / STEP ASIDE (orange) / GO (green)** on the map.

**Limitations**: the step-aside direction is "the nearer edge" and does not consider other forklifts' positions (in many-to-many, workers occasionally step towards another forklift).
Tags have no direction indicator, so we assume people pick the nearer side. Route sharing is an optional feature that requires integration with site systems.

## v1.1: worker WAIT / GO cues — removing the cause of the remaining accidents

**Root cause**: the collisions remaining in v1.0 (23 / 180 under normal conditions) **all occurred when the alert had gone out on time (at least 1 s before)**.
Workers who felt the vibration stopped for about 2 s and then walked on, while the forklift had set its speed on the assumption that "the worker stops",
so it met the worker who had walked back out (8 cases with a reversing forklift, 6 with zigzag walking, etc.). The problem was not prediction but **the cue given to people**.

**Fix** (`edgeguard/worker_cue.py` · `firmware/common/worker_cue.h`, `edgeguard/alerting.py`):
1. **Hold until WAIT ends**: during an alert the tag holds "wait" with a red LED + vibration every second; when `clear` arrives, two short vibrations signal **GO**.
   If no message arrives for 2.5 s (lost release message, silent MEC), the tag releases the wait on its own, so a dead server never keeps people pinned.
2. **WAIT keep-alive**: while an alert is active, the MEC app sends `wait` to the worker only, every second (the forklift speed limit stays as is).
3. **GO safety check**: a stopped worker is not on a collision course now, but may meet the forklift if they resume walking in their original direction.
   In that case the alert is not cleared and the wait is held, while the forklift passes at pass-through speed.

`python -m sim.worker_cue_eval` → `results/worker_cue_eval.json` (11 scenarios × 100 runs × 2 seed sets = 2,200 runs, of which 1,207 are collision-risk encounters, randomised network conditions):

| Method | Collisions | Forklift throughput | Forklift loss / encounter | Worker loss / encounter |
|---|---|---|---|---|
| v1.0 vibration only | 145 / 1207 | 77.3 % | 2.76 s | 2.07 s |
| Hold WAIT | 59 | 80.4 % | 2.37 s | 2.97 s |
| + WAIT keep-alive | 19 | 82.0 % | 2.17 s | 3.35 s |
| **v1.1: + GO safety check (adopted)** | **11** | **81.7 %** | **2.20 s** | 3.51 s |
| v1.1, only 85 % obey WAIT | 22 | 80.9 % | 2.30 s | 3.32 s |
| v1.1, 70 % | 31 | 80.1 % | 2.39 s | 3.12 s |
| v1.1, 50 % | 44 | 79.3 % | 2.51 s | 2.90 s |

- **Collisions down 92 %** (145 → 11), **forklift throughput +5.7 %** (lost time −20 %). Because workers reliably wait, forklifts slow down less.
- The cost is +1.4 s of worker waiting per encounter. Forklift time (equipment + driver) is more expensive, and encounters happen only a few times per worker per hour.
- Even if only half of the workers comply, collisions are one third of v1.0 (non-compliant workers are modelled as behaving as in v1.0).
- Failure conditions (`results/failsafe_eval_hold.json`; v1.0 in `results/failsafe_eval_buzz.json`, same 180 encounters):
  normal 23 → **0**, MEC restart 33 → 11, restart + 20 % loss 42 → 19, MEC down 8 s 36 → 11, forklift · worker coverage holes 17 · 16 → **1 · 1**, network outage 2 → 2.
  Even with only 70 % compliance, every condition is better than v1.0 (`results/failsafe_eval_hold_comply70.json`).
- Tried but not adopted: GO immediately after the forklift passes (worker wait −0.1 s, more collisions); relaxing forklift deceleration at WARNING by trusting the worker to stop (throughput +0.2 pp, more collisions);
  short release hold (clear_hold 1.0–2.0 s, mixed across seeds); retraining the policy for this UX (the existing policy was better); LSTM prediction (false alarms −10 %, more collisions with reversing forklifts).

## Risk assessment: guidance geometry

`r = p_worker − p_forklift`, `v = v_worker − v_forklift`

| Quantity | Formula | Meaning |
|---|---|---|
| LOS rate | λ̇ = (r × v) / R² | Rate of change of the line-of-sight angle. **λ̇≈0 while closing = collision course (CBDR)**, the principle behind proportional navigation (PN) |
| CPA distance | d_cpa = R²·\|λ̇\| / \|v\| | Closest-approach distance written in terms of LOS rate |
| TCPA | −(r·v) / \|v\|² | Time remaining to closest approach |
| ZEM | R²·\|λ̇\| / Vc | PN zero-effort miss (reference value) |
| Collision cone | ∠(−v, r) < asin(R_safe/R) | Relative velocity lies inside the collision cone |
| VO slowdown | Largest k such that scaling speed by k leaves the cone | Forklift `speed_scale` command |

The forklift uses IMU yaw rate for **CTRV** prediction, and turns are assumed to continue only up to the next aisle direction (90° grid).

| Level | Condition (default) | Action |
|---|---|---|
| DANGER | Predicted minimum distance < 1.5 m, within 1.5 s | Vibration + slowdown (VO) |
| WARNING | < 1.8 m, within 3 s | Vibration + beacon light |
| CAUTION | < 2.5 m, within 5 s | Dashboard display only |

## Comparison experiment (simulation)

`python -m sim.evaluate --n 250` → `results/evaluation.json`, `python sim/plot_results.py` → `results/evaluation.png`

8 scenarios × 250 runs = 2,000 runs, UWB noise 0.15 m, the same 0.3 s debounce applied to every method.
"Timely detection" = alert at least 1 s before contact (within 1.5 m).

| Method | Timely detection | False alarm rate | Lead time (median) |
|---|---|---|---|
| Proximity 3 m | 0.0% | 66.7% | 0.4 s |
| Proximity 5 m | 76.3% | 84.8% | 1.2 s |
| TTC < 3 s | 100.0% | 72.6% | 2.1 s |
| Guidance (CPA/LOS) | 100.0% | 31.6% | 2.1 s |
| Guidance + CTRV | 100.0% | 33.8% | 2.4 s |
| **Guidance + CTRV + LSTM** | **100.0%** | **29.8%** | **2.4 s** |

- Adding the "worker standing in the lane" rule in v0.5 (see the online simulation below) increased lead time from 2.2 → 2.4 s,
  and false alarms rose from 28.6 → 33.8% for CTRV and 24.9 → 30.0% for LSTM. Most are `turn_away` (a forklift heading towards a standing worker and then turning).
  We accepted this cost because the rule is needed to prevent collisions in the closed loop.
- The LSTM reduces misreading a stationary worker as walking from noisy positions, cutting `roadside_picker` false alarms from 52 → 15.
- Most remaining false alarms are `worker_yields` (a worker on a collision path who slows down and stops 2–3 m short).
  They are already on a collision course before they start slowing, so an alert 3 s ahead is hard to avoid with any method.
- These results come from hand-built scenarios, so they will be re-validated with RC-car measurements in W6.

### LSTM trajectory prediction

`python -m sim.train_lstm --n 400 --epochs 15` (about 2.5 min on CPU) → `models/worker_lstm.pt`

Input: 20 worker positions (last 1.9 s resampled at 10 Hz) + forklift relative position and velocity / Output: 30 future positions from 0.1 to 3.0 s.
Training and evaluation use episodes from different seeds.

v2 was trained on the 8 base scenarios plus running, zigzag and reversing forklifts. Comparison on the same validation set (3 s prediction error ADE / FDE):

| Model | Base scenarios | Abnormal behaviour (running · zigzag · reversing) |
|---|---|---|
| Constant-velocity Kalman | 0.31 / 0.54 m | 0.73 / 1.19 m |
| LSTM v1 | **0.175 / 0.29 m** | 0.94 / 1.58 m (worse than constant velocity) |
| **LSTM v2 (adopted)** | 0.184 / 0.31 m | **0.50 / 0.77 m** |

**CTRV is the default in the closed loop.** Running the learned policy on the same 330 encounters gave 15 collisions with CTRV and 23 with LSTM,
and even after retraining the policy for LSTM the best was 22 (`results/closed_loop_ctrv_vs_lstm.json`, `results/policy_training_lstm.json`).
Lower prediction error did not yield better safety when the alert timing did not match the policy, so LSTM remains an option.

**Irregular samples (v0.8)**: on the network, samples drop out or jitter, and adaptive reporting sends distant workers at 2 Hz. v0.7 fed in the last 20 samples
assuming 0.1 s spacing, so at 5 Hz it read speeds as double. Now `edgeguard.learned.resample()` **interpolates the last 1.9 s onto a 10 Hz grid by time**,
and falls back to constant-velocity prediction if there is a gap longer than 0.8 s (`sim/lstm_irregular.py`, 3,080 unseen encounters, ADE / FDE m):

| Sampling condition | v0.7 (index-based) | v0.8 (time-based) | Constant-velocity Kalman |
|---|---|---|---|
| regular 10 Hz | 0.26 / 0.40 | **0.26 / 0.40** | 0.41 / 0.68 |
| jitter +-40 ms | 0.26 / 0.42 | **0.26 / 0.42** | 0.42 / 0.71 |
| 20 % uplink loss | 0.38 / 0.66 | **0.27 / 0.42** | 0.45 / 0.75 |
| 40 % loss + jitter | 0.72 / 1.33 | **0.30 / 0.46** | 0.52 / 0.86 |
| 5 Hz | 1.05 / 1.96 | **0.29 / 0.45** | 0.49 / 0.82 |
| adaptive 2 Hz -> 10 Hz | 0.69 / 1.17 | **0.28 / 0.44** | 0.42 / 0.69 |

v0.8 beats constant velocity in every condition, and under loss or low rates its error is 1/2 to 1/4 of v0.7's. The gap threshold was chosen by comparing 0.35 / 0.55 / 0.8 s
(`results/lstm_irregular.json`). No retraining was needed (the model input is again a 10 Hz grid).

PyTorch is required: run `pip install -r requirements-ml.txt`, then enable with `mec.method: guidance_lstm`.
The default is `guidance_ctrv`, which runs without PyTorch.

## Online closed-loop simulation (in place of site measurements)

`python -m sim.online_sim --cases all` → `results/online_sim.json`, `python sim/plot_online.py` → `results/online_sim.png`

![online simulation](../results/online_sim.png)

Instead of RC-car measurements, this simulation runs the entire real stack (Mobius → MEC app → alert) in real time.
Virtual devices **actually react** to alerts: forklifts slow to the received speed limit (actuator delay 0.2 s, deceleration 2.5 m/s²),
and workers stop 0.8 s after feeling the vibration (for 2 s). Each case runs 8 worker–forklift pairs simultaneously for 3 rounds (24 runs),
with injected communication and sensor faults. "Collision" = centre distance below 1.0 m.

| Case | Injected condition | Collisions (no system → with system) | Timely detection | Lead time | Alert latency p95 | Forklift lost time |
|---|---|---|---|---|---|---|
| Baseline | UWB noise 0.15 m, 10 Hz | 6 → **0** | 100% | 2.5 s | 115 ms | 2.0 s |
| Sensor noise | UWB 0.35 m | 8 → **0** | 100% | 2.5 s | 94 ms | 2.9 s |
| Uplink loss 10% | Sensor samples dropped | 8 → 1 | 100% | 2.4 s | 89 ms | 3.1 s |
| Uplink loss 30% | Sensor samples dropped | 6 → **0** | 100% | 2.5 s | 86 ms | 2.6 s |
| Alert loss 20% | Downlink alerts dropped | 7 → **0** | 57% | 2.4 s | 114 ms | 2.4 s |
| Wi-Fi latency | 60±30 ms both ways | 10 → 1 | 100% | 2.5 s | 263 ms | 3.7 s |
| 5 Hz sampling | Half the transmit rate | 9 → 1 | 100% | 2.4 s | 110 ms | 3.1 s |
| Clock skew | ±300 ms per device | 6 → **0** | 100% | 2.9 s | – | 2.3 s |
| UWB dead zone | Worker tag lost for 3 s | 8 → 1 | 100% | 2.6 s | 93 ms | 3.1 s |
| Abnormal behaviour | Running · zigzag · reversing forklift | 24 → 5 | 100% | 2.4 s | 144 ms | 6.2 s |
| Crowded aisle | 6+6 sharing one zone | 10 → **0** | 62%* | 2.5 s | 87 ms | 4.9 s |
| Worst-case combined | Noise + loss + latency + clock skew + dead zone | 8 → 3 | 100% | 2.9 s | – | 2.7 s |
| Proximity 5 m method (comparison) | Conventional proximity alert, 30% slowdown | 14 → 11 | 0% | 0.5 s | 98 ms | 4.3 s |

- Across the 12 EdgeGuard cases, **collisions fell from 110 → 12 (89% reduction)**. The proximity 5 m method under the same conditions went from 14 → 11 (21%), with longer forklift lost time.
- *The 62% timely detection in the crowded aisle is an underestimate. Workers and forklifts already stopped because of another pair do not hit the collisions of the original (non-reacting) timeline,
  while detection is measured against that original timeline. The actual number of collisions in this case is 0.
- Collisions stay at 0 with 20% alert loss even though timely detection drops, because alerts resent every second make up for the losses.
- Remaining weaknesses: **workers walking in a zigzag** (prediction wobbles) and workers approaching a **reversing forklift**. 5 of 24 runs in the abnormal-behaviour case ended in collision.

Control problems found by the simulation and fixed in v0.5:
1. **Release after slowing → re-acceleration collision**: once the forklift slowed, the predicted risk disappeared, the alert cleared, and the forklift sped up again and collided.
   → Keep the alert for a worker standing in the lane regardless of time, wait 2 s before clearing, and keep the forklift limited until a release signal (or 5 s without response).
2. **The ratio-command trap**: "×0.6 of current speed" is relative to an already reduced speed, so the forklift could speed up again → add an **absolute speed limit (m/s)** to alerts.
3. **Worker stop vs. slowdown plan**: if a worker stops in the middle of the lane after the vibration, a "slow down a little" command still hits them
   → compute the slowdown as the stricter of the "worker stops after reaction time" criterion and the stopping-distance criterion.
4. **Vibration overuse**: vibrating every second made workers keep stopping → vibrate only for new alerts, DANGER, or workers still walking in.
5. **MEC overload**: at 16 devices × 10 Hz, computing every pair on each sample pushed alert latency up to 1.1 s
   → compute only pairs involving the device that sent a new sample, and skip prediction for unreachable pairs. Alert latency p50 recovered to 60–80 ms.
6. **Reversing forklifts**: the IMU heading (forward) is opposite to the actual direction of travel (backward) → while moving, predict along the velocity vector.

## Policy learning (reward function + evaluation function)

`python -m sim.train_policy` → `results/policy_training.json`, `config/policy_trained.yaml`, `python sim/plot_policy.py`

![policy training](../results/policy_training.png)

We learned 10 parameters of the alert and slowdown policy (alert timing `t_warn` · `t_danger`, safety margin, assumed worker reaction, braking deceleration and margin,
lane check distance, pass-through speed, release wait, stationary speed threshold). The policy code (`edgeguard/alerting.py`) is shared by the MEC app and
the simulator, so what is learned runs unchanged on site.

- **Learner**: Cross-Entropy Method (gradient-free policy search), 14 candidates × 10 iterations, candidates compared on the same encounters.
  Fast closed-loop training simulator `sim/closed_loop.py` (same logic as the real-time online simulation, about 23 runs per second).
- **Domain randomisation**: per encounter, UWB noise 0.1–0.35 m, latency 40–220 ms, uplink loss 0–20%, alert loss 0–10%, 11 scenarios (including abnormal behaviour).
- **Reward function** (per encounter, maximised):

  `r = − C · collisions − forklift lost time (s) − 0.5 · unnecessary alerts`

  C means "how many forklift-seconds one collision is worth", so we trained separately with C = 5, 20, 50 and 100.
- **Evaluation function** (330 encounters not used in training, randomised conditions):
  - Precision = alerts raised for a real collision risk / all alerts; Recall = risks alerted at least 1 s before contact / all risks
  - **F-β, β = 2**: missed accidents (Recall) weigh more than unnecessary alerts (Precision)
  - Throughput = actual forklift distance travelled / distance it would have travelled without slowing
  - **Selection rule**: among safety-first candidates (collisions within 10% + 1 of the safest candidate), pick the one maximising `F2 × throughput / baseline throughput`

| Policy | Collisions | Recall | Precision | F2 | Throughput | Loss per encounter | Score |
|---|---|---|---|---|---|---|---|
| Baseline (hand-tuned) | 32/180 | 0.944 | 0.694 | 0.881 | 0.689 | 3.8 s | Rejected |
| C = 5 | 21/180 | 0.950 | 0.676 | 0.879 | 0.781 | 2.7 s | Rejected |
| C = 20 | 25/180 | 0.933 | 0.641 | 0.855 | 0.773 | 2.8 s | Rejected |
| **C = 50 (adopted)** | **15/180** | 0.950 | 0.653 | 0.871 | **0.784** | **2.7 s** | **0.991** |
| C = 100 | 14/180 | 0.978 | 0.759 | 0.924 | 0.659 | 4.1 s | 0.884 |

- If C is too small (5, 20), throughput rises but collisions remain; if too large (100), collisions are lowest but forklifts stop so often that throughput falls below the baseline.
  **C = 50** is the point that more than halves collisions versus the baseline (32 → 15) while raising throughput by 14%.
- The learned policy alerts earlier (3.0 → 4.1 s) and slows down less sharply, but with a higher pass-through speed (1.0 → 1.7 m/s), reducing time spent stopped.

**Real-time online simulation validation** (same 4 cases, `results/online_policy_*.json`):

| Policy | Collisions (sum of baseline · abnormal behaviour · Wi-Fi latency · worst-case combined) | Lead time | Forklift lost time | False alarm rate |
|---|---|---|---|---|
| Baseline | 48 → 8 | 2.5 s | 3.4 s | 25–56% |
| **Learned** | **48 → 3** | **3.5 s** | **2.4 s (−27%)** | 67–77% |

- Accidents fell further and forklift lost time also dropped. The price is a higher false alarm rate, which is the intended result of prioritising Recall with β = 2.
  Although there are more alerts, time spent stopped actually got shorter, so work throughput was maintained or improved.
- The learned policy has been applied to `config/site.yaml`. The "Online closed-loop simulation" table above shows results before it was applied (baseline policy).
