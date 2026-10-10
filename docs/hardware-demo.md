# 실물 시연 (Hardware-in-the-loop)

[← README](../README.md)

ESP32 보드 2개가 **작업자 태그(worker_01)** 와 **지게차 모듈(forklift_01)** 역할을 실제로 합니다.
UWB 측위 대신 위치는 `devices/live_devices.py`가 공급하고, 보드는 실제 단말이 하는 일을 그대로 합니다.

| 실제로 일어나는 것 | 시뮬레이션이 맡는 것 |
|---|---|
| 보드가 부팅하며 oneM2M AE · 컨테이너를 스스로 등록 (`registerAE`) | 작업자 · 지게차의 위치와 움직임 |
| MEC 앱 경보를 oneM2M 구독 알림으로 수신 (`/alert`) | |
| 진동 모터 · LED (WAIT / STEP ASIDE / GO), 모터 감속 · 경광등 | |
| 동작 확인을 자기 AE의 `status`에 기록 → 대시보드에 **HW ✓** 표시 | |

UWB 보드(DW1000)까지 붙이면 같은 펌웨어(`HIL_MODE 0`)로 측위까지 실물로 바뀝니다.

## 준비물 (약 5만 원)

| 부품 | 수량 | 용도 |
|---|---|---|
| ESP32 개발 보드 (ESP32-WROOM DevKit 등) | 2 | 태그 · 지게차 모듈 |
| 코인 진동 모터 + NPN 트랜지스터(2N2222) + 다이오드(1N4148) + 1 kΩ 저항 | 1 세트 | 태그 진동 |
| LED + 220 Ω 저항 | 2 | 태그 WAIT 표시, 지게차 경광등 |
| 소형 DC 모터 + 모터 드라이버(L298N 또는 MOSFET 모듈) | 1 | 지게차 구동(감속이 눈에 보이게 바퀴나 팬을 달면 좋음) |
| 브레드보드 · 점퍼선 · 보조배터리 2 | — | |

## 배선

| 보드 | 핀 | 연결 |
|---|---|---|
| 태그 | GPIO 25 (`MOTOR_PIN`) | 1 kΩ → 트랜지스터 베이스, 컬렉터에 진동 모터(반대쪽 3.3 V), 모터 양단에 다이오드 |
| 태그 | GPIO 2 (`LED_PIN`) | 220 Ω → LED → GND (대부분의 보드에 내장 LED) |
| 지게차 | GPIO 27 (`MOTOR_PWM_PIN`) | 모터 드라이버 PWM/EN 입력, 드라이버 전원은 보조배터리 |
| 지게차 | GPIO 26 (`BEACON_PIN`) | 220 Ω → LED → GND |

## 펌웨어 올리기

1. Arduino IDE에 ESP32 보드 패키지(3.x), 라이브러리 **ArduinoJson**, **arduino-dw1000** 설치.
2. `firmware/worker_tag/worker_tag.ino`, `firmware/forklift_module/forklift_module.ino`에서:
   - `#define HIL_MODE 0` → **`1`**
   - `WIFI_SSID` · `WIFI_PASS` — 노트북과 같은 Wi-Fi
   - `CSE_URL` → `http://<노트북 IP>:8080/cse-in` (로컬 ACME), Mobius면 `http://<IP>:7579/Mobius`
3. 업로드 후 시리얼 모니터(115200)에서 `oneM2M AE worker_01: ok`와 보드 **IP**를 확인합니다.

## 실행

```bash
# 1) config/hw-demo.yaml 에 두 보드의 IP를 적습니다 (alert_subscribers)
# 2) 로컬 ACME를 띄운 뒤 (scripts/run_local_demo.sh 가 처음 한 번 설치 · 실행)
HW=1 scripts/run_live_demo.sh          # MEC 앱 + 리소스 + 반응하는 가상 위치 (장면 반복)
# 대시보드 http://localhost:9090/  — oneM2M 패널에 worker_01 / forklift_01 옆 "HW ✓"
```

## 확인 항목 (영상 촬영 체크리스트)

| # | 장면 | 기대 동작 | 결과 |
|---|---|---|---|
| 1 | 부팅 | 시리얼에 `oneM2M AE ... ok`, ACME/Mobius에 `worker_01` · `forklift_01` AE 생성 | |
| 2 | crossing | 태그: 긴 진동 → LED 켜짐 + 1초마다 짧은 진동(WAIT) → 지게차 통과 후 짧은 진동 2번(GO), LED 꺼짐 | |
| 3 | crossing | 지게차: 경광등 깜빡임, 모터가 통과 속도로 느려졌다가 해제 후 원래 속도 | |
| 4 | head_on | 태그: STEP ASIDE(긴 진동) → WAIT → GO / 지게차: 모터 정지 후 재출발 | |
| 5 | 대시보드 | 지도 배지(WAIT/STEP ASIDE/GO)와 oneM2M 패널의 **HW ✓ 상태**가 보드 동작과 일치 | |
| 6 | 장애 | 경보 중(지게차 감속 중)에 MEC 앱 종료(`scripts/mec.sh stop`) → 2초 뒤 지게차 모터 정지(침묵 페일세이프), 태그 WAIT는 2.5초 뒤 스스로 해제 | |
| 7 | 접근제어 | `python3 deploy/check_acl.py http://localhost:8080/cse-in` → 8/8 | |

결과 칸을 채우고 영상(휴대폰 촬영 + 화면 녹화)을 함께 남기면 "실제 작동" 근거가 됩니다.
