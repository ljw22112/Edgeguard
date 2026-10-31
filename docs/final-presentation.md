# Final presentation: script

[← README](../README.md) · deck: Slides artifact *EdgeGuard Final Presentation* (download as PPTX / PDF from the deck) · Q&A: [interview-qa.md](interview-qa.md)

Speaker notes of the 15 slides, about 11 minutes at 140 words per minute. Numbers match `results/large_eval.json`.
Total: 1651 words, about 12 minutes.


## 1. EdgeGuard  (73 words, ~31 s)

Good morning. We are Team EdgeGuard from Sejong University. EdgeGuard predicts collisions between warehouse workers and forklifts one to three seconds ahead, on the network edge, and tells each person exactly what to do: wait, step aside, or go. It is built on oneM2M and ETSI MEC. In the next ten minutes: why today's systems force sites to choose between safety and productivity, how EdgeGuard works, and the evidence that it gives both.

## 2. People and forklifts share the same aisles  (77 words, ~33 s)

Forklifts and people share the same aisles. In Korea alone, two thousand five hundred fifty-nine people were hurt or killed in forklift accidents in two years. One injury costs a company about one hundred sixteen thousand dollars once indirect costs are counted, and in Korea a fatal accident can also bring criminal liability for executives. The hard part is time: at a blind corner, a walker may have two seconds between seeing a truck and being hit.

## 3. A proximity alarm makes sites choose: safe or productive  (100 words, ~43 s)

What do sites use today? Speed limits, and UWB proximity alarms: a tag on the worker, an anchor on the truck. We modelled one the way commercial systems work: a warning zone where the truck slows to walking speed, a danger zone where it stops. Set wide, at six and three metres, it prevented every collision in our test, but trucks ran at forty-eight percent of their normal throughput. So sites narrow the zones. At four and two metres the nuisance drops, but forty-nine collisions got through. The root cause is that a distance alarm has no notion of direction.

## 4. Predict the collision course, and tell each person what to do  (120 words, ~51 s)

EdgeGuard asks a different question: not how close, but will they meet. The test comes from missile guidance: if the bearing stays constant while the range closes, two objects are on a collision course. A truck that will pass by never raises an alert. When a meeting is coming, the worker's tag says WAIT, and GO once the truck has passed, or STEP ASIDE if the worker is standing in the lane. The truck keeps its speed as long as it can still stop short of the person; when it cannot, it gets a stop point and brakes for it by itself. The decision runs on the ETSI MEC edge in about twenty-five milliseconds, and everything is a oneM2M resource.

## 5. A MEC host per zone  (107 words, ~46 s)

Here is the architecture. Each warehouse zone has a MEC host with a oneM2M MN-CSE. Worker tags and forklift modules register their own application entities on that CSE. The EdgeGuard MEC app runs next to it as a container: it subscribes to positions, decides, and writes alerts back as oneM2M resources, which the CSE pushes to the tags and forklifts. A MEC interworking proxy brings ETSI MEC location and radio information into the same CSE. In the cloud, an IN-CSE holds home records for devices moving between zones, runs federated learning across sites, and hosts the AI safety agent. In ESTIMED terms this is deployment option C.

## 6. The CSE does the work our own server would do  (144 words, ~62 s)

Why oneM2M? Because the CSE does the work our own server would otherwise have to do. Subscriptions replaced a broker and polling code. Device twins are SDT flexContainers with labels and SAREF semantics, so a new tag is found by one discovery request and onboarded in about nine seconds, without a device list. Access control is built in: one ACP per device, and with a child-type restriction the MEC app can create subscriptions in a twin but never write data into it. A group fan-out point sends one DANGER alert to every tag in a zone in a single request, and polling channels reach tags behind NAT. Announcement and CSE handover let a forklift's presence move between zones. Devices use the MQTT binding over mutual TLS. The same code runs on Mobius and ACME, and we reported two bugs to ACME along the way.

## 7. MEC services reach the app through oneM2M, both ways  (122 words, ~52 s)

ETSI MEC services reach our application through oneM2M. A MEC interworking proxy subscribes to MEC 013 zone events and MEC 012 per-device signal strength and writes them into the CSE as SDT twins; oneM2M applications can also post MEC requests the other way. A zone event triggers the CSE handover, with one and a half to eight milliseconds of interruption and no samples lost. Applications are deployed by intent: one oneM2M resource drives discovery, host selection, deployment and Mp1 service registration, and when a host crashes the app runs again elsewhere in two to three seconds. On the edge the median alert latency is twenty-five milliseconds, against eighty-five for a cloud-only path. We ran this live on the public ETSI MEC Sandbox.

## 8. No server, still safe: four layers of protection  (157 words, ~67 s)

A safety system is judged by its bad days, so protection is layered. The MEC app does the prediction and the guidance, and a standby takes over in under a second. Stop points live on the truck: the module brakes for its point from its own position every cycle, so a lost or late message does not delay braking. Devices broadcast their state to each other directly, signed, and when the MEC app goes quiet, for example after a restart, the tag checks for itself whether it is safe to walk on. And the last line is an always-on emergency brake on the forklift module: a person on a collision course within one and a half seconds stops the truck, and since version 3.1 the truck stays stopped while that person is in front of it. All of this is the same code in our Python reference and the ESP32 firmware, and CI checks that they agree.

## 9. As safe as the wide alarm, at twice the throughput  (99 words, ~42 s)

Now the evidence. Every system ran on the same one thousand simulated episodes: eight workers, four forklifts, three thousand six hundred seventeen conflicts, and nobody looks out, so this is what each system alone prevents. These episodes were never used to train, select or tune our policy. EdgeGuard had zero collisions, like the wide proximity alarm, but trucks kept ninety-seven point three percent of their throughput, twice the alarm's forty-eight. It raised eighty-one percent fewer alarms and halved the time workers spent waiting. Against the narrowed alarm, it is zero collisions instead of forty-nine and thirty-seven points more throughput.

## 10. 30 collisions to 0, under eight exceptional conditions  (106 words, ~45 s)

A safety system has to hold up on bad days. We ran eight thousand more fresh episodes under eight conditions: a bad network with up to six hundred milliseconds of delay and forty percent loss, the MEC app restarting and losing its state, workers who ignore fifteen or thirty percent of alerts, noisy positioning, a dense floor and attentive drivers. Our previous policy had thirty collisions in thirty-four thousand six hundred forty-four conflicts. The current version, 3.1, had none; the upper bound of the ninety-five percent interval is about one in nine thousand conflicts. And trucks were faster in every scenario, by five to ten points.

## 11. Trace every collision, fix the cause, retest on new seeds  (134 words, ~57 s)

How did we get to zero? Not by tuning until the numbers looked good. Every collision the simulator found was traced to its cause, fixed in both the Python reference and the firmware, and checked again on seeds the fix had never seen. Four examples: stop points that crept away with position noise; a sidestep that led a worker into a second truck; a WAIT lost when the MEC app restarted, which led to the tag checking GO itself; and in version 3.1, an emergency stop that released while the person still stood in front of the truck. We train, select and test on separate seeds, and we reject candidates that are faster but less safe. The safety case lists six hazards and eight claims, each linked to the tests that are its evidence.

## 12. Learning across sites, trucks that coordinate, an agent that reports  (115 words, ~49 s)

Beyond a single zone. Worker trajectories are personal data, so each site trains a small motion model on its own data, and only the weights travel through oneM2M, following TR-0084. The two-second prediction error dropped from sixty to forty-nine centimetres, and new models go through canary, activation and rollback. Forklifts form a swarm: they share their plans through a oneM2M group and each computes the same conflict-free schedule, cutting total delay from twenty-three and a half seconds to fourteen and a half. And an AI safety agent writes shift reports by calling MCP servers for the cloud CSE, both zone CSEs and ETSI MEC. Every one of these demos runs in CI on every commit.

## 13. Low-cost devices, paid back by forklift time  (120 words, ~51 s)

Is it worth it? A ten-thousand-square-metre warehouse with fifty workers and ten forklifts costs about fifteen thousand dollars up front, with low-cost ESP32 and UWB devices and two edge servers. Against a proximity alarm, a forklift loses one point four seconds per encounter with a person; with EdgeGuard, under a tenth of a second. At ten to thirty encounters an hour that pays the system back in one to three and a half years on time alone, and a single prevented injury pays for it eight times. Revenue comes from the hardware kit, a subscription, and bundling with operators' private 5G and MEC offers. And because alerts are oneM2M resources, a site's warehouse system can use them simply by subscribing.

## 14. What is real, and what is simulated  (114 words, ~49 s)

We want to be clear about scope. What is real and checked on every commit: the oneM2M resources on real Mobius and ACME CSEs; the ESP32 firmware, compiled unmodified for a PC and run against a real CSE over HTTP, MQTT and mutual TLS; handover, orchestration, federated learning and the agent; and live runs on the public ETSI MEC Sandbox. What is simulated: the workers and drivers, and therefore the collision and throughput figures; and the proximity alarm uses typical settings, not one product's. Running people, people hidden from UWB and unplanned reversing are not covered yet. The next step is a board demo and a pilot at a site, measured with near-miss data.

## 15. Safe and productive, not one or the other  (63 words, ~27 s)

To sum up: today sites choose between a safe alarm and a productive one. EdgeGuard gives both: zero collisions at twice the throughput of a proximity alarm, and zero in thirty-four thousand conflicts on bad days, built on standard oneM2M and ETSI MEC. The code, the judge site and the video are linked here. Thank you, we are happy to take your questions.
