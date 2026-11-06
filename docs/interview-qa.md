# Interview preparation: expected questions and answers

[← README](../README.md)

These are short answers for the finals interview (rubric item 9: the resource tree, the benefits of oneM2M, how the integration works). Every number comes from CI or from `results/`; the file behind each claim is named.

## oneM2M design

**Q1. Walk us through your resource tree.**
Each device is its own AE on the zone MN-CSE (`worker_01`, `forklift_01`), with its own ACP.
- The twin is a flexContainer from our SDT domain: `egs:wrkTg` for tags and `egs:frkMe` for forklift modules, with `kinematics`, `cue`/`speedLimit` and `cod:bat` modules.
- A SAREF semanticDescriptor sits next to it.
- The MEC app is its own AE, `EdgeGuard`, with `risk`, `alert`, `control` and `nearmiss` containers, plus one `<group>` per zone.
- The IN-CSE holds home records (`<dev>/serving`), announcements, the FL coordinator, the orchestrator and the AI agent's state.

[data-model.md](data-model.md), [deployment.md](deployment.md#onem2m-resource-tree).

**Q2. Why flexContainers and not plain containers?**
The device's state is typed and self-describing (`egs:kinSt` has `posX`, `speed`, `smpTe` and so on), so another application understands it without our code. An update notifies subscribers with only the changed module, and `mni` keeps the history as flexContainerInstances. New devices onboard by label discovery (`egs:module/kinematics`), with no device list: a self-registered tag is picked up in about 9 s.

**Q3. Which oneM2M features did you use that a plain MQTT broker would not give you?**
- discovery by label, and semantic queries (SAREF)
- ACPs with `accessControlObjectDetails`: the MEC app may create subscriptions but no data in a twin
- announcement and Mcc between zone MN-CSEs and the IN-CSE
- `<group>` fan-out: one request reaches every tag in a zone
- `<pollingChannel>` for tags behind NAT
- portable subscriptions that follow a device on handover

**Q4. How does CSE handover work, and what is preserved?**
Make-before-break:
1. The device keeps publishing to zone A while it rebuilds its twin on zone B: state, ACP, every subscription (subscribers attach the device's ACP so it can carry them) and the announcement.
2. It switches, updates its home record and releases zone A.

Triggers are location, CSE availability, or a MEC zone event. Results:
- location trigger: interruption 1.5–11 ms, 0 samples lost
- availability failover: about 0.3 s, with 3 samples lost in the detection window

[handover.md](handover.md).

**Q5. What happens if the network or the MEC app fails?**
The devices notice that the MEC heartbeat is missing and switch to local rules: UWB ranging between devices, D2D state exchange over HMAC-signed ESP-NOW, and alert relay to neighbours in coverage holes. They stop only when nothing else is known. In a total outage, collisions drop from 180 to 2 while forklifts keep 57 % throughput. A standby MEC app takes over in 0.73 s. [resilience.md](resilience.md).

## ETSI MEC integration (ESTIMED / TR-0077 clause 7)

**Q6. Where does EdgeGuard sit on the ESTIMED deployment continuum?**
Option C per zone: the MN-CSE, the MEC app and the MEC-IPE share the zone's MEC host. The IN-CSE runs in the cloud. [estimed-mapping.md](estimed-mapping.md).

**Q7. How do MEC services reach oneM2M applications, and the other way round?**
- **MEC → oneM2M:** the MEC-IPE subscribes to MEC 013 zone events and MEC 012 MeasRepUe reports and writes them as SDT twins (`egs:mecUe`, `egs:ueLoc`, `egs:rdLnk`) and zone-event contentInstances. Median latency is 15–45 ms.
- **oneM2M → MEC:** an application posts `{op: zone_subscribe | radio_subscribe | location}` into `MEC-IPE/requests`, and the IPE answers in `responses`. Applications never hold MEC credentials.

[mobility.md](mobility.md).

**Q8. How is a MEC application deployed?**
1. An operator creates one `egs:depIn` intent.
2. The orchestrator discovers hosts by label (`egs:mecHs`, with a one-second heartbeat) and selects one by zone, CPU, memory and latency.
3. It deploys through the host's lifecycle API. The instance is a real container (`deploy/edge-app`).
4. It waits for the instance to register its own AE, then provisions it: device ACP grant plus configuration.

When a host crashes, the instance is re-placed in about 2.5 s and the old grants are revoked. [orchestration.md](orchestration.md).

**Q9. How is federated learning done, and how does the model get to the edge?**
- **Learning:** TR-0084 roles as oneM2M resources: task, participants, rounds, and model versions with lineage. Participants are found by label, and dropout and late join are tolerated. Only weights travel. The 2 s prediction error goes from 0.604 m (constant velocity) to 0.486 m.
- **Delivery:** each site canaries a new version on its own held-out data, activates it in the risk engine (`guidance_fl`), shadow-evaluates the previous version, and rolls back on regression. The status is kept in `egs:mdlDp`.

[federated-learning.md](federated-learning.md), [swarm-and-model-delivery.md](swarm-and-model-delivery.md).

**Q10. What is "swarm" in your system?**
Forklifts in a zone form a `<group>` of their plan containers. Each member reads the whole context with one request (`<group>/fopt/la`) and computes the same conflict-free schedule itself, so no coordinator is needed. In the demo, conflicts drop from 4 to 0, with 14.5 s of total delay against 23.5 s for braking at each intersection.

## Security and privacy

**Q11. How do you secure devices?**
- Each device has its own certificate from the site CA, and its CN is its originator. The broker's mutual-TLS listener takes the CN as the identity, and its ACL lets a device publish only as itself.
- Revocation goes through a CRL; rotation means a new key plus revoking the old serial.
- Applications use HTTPS.
- In CI, these are refused: no certificate, a certificate from another CA, impersonation, a revoked certificate, plaintext and a wrong password.

[transport-security.md](transport-security.md).

**Q12. Does personal data leave the site?**
Worker trajectories stay in the zone's edge CSE. Only alerts, risk summaries and near-miss records (event positions) go to the cloud. Federated learning moves weights, never positions, and CI checks that.

## Engineering and evidence

**Q13. How do you know the firmware works without boards?**
The unmodified ESP32 firmware is compiled for a PC (software-in-the-loop) and talks to a real ACME CSE on every commit. It runs over HTTP, over the MQTT binding with TLS, and with device certificates. CI checks the WAIT/GO cue, the forklift speed limit, the beacon and the confirmations.

**Q14. Which interoperability problems did you find?**
Seven are documented in [interop-notes.md](interop-notes.md). Two ACME bugs were reported upstream, and the maintainer fixed both in release 2026.05.3 three days later:
- [#199](https://github.com/ankraft/ACME-oneM2M-CSE/issues/199): Content-Type with media-type parameters was not parsed.
- [#200](https://github.com/ankraft/ACME-oneM2M-CSE/issues/200): the MQTT binding could not send requests. With the fix, our tags now receive alerts over MQTT too (CI, p50 ≈ 10 ms).

The same code runs on ACME and KETI Mobius.

**Q15. What is simulated, and what is real?**
- **Real:** the oneM2M CSEs (ACME, Mobius), the MQTT broker with TLS, the containers, and the firmware compiled for a PC.
- **Simulated:** UWB error and people's behaviour (with sensitivity analyses), the MEC platform for events (`mec_mock` plays AdvantEDGE scenarios; the polling path ran on the ETSI Sandbox), and the MEC hosts.

The board demo and the user study are next.

**Q16. Why should a site adopt this rather than a proximity alarm?**
Because a proximity alarm makes the site choose. On the same 1,000 fresh simulated episodes (3,617 conflicts), the wide alarm (6 m / 3 m) had 0 collisions but 48.3 % throughput; narrowed to 4 m / 2 m it had 49 collisions. EdgeGuard had 0 at 97.2 %, with 81 % fewer alarms and half the worker waiting. A distance alarm cannot tell a truck that will pass from one that will hit; EdgeGuard tests the collision course and tells each person what to do. Because alerts are standard oneM2M resources, a WMS or dashboard can use them without integration work. [site-compare.md](site-compare.md), [business.md](business.md).

## Safety evidence

**Q17. Zero collisions sounds too good. How do you know?**
First, we do not claim zero any more: the adopted v3.2 had 1 collision in 34,644 conflicts, with a truck that had already stopped. Then three things. (1) The test episodes (seeds 21,000+ and 23,000+) were never used to train, select or tune the policy; training, validation and test seeds are separate, and a faster candidate that had 4 collisions on validation was rejected. (2) We report 95 % intervals, not only counts: v3.2's 1 in 34,644 conflicts has an upper bound of 0.16 per 1,000 conflicts, and the previous policy's interval (0.61–1.24) lies well above it. Every collision also records the truck's speed at contact. (3) It is simulation with modelled people, checked with two walker models (Q27); we say so on every chart. [large_eval.py](../sim/large_eval.py), [robustness.md](robustness.md).

**Q18. What changed from v3 to v3.1, and why?**
v3 had 2 collisions in 34,644 conflicts, both after a MEC restart. Traces showed the emergency brake stopped the truck and then released it: a person standing right in front is no longer "closing fast", so the collision-course test went quiet. v3.1 holds the brake while that person is ahead in the truck's path (3 m ahead, 1.3 m aside), and within 1.8 m any closing speed counts. Checked on development and validation seeds first, then on the test seeds: 0 collisions, close passes −24 %, same throughput. Same change in Python and firmware, equivalence tests in CI.

**Q19. What if the network or the MEC app fails?**
Four layers: the MEC app (standby takeover 0.73 s); stop points that the truck brakes for from its own position; device-to-device state, with the tag checking GO itself when the MEC app is silent; an always-on emergency brake on the forklift module. Under bad network (300–600 ms, up to 40 % loss) and MEC restart scenarios: 0 collisions in 7,492 conflicts (v3.2, straight walkers); with social-force walkers 1, with the truck already stopped. [safety-case.md](safety-case.md).

**Q20. Is the comparison with the proximity alarm fair?**
Same floor, same episodes, same sensing noise for every system. The alarm follows how commercial UWB systems work (warning zone: slow to walking speed and vibrate; danger zone: stop), with two zone settings sites use. Products differ and sites tune them, so we call these typical settings, not one product. With an attentive driver the picture is the same: EdgeGuard 0 collisions at 96.0 %, narrowed alarm 20. [site-compare.md](site-compare.md).

**Q21. What does the worker experience? Is WAIT annoying?**
About 7 alarms per episode against 38 for the wide proximity alarm, and 2.1 s of waiting per worker per episode against 4.3 s. WAIT holds only until the truck has passed, then GO; a standing worker in the lane gets STEP ASIDE to a side clear of every truck. A user study with real people is planned; today the behaviour is modelled, including workers who ignore 15 % or 30 % of alerts (still 0 collisions).

**Q22. What does it cost, and when does it pay back?**
About USD 15,100 up front for 10,000 m², 50 workers, 10 forklifts. Against a proximity alarm a forklift loses 1.38 s per encounter, with EdgeGuard 0.07 s: about KRW 6–18 million a year, payback 1.2–3.5 years on time alone. At a quiet site the time savings roughly cover the subscription, so the case there rests on safety; one prevented injury (about USD 116,000) pays the system 8 times. [business.md](business.md).

**Q23. What would you do with three more months?**
A board demo with ESP32 tags and modules, a user study (do people follow WAIT / GO, how long they wait), and a three-month site pilot measured with near-miss data. Technically: people running and people hidden from UWB (camera fusion), and the module's own diagnostics and watchdog for a product.

**Q24. Which TR-0086 deployment option did you choose, and why?**
Option C in each zone: the MN-CSE runs as a MEC app on the same MEC host as our MEC app and the MEC-IPE, with an IN-CSE in the cloud. A collision warning has a 1-3 s budget, so the CSE, the decision and the MEC data sit together: 25 ms median alert latency instead of 85 ms cloud-only, trajectories stay in the zone, and a zone keeps working if the cloud link fails. We also cover the guide's optional steps, 5.5 handover (triggered by MEC zone events, RNIS signal strength or AMS) and 5.6 location (MEC 013 plus the device's own UWB position). We used our own ACME MN-CSEs rather than the local MEC Sandbox. [tr0086-mapping.md](tr0086-mapping.md).

**Q25. Your MEC platform is a stand-in. How do you know your MEC integration is right?**
We check EdgeGuard's own MEC traffic against the official ETSI Forge OpenAPI files in CI: every request, response and notification of MEC 011, 012, 013 and 021 that our clients exchange. The first run found real mismatches (a v2-style callbackReference, names where ETSI uses integer codes, missing `_links`); after fixing them, 19 of 19 exchanges and 160 of 160 notifications conform. Where the published files themselves are inconsistent, the validator records it instead of bending our code. The polling path also ran against the public ETSI MEC Sandbox. [ecosystem.md](ecosystem.md).

**Q26. Does it only work on the CSEs you chose?**
The application code runs on ACME and KETI Mobius, and the oneM2M tutorial runs on a third, independent CSE, tinyIoT, in CI. A feature probe shows what each CSE supports (ACME 13 of 13, tinyIoT 9 of 13), and every difference is documented with what EdgeGuard does about it. [interop-notes.md](interop-notes.md).

**Q27. Your simulated people walk in straight lines. Isn't that too simple?**
It was, so we added a second walker model: Helbing's social force model through PySocialForce (MIT). The same people now drift sideways, change pace, hesitate for 0.6-2 s and avoid each other (speed spread 0.17 -> 0.26, straightness 1.00 -> 0.95); they still do not look out for trucks. On the same 8,000 test episodes (35,248 conflicts), **no moving truck touched anyone under v3.2**; the previous policy had 5 such contacts, up to 0.69 m/s. There were 4 collisions, all with a truck already standing still: a person who does not look walks into it, and only the warning can stop that. These runs also found one development-seed case that led to v3.2 (emergency-brake distance 1.3 -> 1.5 m), adopted before the test run. Throughput is 93.6 % against 86.1 % for the previous policy. What neither model has: people running, and the truck's real footprint (we count any centre distance under 1.0 m). [robustness.md](robustness.md#policy-v32-and-a-second-walker-model).
