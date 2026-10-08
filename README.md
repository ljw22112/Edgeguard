# EdgeGuard

MEC 기반 산업현장 작업자–지게차 충돌 예측 AIoT 안전 서비스
(2026 oneM2M International Hackathon · Team EdgeGuard, Sejong University)

작업자 태그와 지게차 센서 데이터를 **oneM2M**으로 수집하고, **ETSI MEC** 엣지의 위험도 엔진이
충돌을 1~3초 전에 예측해 **작업자 진동 + 지게차 감속** 경보를 보냅니다. 망이나 서버가 끊겨도 단말끼리(D2D) 판단을 이어 갑니다.

```
디바이스 ──CIN──▶ oneM2M CSE ──Notify──▶ MEC 앱 (추적 → 예측 → 가이던스 판정)
   ▲     ◀──D2D──▶    │                          │
   └──── alert Notify ┴────── risk / alert CIN ◀─┘
```

## 핵심 결과

| 항목 | 결과 | 비교 대상 |
|---|---|---|
| 적시 감지 (접촉 1 s 전) | **100 %**, 리드타임 중앙값 2.4 s | 근접 5 m 경보 76 % |
| 오경보율 | **30 %** | 근접 5 m 경보 85 % |
| 충돌 · 처리량 (학습 정책) | 충돌 32 → **15** / 180, 처리량 **+14 %** | 수동 설정 정책 |
| 망 완전 단절 | 충돌 180 → **2**, 처리량 **57 %** | 전부 정지 방식 18 % |
| 통신 음영 (작업자 / 지게차) | 충돌 66 → **16** / 52 → **19**, 처리량 76 % | 기존 페일세이프 |
| 사각 코너 (현장 지도) | 충돌 17 → **11** / 80 | 지도 없음 |
| 경보 지연 중앙값 | **25 ms** (엣지), 팀 노트북 58 ms | 클라우드 전용 85 ms · 단절 시 0건 |
| MEC 앱 장애 인수 | **0.73 s**, 하트비트 공백 1.0 s | 지게차 로컬 전환 기준 2 s |
| 규모 (40대) | 경보 지연 p95 1,642 → **256 ms** | 고정 보고 주기 |
| ETSI MEC Sandbox | 공개 Sandbox **실연동**, 자체 설치 Sandbox 창고 시나리오 경보 70건 | — |

검증 범위: 하드웨어 실기 시험은 하지 않습니다. 시뮬레이션(온라인 · 고속 폐루프), 실제 Mobius/ACME CSE, ETSI MEC Sandbox로 검증하고,
펌웨어는 PC 타입 검사와 Python 기준 구현과의 교차 테스트까지 마친 참조 구현입니다.

## 차별점

- **거리 대신 충돌 코스 판정** — 미사일 유도의 시선각 변화율(LOS rate) · 최근접점(CPA)으로 "가까움"이 아니라 "부딪힐 코스"에만 경보합니다.
- **끊겨도 멈추지 않는 단계적 강등** — MEC 예측 → 단말 간 UWB 거리 · D2D 상태 교환(터널 속 자율주행차처럼) → 정지. 중계로 음영 지역까지 경보를 전달합니다.
- **표준 기반** — oneM2M(Mobius) 리소스와 ETSI MEC Location(013) · RNIS(012) API. 실제 ETSI MEC Sandbox에서 동작을 확인했습니다.
- **운영까지 고려** — 이중화, 모니터링, 아차사고 히트맵과 개선안, 디바이스별 접근제어, D2D 프레임 인증.

## 빠른 시작

```bash
cd deploy
docker compose --profile demo up -d                   # Mobius + MEC 앱 + 가상 디바이스 (조우 4회)
python3 check_demo.py out/devices.json http://localhost:9090/health
# 대시보드 http://localhost:9090/

MEC_HA=1 docker compose --profile ha up -d            # + 대기 MEC 앱 (이중화)
docker compose --profile monitoring up -d             # + Prometheus :9095 · Grafana :3000
```
하드웨어 · Docker 없이: `pip install -r requirements.txt && scripts/run_local_demo.sh crossing_conflict`
· 테스트: `python -m pytest`

## 구성

| 영역 | 내용 |
|---|---|
| 위험도 엔진 | 칼만 추적, CV/CTRV · LSTM 예측, 가이던스 판정(CPA/TCPA · LOS rate · collision cone · VO 감속량), 학습된 경보 정책 |
| MEC 앱 | FastAPI: 알림 수신 → risk/alert/control 게시, 우선순위 송신 큐, 대시보드, `/health` · `/metrics` · `/nearmiss` |
| 단말 | ESP32 + DW1000 펌웨어(작업자 태그, 지게차 모듈): UWB 측위, 적응형 주기, 로컬 규칙, ESP-NOW D2D + HMAC |
| 연동 | oneM2M Mobius / ACME, ETSI MEC Location · RNIS (MEC-IPE), 클라우드 사본 동기화, 카메라(YOLOv8n) 노드 |
| 배포 · CI | Docker Compose(demo · ha · monitoring · sandbox 프로필), GitHub Actions: 테스트 → 스택 종단 · 재시작 · 장애 인수 · 모니터링 시험 → GHCR |

## 문서

| 문서 | 내용 |
|---|---|
| [위험도 엔진과 성능 평가](docs/risk-and-evaluation.md) | 가이던스 기하, 방식별 비교 실험, LSTM, 폐루프 시뮬레이션, 정책 학습 |
| [신뢰성](docs/resilience.md) | 망 장애 단계적 강등(v0.8), D2D 협력(v0.9), 이중화(v1.0), 규모 · 재시작 · 서버 안정화 |
| [현장 기능](docs/site-features.md) | 사각 코너, D2D 인증, 모니터링, 아차사고 분석, 카메라, 접근제어, 대시보드 · 리포트 |
| [배포](docs/deployment.md) | Compose 스택, 로컬 데모, 배포 구조 결정(측정), oneM2M 리소스 트리, 펌웨어 · CI |
| [ETSI MEC 연동 · Sandbox](docs/mec-sandbox.md) | MEC API 연동, 공개 Sandbox 실연동, 자체 설치 Sandbox — 설치 절차는 [deploy/sandbox-host](deploy/sandbox-host/README.md) |
| [도입 장벽과 대응](docs/adoption.md) | 유사 시스템이 퍼지지 못한 이유와 대응 |
| [상호운용성 노트](docs/interop-notes.md) | CSE 간 시험에서 찾은 문제와 해결 |

## 폴더

```
edgeguard/   위험도 엔진 · 추적 · 예측 · 경보 정책 · 기기 규칙 · 사이트 지도 · 아차사고 · 이중화 · oneM2M/MEC 클라이언트
mec_app/     MEC 앱 (FastAPI) + 대시보드 + Dockerfile
firmware/    ESP32 스케치 (worker_tag, forklift_module) + 공용 헤더 (UWB 측위, 기기 규칙, D2D, HMAC)
deploy/      Docker Compose 스택, 모니터링 설정, Sandbox 호스트 설치 스크립트, 시험 스크립트
sim/         시나리오 · 비교 실험 · 폐루프 시뮬레이션 · 정책/LSTM 학습
tools/       리소스 셋업 · MEC-IPE · Sandbox 연동/점검 · 부하/구성 시험 · 안전 리포트
devices/ mec_mock/ scenarios/ models/ results/ scripts/ tests/ docs/
```

## 알려진 한계

- `emulated_extra_delay_ms`는 클라우드 경로를 흉내 내는 옵션일 뿐이며, W6에서 실제 클라우드 대비 측정을 해야 합니다.
- 규모 시험은 2코어 PC 한 대에서 부하 생성기까지 함께 돌린 값이라, 같은 시험도 PC 성능에 따라 지연이 크게 달라집니다 ([배포](docs/deployment.md)).
- 실기(ESP32 + DW1000 + RC카)는 검증 범위 밖입니다. 펌웨어 타이밍 · UWB 실측 오차는 시뮬레이션으로 대신했고(직접 측정 가정은 민감도 시험으로 보완),
  공식 MEC-IPE(TR-0086)는 아직 공개 전이라 `tools/mec_ipe.py`가 같은 역할을 합니다. 실제 Sandbox 연동은 연결 확인까지이며, 위치 정확도에 따른 성능 변화는 오차를 주입해 측정했습니다 ([MEC 연동](docs/mec-sandbox.md)).
- 현장 지도는 손으로 넣는 직사각형 장애물이며(자동 지도 작성 없음), 사각 코너 보정은 그 구간의 오경보를 늘립니다(39 → 57 / 80).
- D2D 키는 사이트 공용 사전 공유 키입니다. 장치 하나가 탈취되면 키 교체(펌웨어 재배포)가 필요하고, 장치별 키 · 자동 교체는 하지 않았습니다.
- 이중화는 같은 CSE를 공유하는 MEC 앱 2개까지입니다. CSE(Mobius) 자체의 이중화는 범위 밖이며, 그 장애는 단말 로컬 규칙 · D2D(v0.8~0.9)가 맡습니다.
