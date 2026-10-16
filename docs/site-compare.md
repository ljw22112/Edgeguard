# EdgeGuard compared with what sites use today

[← README](../README.md) · [한국어](ko/site-compare.md)

How much safer, and how much more productive, is EdgeGuard than the systems warehouses use now? All systems run on the **same simulated floor, the same 300 episodes and the same sensing noise** ([`sim/site_compare.py`](../sim/site_compare.py)). The episodes (seeds from 200 on) were not used to tune or audit EdgeGuard.

![Comparison with site practice](img/site_compare.png)

![Safety and throughput together](img/site_compare_tradeoff.png)

## The systems

| System | What it does | Basis |
|---|---|---|
| No system | Drivers and walkers rely on their own attention | — |
| Speed zoning 5 km/h | Trucks capped at the usual pedestrian-area speed in the shared aisles | Pedestrian areas and crossings are commonly limited to about 3 mph (5 km/h); OSHA asks for a speed at which the truck can stop and sets no number ([BigRentz](https://www.bigrentz.com/blog/forklift-speed-limits-osha-rules-and-best-practices-for-safe-operation), [ELOKON speed zoning](https://www.elokon.com/en-US/blog/details/automated-speed-zoning-reducing-forklift-accidents-in-real-time)) |
| UWB proximity 6 m / 3 m | Tag on the worker, anchor on the truck. Inside the warning zone the truck is slowed to walking speed (1.4 m/s) and the tag vibrates; inside the danger zone the truck stops. No notion of direction. | Warning and danger zones; slow to walking speed and stop; pedestrian alerted by vibration; detection up to 12 m ([ELOshield](https://www.elokon.com/en-US/material-handling/eloshield-vehicle-pedestrian-proximity-detection)) |
| UWB proximity 4 m / 2 m | The same, with zones narrowed to cut nuisance alarms | Sites tune zone sizes |
| EdgeGuard | Collision-course prediction on the MEC host; WAIT / GO / STEP ASIDE; one speed plan per pair; GO check; D2D fall-back | This repository |

Two crews: **nobody looks out** (what the system alone prevents) and **attentive driver** (the driver brakes for a person right in front of the truck after a 1 s reaction).

## Results (300 episodes, 8 workers and 4 forklifts each, 1,123 conflicts)

| | Collisions (nobody looks out / attentive driver) | Forklift throughput | Worker time lost per episode | Alarms per forklift-hour (not needed) |
|---|---|---|---|---|
| No system | 827 / 650 | 100 % / 85 % | 0.1 s | 0 |
| Speed zoning 5 km/h | 666 / 387 | 75 % / 62 % | 0.1 s | 0 |
| UWB proximity 6 m / 3 m | **0** / **0** | 48 % / 48 % | 4.3 s | 1,356 (22 %) |
| UWB proximity 4 m / 2 m | 12 / 4 | 60 % / 60 % | 3.2 s | 929 (10 %) |
| **EdgeGuard** | 2 / 1 | **86 % / 86 %** | 2.9 s | **229 (14 %)** |

**What this says:**
- Against the wide proximity alarm, EdgeGuard keeps trucks moving at **86 % instead of 48 % of nominal (+79 %)**, with **83 % fewer alarms** and **32 % less worker waiting**. The price is 2 collisions in 1,123 conflicts (0.18 %) where the proximity alarm, which stops every truck that comes within 3 m of anyone, has none.
- Against the narrowed proximity alarm, the setting sites choose to cut nuisance alarms, EdgeGuard has **6 times fewer collisions** (2 vs 12) and **43 % more throughput** (86 % vs 60 %).
- Speed zoning alone barely helps here: a walker who steps out in front of a truck at 5 km/h is still hit (593 per 1,000 conflicts), and throughput drops to 75 %.
- With an attentive driver, EdgeGuard's throughput is above the no-system case (86 % vs 85 %), because the alert slows a truck only as much as the conflict needs, while a startled driver brakes hard.

## Limits

- Simulation. Walkers and drivers follow simple models: nobody looks out except where stated, and a buzzed worker stops for about 2 s (proximity) or waits until GO (EdgeGuard tag).
- Proximity parameters are typical settings. Products differ, and sites tune zones, speeds and acknowledgement rules.
- Collision counts this small (0–12) have wide uncertainty: 2 vs 0 is not a significant difference, 2 vs 12 and the throughput gaps are.
- "Not needed" counts alarms for pairs that would not have come within 4 m of each other anyway.

Reproduce: `python -m sim.site_compare --episodes 300` (about 15 minutes on 2 cores; `--charts-only` redraws from `results/site_compare.json`).
