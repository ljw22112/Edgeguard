# Contributing to EdgeGuard

[한국어 요약은 아래에](#한국어)

Thanks for looking. EdgeGuard is a hackathon project, but the code is meant to be run and reused.

## Set up

```bash
git clone https://github.com/ljw22112/Edgeguard && cd Edgeguard
pip install -r requirements.txt pytest httpx
scripts/acme.sh start in mn-a mn-b       # ACME IN-CSE + two zone MN-CSEs (pinned commit, see the script)
python -m pytest -q                      # unit tests, no CSE needed
python tools/mobility_demo.py            # one end-to-end demo; each prints PASS / FAIL per check
```

The full list of end-to-end demos is the CI workflow, [`.github/workflows/ci.yml`](.github/workflows/ci.yml). Run the ones your change touches.

## Making a change

- Open an issue first for anything larger than a fix, so we can agree on the oneM2M resource design.
- Keep the oneM2M resource tree documented: a new container, flexContainer class or ACP belongs in [`docs/data-model.md`](docs/data-model.md) or the feature's doc, and new SDT classes in [`config/onem2m/edgeguard.fcp`](config/onem2m/edgeguard.fcp).
- A new feature comes with a demo that checks it against a real CSE and a CI step that runs it.
- Docs are in English and Korean (`docs/` and `docs/ko/`). Update both, or say in the PR that the other language is pending.
- Never commit certificates, keys, broker passwords or API keys. `.certs/` is ignored; `scripts/certs.sh` creates demo material locally.

## Commit and PR

- One topic per commit, imperative subject line (`MEC-IPE: area subscriptions`).
- The PR template asks which demos you ran. CI must be green.

## 한국어

- 설치 · 실행은 위 명령 그대로입니다. 데모마다 검사별 PASS / FAIL을 출력합니다.
- 큰 변경은 이슈로 먼저 리소스 설계를 맞춥니다.
- 새 리소스 · SDT 클래스 · ACP는 문서와 `edgeguard.fcp`에 반영합니다.
- 새 기능에는 실제 CSE로 검사하는 데모와 CI 단계를 붙입니다.
- 문서는 영어 · 한국어 둘 다 갱신합니다.
- 인증서 · 키 · 비밀번호 · API 키는 커밋하지 않습니다.
