# 데이터 모델: SDT flexContainer · 라벨 · 시맨틱

[← README](../../README.ko.md) · [English](../data-model.md)

장치 상태는 contentInstance 속 불투명한 JSON 대신, 자체 SDT 도메인(oneM2M TS-0023 방식)의 **flexContainer 특화 타입**으로 모델링합니다. 모든 리소스에는 탐색용 **라벨**을 달고, 모든 장치는 SAREF로 **시맨틱하게 기술**합니다.

| | `data_model: sdt` (ACME, 로컬 데모 기본값) | `data_model: cin` (모든 CSE, Mobius · ESP32 펌웨어 포함) |
|---|---|---|
| 위치 샘플 | `<dev>/tag\|module/kinematics` UPDATE (egs:kinSt) | `<dev>/location\|motion`에 새 contentInstance |
| 장치 상태 | `cue` / `speedLimit` / `battery` 모듈 | `<dev>/status` contentInstance |
| 탐색 | 라벨 + 시맨틱 쿼리 | 설정 파일의 장치 목록 |

두 모델은 함께 동작하고(카메라와 펌웨어는 contentInstance 유지), MEC 앱은 둘 다 받습니다.

## SDT 도메인 `org.edgeguard.safety` (접두사 `egs`)

파일: [`config/onem2m/edgeguard.fcp`](../../config/onem2m/edgeguard.fcp). `scripts/acme.sh`가 시작할 때마다 ACME 자체 `.fcp` 파일 옆에 복사합니다.

| 타입 | 종류 | 속성 |
|---|---|---|
| `egs:wrkTg` workerTag | 디바이스 클래스 | zone; 자식 kinematics, workerCue, `cod:bat` |
| `egs:frkMe` forkliftModule | 디바이스 클래스 | zone; 자식 kinematics, speedLimit, `cod:bat` |
| `egs:kinSt` kinematicState | 모듈 클래스 | positionX/Y, positionSigma, positionSource, speed, heading, yawRate, sampleTime |
| `egs:wrkCe` workerCue | 모듈 클래스 | cueState (IDLE, WAIT, ASIDE, GO), cueSource |
| `egs:spdLt` speedLimit | 모듈 클래스 | limit, maxSpeed |
| `cod:bat` battery | 표준 모듈 클래스 (org.onem2m.common) | level, charging, … |
| `egs:flTsk`, `egs:flPrt` | 모듈 클래스 | 연합학습 태스크 · 참여자 ([연합학습](federated-learning.md)) |

## 디바이스 트윈

```
<dev> (AE, lbl egs:site/<site>, egs:role/<kind>, egs:id/<dev>)
  tag | module     egs:wrkTg | egs:frkMe        lbl … egs:device
    kinematics     egs:kinSt  fcied, mni 100   lbl … egs:module/kinematics     <- MEC 앱이 구독 (net 1, update)
    cue | speedLimit                            장치가 표시 · 적용하는 값 (장치가 기록)
    battery        cod:bat
    smd            semanticDescriptor, RDF/Turtle (dcrp 5), SAREF
  relay · status   컨테이너 (D2D 중계, 구동기 동작 확인)
  acp_<dev>        장치: 전체 · MEC 앱, MEC-IPE: 조회 · 탐색 · 알림 · 구독 생성만
```

`edgeguard/sdt.py: build_twin()`이 만들고, 초기 설정 · 자가 등록 · CSE 핸드오버에서 씁니다.

## 탐색: 라벨

- `GET /<cse>?fu=1&ty=28&lbl=egs:module/kinematics`는 모든 kinematics 모듈을 돌려줍니다.
- MEC 앱은 10 s마다 이를 실행합니다(`mec_app/app.py`의 `discover_devices`). 스스로 등록한 장치는 어떤 설정에도 없어도 구독 · 추적됩니다. CI에서는 약 9 s 만에 편입됩니다.

## 시맨틱: SAREF

각 트윈에는 시맨틱 디스크립터가 있습니다.

```turtle
egs:forklift_01 a saref:Device , saref:Sensor , saref:Actuator , egs:ForkliftModule ;
    egs:role "forklift" ; egs:resource "forklift_01/module" ;
    saref:measuresProperty egs:Position , egs:Velocity ;
    saref:controlsProperty egs:DriveSpeed ;
    saref:consistsOf egs:DriveSpeedLimiter .
```

시맨틱 쿼리(`fu=2&sqi=true&rcn=10&smf=<SPARQL>`)는 "구역 A에서 주행 속도를 제어하는 지게차" 같은 질문에 답하고 oneM2M 경로를 돌려줍니다: `edgeguard/sdt.py: query_devices()`, `OneM2MClient.semantic_query()`. ACME의 시맨틱 *리소스 탐색*(`sqi=false`)은 인자 검사에서 거부되므로, EdgeGuard는 시맨틱 쿼리 형식을 씁니다.

## 접근 제어

- `accessControlObjectDetails`(`chty: [23]`)를 쓴 ACP로, MEC 앱은 장치 트윈에 **구독만** 만들 수 있습니다. 데이터는 쓸 수 없습니다.
- 다른 장치의 UPDATE는 403으로 거부됩니다(`deploy/check_sdt.py`로 확인).

## 확인

```bash
scripts/acme.sh start in
EDGEGUARD_CONFIG=config/site.yaml EDGEGUARD_OVERRIDES=config/local-acme.yaml,config/live-demo.yaml scripts/run_live_demo.sh &
python deploy/check_sdt.py --onboard        # 6개 확인, CI에서도 실행
```

6개 확인 항목: 라벨이 달린 트윈 · 라벨 탐색 · kinematics 이력 · 시맨틱 쿼리 · 다른 장치 거부(ACP) · 자가 등록 장치 편입.
