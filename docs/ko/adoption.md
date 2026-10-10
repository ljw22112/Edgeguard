# 도입 장벽과 대응

유사한 작업자–지게차 안전 시스템이 산업 현장에 퍼지지 못한 이유와 EdgeGuard의 대응.

[← README](../../README.ko.md)

| 기존 시스템의 실패 이유 | 근거 | EdgeGuard |
|---|---|---|
| **오경보 → 경보 피로**: 고정 거리 기준이라 자주 울리고, 작업자가 믿지 않게 됨 | Essensium; NIOSH 광산 PDS 조사("처음엔 너무 자주 멈췄다") | ✅ 충돌 예측: 오경보 85 % → 30 % (거리 5 m 대비, `results/evaluation.json`), 장애 시에도 CPA 판단(v0.9) |
| **생산성 손실 → 우회 행동**: 멈춤이 잦으면 장치를 "속이며" 일함 | NIOSH | ✅ 안전과 처리량을 항상 함께 측정, 단계적 강등(망 단절 시 처리량 57 %, 전부 정지 18 %) |
| **태그 미착용·미충전** | Essensium; NIST | 🔶 카메라 노드로 태그 없는 작업자 감지 (비용 증가) |
| **비용·기존 장비 개조**: 미국 지게차 약 100만 대 | NIST | 🔶 단말은 ESP32 + UWB로 저렴·개조형, 앵커·망 인프라 비용은 남음 |
| **인프라 밀도·보정·유지보수** | Essensium | ❌ UWB 앵커 필요 (망 위치는 보조) |
| **MEC 사업성**: ROI 불분명, Wi-Fi가 저렴, PoC 2~3년 | SDxCentral / Dell'Oro | 🔶 생명 안전은 ROI가 가장 분명한 MEC 응용. oneM2M 기반이라 Wi-Fi CSE로도 동작 |
| **V2X 보급 실패**: 20년·22억 달러, 장착 차량 약 1.5만 대, 2020년 주파수 절반 이상 회수 — 상대도 달아야 효과(닭과 달걀) | 미 의회조사국(CRS) | ✅ 공장은 한 회사가 모든 장비를 관리하는 닫힌 공간 → 장착률 100 % 가능, D2D(v0.9)가 바로 효과 |
| **책임 소재·안전 인증**: 비접촉 센서 표준(ANSI B56.5) 개정 중 | NIST | ❌ 기능안전 인증 전 — 운전자 보조 시스템으로 포지셔닝 |

출처: [Essensium](https://essensium.com/why-safety-tags-and-wearables-are-reaching-their-limits/) ·
[NIOSH 운전자 반응 (Coal Age)](https://www.coalage.com/?p=5613) ·
[NIST PerMIS 2009 지게차 안전 백서](https://www.nist.gov/document/permis-09-forklift-safety-whitepaperpdf) ·
[CRS: Spectrum Use for Vehicle Safety](https://www.everycrsreport.com/reports/IF11260.html) ·
[SDxCentral: What's wrong with the MEC market](https://www.sdxcentral.com/analysis/whats-wrong-with-the-mec-market/)
