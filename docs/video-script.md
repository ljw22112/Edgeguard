# Final video: storyboard and narration

[← README](../README.md)

`results/edgeguard_final.mp4` lasts 2 min 34 s, at 1920×1080. It has captions (`results/edgeguard_final.srt`) and **no audio track**, so the team can record the narration below over it. Rebuild with `python tools/mobility_map.py && python tools/make_final_video.py`. The cards and the timeline are in `tools/make_final_video.py`.

| Time | Picture | Narration (≈ 150 words per minute) |
|---|---|---|
| 0:00 | Title card | "This is EdgeGuard. It stops forklift accidents before they happen, with oneM2M and ETSI MEC." |
| 0:04 | Problem | "Workers and forklifts share the same aisles. In Korea alone there were over 2,500 forklift casualties in two years. Proximity alarms fire on forklifts that would pass safely, so people stop listening. And a buzz says danger, but not what to do." |
| 0:10 | WAIT · STEP ASIDE · GO | "EdgeGuard predicts the collision one to three seconds ahead on the MEC edge. It tells each worker WAIT, STEP ASIDE or GO, and slows the forklift only as much as needed." |
| 0:16 | Architecture | "Each warehouse zone has a MEC host running a oneM2M MN-CSE and our MEC app. Tags and forklift modules register their own AEs. An IN-CSE in the cloud ties the zones together." |
| 0:23 | Live demo (1.5× speed) | "Here it is live. The worker crossing gets WAIT until the forklift has passed, then GO. A worker standing in the lane is told to step aside. With two forklifts, GO comes only after both have passed. Every position and every alert is a oneM2M resource." |
| 1:26 | Firmware in the loop | "The ESP32 firmware runs unmodified against a real CSE, and a phone acts as the worker tag. This is checked in CI on every commit." |
| 1:45 | Mobility map | "Now mobility, through ETSI MEC. The MEC platform sees the forklift attach to zone B's cell. Our MEC-IPE writes that event into oneM2M, and the forklift's twin moves to zone B's MN-CSE. The interruption is a few milliseconds, and no sample is lost. Below, the signal strength of both cells crosses at the boundary." |
| 2:04 | TR-0077 clause 7 | "All four ESTIMED gaps run as features: MEC interworking and orchestration, handover, federated learning with model delivery and rollback, and forklift swarm coordination." |
| 2:14 | Why oneM2M | "oneM2M does the work: SDT twins with SAREF, group fan-out, polling channels, access control with TLS, and an AI agent over MCP." |
| 2:22 | Results | "In simulation, collisions drop from 100 to 4, throughput rises to 86 percent, and the site stays safe even when the network fails." |
| 2:29 | Closing | "EdgeGuard. Thank you." |

To add the voice:

```bash
ffmpeg -i results/edgeguard_final.mp4 -i narration.m4a -c:v copy -c:a aac -shortest results/edgeguard_final_voice.mp4
```
