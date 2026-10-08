#!/usr/bin/env bash
# EdgeGuard - MEC Sandbox host, step 2 of 2: build and deploy the MEC platform (AdvantEDGE v1.9.2,
# the open-source base of the ETSI MEC Sandbox; MEC 011/012/013/021/030 APIs).
# Run after install-runtime.sh and a re-login:  bash install-advantedge.sh      (~30-60 min)
set -euo pipefail
NODE_IP="${NODE_IP:-192.168.200.10}"
AE_TAG="${AE_TAG:-v1.9.2}"
AE_DIR="$HOME/AdvantEDGE"
GO_VER=1.18.10
log() { printf '\n\033[1;32m== %s\033[0m\n' "$*"; }

id -nG | grep -qw docker || { echo "log out and back in first (docker group)"; exit 1; }
kubectl get nodes --no-headers | grep -q " Ready" || { echo "Kubernetes node not Ready - run install-runtime.sh"; exit 1; }

log "Go $GO_VER"
if ! /usr/local/go/bin/go version 2>/dev/null | grep -q "go$GO_VER "; then
  curl -fsSL "https://go.dev/dl/go$GO_VER.linux-amd64.tar.gz" -o /tmp/go.tgz
  sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf /tmp/go.tgz && rm /tmp/go.tgz
fi
mkdir -p "$HOME/gocode/bin"
if ! grep -q "GOPATH=\$HOME/gocode" "$HOME/.bashrc"; then
  printf '\nexport GOPATH=$HOME/gocode\nexport PATH=$PATH:$GOPATH/bin:/usr/local/go/bin\n' >> "$HOME/.bashrc"
fi
export GOPATH="$HOME/gocode" PATH="$PATH:$HOME/gocode/bin:/usr/local/go/bin"

log "Node.js 12.19 + npm 6.14.8 (newer versions break the AdvantEDGE frontend build)"
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] || curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
set +u                                                     # nvm is not nounset-safe
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"
nvm install 12.19.0 >/dev/null && nvm alias default 12.19.0 >/dev/null && nvm use 12.19.0 >/dev/null
set -u
[ "$(npm -v)" = "6.14.8" ] || npm install -g npm@6.14.8 >/dev/null

log "AdvantEDGE $AE_TAG"
[ -d "$AE_DIR/.git" ] || git clone https://github.com/InterDigitalInc/AdvantEDGE.git "$AE_DIR"
git -C "$AE_DIR" fetch --tags -q && git -C "$AE_DIR" checkout -q "$AE_TAG"

log "meepctl"
(cd "$AE_DIR/go-apps/meepctl" && ./install.sh) || true      # its lint step fails without golangci-lint; the build still happens
command -v meepctl >/dev/null || { echo "meepctl was not installed"; exit 1; }
meepctl config ip "$NODE_IP"
meepctl config gitdir "$AE_DIR"
meepctl config

log "deploy dependencies (registry, ingress, databases)"
meepctl deploy dep
for _ in $(seq 120); do
  kubectl get pods --no-headers | grep -q "meep-docker-registry.*Running" && break; sleep 5
done

log "build (Go micro-services + frontend)"
meepctl build all --nolint

log "containerize and push to the cluster registry"
meepctl dockerize all

log "deploy core"
meepctl deploy core
for _ in $(seq 120); do
  [ "$(kubectl get pods --no-headers | grep meep- | grep -vc Running)" = "0" ] && break; sleep 5
done
kubectl get pods | grep meep-
echo
echo "Done. Open http://$NODE_IP from Windows (AdvantEDGE GUI) and continue with README.md step 5."
