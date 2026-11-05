# EdgeGuard와 oneM2M · ETSI MEC 생태계

[← README](../../README.ko.md) · [English](../ecosystem.md)

다른 사람들이 만든 것에 EdgeGuard를 붙여 보는 세 가지 점검이며, 모두 매 커밋 CI에서 돕니다.

## 1. 세 번째 CSE: tinyIoT

[tinyIoT](https://github.com/seslabSJU/tinyIoT)는 세종대학교 소프트웨어공학 · 보안 연구실이 C로 만든 가벼운 oneM2M CSE(BSD-3-Clause)입니다. oneM2M 공식 오픈소스 목록에 있고 ESTIMED 개발 자료에서도 추천합니다. TR-0086 옵션 C의 MEC 호스트에 필요한 것이 바로 가벼운 MN-CSE입니다.

| | ACME | tinyIoT |
|---|---|---|
| oneM2M 튜토리얼([`tools/tutorial_safety_app.py`](../../tools/tutorial_safety_app.py), 점검 5개) | 5/5 | **5/5**(대체 처리 3가지, 문서화) |
| EdgeGuard 사용 기능([`tools/cse_probe.py`](../../tools/cse_probe.py)) | 13/13 | 9/13 |
| tinyIoT에 없는 것 | — | content의 JSON 객체, ACP `chty`, pollingChannel, semanticDescriptor |

차이와 EdgeGuard의 대응은 [interop-notes.md](interop-notes.md)의 상호운용 이슈 8~11입니다. 이제 같은 애플리케이션 코드가 ACME, KETI Mobius, tinyIoT 세 가지 독립 CSE 구현에서 동작합니다.

## 2. ETSI 공식 OpenAPI로 EdgeGuard의 MEC 트래픽 검증

[`tools/mec_conformance.py`](../../tools/mec_conformance.py)는 두 구역 시나리오로 MEC 플랫폼 대역을 띄우고, EdgeGuard 자체 클라이언트를 그대로 실행합니다(MEC-IPE: MEC 013 구역 · 영역 · 거리 구독과 위치 조회, MEC 012 무선 구독 / Mp1: MEC 011 READY · 서비스 등록 · 탐색 · 가용성 구독 / MEC 021 AMS 등록 · 구독 · 컨텍스트 이전). 모든 교환을 [openapi-core](https://github.com/python-openapi/openapi-core)로 ETSI Forge 정의(MEC 013 3.1.1, MEC 012 2.2.1, MEC 011 3.1.1, MEC 021 2.2.1, BSD-3-Clause 라이선스와 함께 [`third_party/etsi-mec/`](../../third_party/etsi-mec/))에 대조합니다.

| | 이전 | 이후 |
|---|---|---|
| 명세에 맞는 요청 · 응답 | 19건 중 13건 | **19건 중 19건** |
| 명세에 맞는 알림(6종) | 77건 중 0건(더 짧은 실행) | **160건 중 160건** |

찾은 것과 바꾼 것:
- MEC 013 v3의 `callbackReference`는 `{notifyURL}`(v2 형식)이 아니라 URI 문자열이고, 거리 조건은 `ALL_WITHIN_DISTANCE`가 아니라 `AllWithinDistance`입니다.
- MEC 012와 MEC 021은 `AssociateId.type`, 보고 트리거, `mobilityStatus`를 정수로 씁니다.
- 알림에는 `_links`가 들어가고, 거리 알림의 사용자 정보는 완전한 `UserInfo`, ServiceInfo에는 `_links`와 전송 `security` 블록이 들어갑니다.

EdgeGuard는 이제 ETSI 형식으로 보내고, 예전 이름도 계속 읽습니다([`edgeguard/mec_codes.py`](../../edgeguard/mec_codes.py)). MEC 플랫폼 · 모빌리티 데모는 이전처럼 10/10입니다.

공개된 정의 파일 자체의 결함은 EdgeGuard에서 우회하지 않고 검증기에서 고쳐 보고서에 적습니다: RniAPI.yaml의 `$ref` 옆 `type`(80곳, 3.0→3.1 변환 잔재), MEC 021 AssociateId 자리 표시자, MEC 011 `confirm_ready`의 성공 응답 누락, `changeType`의 `SEE_DESCRIPTION` 자리 표시자. 정의 파일의 기본 경로(`location/v2`, `mec_app_support/v1`)는 ETSI MEC Sandbox가 쓰는 경로(`location/v3`, `mec_app_support/v2`)보다 오래된 것이며, EdgeGuard는 Sandbox 경로를 씁니다.

## 3. 커뮤니티 oneM2M MCP 서버

[onem2m-mcp](https://pypi.org/project/onem2m-mcp/)(Rostan Technologies, BSD-3-Clause)는 어떤 CSE에도 붙는 범용 MCP 게이트웨이로 도구 17개를 제공합니다. [`tools/onem2m_mcp_check.py`](../../tools/onem2m_mcp_check.py)는 EdgeGuard 트윈이 있는 CSE에 이를 띄우고, 일반 MCP 클라이언트로서:

1. 라벨로 kinematics 트윈을 탐색: **아무것도 안 보임**. 단말마다 ACP가 그 단말, MEC 앱, MEC-IPE만 허용하기 때문입니다.
2. 현장 운영자가 단말 하나의 ACP에 에이전트 originator의 RETRIEVE · DISCOVERY를 추가합니다.
3. 에이전트가 라벨로 트윈을 찾아 읽고(`egs:kinSt`), 권한은 다시 회수합니다.

즉 MCP를 쓰는 어떤 에이전트든 표준 게이트웨이로 EdgeGuard 데이터를 쓸 수 있고, 운영자가 허용한 만큼만 볼 수 있습니다.

재현: `python tools/cse_probe.py --cse <url> --rn <cse>`, `python tools/mec_conformance.py`, `/tmp/mcpv/bin/python tools/onem2m_mcp_check.py`(각 파일 머리말 참고).
