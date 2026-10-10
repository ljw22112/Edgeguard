# 현장 기능

사각 코너 인지, D2D 프레임 인증, 모니터링, 아차사고 분석, 카메라 노드, 접근제어, 대시보드 · 안전 리포트.

[← README](../README.md)

## 사각 코너 인지 (현장 지도)
`config/site.yaml`의 `sitemap.obstacles`(랙 등 직사각형)를 넣으면 MEC 앱이 쌍마다 시야선을 검사합니다
(`edgeguard/sitemap.py`, Liang–Barsky 선분 클리핑). 서로 안 보이는 쌍은 안전반경 +0.5 m, 디바운스 1회로 더 일찍 경보하고,
대시보드에는 "시야 없음" 선으로 표시됩니다. 사람이 서로 보면 스스로 피하는 효과(12 m 시야)를 넣은 시뮬레이션 320회
(`sim/occlusion_eval.py` → `results/occlusion_eval.json`):

| 사각 코너 80건 | 충돌 | 오경보 |
|---|---|---|
| 지도 없음 | 17 | 39 |
| 지도: 시간 여유 +1 s | 22 | 48 |
| **지도: 반경 +0.5 m, 디바운스 1** | **11** | 57 |

개방 구간 결과는 그대로(충돌 7)이고, 늘어난 오경보는 사각 코너에서만 생깁니다. 시간 여유 방식은 오히려 나빠져 채택하지 않았습니다.

## D2D 프레임 인증 (HMAC)
ESP-NOW 프레임(66 B, 한도 250 B)에 HMAC-SHA256 8바이트 태그와 송신자별 일련번호를 붙입니다
(`firmware/common/d2d_auth.h`, 외부 라이브러리 없는 SHA-256). 수신 측은 태그를 상수 시간 비교로 확인하고,
송신자별 최근 50개 이내가 아닌 번호와 이미 받은 번호는 버립니다 — 위조 "정지 해제"나 오래된 경보 재전송(리플레이)을 막습니다.
릴레이는 서명된 원본을 그대로 3회 반복하므로 중계 장치가 키를 몰라도 됩니다(사이트 키는 펌웨어와 함께 사전 배포).
C++ 구현은 Python 기준 구현(`edgeguard/d2d_auth.py`)과 바이트 단위로 교차 검증합니다(`tests/test_d2d_auth.py`).

## 모니터링 (Prometheus + Grafana)
MEC 앱 `/metrics`(샘플 · 경보 · CSE 쓰기 성공/실패/폐기 · 대기열 · 입력 오류 · 혼잡 · 아차사고 · HA 리더)를 Prometheus가 2 s마다
수집하고, Grafana에 대시보드가 자동 등록됩니다. 운영자 경보 규칙 5개: CSE 쓰기 실패, 샘플 끊김, 리더 없음, 경보 없는 아차사고, 대기열 적체.
```
docker compose --profile monitoring up -d         # Grafana http://localhost:3000 · Prometheus http://localhost:9095
```
CI에서 수집 · 규칙 로드 · 대시보드 등록을 확인합니다(`deploy/check_monitoring.py`). 노트북(8 GB)에서도 두 컨테이너 합쳐 수백 MB 수준입니다.

## 아차사고 분석
경보는 *예측*, 아차사고는 *실제*입니다. 지게차가 움직이는 중 작업자와의 실측 거리가 2 m 미만으로 들어온 접근을 한 건으로,
최근접 시점에 기록합니다(`edgeguard/nearmiss.py`). 그 전에 경보가 나갔는지(`alerted`)와 1 m 격자 히트맵을 함께 남기고,
많이 모이는 칸은 원인별 개선안을 붙입니다 — 사각 코너(지도 추가 · 볼록거울), 고속 통행(속도 제한 구역), 경보 없이 근접(태그 · 앵커 점검),
잦은 교차(보행로 분리). `<AE>/nearmiss`(oneM2M)·`/nearmiss` API·대시보드 히트맵·`tools/safety_report.py`에서 봅니다.
"경보 없는 아차사고"는 시스템의 빈틈이므로 별도로 집계하고 운영자 경보로도 올립니다.

## 카메라 노드 (태그 없는 작업자)

`devices/camera_node.py`: YOLOv8n으로 사람을 찾고, 발 위치(박스 아래 중앙)를 호모그래피로 바닥 좌표(m)로 바꿔
`camera_01/detect`에 씁니다. MEC 앱은 태그 트랙 1.5 m 이내의 탐지는 같은 사람으로 보고, 나머지는 `untagged_N` 트랙으로 만들어
지게차 감속·경광등 경보를 냅니다 (진동은 보낼 태그가 없으므로 생략).

- 추론 시간 (2코어 CPU, YOLOv8n): 640px 113 ms, 320px 39 ms → 5 Hz 가능. Jetson에서는 더 빠릅니다.
- 태그 없이 카메라로만 보이는 작업자 시나리오에서 첫 경보 리드타임 2.27 s, 1.67 s.
- 실행: `EDGEGUARD_YOLO=yolov8n.pt python devices/camera_node.py --source 0` (보정점은 `camera.calib_points`).

## 접근제어 (디바이스별 ACP)

디바이스마다 자기 AE를 등록하고(v1.3), 그 AE의 ACP가 디바이스 자신과 MEC 앱(조회 · 구독)만 허용합니다.
`risk` · `alert` · `control` · `nearmiss`는 MEC 앱만 쓰고 디바이스는 읽기만 합니다. CI가 매 커밋 Mobius에서 아래를 확인합니다(`deploy/check_acl.py`, 8/8 통과):

| 시도 | 결과 |
|---|---|
| SWorker01 → 자기 `worker_01/location` 쓰기 | 허용 |
| SWorker01 → `forklift_01/motion` 쓰기 (위조) | 403 / 4103 거부 |
| SWorker01 → `alert` 쓰기 (가짜 경보) | 403 / 4103 거부 |
| 등록 안 된 SIntruder → `worker_01/location` 쓰기 | 403 / 4103 거부 |
| 디바이스 AE · MEC AE · MEC 구독 존재 | 확인 |

## 안전 리포트 · 데모 영상

- `python tools/safety_report.py --config config/site.yaml` → `results/safety_report.html`:
  CSE에 쌓인 경보 기록으로 1 m 단위 위험 구역 히트맵, 경보가 많은 구역·쌍, 개선 제안을 만듭니다.
- `python tools/record_demo.py --config config/site.yaml` → `results/edgeguard_demo.mp4`:
  대시보드를 띄워 놓고 4개 장면(교차 충돌, 회전 지게차, 태그 없는 작업자, UWB 음영 + Location API)을 재생하며 녹화합니다.

## 관제 대시보드

MEC 앱을 띄우고 브라우저에서 `http://<mec-host>:9090/` 를 엽니다.
작업자·지게차 위치, 3초 예측 경로, 예측 최근접 지점(✕와 남은 시간), 안전 반경, 쌍별 위험도 지표, 경보 로그를 0.2초마다 갱신합니다.
작업자마다 태그 상태(**WAIT** 빨강 · **STEP ASIDE** 주황 · **GO** 초록)를 지도에 표시합니다. MEC 앱이 태그에 보낸 신호로 태그와 같은 상태 기계(`edgeguard/worker_cue.py`)를 돌려 따라갑니다.
