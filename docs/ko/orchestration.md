# oneM2M을 통한 MEC 앱 오케스트레이션

[← README](../../README.ko.md) · [English](../orchestration.md) · [TR-0077 매핑](estimed-mapping.md)

ESTIMED PoC의 오케스트레이션 흐름은 탐색 → 선택 → 배포 → 등록 → 프로비저닝입니다. oneM2M은 의도, 식별, 자원, 상태를 담당하고, MEC 플랫폼은 실행 수명주기를 담당합니다. [`edgeguard/orchestration.py`](../../edgeguard/orchestration.py)가 EdgeGuard용으로 이 흐름을 구현합니다. 모든 상태가 oneM2M에 있으므로 AI 에이전트를 포함한 어떤 oneM2M 앱이든 EdgeGuard가 어디서 왜 실행되는지 볼 수 있습니다. 운영자는 **자원 하나**를 만들어 배포합니다.

```
<host>/host            egs:mecHs   스스로 등록한 MEC 호스트: 구역, 여유 CPU/메모리, 사이트까지 RTT,
                                   수명주기 API; 매초 갱신 (하트비트 = lastModifiedTime)
EGOrch/intent_<name>   egs:depIn   의도: 앱, 구역, CPU, 메모리, 최대 지연
                                   -> 오케스트레이터가 상태, 배치, 앱 AE를 기록
app-<instance>         AE          배포된 인스턴스가 스스로 등록 (lbl egs:app/<name>)
  config               CNT         프로비저닝: 구독할 디바이스 데이터
  status               CNT         하트비트 + 처리 카운터
```

| 단계 | 일어나는 일 |
|---|---|
| 탐색 | 레이블 `egs:mec/host`로 탐색하고, 각 `egs:mecHs`를 읽어 `lt`로 나이를 계산 |
| 선택 | 제약: 호스트 가동, 하트비트 2.5 s 이내, CPU/메모리 여유, RTT ≤ 최대 지연, 구역(또는 구역 없는 지역 호스트). 순위: 같은 구역, 낮은 RTT, 많은 여유 CPU 순 |
| 배포 | `POST <lcmUr>/app_instances`(단순화한 MEC 010-2: 생성, 조회, 종료). 용량이 없는 호스트는 409로 답하고 다음 후보로 넘어감 |
| 등록 | 인스턴스가 자기 AE와 `config`, `status`를 만들고 자기 `config`를 구독 |
| 프로비저닝 | 디바이스 ACP의 소유자인 오케스트레이터가 인스턴스 발신자에게 권한(조회, 알림, 구독 생성만)을 추가하고 설정을 기록. 인스턴스가 디바이스 데이터를 구독 |
| 실행 | 첫 `status` 하트비트가 오면 의도에 `running`, `plcmt`, `appAe`가 기록됨 |
| 감시 | 호스트 하트비트가 2.5 s 넘게 오래되면 호스트 상실로 판단. 의도를 `migrating`으로 바꾸고 그 호스트를 빼고 다시 배치하며, 이전 인스턴스의 ACP 권한은 회수 |

## 데모 (매 커밋 CI)

```bash
scripts/acme.sh start in
python tools/orchestration_demo.py      # 11개 검사 -> results/orchestration.json
```

**호스트:**

| 호스트 | 구역 | CPU | 사이트까지 RTT |
|---|---|---|---|
| host-a1 | A | 4 | 2 ms |
| host-a2 | A | 2 | 4 ms |
| host-cloud | 지역 | 16 | 25 ms |

**의도와 배치 결과:**

| 의도 | 요구 사항 | 배치 |
|---|---|---|
| edgeguard-risk | 구역 A, 2 CPU, ≤ 10 ms | **host-a1** |
| site-analytics | 8 CPU, ≤ 100 ms | **host-cloud** |
| edgeguard-risk-xl | 64 CPU | **배치 불가**(아무것도 배포하지 않음) |
| host-a1 장애(하트비트·API 중단) | | 위험 엔진을 **host-a2에 재배치** |

**CI 측정:**
- 의도 → 실행까지 ≈ 0.75 s
- 장애 감지 ≈ 2.0–2.4 s
- host-a2에서 재실행까지 ≈ 2.3–2.7 s
- 새 인스턴스가 지게차의 실시간 데이터를 처리
- 이전 인스턴스는 더 이상 읽지 못함(403)

**한계.** 호스트와 수명주기 API는 시뮬레이션입니다. 인스턴스는 실제 oneM2M 앱(AE, 구독, ACP, 하트비트)이지만, 저장소에서 받은 컨테이너 이미지가 아니라 스레드로 실행됩니다.
