# Adoption barriers and responses

Why similar worker–forklift safety systems have not spread across industrial sites, and how EdgeGuard responds.

[← README](../README.md) · [한국어](ko/adoption.md)

| Why existing systems failed | Evidence | EdgeGuard |
|---|---|---|
| **False alarms → alert fatigue**: fixed distance thresholds trigger often, and workers stop trusting them | Essensium; NIOSH survey of mining PDS ("at first it stopped too often") | ✅ Collision prediction: false alarms 85 % → 30 % (vs. 5 m distance, `results/evaluation.json`); CPA decisions even during failures (v0.9) |
| **Lost productivity → workarounds**: frequent stops lead workers to "game" the device | NIOSH | ✅ Safety and throughput always measured together; graceful degradation (throughput 57 % on network cut vs. 18 % for stopping everything) |
| **Tags not worn or not charged** | Essensium; NIST | 🔶 Camera node detects untagged workers (added cost) |
| **Cost and retrofitting existing equipment**: about 1 million forklifts in the US | NIST | 🔶 Devices are cheap ESP32 + UWB retrofits; anchor and network infrastructure costs remain |
| **Infrastructure density, calibration, maintenance** | Essensium | ❌ Requires UWB anchors (network positioning is only supplementary) |
| **MEC business case**: unclear ROI, Wi-Fi is cheaper, 2–3 year PoCs | SDxCentral / Dell'Oro | 🔶 Life safety is the MEC application with the clearest ROI. Built on oneM2M, so it also runs with a Wi-Fi CSE |
| **V2X failed to spread**: 20 years and USD 2.2 billion, about 15,000 equipped vehicles, more than half the spectrum reclaimed in 2020 — only works if the other party is equipped too (chicken and egg) | US Congressional Research Service (CRS) | ✅ A factory is a closed space where one company manages all equipment → 100 % fitment possible, so D2D (v0.9) is effective immediately |
| **Liability and safety certification**: the non-contact sensor standard (ANSI B56.5) is under revision | NIST | ❌ Not yet functional-safety certified — positioned as a driver assistance system |

Sources: [Essensium](https://essensium.com/why-safety-tags-and-wearables-are-reaching-their-limits/) ·
[NIOSH operator reactions (Coal Age)](https://www.coalage.com/?p=5613) ·
[NIST PerMIS 2009 forklift safety white paper](https://www.nist.gov/document/permis-09-forklift-safety-whitepaperpdf) ·
[CRS: Spectrum Use for Vehicle Safety](https://www.everycrsreport.com/reports/IF11260.html) ·
[SDxCentral: What's wrong with the MEC market](https://www.sdxcentral.com/analysis/whats-wrong-with-the-mec-market/)
