# 자체 MEC Sandbox 호스트 (Hyper-V VM)

EdgeGuard 창고 시나리오(`scenarios/edgeguard-warehouse.yaml`)를 실제 MEC 플랫폼에서 돌리기 위한 설치 절차입니다.
공개 Sandbox(try-mec.etsi.org)는 미리 준비된 시나리오만 고를 수 있어서, ETSI MEC Sandbox의 오픈소스 기반인
**AdvantEDGE v1.9.2**를 VM에 직접 설치합니다(MEC 011/012/013 API 동일). 운영측 VM 사양: 4코어 · 9GB · 80GB, Ubuntu.

```
Windows PC (32GB)
 ├─ Hyper-V VM "mec-sandbox" 192.168.200.10   Ubuntu 22.04 · Kubernetes · AdvantEDGE (창고 시나리오)
 └─ Docker Desktop: EdgeGuard 스택 (Mobius · MEC 앱 · MEC-IPE)
        └─ http://host.docker.internal:8088  ──(포트 프록시)──>  192.168.200.10:80
```

소요: 처음 한 번 2~3시간(대부분 자동 빌드 대기).

## 1. Windows 준비 (관리자 PowerShell)

```
winget install -e --id Git.Git
winget install -e --id Docker.DockerDesktop
git clone https://github.com/ljw22112/Edgeguard.git $HOME\Edgeguard
```
Ubuntu 22.04 서버 ISO를 내려받습니다: https://releases.ubuntu.com/22.04/ → `ubuntu-22.04.x-live-server-amd64.iso`

## 2. VM 만들기 (관리자 PowerShell)

```
cd $HOME\Edgeguard\deploy\sandbox-host
Set-ExecutionPolicy -Scope Process Bypass
.\create-vm.ps1 -Iso $HOME\Downloads\ubuntu-22.04.5-live-server-amd64.iso
```
Hyper-V가 꺼져 있었다면 켜고 끝나므로, **재부팅 후 같은 명령을 한 번 더** 실행합니다. VM 창이 열립니다.

## 3. Ubuntu 설치 (VM 창)

기본값으로 진행하되 아래 두 곳만 바꿉니다.

- **Network**: `eth0` → Edit IPv4 → **Manual**
  - Subnet `192.168.200.0/24` · Address `192.168.200.10` · Gateway `192.168.200.1` · Name servers `8.8.8.8,1.1.1.1`
- **SSH**: "Install OpenSSH server" 체크
- 디스크는 "Use an entire disk"(LVM 체크 해제 권장 — 기본 LVM은 디스크의 절반만 씁니다)

설치가 끝나면 "Reboot Now". (ISO 제거 안내가 나오면 Enter)

## 4. 플랫폼 설치 (Windows PowerShell에서 VM으로 접속)

```
cd $HOME\Edgeguard\deploy\sandbox-host
scp install-runtime.sh install-advantedge.sh <사용자>@192.168.200.10:
ssh <사용자>@192.168.200.10
```
VM 안에서:
```
bash install-runtime.sh          # Docker · Kubernetes · Helm (10~15분), 마지막에 Ready 노드 표시
exit                             # 다시 로그인 (docker 그룹 적용)
```
```
ssh <사용자>@192.168.200.10
bash install-advantedge.sh       # AdvantEDGE 빌드 · 배포 (30~60분)
```
끝에 `meep-...` 파드들이 모두 `Running`이면 성공입니다.

## 5. 창고 시나리오 실행 (Windows 브라우저 → http://192.168.200.10)

1. **Configure** → **Import** → `Edgeguard\scenarios\edgeguard-warehouse.yaml` → **Save**
2. **Execute** → **New**로 샌드박스 생성(이름 예: `edgeguard`) → **Deploy** → `edgeguard-warehouse`
3. Execute 화면의 **Automation**에서 **Movement**를 켭니다(UE가 경로를 따라 움직임).

## 6. EdgeGuard 연결 (Windows PowerShell, Docker Desktop 실행 상태)

```
cd $HOME\Edgeguard\deploy
docker compose up -d --build
docker compose run --rm sandbox-setup http://host.docker.internal:8088/edgeguard --vehicle-mps 1.7
docker compose --profile sandbox up -d --force-recreate
docker compose run --rm sandbox-check
```
- `sandbox-setup`이 API를 못 찾으면 MEP 경로를 붙여 다시: `http://host.docker.internal:8088/edgeguard/mec-edge`
- 대시보드 http://localhost:9090 에서 경보를, `deploy\sandbox\report.json`에서 결과를 확인합니다.
- 지게차 2~2.5 m/s · 작업자 ~1.2 m/s라 `--vehicle-mps 1.7`로 나눕니다.

## 끄고 켜기

- 끌 때: VM 안에서 `sudo poweroff`(또는 Hyper-V 관리자에서 종료). 다음에 VM을 켜면 Kubernetes와 플랫폼이 자동으로 다시 올라옵니다(2~3분).
- 문제가 생기면: VM에서 `kubectl get pods -A | grep -v Running` 출력을 보내 주세요.
