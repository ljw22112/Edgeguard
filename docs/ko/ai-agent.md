# MCP 기반 AI 안전 에이전트

[← README](../../README.ko.md) · [English](../ai-agent.md)

안전 관리자에게 필요한 것은 원시 리소스가 아니라 교대 보고서입니다. EdgeGuard 에이전트([`agent/`](../../agent/))는 **Model Context Protocol (MCP)** 서버를 통해 동작하므로, 같은 도구를 우리 워크플로와 모든 MCP 클라이언트(Claude Desktop, Claude Code, …)가 함께 씁니다.

## MCP 서버

| 서버 | 도구 |
|---|---|
| `agent/onem2m_mcp.py`, CSE마다 1개 (IN-CSE, 구역 A, 구역 B) | `cse_info`, `discover` (라벨 / 타입), `retrieve`, `latest`, `history`, `find_devices` (SAREF 시맨틱 쿼리), `semantic_query`, `serving_cse` (홈 기록), `write_content` (안전장치 적용) |
| `agent/mec_mcp.py` | `ue_location`, `all_ue_locations` (MEC 013 Location), `cell_load` (MEC 012 RNIS) |

oneM2M 서버는 자체 originator(`SEdgeGuardAgent`)로 동작하므로 CSE의 ACP가 그대로 적용됩니다. `write_content`는 여기에 더해 에이전트 자신의 AE 밖으로의 쓰기를 모두 거부합니다.

## 교대 보고서 워크플로

`python -m agent.safety_agent report`

| 단계 | 도구 호출 |
|---|---|
| 1 상태 | `in.latest(EdgeGuardAgent/state)`: 커서 (마지막으로 읽은 아차사고의 생성 시각) |
| 2 목록 | 모든 oneM2M 서버에서 `find_devices` |
| 3 아차사고 | `in.history(EdgeGuard/nearmiss)`, 커서보다 새 기록만 남김 |
| 4 위험 지점 | 1 m 격자 칸, 사각 코너 · 경보 없음 · 고속 통행 · 교차로 분류 |
| 5 맥락 | `mec.all_ue_locations` (지금 각 위험 지점 근처의 사람), `mec.cell_load`; 관련 지게차마다 `in.serving_cse` → 해당 구역 서버로 **라우팅** → `retrieve(<twin>/speedLimit)` |
| 6 검증 | 위험 지점 건수가 전체 이내 · 스냅숏 불변(다시 셈) · 모든 지게차 확인 |
| 7 저장 | 보고서 → `EdgeGuardAgent/reports`, 커서 → `state`, 단계 로그 → `runs` |

**오류.** CSE나 MEC 플랫폼에 닿지 않거나 도구가 실패하면 오류를 기록하고 실행을 계속합니다. 보고서는 **partial**로 표시되고 커서는 그대로 두어, 다음 실행이 그 기록을 다시 다룹니다.

**자유 질문 (선택).** `ANTHROPIC_API_KEY`를 설정하고 `pip install anthropic` 후 `python -m agent.safety_agent ask "Why did forklift_01 slow down?"`를 실행합니다. Claude가 허브의 모든 MCP 도구를 써서 답합니다.

## 데모 (CI)

```bash
scripts/acme.sh start in mn-a mn-b
python tools/agent_demo.py          # 9개 확인; results/agent.json
```

데모는 한 교대를 미리 채웁니다.
- IN-CSE의 트윈, CSE 핸드오버 클라이언트로 구역 B에 붙은 forklift_01
- 위험 지점 3곳이 있는 아차사고 25건
- MEC 모의 서버의 사람 · 무선 부하

**실행 1:** 완료, 도구 호출 16번.
> (12, 4) m, 아차사고 9건: 사각 코너: 현장 지도에 랙 추가 / 볼록 거울 설치 - 지금 6 m 안에 3명
> (-7, 0) m, 아차사고 6건: 고속 지게차 통행: 속도 제한 구역 지정 - forklift_02 현재 속도 제한 없음

**실행 2:** 새 아차사고 5건이 들어오고 구역 B의 MN-CSE가 다운됩니다. 에이전트는 새 기록 5건만 읽고, forklift_01에 닿지 못했다고 기록한 partial 보고서를 씁니다.

**확인 항목:**
- 서버 4개에서 도구 발견
- 워크플로 검증
- forklift_01을 구역 B 서버로 라우팅
- 사각 코너가 최상위 위험 지점
- 속도 제한 없는 지게차를 지목
- MEC 맥락 포함
- 지속 상태 (새 기록 5건만)
- partial 보고서 저장
- 안전장치(guardrail)가 에이전트 AE 밖 쓰기를 거부

## MCP 클라이언트에서 서버 쓰기

```json
{"mcpServers": {
  "edgeguard-in":  {"command": "python", "args": ["-m", "agent.onem2m_mcp", "--name", "in", "--base-url", "http://127.0.0.1:8080", "--cse-rn", "cse-in"], "cwd": "/path/to/Edgeguard"},
  "edgeguard-mec": {"command": "python", "args": ["-m", "agent.mec_mcp", "--mec-url", "http://127.0.0.1:8085"], "cwd": "/path/to/Edgeguard"}}}
```
