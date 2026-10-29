# Safety case

[← README](../README.md) · [한국어](ko/safety-case.md) · [robustness](robustness.md) · [comparison with site practice](site-compare.md)

A structured argument, in the spirit of a Goal Structuring Notation (GSN) safety case, for why EdgeGuard keeps workers and forklifts apart: the hazards, how each is mitigated, and the evidence for every claim. Everything here is **simulation and software evidence** (the project does not do real-device validation); it is the argument a pilot site would extend with field data, not a certification.

## Top-level claim

**G0.** In a warehouse where workers and forklifts share aisles, EdgeGuard keeps contact between them at least as rare as the strictest system sites use today (a 6 m / 3 m UWB proximity alarm), while keeping trucks productive - under normal **and** exceptional conditions.

Context: the many-to-many floor of [`sim/multi_sim.py`](../sim/multi_sim.py) (36 x 24 m, 8 workers, 4 forklifts, randomised network and UWB noise), the scenarios of [`sim/robust_eval.py`](../sim/robust_eval.py), the device rules of [`edgeguard/device_policy.py`](../edgeguard/device_policy.py) and the firmware ([`firmware/`](../firmware)).

## Hazards

| ID | Hazard | Typical cause |
|---|---|---|
| H1 | A truck reaches a person who crosses or stands in its path | late warning, the person does not stop, the truck cannot stop in time |
| H2 | A person walks into a truck from the side | the person walks on after a WAIT (non-compliance, timeout), a sidestep in the wrong direction |
| H3 | The MEC app is silent or restarts | host fault, software update, network partition |
| H4 | Messages are lost, late or out of order | lossy radio, congested cell, jitter |
| H5 | Positions are wrong | UWB noise, non-line-of-sight, tracker lag |
| H6 | Alarms nobody heeds | nuisance alarms teach people to ignore the tag (the main reason proximity systems are switched off) |

## Claims, arguments and evidence

| Claim | Argument (mitigation) | Evidence |
|---|---|---|
| **C1** A conflict is predicted early enough to act (H1) | collision-course prediction on the MEC host (worker CV / forklift CTRV), WARNING at the learned lead time, the worker yields (WAIT / STEP ASIDE), the truck is limited to its stopping envelope | [`tests/test_alert_state.py`](../tests/test_alert_state.py), [`tests/test_multi_pair.py`](../tests/test_multi_pair.py); site comparison and large-scale test ([site-compare.md](site-compare.md)) |
| **C2** A truck stops short of a person in its path (H1, H4) | **stop point** ("movement authority"): the module brakes for a site position from its own pose every 0.1 s, with `v_cap(d) = a(-tau + sqrt(tau^2 + 2d/a))`, a = 2.3 m/s^2 < the drive's 2.5, tau = 0.1 s; latency and a lost refresh cannot delay braking | [`tests/test_stop_guarantee.py`](../tests/test_stop_guarantee.py) (property-based, ~5,000 cases on the exact device and drive code): a point received in time is **never passed**; a late one is overshot by at most the physical stopping distance; it holds through MEC silence; firmware = Python ([`tests/test_device_policy.py`](../tests/test_device_policy.py)) |
| **C3** The stop point is placed where stopping keeps the safety radius (H5) | placed `sqrt(r_safe^2 - lat^2) + env_margin` before the person along the path; rounded towards the truck; held against position noise (only moves closer, or farther once he has really moved) | `test_stop_point_placement_keeps_r_safe`: distance >= r_safe for along-path errors within `env_margin` (0.505 m in the adopted policy) |
| **C4** A person who walks on into a truck is still protected (H2) | GO only when walking on is safe for every truck; a tag keeps WAIT through MEC silence while its own D2D rule sees a truck close; STEP ASIDE only to a side clear of every truck and never across a path; **always-on D2D emergency brake** on the forklift module (collision course within 1.5 s, closest approach < 1.3 m) independent of MEC and network | [`tests/test_device_policy.py`](../tests/test_device_policy.py) (`test_aeb_*`, firmware equivalence), [`tests/test_worker_cue.py`](../tests/test_worker_cue.py); scenarios comply 85 % / 70 % |
| **C5** Silence or a restart of the MEC app does not create a gap (H3) | silence: hold the last plan 1.3 s, then stop a truck under a plan after 2 s; the local D2D rule runs while MEC is silent **and 1.5 s after it returns** (a restarted app has lost its alert state); stop points are part of the held plan; **tag GO check**: a WAIT that runs out unheard, or one given before the silence that is then cleared (the restarted app may have lost it), ends only when walking on at the worker's last pace would not meet a truck (D2D); a truck standing before someone in its path stays stopped | `test_silence_never_lifts_the_limit`, `test_local_fallback_only_while_mec_silent`, `test_stop_point_survives_silence`, `test_tag_go_check_sees_the_truck_he_would_walk_into`, `test_wait_is_orphaned_only_by_a_silence_after_it`, `test_firmware_tag_go_check`; scenario MEC restart |
| **C6** Lost, late and overtaken messages do not change the outcome (H4) | plan confirmation: the forklift reports every plan it applies (motion samples, SDT speedLimit module) and the MEC app re-sends what is missing; devices drop a message older than the last one applied for the pair | `test_plan_not_reported_by_the_forklift_is_sent_again`, `test_plan_report_through_the_twin_confirms_the_plan`, `test_late_message_is_dropped`, `test_firmware_msg_order`; scenario bad network |
| **C7** Alarms stay worth heeding (H6) | a person near a path limits the truck quietly (no buzz); predicted conflicts only; one cue per encounter | alarms per forklift-hour and the share not needed ([site-compare.md](site-compare.md)) |
| **C8** The policy is not tuned to the test (all) | trained on seeds 10,000+ ... 100,000+, picked on separate validation seeds with no collision, reported on test seeds never used for either; candidates that failed validation are reported, not hidden | [robustness.md](robustness.md) (rejected: refinement with 4 validation collisions, the sensor-upgrade policy with 2) |

## Assumptions (what the argument rests on)

| ID | Assumption | Where it enters | If it does not hold |
|---|---|---|---|
| A1 | The drive decelerates at >= 2.5 m/s^2 when commanded, within 0.2 s | C2 | lower `STOP_DECEL` in the module (a site parameter) |
| A2 | The worker's position error along the truck's path is <= `env_margin` (0.5 m) | C3 | the noisy-UWB scenario (0.35-0.6 m) is where the remaining collisions were; positioning quality is a deployment requirement |
| A3 | Both devices broadcast their state peer to peer (ESP-NOW / sidelink), 10 Hz, about 25 m | C4, C5 | without D2D the emergency brake and the silence fall-back are off; the MEC plan and the 2 s stop remain |
| A4 | A worker told to WAIT stops after about 0.8 s (compliance modelled 100 / 85 / 70 %) | C1, C4 | measured in the scenarios with 85 % and 70 % compliance |
| A5 | The simulation's physics and human models represent a site well enough to rank systems | G0 | the ranking against proximity alarms is large (throughput 2.0 x, 0 vs 12 collisions against the narrowed alarm); absolute numbers need field data |

## Residual risk

- **Measured** ([large-scale test](robustness.md#large-scale-test-8000-fresh-episodes-per-policy-with-confidence-intervals), 8,000 fresh episodes, 34,644 conflicts under the 8 scenarios): the adopted policy v3 had **2 collisions, 0.06 per 1,000 conflicts [95 % CI 0.02-0.21]**, both right after a MEC restart; v2 had 5 (0.14), the previous policy 30 (0.87). No collision in seven of the eight scenarios, nor in 3,617 conflicts of the site comparison ([site-compare.md](site-compare.md#large-scale-test-1000-fresh-episodes-with-confidence-intervals)).
- **Not covered by the simulation:** people running, people hidden from UWB entirely, trucks reversing on unplanned routes, loads that block the driver's view, hardware faults of the modules themselves (a site would add the module's own diagnostics and a watchdog).

## Related standards (orientation, not a compliance claim)

- OSHA 29 CFR 1910.178(n)(8): trucks are to be operated at a speed that allows a safe stop - the stopping envelope and stop points make this explicit per person.
- ISO 3691-4 (driverless industrial trucks): personnel detection and speed reduction zones - the closest analogue for automated speed control around people.
- ISO 13849-1 (safety-related parts of control systems): the emergency brake and the silence fall-back are on the module (local, independent of the network), the part that would be designed to a performance level in a product.
