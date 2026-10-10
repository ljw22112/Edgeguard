# ETSI MEC 연동 · Sandbox

MEC 서비스 API(013/012) 연동, 공개 ETSI MEC Sandbox 실연동, 자체 설치 Sandbox(AdvantEDGE) 창고 시나리오.

[← README](../../README.ko.md)

## ETSI MEC 서비스 연동

`edgeguard/mec_services.py` (클라이언트), `mec_mock/server.py` (시험용 MEC 플랫폼, ETSI 데이터 모델 부분집합).
`config/site.yaml`의 `mec_services`로 켭니다.

- **Location API (MEC 013)**: 작업자 UWB 태그가 0.5초 이상 끊기면(선반 뒤 음영) 네트워크 기반 위치를 받아
  정확도만큼 큰 잡음으로 추적기에 넣습니다. 대시보드에는 점선 원과 "MEC Location API"로 표시됩니다.
- **RNIS (MEC 012)**: 현장 셀의 PRB 사용률이 80% 이상이면 경보 판정 시간을 0.5초 늘리고 경보 갱신을 2배로 자주 보냅니다.

충돌 시나리오 4회, 첫 경보의 접촉 전 리드타임 (`results/mec_services.json`):

| 조건 | 리드타임 (s) |
|---|---|
| UWB 정상 | 2.48, 2.37, 2.37, 2.27 |
| UWB 3.0~6.5 s 끊김, 폴백 없음 | 2.07, 2.37, **0.87**, 2.27 |
| UWB 끊김 + Location API 폴백 | 2.38, 2.37, 2.28, 2.28 |
| 셀 혼잡 (RNIS 90%) | 2.86, 2.77, 2.97, 3.17 |

폴백이 없으면 한 번은 1초 기준을 못 맞췄고, 폴백을 켜면 정상 때와 같은 수준으로 돌아왔습니다.

## 자체 설치 MEC Sandbox + 창고 시나리오 (AdvantEDGE v1.9.2)

공개 Sandbox는 기본 시나리오만 고를 수 있어, ETSI MEC Sandbox의 오픈소스 기반인 AdvantEDGE v1.9.2를 팀 PC의 Hyper-V VM
(Ubuntu 22.04, Kubernetes 1.27)에 설치하고 **우리 창고 시나리오**(`scenarios/edgeguard-warehouse.json`)를 배포했습니다.
설치 절차와 2026년 현재 깨진 이미지 경로 보정은 `deploy/sandbox-host/` (README · 스크립트)에 있습니다.

경로: AdvantEDGE Location API → MEC-IPE → Mobius 리소스 → 구독 알림 → MEC 앱 → 경보 (`results/sandbox_selfhosted_live.json`)

| 항목 | 결과 (2026-10-08, 2분) |
|---|---|
| 판정 | **CONNECTED** |
| UE 분류 (최고 속도 기준) | 지게차 2 · 작업자 4 — 시나리오와 일치 |
| 위치 수신 | 828회, 6.0 회/s, 미등록 UE 0 |
| 평가한 작업자-지게차 쌍 | 8 |
| **경보** | **70건** |

## 실제 ETSI MEC Sandbox 연동 (try-mec.etsi.org)

팀 노트북(갤럭시 북2 프로, RAM 8GB, Windows 11, Docker Desktop)에서 공개 ETSI MEC Sandbox에 네트워크 시나리오를 배포하고 EdgeGuard 스택을 연결했습니다.
경로: **Sandbox Location API → MEC-IPE → Mobius 리소스 → 구독 알림 → MEC 앱** (MEC API를 앱이 직접 부르지 않음).

```
cd deploy
docker compose up -d --build
docker compose run --rm sandbox-setup https://try-mec.etsi.org/<sbx-id>/mep1/location/v3   # API·UE 탐지 → sandbox/overrides.yaml
docker compose --profile sandbox up -d --force-recreate                                   # MEC-IPE 기동, MEC 앱 Sandbox 모드
docker compose run --rm sandbox-check                                                     # sandbox/report.json, CONNECTED 판정
```

| 항목 | 결과 (2026-10-07) |
|---|---|
| 판정 | **CONNECTED** |
| MEC-IPE가 만든 UE / 셀 컨테이너 | 3 / 10 |
| MEC 앱의 IPE 구독 | 13 |
| 위치 수신 | 32회, 2.0 회/s, 미등록 UE 0 |
| 추적 중인 UE | 2 |

- 대시보드에는 Location API가 v2로 나오지만 실제로는 `location/v3`만 응답합니다. `sandbox_probe`가 두 버전을 모두 시도합니다.
- Sandbox UE는 도시 규모(수백 m 간격)로 움직여 작업자-지게차 쌍이 평가 범위에 들어오지 않았고, 그래서 경보는 0건입니다.
  충돌 위험 판단 성능은 아래 자체 창고 시나리오로 평가합니다.
- 이 시나리오는 셀 부하(layer2_meas)를 주지 않아 혼잡 여유 보정은 꺼진 상태로 동작했습니다.
- Sandbox 모드 해제: `deploy/sandbox/overrides.yaml` 삭제 후 `docker compose up -d --force-recreate mec`.

## 해커톤 MEC Sandbox 정렬 (oneM2M 리소스 경유, MEC-IPE)

운영측 안내(2026-10-06): CSE에 연결된 AE는 MEC 호스트 등록을 CSE가 대신하고, UE 위치는 **MEC-IPE가 CSE 리소스로**
넣어 주며, MEC API 직접 호출보다 oneM2M 리소스 경유를 권장합니다. 팀 고유 지도·궤적으로 **시나리오를 직접 만드는 것**도 권장됩니다.
이에 맞춰 바꾼 것:

- **위치 출처 = CSE (기본값)**: `mec_services.location_source: cse`. MEC 앱이 `<ipe.root>/location/*`, `<ipe.root>/rnis/*`
  컨테이너를 주기적으로 탐색(`fu=1&ty=3`)해 구독하고, 알림의 내용(MEC 013 UserInfo / MEC 012 cellInfo)을 그대로 씁니다.
  `direct`(API 직접 호출)는 비교·탐색용 옵션으로 남겼습니다. 앱 등록(MEC 011)은 하지 않습니다.
- **MEC-IPE 대역** `tools/mec_ipe.py`: TR-0086이 공개 전이라, MEC API를 읽어 CSE에 쓰는 역할을 같은 형식으로 대신합니다.
  리소스 구조는 설정으로 바꿀 수 있어 실제 IPE가 공개되면 경로만 맞추면 됩니다.
- **샌드박스 시나리오** `scenarios/edgeguard-warehouse.yaml` (`tools/sandbox_scenario.py`): 40×24 m 창고, 사설 5G 소형셀 2개, MEC 호스트 1개,
  지게차 2대·작업자 4명이 GeoJSON 경로를 일정 속도로 오가며 주기적으로 마주칩니다. AdvantEDGE 1.8.0 데이터 모델 스키마 검증 통과.
  `mec_mock`이 같은 시나리오를 재생합니다 (`MEC_MOCK_SCENARIO=...`).
- **UWB는 주 출처, MEC 위치는 보조**: 태그 데이터가 0.5 s 이내로 들어오면 MEC 위치는 버리고, 끊기면 정확도만큼 큰 잡음으로 받습니다.
  아래 결과처럼 1 Hz·수 m급 망 위치만으로는 충돌 회피에 부족하므로, 디바이스가 위치를 직접 쓰는 것은 안내된 "예외"에 해당한다고 봅니다.
- 1 Hz처럼 듬성한 위치에서도 경보 디바운스가 시간 기준(0.2 s)으로 동작하도록 고쳤습니다 (10 Hz 결과는 동일: 폐루프 19/180).

종단 시험 `python tools/sandbox_e2e.py` — 시나리오 → MEC → (IPE → Mobius) → MEC 앱 → 경보, 120 s, 시나리오 궤적으로 정답 채점, 접촉 16회:

| 위치 출처 | 갱신 | 위치 오차 / 보고 정확도 | 1 s 전 경보 | 리드타임 중앙값 | 오경보 | 위치→경보 p50 |
|---|---|---|---|---|---|---|
| CSE (MEC-IPE) | 1 s | 0 / 1 m | 62.5 % | 1.26 s | 4 | 114 ms |
| MEC API 직접 | 1 s | 0 / 1 m | 62.5 % | 1.44 s | 4 | 169 ms |
| CSE (MEC-IPE) | 1 s | 0 / 0.3 m | 93.8 % | 2.03 s | 2 | 156 ms |
| CSE (MEC-IPE) | 1 s | 1 m / 1 m | 68.8 % | 2.23 s | 7 | 119 ms |
| CSE (MEC-IPE) | 1 s | 3 m / 3 m | 43.8 % | 4.05 s | 12 | 178 ms |
| CSE (MEC-IPE) | 0.1 s | 0 / 1 m | 93.8 % | 2.13 s | 5 | 87 ms |
| *(참고) UWB 태그* | *0.1 s* | *0.15 m* | *100 % (온라인 시뮬)* | | | *~70 ms* |

- CSE 경유와 직접 호출은 같은 탐지율에 지연도 비슷합니다 → 권장 경로(CSE)를 기본으로 써도 손해가 없습니다.
- 성능을 정하는 건 경로가 아니라 **위치의 갱신 주기와 정확도**입니다. 실제 망처럼 1~3 m 오차가 있으면 69 → 44 %로 떨어지고 오경보가 늘어,
  안전 기능에는 UWB(0.1 s, 0.15 m)가 필요하고 MEC 위치는 태그 음영 보완·구역 판단용이 맞습니다.
