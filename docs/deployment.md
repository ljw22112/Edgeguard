# 배포

Docker Compose 스택, 로컬 데모, 배포 구조 결정(측정), oneM2M 리소스 트리, 펌웨어 · CI.

[← README](../README.md)

## MEC 호스트 배포 (Docker Compose)

MariaDB + Mobius(oneM2M IN-CSE) + MEC 앱을 한 번에 띄웁니다. 경보 정책 · 적응형 주기 · 접근제어는 `config/site.yaml` 그대로이고,
주소만 `deploy/compose-overrides.yaml`로 덮습니다 (`EDGEGUARD_OVERRIDES`, 깊은 병합).

```bash
cd deploy
docker compose up -d                    # MEC 호스트 스택 (빌드 포함)
docker compose --profile demo up        # + oneM2M 리소스 셋업 + 가상 디바이스 (조우 4회)
python3 check_demo.py out/devices.json http://localhost:9090/health
# 대시보드 http://localhost:9090/ · 실기 디바이스는 http://<호스트>:7579/Mobius 로 접속
```

미리 빌드된 이미지 (저장소가 비공개라 토큰으로 로그인 필요: `read:packages` 권한의 PAT):
```bash
echo $GHCR_TOKEN | docker login ghcr.io -u <GitHub 아이디> --password-stdin
export EDGEGUARD_IMAGE_TAG=latest EDGEGUARD_PULL_POLICY=always   # Windows cmd: set 로 각각 지정
docker compose up -d
```

| 구성 요소 | 이미지 | 비고 |
|---|---|---|
| MariaDB | `mariadb:11.4` | 데이터는 `db-data` 볼륨 |
| Mobius | `ghcr.io/ljw22112/edgeguard-mobius` | 커밋 고정 + 의존성 잠금. 시작 시 `conf.json` 작성 · 봉인 · 스키마 1회 가져오기 |
| MEC 앱 | `ghcr.io/ljw22112/edgeguard-mec` | 비루트 실행, `/health` 상태 검사. 같은 이미지로 셋업 · 가상 디바이스 실행 |

- Mobius는 DB를 `localhost:3306`으로 고정해 접속하므로 MariaDB 컨테이너의 네트워크를 공유하고, 다른 서비스는 별칭 `mobius`로 찾습니다.
- `.github/workflows/docker.yml`: 푸시마다 공식 베이스 이미지로 빌드 → 스택 기동 → 데모 조우 4회 경보 확인
  (`deploy/check_demo.py`: 4회 모두 1 s 이상 전에 경보, 쓰기 실패 0) → DB를 유지한 채 재시작해 다시 확인 → main이면 GHCR 게시
  (`latest`, `sha-<커밋>`).
- 시험 결과 (이 환경, 4회 × 반복 3번): 리드타임 3.6~3.9 s, 경보 지연 중앙값 25~31 ms, 쓰기 실패 0.
- 팀 노트북 실측 (갤럭시 북2 프로 · RAM 8GB, Windows 11 + Docker Desktop/WSL2, `results/deploy_windows_pc.json`): 조우 4회 모두 경보, 리드타임 3.83 / 3.54 / 3.62 / 3.51 s,
  경보 지연 중앙값 58 ms (p95 82 ms), 경보 30건, 쓰기 실패 0.
- 배포 시험에서 버그 하나를 찾아 고쳤습니다: 조우 사이에 추적이 끊기면 짝의 경보 상태가 WARNING으로 남아,
  다음 조우의 첫 경보가 진동이 안 날 수 있는 "refresh"로 나갔습니다. 이제 2 s 이상 평가되지 않은 짝은 새 조우로 시작합니다
  (반복 실행 리드타임 1.1 / 0.8 / 3.7 / 1.3 s → 3.9 / 3.6 / 3.7 / 3.6 s).

## 로컬 데모 (하드웨어 없이)

```bash
pip install -r requirements.txt
scripts/run_local_demo.sh crossing_conflict
```
ACME CSE(오픈소스 oneM2M)를 받아 실행하고, MEC 앱과 가상 디바이스를 띄운 뒤 리소스를 만듭니다.
시나리오: `crossing_conflict crossing_clear head_on adjacent_aisle roadside_picker turn_into_worker turn_away worker_yields`

로컬 실행 시 센서 샘플 → CSE → MEC → CSE → 디바이스 경보까지 중앙값 약 25~35 ms였습니다
(한 대의 PC 안에서 측정, 실제 네트워크 지연 미포함).

## 배포 구조 (측정으로 결정)

![구성도](architecture.png)

**결정: 엣지 Mobius(MEC 호스트) + 클라우드 Mobius, MEC 앱이 클라우드로 동기화** — `config/site.yaml`

후보 4개를 한 대의 PC에서 띄우고, 현장↔클라우드 구간은 `tools/wan_proxy.py`로 단방향 25±5 ms(왕복 약 50 ms)를 걸어 측정했습니다.
충돌 시나리오 6회씩, `python tools/topology_bench.py` → `results/topology_25ms.json`.

| 구성 | 경보 지연 중앙값 / p95 | WAN 단절 시 현장 경보 | 클라우드 사본 | 엣지 CSE 처리량 |
|---|---|---|---|---|
| ① 클라우드 Mobius만 | 85 / 133 ms | ❌ 0건 (전부 중단) | 해당 없음 | — |
| ② 엣지 Mobius만 | 23.5 / 29 ms | ✅ | ❌ 없음 | 250 writes/s 여유 |
| **③ 엣지 Mobius + 클라우드 동기화** | **25 / 52 ms** | **✅ 26/26건 유지** | **✅** | **250 writes/s 여유** |
| ④ 엣지 ACME MN ↔ 클라우드 Mobius (Mcc) | 33 / 43 ms | ✅ 26/26건 유지 | ✅ (MN 재지정) | ❌ 약 110 writes/s에서 포화 |

엣지 CSE 부하 시험 (`tools/cse_load_bench.py`, 디바이스마다 10 Hz, 모든 컨테이너에 구독):

| 디바이스 수 (요청/s) | Mobius 쓰기 p95 | Mobius 알림 p95 | ACME 처리량 | ACME 쓰기 p95 |
|---|---|---|---|---|
| 10 (100) | 10 ms | 12 ms | 100.7/s | 32 ms |
| 25 (250) | 63 ms | 71 ms | **109/s (포화)** | 323 ms |
| 50 (500) | 205 ms (355/s) | 237 ms | 112/s | 642 ms |

판단 근거
- **가용성이 결정적입니다.** ①은 클라우드 연결이 끊기면 경보가 하나도 나가지 않습니다. 안전 시스템으로 쓸 수 없습니다.
  지연 차이(약 60 ms)는 예측 리드타임 2초에 비하면 작지만, 단절 시 동작 차이는 0과 100%입니다.
- **규모에서 ④가 탈락했습니다.** 작업자 20명 + 지게차 5대(10 Hz)면 초당 250건인데, ACME는 약 110건에서 포화되어 지연이 수백 ms로 늘어납니다.
  Mobius는 같은 조건에서 p95 63 ms입니다 (부하 생성기와 같은 2코어 PC에서 측정한 보수적인 값).
- **③이 ②의 성능을 그대로 유지하면서 클라우드 사본을 얻습니다.** 동기화는 별도 큐에서 돌기 때문에 WAN이 느리거나 끊겨도 현장 경보에 영향이 없습니다 (단절 시 실패 74건은 `/health`에 집계).
- 한계: Mobius 3은 IN-CSE 전용이라 엣지와 클라우드 Mobius 사이는 oneM2M Mcc 등록이 아니라 MEC 앱의 동기화입니다.
  표준 Mcc 연동은 ④ 구성(ACME MN → Mobius IN)으로 별도 검증했으며, 저속 게이트웨이(카메라 노드 등)를 붙이는 용도로 남겨 둡니다.

실행 (엣지 서버에 Mobius가 떠 있다고 가정):
```bash
export EDGEGUARD_CONFIG=config/site.yaml      # cloud_sync.base_url만 클라우드 주소로 수정
scripts/mec.sh start
python devices/device_sim.py --config config/site.yaml --start-delay 4 &
python tools/setup_resources.py --config config/site.yaml --reset
```
Mobius 3.x의 CSEBase는 `srv: ["1","2","2a"]`라서 `rvi: "2a"`를 씁니다.

상호운용성 시험에서 찾은 문제와 해결은 [docs/interop-notes.md](interop-notes.md)에 정리했습니다.

## oneM2M 리소스 트리

```
/Mobius (CSEBase)
└── EdgeGuard (AE)                          originator SEdgeGuard (MEC 앱)
    ├── worker_01 (CNT) / location (CNT)    작업자 태그 → CIN {id, kind:"worker", ts, x, y}
    ├── forklift_01 (CNT) / motion (CNT)    지게차 모듈 → CIN {id, kind:"forklift", ts, x, y, speed, heading, yaw_rate, route?}
    ├── camera_01 (CNT) / detect (CNT)      카메라 노드 → CIN {kind:"camera", ts, persons:[{x, y}, ...]}
    ├── risk (CNT)                          MEC → 쌍별 위험도 요약 {pairs:[{level, range, tcpa, dcpa, ttc, d_min, speed_scale, reason}]}
    ├── alert (CNT)                         MEC → 경보 {event, level, worker, forklift, actions, reason, src_ts, mec_tx_ts}
    │                                        event: raise · refresh · clear (지게차 + 작업자), wait · release · aside (작업자만)
    ├── control (CNT)                       MEC → 하트비트 1 s + 보고 주기 명령 {ts, hb, rates}
    ├── nearmiss (CNT, mni 2000)            MEC → 아차사고 기록 {worker, forklift, d_min, x, y, alerted}
    ├── mec_lease (CNT, mni 20)             MEC 앱 이중화 임대 {id, seq, ts}
    └── acp_<device> · acp_risk · acp_alert · acp_control · acp_nearmiss (ACP)
```

| 구독 (SUB) | 대상 | 알림 받는 곳 |
|---|---|---|
| `sub_mec` (이중화 시 `sub_mec_mec2` 추가) | 각 `location` · `motion` · `detect` | MEC 앱 `/notify` |
| `sub_devices`, `sub_hw<N>` | `alert`, `control` | 가상 디바이스 · 실기 단말 |

- 접근제어: 디바이스 컨테이너는 그 디바이스와 MEC 앱만 쓸 수 있고, `risk` · `alert` · `control`은 MEC 앱만 쓰고 디바이스는 읽기만 합니다
  ([현장 기능](site-features.md) "접근제어"). Mobius에서 위조 쓰기 차단을 확인했습니다.
- 현재는 AE 하나 아래에 디바이스별 컨테이너를 두고, 디바이스별 ACP로 쓰기 권한을 나눕니다.

## 펌웨어
- 작업자 태그: DW1000 양방향 거리 측정 → `firmware/common/uwb_position.h`(선형화 최소제곱 + 가우스-뉴턴, 앵커 1개 NLOS 배제).
  Python 쌍둥이 `edgeguard/uwb.py`와 같은 결과인지 테스트합니다 (잡음 0.1 m에서 평균 오차 < 0.15 m, NLOS 앵커 +1.5 m 배제).
- 두 스케치 모두 `<ae>/control`의 주기 명령과 하트비트를 처리하고, 지게차는 위 페일세이프 규칙으로 PWM을 제한합니다.
- `tests/test_firmware_build.py`: 실제 ArduinoJson + ESP32 API 스텁으로 두 스케치를 `-Wall -Wextra -Werror` 타입 검사합니다 (CI에서도 실행).

## 설치 · CI
- `scripts/setup_mobius.sh` — Mobius 3 + MariaDB 설치 · 시작 (`install | start | stop | status`). 스키마의 MySQL 8 정렬 규칙을 MariaDB용으로 바꾸고, 대화형 비밀값 설정도 자동으로 처리합니다.
- `.github/workflows/ci.yml` — 푸시마다 Python 3.11에서 전체 테스트 (LSTM 포함, CPU torch) + 펌웨어 타입 검사.
