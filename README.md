# EdgeGuard

MEC 기반 산업현장 작업자–지게차 충돌 예측 AIoT 안전 서비스
(2026 oneM2M International Hackathon · Team EdgeGuard, Sejong University)

작업자 태그와 지게차 센서 데이터를 **oneM2M**으로 수집하고, **ETSI MEC** 엣지의 위험도 엔진이
충돌을 1~3초 전에 예측해 **작업자 진동 + 지게차 감속** 경보를 보냅니다.

```
디바이스 ──CIN──▶ oneM2M CSE ──Notify──▶ MEC 앱 (추적 → 예측 → 가이던스 판정)
   ▲                  │                          │
   └──── alert Notify ┴────── risk / alert CIN ◀─┘
```

## 현재 상태 (v0.1)

| 구성 | 상태 |
|---|---|
| 가이던스 위험도 엔진 (CPA/TCPA, LOS rate, collision cone, VO 감속량) | ✅ 구현 · 단위테스트 |
| 칼만 추적기, CV/CTRV 예측 (통로 격자 회전 제한) | ✅ |
| 창고 시나리오 시뮬레이터 8종 + 비교 실험 | ✅ 결과는 아래 |
| oneM2M 클라이언트, 리소스 트리/구독 셋업 | ✅ ACME CSE에서 검증 |
| MEC 앱 (FastAPI, 알림 수신 → risk/alert 게시, 디바운스·홀드) | ✅ end-to-end 검증 |
| 가상 디바이스 (실기 도착 전 대체) | ✅ |
| ESP32 펌웨어 (작업자 태그, 지게차 모듈) | ⚠️ 골격만, 아직 컴파일·실기 검증 안 됨 |
| MEC Docker 이미지 | ⚠️ Dockerfile만, 빌드 미검증 |
| Mobius 연동 | ⏳ 같은 oneM2M API로 작성, 팀 서버에서 확인 필요 |
| MEC Location API / RNIS, LSTM 예측, 대시보드, YOLO | ⏳ 로드맵 W3~W6 |

## 위험도 판정: 가이던스 기하

`r = p_worker − p_forklift`, `v = v_worker − v_forklift`

| 양 | 식 | 의미 |
|---|---|---|
| LOS rate | λ̇ = (r × v) / R² | 시선각 변화율. **λ̇≈0 이면서 접근 중 = 충돌 코스 (CBDR)**, 비례항법(PN)의 원리 |
| CPA 거리 | d_cpa = R²·\|λ̇\| / \|v\| | 최근접 거리를 LOS rate로 쓴 형태 |
| TCPA | −(r·v) / \|v\|² | 최근접까지 남은 시간 |
| ZEM | R²·\|λ̇\| / Vc | PN의 zero-effort miss (참고값) |
| Collision cone | ∠(−v, r) < asin(R_safe/R) | 상대속도가 충돌 원뿔 안 |
| VO 감속량 | 속도를 k배 했을 때 원뿔을 벗어나는 최대 k | 지게차 `speed_scale` 명령 |

지게차는 IMU yaw rate로 **CTRV** 예측을 하고, 회전은 다음 통로 방향(90° 격자)까지만 이어진다고 봅니다.

| 단계 | 조건 (기본값) | 동작 |
|---|---|---|
| DANGER | 예측 최소거리 < 1.5 m, 1.5 s 이내 | 진동 + 감속(VO) |
| WARNING | < 1.8 m, 3 s 이내 | 진동 + 경광등 |
| CAUTION | < 2.5 m, 5 s 이내 | 대시보드 표시만 |

## 비교 실험 (시뮬레이션)

`python -m sim.evaluate --n 250` → `results/evaluation.json`, `python sim/plot_results.py` → `results/evaluation.png`

8개 시나리오 × 250회 = 2,000회, UWB 잡음 0.15 m, 모든 방식에 동일한 0.3 s 디바운스 적용.
"적시 감지" = 접촉(1.5 m 이내) 1초 전 이상 경보.

| 방식 | 적시 감지 | 오경보율 | 리드타임(중앙값) |
|---|---|---|---|
| 근접 3 m | 0.0% | 67.7% | 0.4 s |
| 근접 5 m | 76.3% | 84.8% | 1.2 s |
| TTC < 3 s | 100.0% | 72.7% | 2.1 s |
| 가이던스 (CPA/LOS) | 100.0% | 31.7% | 2.1 s |
| **가이던스 + CTRV** | **100.0%** | **28.7%** | **2.2 s** |

- CTRV는 지게차가 작업자 반대쪽으로 꺾는 `turn_away`에서 오경보를 47 → 15건으로 줄였습니다.
- 남은 오경보의 대부분은 `worker_yields`(충돌 경로로 오다가 2~3 m 앞에서 멈추는 작업자)입니다.
  멈출지 미리 알 수 없어 모든 방식이 경보하며, LSTM 예측으로 개선할 대상입니다.
- 직접 만든 시나리오에서의 결과이므로, W6에 RC카 실측으로 다시 검증합니다.

## 로컬 데모 (하드웨어 없이)

```bash
pip install -r requirements.txt
scripts/run_local_demo.sh crossing_conflict
```
ACME CSE(오픈소스 oneM2M)를 받아 실행하고, MEC 앱과 가상 디바이스를 띄운 뒤 리소스를 만듭니다.
시나리오: `crossing_conflict crossing_clear head_on adjacent_aisle roadside_picker turn_into_worker turn_away worker_yields`

로컬 실행 시 센서 샘플 → CSE → MEC → CSE → 디바이스 경보까지 중앙값 약 25~35 ms였습니다
(한 대의 PC 안에서 측정, 실제 네트워크 지연 미포함).

## Mobius로 전환

`config/edgeguard.yaml`의 `cse`만 바꿉니다.
```yaml
cse:
  base_url: http://<mobius-server>:7579
  cse_rn: Mobius
  origin: SEdgeGuard
```
그다음 `python tools/setup_resources.py`. 실기 디바이스는 `alert_subscribers`에 `http://<esp32-ip>/alert`를 추가합니다.

## oneM2M 리소스 트리

```
/<CSE>/EdgeGuard (AE)
   worker_01/location   {id, kind:"worker", ts, x, y}
   forklift_01/motion   {id, kind:"forklift", ts, x, y, speed, heading, yaw_rate}
   camera_01/detect     (W5: YOLO 결과)
   risk                 {ts, pairs:[{level, range, los_rate, tcpa, dcpa, ttc, d_min, t_min, speed_scale, reason}]}
   alert                {event: raise|refresh|clear, level, worker, forklift,
                         actions:{worker_01:{vibrate}, forklift_01:{beacon, speed_scale}},
                         reason, src_ts, mec_rx_ts, mec_tx_ts}
```
구독: 각 location/motion/detect → MEC 앱 `/notify`, alert → 디바이스 `/alert`.
지금은 AE 하나에 모든 컨테이너를 두는 단순 구조입니다. 디바이스별 AE와 ACP 분리는 W5 작업입니다.

## 폴더

```
edgeguard/   geometry.py (가이던스 기하) · tracking.py (칼만) · predict.py (CV/CTRV) · risk.py · onem2m.py · config.py
mec_app/     MEC 앱 (FastAPI) + Dockerfile
devices/     가상 디바이스
sim/         시나리오 · 비교 실험 · 그래프
tools/       oneM2M 리소스 셋업
firmware/    ESP32 스케치 (worker_tag, forklift_module)
scripts/     로컬 데모, MEC 앱 실행
tests/       단위 테스트 (python -m pytest)
```

## 알려진 한계

- VO 감속량은 직선 운동을 가정합니다. 회전 중에는 감속 명령이 약하게 나올 수 있습니다.
- 모든 디바이스가 같은 originator를 씁니다. 운영 환경에서는 디바이스별 AE와 ACP가 필요합니다.
- `emulated_extra_delay_ms`는 클라우드 경로를 흉내 내는 옵션일 뿐이며, W6에서 실제 클라우드 대비 측정을 해야 합니다.
