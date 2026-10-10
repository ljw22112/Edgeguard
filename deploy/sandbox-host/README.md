# Self-hosted MEC Sandbox host (Hyper-V VM)

[한국어](README.ko.md)

Installation procedure for running the EdgeGuard warehouse scenario (`scenarios/edgeguard-warehouse.yaml`) on a real MEC platform.
The public Sandbox (try-mec.etsi.org) only offers pre-built scenarios, so we install
**AdvantEDGE v1.9.2**, the open-source base of the ETSI MEC Sandbox, directly on a VM (same MEC 011/012/013 APIs). Organiser VM spec: 4 cores · 9 GB · 80 GB, Ubuntu.

```
Windows PC (32GB)
 ├─ Hyper-V VM "mec-sandbox" 192.168.200.10   Ubuntu 22.04 · Kubernetes · AdvantEDGE (warehouse scenario)
 └─ Docker Desktop: EdgeGuard stack (Mobius · MEC app · MEC-IPE)
        └─ http://host.docker.internal:8088  ──(port proxy)──>  192.168.200.10:80
```

Time required: 2–3 hours the first time (mostly waiting for automated builds).

## 1. Prepare Windows (administrator PowerShell)

```
winget install -e --id Git.Git
winget install -e --id Docker.DockerDesktop
git clone https://github.com/ljw22112/Edgeguard.git $HOME\Edgeguard
```
Download the Ubuntu 22.04 server ISO: https://releases.ubuntu.com/22.04/ → `ubuntu-22.04.x-live-server-amd64.iso`

## 2. Create the VM (administrator PowerShell)

```
cd $HOME\Edgeguard\deploy\sandbox-host
Set-ExecutionPolicy -Scope Process Bypass
.\create-vm.ps1 -Iso $HOME\Downloads\ubuntu-22.04.5-live-server-amd64.iso
```
If Hyper-V was disabled, the script only enables it and exits, so **reboot and run the same command once more**. The VM window opens.

## 3. Install Ubuntu (VM window)

Keep the defaults except for the following.

- **Network**: `eth0` → Edit IPv4 → **Manual**
  - Subnet `192.168.200.0/24` · Address `192.168.200.10` · Gateway `192.168.200.1` · Name servers `8.8.8.8,1.1.1.1`
- **SSH**: check "Install OpenSSH server"
- Disk: "Use an entire disk" (unchecking LVM is recommended — the default LVM uses only half the disk)

When installation finishes, choose "Reboot Now". (Press Enter if prompted to remove the ISO.)

## 4. Install the platform (connect to the VM from Windows PowerShell)

```
cd $HOME\Edgeguard\deploy\sandbox-host
scp install-runtime.sh install-advantedge.sh fix-images.sh <user>@192.168.200.10:
ssh <user>@192.168.200.10
```
Inside the VM:
```
bash install-runtime.sh          # Docker · Kubernetes · Helm (10–15 min), shows a Ready node at the end
exit                             # log in again (applies docker group)
```
```
ssh <user>@192.168.200.10
bash install-advantedge.sh       # build and deploy AdvantEDGE (30–60 min)
```
Success when all `meep-...` pods are `Running` at the end.

## 5. Run the warehouse scenario (Windows browser → http://192.168.200.10)

1. **Configure** → **Import** → `Edgeguard\scenarios\edgeguard-warehouse.yaml` → **Save**
2. **Execute** → **New** to create a sandbox (e.g. `edgeguard`) → **Deploy** → `edgeguard-warehouse`
3. Under **Automation** on the Execute screen, turn on **Movement** (UEs follow their paths).

## 6. Connect EdgeGuard (Windows PowerShell, with Docker Desktop running)

```
cd $HOME\Edgeguard\deploy
docker compose up -d --build
docker compose run --rm sandbox-setup http://host.docker.internal:8088/edgeguard --vehicle-mps 1.7
docker compose --profile sandbox up -d --force-recreate
docker compose run --rm sandbox-check
```
- If `sandbox-setup` cannot find the API, retry with the MEP path appended: `http://host.docker.internal:8088/edgeguard/mec-edge`
- Check alerts on the dashboard at http://localhost:9090 and results in `deploy\sandbox\report.json`.
- Forklifts move at 2–2.5 m/s and workers at ~1.2 m/s, so `--vehicle-mps 1.7` separates them.

## Shutting down and restarting

- To shut down: `sudo poweroff` inside the VM (or shut down from Hyper-V Manager). The next time the VM starts, Kubernetes and the platform come back up automatically (2–3 min).
- If something goes wrong: send the output of `kubectl get pods -A | grep -v Running` from the VM.
