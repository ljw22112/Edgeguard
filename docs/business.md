# Cost, market and business model

[← README](../README.md) · [한국어](ko/business.md)

> **Currency note:** KRW figures are shown with approximate USD equivalents at USD 1 ≈ KRW 1,400.

## 1. Size of the problem

| Indicator | Figure | Source |
|---|---|---|
| Forklift accident casualties (Korea) | 1,396 in 2021, 1,163 in 2022 (2,559 over two years) | KOSHA statistics (reported by Safety First News) |
| Struck-by accident deaths (Korea) | 92 in 2022 (236 deaths from being struck by vehicles or construction machinery over the last three years) | Ministry of Employment and Labor, KOSHA (reported by Newsis) |
| Forklift accidents (US) | About 85 deaths, 34,900 serious injuries and 61,800 non-serious injuries per year | OSHA estimates |
| Share involving pedestrians (US) | 12 % of forklift deaths, 20 % of non-fatal injuries | BLS 2017 |
| Cost per injury | About USD 43,000 per medically consulted work injury; about USD 116,000 including indirect costs (indirect costs 2.7×) | NSC Injury Facts, OSHA 3885 |
| Legal liability (Korea) | Serious Accidents Punishment Act: for a death, the responsible executive faces at least one year in prison or a fine of up to KRW 1 billion (≈ USD 714,000); the company faces a fine of up to KRW 5 billion (≈ USD 3.6 million) | Serious Accidents Punishment Act |

## 2. Market

| Indicator | Figure | Source |
|---|---|---|
| Global forklift collision avoidance system market | About USD 1.18 billion in 2024 → about USD 5.11 billion in 2034 (CAGR 10.9 %) | Zion Market Research |
| Forklifts in use in the US | About 1 million | NIST PerMIS 2009 forklift safety white paper |
| First target customers (Korea) | Logistics centres, 3PLs and factory warehouses — strong demand for safety investment since the Serious Accidents Punishment Act was extended to all workplaces with five or more employees | — |

## 3. Deployment cost (example site)

**Assumptions**: 10,000 m² warehouse, 50 workers, 10 forklifts, 16 hours a day, 300 days a year. Unit prices are prototype-level retail prices and will fall at volume.

| Item | Qty | Unit price | Total | Basis |
|---|---|---|---|---|
| Worker tag (ESP32 + DW1000 UWB, vibration, LED, battery, case) | 50 | USD 70 | USD 3,500 | ESP32 UWB board retail about USD 61 (Makerfabs) + parts |
| Forklift module (UWB + IMU + beacon light + slow-down interface) | 10 | USD 120 | USD 1,200 | Same board + IMU, relay, wiring |
| UWB anchor (incl. installation and power) | 24 | USD 100 | USD 2,400 | One per 400–500 m² |
| Two edge servers (high availability) | 2 | USD 1,500 | USD 3,000 | 40 devices handled on a 2-core PC ([deployment](deployment.md) scale test) |
| Installation and positioning calibration | 1 lot | — | USD 5,000 | |
| **Total (initial cost)** | | | **About USD 15,100 (about KRW 21 million)** | USD 1 = KRW 1,400 |

- **At sites using a private 5G network or MNO MEC**, the edge servers are replaced by MEC usage fees. EdgeGuard is built on standard MEC APIs and oneM2M, so it runs on either as is.
- The devices use low-cost, general-purpose parts (ESP32), so they can be retrofitted to existing forklifts.

## 4. Expected benefits and payback

| Benefit | Calculation | Annual amount (example site) |
|---|---|---|
| **Preventing one accident** | Total cost of one injury about USD 116,000 (NSC × OSHA indirect-cost multiplier) | Preventing a single accident saves about KRW 160 million (≈ USD 116,000) — about 8× the initial cost |
| **Forklift time saved** | Forklift loss per encounter 2.76 → 1.62 s (vs v1.0, same simulator) × 10–30 encounters per hour × 16 h × 300 days × 10 forklifts, at KRW 35,000 (≈ USD 25) per hour for forklift + driver | **About KRW 5.3–16 million (≈ USD 3,800–11,400)** |
| Lower legal risk from accidents | Evidence for Serious Accidents Punishment Act compliance (risk records, near-miss analysis, records of corrective actions) | Not quantified |
| Insurance and safety management | Manage hazardous zones with near-miss heatmaps and improvement proposals; material for insurance premium negotiations | Not quantified |

- **Payback**: about 1.3–4 years from time savings alone; immediate if a single accident is prevented.
- Savings are larger against the baseline proximity-alert approach (85 % false alarms). The calculation above is against our own v1.0, so it is conservative.
- Encounters per hour and hourly cost are assumptions and must be recalculated for each site.

## 5. Business model

| Revenue stream | Description | Example price |
|---|---|---|
| **Hardware kit** | Sale and installation of tags, forklift retrofit modules and anchors | Cost above + margin |
| **Subscription software (SaaS)** | MEC app, monitoring dashboard, near-miss analysis, monthly safety report, remote updates | KRW 30,000 (≈ USD 21) per forklift per month, KRW 5,000 (≈ USD 3.6) per worker per month → KRW 550,000 (≈ USD 390) per month for the example site (KRW 6.6 million (≈ USD 4,700) per year) |
| **MNO MEC partnership** | Bundled as a safety app in private 5G / MEC offerings, with usage-based revenue sharing | To be negotiated with partners |
| **Data services** | Near-miss and hazardous-zone statistics provided to insurers and safety consultancies (with site consent) | Negotiable |

**Sales channels**: forklift manufacturers and dealers (retrofit kits), direct sales to logistics centres and 3PLs, MNO private 5G / MEC partners, industrial safety consultancies.

**Phases**: ① 3-month pilot at one site (measure impact with near-miss data) → ② roll out to the same customer's other centres → ③ standard product through partnerships with forklift manufacturers and MNOs.

## 6. Scalability

- **Site size**: with adaptive reporting intervals, alert latency p95 is 256 ms with 40 devices, and the edge Mobius comfortably handles 250 writes per second (`docs/deployment.md`).
- **Many-to-many sites**: with 8 workers and 4 forklifts in simultaneous encounters, collisions −96 % and throughput 86 % (`results/multi_sim.json`).
- **Multiple sites**: an edge (Mobius + MEC app) per site, with headquarters monitoring all sites through a cloud replica (store-and-forward keeps records through WAN outages).
- **Other industries**: the same architecture extends to ports (yard tractors and workers), construction sites (excavators and workers), and factory AGVs/AMRs alongside people — collision-course detection and WAIT/GO signals are independent of vehicle type.

## 7. Contribution to the oneM2M ecosystem

- **Standards-native integration**: each device is an AE, and risk, alerts and near misses are exposed as oneM2M resources (`EdgeGuard/risk`, `alert`, `nearmiss`), so
  other oneM2M apps such as WMS and smart factory platforms can use them simply by subscribing.
- **Interoperability improvements**: Mobius ↔ ACME testing found and documented seven issues ([interoperability notes](interop-notes.md)), and we produced a fix patch for ACME (`docs/acme-content-type.patch`).
- **Open source**: MIT licence, with third-party licence notices. We also publish the fix-up scripts for installing the ETSI MEC Sandbox (AdvantEDGE) in a 2026 environment (`deploy/sandbox-host/`).
- **Standards-based AIoT reference case**: an industrial safety reference implementation combining oneM2M (data, access control) + ETSI MEC (location, radio information) + edge AI (prediction).

## Sources

- [KOSHA forklift accident statistics (Safety First News)](https://www.safety1stnews.com/news/articleView.html?idxno=4768)
- [Ministry of Employment and Labor struck-by accident deaths (Newsis, 2023-05-10)](https://www.newsis.com/view/NISX20230510_0002296943)
- [OSHA forklift accident statistics (compiled by Forklift Training Systems)](https://www.forklifttrainingsystems.com/osha/)
- [Pedestrian–forklift collision statistics (citing BLS, NSC, OSHA; Voxel)](https://www.voxelai.com/industry-insights/pedestrian-forklift-collision-statistics)
- [Forklift Collision Avoidance System Market (Zion Market Research)](https://www.zionmarketresearch.com/report/forklift-collision-avoidance-system-market)
- [Makerfabs ESP32 UWB Pro price (RobotShop)](https://www.robotshop.com/products/esp32-uwb-pro)
- [NIST PerMIS 2009 forklift safety white paper](https://www.nist.gov/document/permis-09-forklift-safety-whitepaperpdf)
- Serious Accidents Punishment Act (Act No. 17907)
