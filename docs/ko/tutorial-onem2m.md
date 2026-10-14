# 튜토리얼: 10분 만에 만드는 oneM2M 안전 앱

[← README](../../README.ko.md) · [English](../tutorial-onem2m.md)

oneM2M CSE에 HTTP 요청만 보내서 EdgeGuard의 핵심을 만듭니다. 작업자 태그가 위치를 올리고, 안전 앱이 태그를 찾아 구독하고, 작업자가 지게차 통로에 들어가면 태그의 수신함에 경보를 씁니다. 전체 스크립트는 [`tools/tutorial_safety_app.py`](../../tools/tutorial_safety_app.py)이고, `requests`만 쓰는 약 100줄이며 매 커밋 CI에서 실행됩니다.

```bash
scripts/acme.sh start in                 # :8080의 ACME CSE (Mobius 등은 CSE / CSE_RN 환경 변수로)
python tools/tutorial_safety_app.py      # 요청을 모두 출력하고 PASS 5줄
```

## 모든 요청에 붙는 헤더 세 개

HTTP 위의 oneM2M(TS-0009)은 발신자, 요청 ID, 릴리스 버전을 헤더에 넣습니다. CREATE의 리소스 타입은 Content-Type에 들어갑니다.

```
POST /cse-in              X-M2M-Origin: CTutorialTag   X-M2M-RI: 8f3a…   X-M2M-RVI: 3
Content-Type: application/json;ty=2
```

## 1. 태그 등록과 컨테이너 생성

```json
POST /cse-in  ty=2   {"m2m:ae": {"rn": "tutorial_tag", "api": "Ntutorial.tag", "rr": false, "srv": ["3"],
                                 "lbl": ["tutorial/worker-tag", "zone/A"]}}
POST /cse-in/tutorial_tag  ty=3   {"m2m:cnt": {"rn": "position", "mni": 50}}
POST /cse-in/tutorial_tag  ty=3   {"m2m:cnt": {"rn": "alerts", "mni": 20}}
```

`rr: false`는 태그가 NAT 뒤에 있어 밖에서 접근할 수 없다는 뜻입니다. `mni`는 이력 개수를 제한합니다. 앱은 나중에 디바이스 목록 없이 라벨로 태그를 찾습니다.

## 2. 누가 무엇을 할 수 있는지는 태그가 정합니다

접근 제어 정책(TS-0003) 세 개입니다. `acr` 규칙마다 발신자와 연산 비트를 적습니다: CREATE 1, RETRIEVE 2, UPDATE 4, DELETE 8, NOTIFY 16, DISCOVERY 32.

| ACP | 대상 | 앱에 허용 |
|---|---|---|
| `acp_ae` | AE | RETRIEVE + DISCOVERY: 태그 찾기 |
| `acp_tag` | `position` | RETRIEVE, DISCOVERY, NOTIFY, 구독만 생성(`acod.chty = [23]`) |
| `acp_alerts` | `alerts` | contentInstance 생성만(`chty = [4]`), 읽기도 불가 |

```json
POST /cse-in/tutorial_tag  ty=1
{"m2m:acp": {"rn": "acp_tag",
  "pv":  {"acr": [{"acor": ["CTutorialTag"], "acop": 63},
                  {"acor": ["CTutorialApp"], "acop": 51, "acod": [{"chty": [23]}]}]},
  "pvs": {"acr": [{"acor": ["CTutorialTag"], "acop": 63}]}}}
PUT  /cse-in/tutorial_tag/position   {"m2m:cnt": {"acpi": ["<acp_tag의 ri>"]}}
```

## 3. 앱 등록과 라벨 탐색

```
POST /cse-in  ty=2   {"m2m:ae": {"rn": "tutorial_app", "rr": true, "poa": ["http://127.0.0.1:9399"], …}}
GET  /cse-in?fu=1&lbl=tutorial/worker-tag&ty=2        →  {"m2m:uril": ["cse-in/tutorial_tag"]}
```

`poa`는 CSE가 알림을 보낼 주소입니다. 탐색 결과에는 앱이 볼 권한이 있는 것만 나옵니다.

## 4. 구독

```json
POST /cse-in/tutorial_tag/position  ty=23
{"m2m:sub": {"rn": "sub_app", "nu": ["cse-in/tutorial_app"], "enc": {"net": [3]}}}
```

`nu`에는 앱의 AE를 적고, CSE가 `poa`로 바꿉니다. 구독을 받아들이기 전에 CSE가 확인 요청(`vrq: true`)을 보내고 앱은 2000으로 답합니다. `net: 3`은 "새 자식 리소스가 생기면 알려 달라"는 뜻입니다.

## 5. 게시 → 알림 → 판단 → 경보

```
POST /cse-in/tutorial_tag/position  ty=4   {"m2m:cin": {"con": {"x": 31.0, "y": 12.5}}}
   → CSE가 앱에 알림:  {"m2m:sgn": {"nev": {"rep": {"m2m:cin": {"con": {"x": 31.0, "y": 12.5}}}, "net": 3}, "sur": "…/sub_app"}}
   → 앱: y가 통로(7~13 m) 안
POST /cse-in/tutorial_tag/alerts  ty=4  (CTutorialApp)   {"m2m:cin": {"con": {"cue": "WAIT"}}}
```

태그와 앱은 서로 직접 통신하지 않습니다. ACP만 맞으면 다른 앱도 같은 위치를 구독할 수 있고, EdgeGuard는 이렇게 디바이스를 건드리지 않고 대시보드, AI 에이전트, 연합학습을 붙였습니다.

## 6. 접근 제어 확인

```
GET  /cse-in/tutorial_tag/alerts/la   (CTutorialTag)  → 200 {"cue": "WAIT", …}
POST /cse-in/tutorial_tag/alerts      (CStranger)     → 403
GET  /cse-in/tutorial_tag/alerts/la   (CTutorialApp)  → 403   앱은 경보를 만들 수만 있고 읽을 수 없음
```

## EdgeGuard는 여기서 더 나아갑니다

| 튜토리얼 단계 | EdgeGuard | oneM2M 표준 | 코드 |
|---|---|---|---|
| contentInstance로 위치 | SAREF 시맨틱을 붙인 SDT flexContainer 트윈 | TS-0023, TS-0034 | [data-model.md](data-model.md) |
| 태그 하나에 경보 하나 | 구역 `<group>`의 fanOutPoint로 요청 한 번에 구역 전체 태그 | TS-0001 §9.6.13 | [zones.py](../../edgeguard/zones.py) |
| `rr: false` | 태그가 `<pollingChannel>`로 수신 | TS-0001 §9.6.21 | [transport-security.md](transport-security.md) |
| HTTP | 디바이스는 상호 TLS MQTT 바인딩, 앱은 HTTPS | TS-0010, TS-0009 | [mqtt_binding.py](../../edgeguard/mqtt_binding.py) |
| CSE 하나 | IN-CSE 아래 구역 MN-CSE, 지게차 AE가 공지와 함께 이동 | TS-0001 §9.6.26, TR-0077 §7.2 | [handover.md](handover.md) |
| 고정된 통로 규칙 | ETSI MEC 호스트의 충돌 경로 예측, MEC-IPE로 MEC 013 위치 | TR-0077 §7.1 | [mobility.md](mobility.md), [mec-platform.md](mec-platform.md) |
| 앱 하나 | 의도 리소스 하나로 오케스트레이터가 앱 배포, 연합학습 클라이언트도 같은 방식 | TR-0077 §7.1, §7.3, TR-0084 | [orchestration.md](orchestration.md) |
