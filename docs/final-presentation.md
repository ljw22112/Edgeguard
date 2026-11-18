# Final presentation: script

[← README](../README.md) · deck: Slides artifact *EdgeGuard Final Presentation* (download as PPTX / PDF from the deck) · Q&A: [interview-qa.md](interview-qa.md) · rehearsal pack (Korean): [ko/presentation-rehearsal.md](ko/presentation-rehearsal.md)

Speaker notes of the 16 main slides, written for a 10-minute slot (about 125 words per minute), plus three backup slides for the Q&A. Jeongwon presents slides 1-8, Kihwan slides 9-16. Numbers match `results/large_eval.json` and `results/large_eval_social.json`.
Total (main slides): 1168 words, about 9.3 minutes at 125 words per minute. With the demo video (1 min 41 s) after slide 8: **about 11 minutes**, inside the organisers' 10-15 minutes, leaving about 9 minutes of the 20-minute slot for questions.


## 1. EdgeGuard  (Jeongwon (jw), 59 words, ~28 s)

Good morning. We are Team EdgeGuard from Sejong University. I'm Jeongwon Lee, and this is my teammate Kihwan Kim. EdgeGuard predicts collisions between warehouse workers and forklifts one to three seconds ahead, on the ETSI MEC edge, and tells each person exactly what to do: wait, step aside, or go. It is built on oneM2M from end to end.

## 2. People and forklifts share the same aisles  (Jeongwon (jw), 57 words, ~27 s)

Forklifts and people share the same aisles. In Korea alone, two thousand five hundred fifty-nine people were hurt or killed in forklift accidents in just two years. One injury costs a company about one hundred sixteen thousand dollars. And the hard part is time: at a blind corner, a worker may have only two seconds to react.

## 3. A proximity alarm makes sites choose: safe or productive  (Jeongwon (jw), 81 words, ~39 s)

So what do sites use today? Mostly UWB proximity alarms. We modelled one the way commercial systems work: the truck slows down in a warning zone and stops in a danger zone. With wide zones, six and three metres, there were no collisions in our test, but trucks kept only forty-eight percent of their throughput. So sites narrow the zones. At four and two metres, forty-nine collisions got through. The reason is simple: a distance alarm has no sense of direction.

## 4. Predict the collision course, and tell each person what to do  (Jeongwon (jw), 96 words, ~46 s)

EdgeGuard asks a different question: not how close, but will they meet? We borrowed a test from missile guidance. If the bearing stays the same while the distance shrinks, two objects are on a collision course. So a truck that will pass by never raises an alert. When they will meet, the worker's tag says WAIT, and GO once the truck has passed, or STEP ASIDE if the worker stands in the lane. The truck keeps its speed while it can still stop. If not, it gets a stop point and brakes for it by itself.

## 5. A MEC host per zone  (Jeongwon (jw), 82 words, ~39 s)

Here is the architecture. Each warehouse zone has a MEC host with a oneM2M MN-CSE. Worker tags and forklift modules register as their own AEs on that CSE. Our MEC app runs right next to it. It subscribes to positions, decides in about twenty-five milliseconds, and writes alerts back as oneM2M resources. In the cloud, an IN-CSE keeps track of devices that move between zones, and runs federated learning and an AI agent. In the TR-0086 developer guide, this is option C.

## 6. The CSE does the work our own server would do  (Jeongwon (jw), 82 words, ~39 s)

Why oneM2M? Because the CSE does the work our own server would otherwise have to do. Subscriptions replace a message broker and polling. Access control is built in: one ACP per device, and the MEC app can only create subscriptions, never write data into a device. One group request alerts every tag in a zone, even behind NAT. Devices use MQTT over mutual TLS. And we tested on three CSEs, Mobius, ACME and tinyIoT, and reported two ACME bugs, which were fixed.

## 7. One AE per device, a standard twin  (Jeongwon (jw), 72 words, ~35 s)

This is the actual resource tree on a zone CSE. Every tag and forklift module is its own AE. Its state is an SDT flexContainer twin: kinematics, the cue it shows or the speed limit it enforces, and battery. A SAREF semantic descriptor makes each device self-describing. The MEC app finds new devices with one label query, subscribes to their kinematics, and writes risk, alerts and near misses into its own AE.

## 8. MEC services reach the app through oneM2M, both ways  (Jeongwon (jw), 89 words, ~43 s)

ETSI MEC reaches our app through oneM2M, in both directions. A MEC interworking proxy turns MEC location zone events and radio signal strength into oneM2M resources. A zone event triggers the CSE handover, with only a few milliseconds of interruption and no data lost. Apps are deployed from one intent resource, and if a host crashes, the app runs again elsewhere in two to three seconds. We also ran this on the public ETSI MEC Sandbox. Let's see it running.

## ▶ Demo video after slide 8  (play `results/edgeguard_demo_clip.mp4`, 1 min 41 s, narrated)

Live demo (WAIT → GO, STEP ASIDE, two forklifts), the ESP32 firmware against a real CSE with a phone as the worker tag, and the zone handover driven by ETSI MEC events. The clip is cut from the final video and carries its own narration and captions, so nobody speaks over it. Afterwards Jeongwon hands over: "Now Kihwan will show you how we keep people safe, and the evidence."

## 9. No server, still safe: four layers of protection  (Kihwan, 92 words, ~44 s)

Thank you. A safety system is judged by its bad days, so we built four layers of protection. One: the MEC app, with a standby that takes over in under a second. Two: stop points live on the truck, so a late message never delays braking. Three: devices talk to each other directly, and the tag checks GO by itself when the server is silent. Four: an always-on emergency brake on the forklift. The same logic runs in our Python code and in the ESP32 firmware, and CI checks that they agree.

## 10. As safe as the wide alarm, at twice the throughput  (Kihwan, 68 words, ~33 s)

Now the results. Every system ran on the same one thousand simulated episodes, with eight workers and four forklifts. We never used these episodes for training or tuning. EdgeGuard had zero collisions, just like the wide alarm, but trucks kept ninety-seven percent of their throughput. That is twice as much. It also raised eighty-one percent fewer alarms. Against the narrowed alarm, it is zero collisions instead of forty-nine.

## 11. 30 collisions to 1, and no moving truck touching anyone  (Kihwan, 78 words, ~37 s)

But what about bad days? We ran eight thousand more episodes: a bad network, server restarts, workers who ignore alerts, noisy positioning and a crowded floor. Our previous policy had thirty collisions in about thirty-five thousand conflicts. The current version had one, and in that case the truck had already stopped. Then we made the people more human: they drift, change speed and hesitate. Even then, no moving truck touched anyone. And trucks were faster in every scenario.

## 12. Trace every collision, fix the cause, retest on new seeds  (Kihwan, 78 words, ~37 s)

How did we get there? Not by tuning until the numbers looked good. We traced every collision to its cause, fixed it in both the Python code and the firmware, and tested again on new seeds. For example, version 3.1 keeps the emergency brake on while the person is still in front of the truck. We also rejected a faster version because it was less safe. Our safety case links each claim to the tests behind it.

## 13. Learning across sites, trucks that coordinate, an agent that reports  (Kihwan, 59 words, ~28 s)

Beyond one zone. Sites learn together with federated learning: only model weights travel through oneM2M, never people's trajectories, and the prediction error dropped from sixty to forty-nine centimetres. Forklifts share their plans through a oneM2M group to avoid conflicts. And an AI agent writes safety reports through MCP servers. All of these demos run in CI on every commit.

## 14. Low-cost devices, paid back by forklift time  (Kihwan, 77 words, ~37 s)

Is it worth it? A ten-thousand-square-metre warehouse costs about fifteen thousand dollars to equip. With a proximity alarm, a forklift loses about one point four seconds per encounter; with EdgeGuard, less than a tenth of a second. That pays the system back in one to three and a half years from time alone, and one prevented injury pays for it eight times. And because alerts are oneM2M resources, any warehouse system can use them just by subscribing.

## 15. What is real, and what is simulated  (Kihwan, 65 words, ~31 s)

We want to be clear about scope. Real, and checked on every commit: the oneM2M resources on real CSEs, the ESP32 firmware running unmodified against a real CSE over MQTT and TLS, and our runs on the ETSI MEC Sandbox. Simulated: how people and drivers behave, and so the collision numbers. Next, we will demo on real boards and run a pilot at a site.

## 16. Safe and productive, not one or the other  (Kihwan, 33 words, ~16 s)

To sum up: today, sites must choose between a safe alarm and a productive one. EdgeGuard gives both, on standard oneM2M and ETSI MEC. Thank you. We are happy to take your questions.

## Backup B1. TR-0077 clause 7 and TR-0086, item by item  (Jeongwon (jw), 57 words, ~27 s)

Backup. Show this if judges ask how we cover TR-0077 clause 7 or which TR-0086 option we chose. Answer: option C in each zone, because a collision warning has a one-to-three-second budget, so the CSE, the decision and the MEC data sit on the same host: twenty-five milliseconds instead of eighty-five, and trajectories stay in the zone.

## Backup B2. Each device can act only as itself  (Kihwan, 38 words, ~18 s)

Backup. Show this if judges ask about security or personal data. Key line: each device can act only as itself, and people's trajectories never leave the zone. Six kinds of attack are refused in CI on every commit.

## Backup B3. Tested against other people's work  (Jeongwon (jw), 46 words, ~22 s)

Backup. Show this if judges ask about interoperability or our contribution to the oneM2M ecosystem. Key line: the same application runs on independent CSEs, our MEC traffic is checked against the official ETSI OpenAPI files, and the two bugs we reported to ACME were fixed upstream.
