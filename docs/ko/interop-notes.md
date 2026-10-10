# 상호운용성 시험 노트

EdgeGuard는 같은 코드로 두 oneM2M 구현체(ACME CSE, KETI Mobius)에 붙고, 두 CSE를 서로 등록(Mcc)하는 시험을 했습니다.
시험 중 발견한 문제와 대응을 기록합니다.

## 시험 환경

| 구성 요소 | 버전 / 설정 |
|---|---|
| KETI Mobius | 3.0.1 (IN-CSE), MySQL 백엔드(MariaDB 10.11), `cseId=/Mobius2`, `srv: 1, 2, 2a` |
| ACME CSE | 2026.05.1, MN-CSE 모드 (`cse-mn`, `/id-mn`), `releaseVersion=2a` |
| EdgeGuard 클라이언트 | `edgeguard/onem2m.py`, HTTP 바인딩, JSON |

## 결과 요약

| 항목 | 결과 |
|---|---|
| EdgeGuard → ACME (IN, RVI 3) 전체 루프 | ✅ |
| EdgeGuard → Mobius (IN, RVI 2a) 전체 루프 | ✅ 코드 수정 없이 설정만 변경 |
| ACME MN-CSE → Mobius IN-CSE CSR 등록 | ✅ (MySQL 백엔드 필요) |
| ACME MN 경유 재지정(`~/Mobius2/Mobius/...`)으로 클라우드에 CIN 생성 | ✅ |

## 발견한 문제

### 1. ACME가 Mobius 응답의 Content-Type을 해석하지 못함 (ACME 측 수정)

- 증상: ACME MN이 Mobius로 보낸 요청의 응답을 처리하지 못해 등록이 실패.
- 원인: Mobius는 `Content-Type: application/json; charset=utf-8`로 응답하는데, ACME `HttpServer.sendHttpRequest()`가
  헤더 값을 그대로 직렬화 타입 조회에 써서 `; charset=utf-8` 부분 때문에 JSON으로 인식하지 못함.
- 수정 (ACME `acmecse/plugins/bindings/HttpServer.py`):
  ```python
  resp.ct = ContentSerializationType.getType(r.headers.get('Content-Type', ct).split(';')[0].strip())
  ```
  미디어 타입 매개변수를 떼고 비교합니다 (패치: [acme-content-type.patch](../acme-content-type.patch)). HTTP 표준상 매개변수는 허용되므로 ACME 쪽 버그로 보고할 대상입니다.

### 2. Mobius SQLite 백엔드는 remoteCSE 미지원

- Mobius 3의 SQLite 백엔드는 CSEBase, AE, ACP, container, contentInstance, subscription만 지원하고
  나머지(remoteCSE 포함)는 `501 / RSC 5001`로 거부합니다. Mcc 등록 시험에는 MySQL 백엔드가 필요합니다.
- MariaDB에서 `mobiusdb.sql`을 가져올 때 `utf8mb4_0900_ai_ci` 콜레이션이 없어 실패하므로
  `utf8mb4_general_ci`(및 `utf8mb4_0900_bin` → `utf8mb4_bin`)로 바꿔 가져왔습니다.

### 3. Mobius에서 AE 삭제 직후 같은 이름으로 재생성 시 간헐적 404/409

- 증상: AE를 지우고 바로 다시 만든 뒤 하위 컨테이너를 만들면, 이름 충돌(409)이 나거나 경로가 없다(404)고 나옴.
- 원인 추정: 클러스터 워커 간 반영 지연과 하위 리소스 정리 타이밍.
- 대응 (`tools/setup_resources.py`, `edgeguard/onem2m.py`): 초기화 시 하위 리소스부터 지우고,
  생성은 404일 때 짧게 재시도하며, 이미 있는 구독은 `nu`만 갱신(PUT)합니다.

### 4. MN-CSE 재지정이 등록 시 받은 poa로 직접 나감 (시험 환경 한정)

- ACME MN은 등록 후 Mobius가 광고하는 poa(호스트 IP)로 재지정 요청을 보냅니다.
  한 대의 PC에서 WAN 지연을 흉내 낼 때는 이 경로가 지연 프록시를 우회하므로,
  시험 스크립트가 MN의 CSR `poa`를 프록시 주소로 바꿔 둡니다 (`tools/topology_bench.py`의 `pin_registrar_poa`).
  실제 배포에서는 그 주소 자체가 WAN 너머에 있으므로 해당 없습니다.

### 5. 지원 릴리스 버전 차이

- Mobius 3 CSEBase는 `srv: ["1","2","2a"]`, ACME는 `2a, 3, 4, 5`를 지원합니다.
  공통 분모인 `2a`로 맞추면 양쪽 모두 동작합니다 (`config/site.yaml`의 `rvi: "2a"`).

### 6. Mobius는 originator 하나에 AE 하나

- 같은 `X-M2M-Origin`으로 이름이 다른 AE를 또 만들면 409(충돌)가 나고, 그 경로는 404로 보입니다.
  AE-ID가 originator에서 정해지기 때문입니다. 시험용 AE를 따로 만들 때는 originator도 따로 써야 합니다.

### 7. Mobius ACP의 acpi 참조 형식

- `acpi`에 구조적 경로(`Mobius/EdgeGuard/acp_worker_01`)를 넣으면 동작하고, Mobius는 `/Mobius/...` 형태로 돌려줍니다.
  `edgeguard/onem2m.py`의 `set_acpi`는 구조적 경로를 먼저 쓰고, 실패하면 리소스 ID로 다시 시도합니다.
