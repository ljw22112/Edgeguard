#!/usr/bin/env bash
# EdgeGuard - repair an AdvantEDGE v1.9.2 install whose images can no longer be fetched (2026):
#   - Debian 11 (bullseye) left the regular mirrors, so `apt-get update` fails (exit 100) in the
#     meep-auth-svc / meep-virt-engine / meep-tc-sidecar images  -> build them on debian:12-slim
#   - Bitnami moved its old Docker Hub images to docker.io/bitnamilegacy  -> redis, postgis exporters
#   - quay.io/coreos/kube-state-metrics is gone  -> registry.k8s.io
# Safe to re-run. install-advantedge.sh applies the same patches before building.
set -euo pipefail
AE_DIR="${AE_DIR:-$HOME/AdvantEDGE}"
export GOPATH="$HOME/gocode" PATH="$PATH:$HOME/gocode/bin:/usr/local/go/bin"
log() { printf '\n\033[1;32m== %s\033[0m\n' "$*"; }
cd "$AE_DIR"

log "patch Dockerfiles and charts"
for app in meep-auth-svc meep-virt-engine meep-tc-sidecar; do
  sed -i 's#^FROM debian:11[^ ]*#FROM debian:12-slim#' "go-apps/$app/Dockerfile"
done
sed -i 's#repository: bitnami/#repository: bitnamilegacy/#' charts/redis/values*.yaml charts/postgis/values*.yaml
# bitnamilegacy kept the plain version tags (6.0.9, 1.15.0, 0.8.0) but not the old -debian-10-rNN ones;
# minideb is still published under bitnami/ (buster gone -> bookworm)
sed -i -E 's#tag: ([0-9.]+)-debian-10-r[0-9]+#tag: \1#' charts/redis/values*.yaml charts/postgis/values*.yaml
sed -i 's#repository: bitnamilegacy/minideb#repository: bitnami/minideb#; s#tag: buster#tag: bookworm#' charts/redis/values*.yaml charts/postgis/values*.yaml
sed -i 's#repository: quay.io/coreos/kube-state-metrics#repository: registry.k8s.io/kube-state-metrics/kube-state-metrics#; s#tag: v1.9.7#tag: v1.9.8#' \
  charts/kube-state-metrics/values.yaml
grep -h "^FROM" go-apps/meep-auth-svc/Dockerfile go-apps/meep-virt-engine/Dockerfile go-apps/meep-tc-sidecar/Dockerfile

if [ "${1:-}" = "--patch-only" ]; then exit 0; fi

log "rebuild the three images"
meepctl dockerize meep-auth-svc meep-virt-engine meep-tc-sidecar

log "redeploy redis, postgis, kube-state-metrics with the new image locations"
for rel in meep-redis meep-postgis meep-kube-state-metrics; do
  helm uninstall "$rel" 2>/dev/null || true
done
sleep 10
meepctl deploy dep

log "restart core services"
kubectl get pods --no-headers | awk '{print $1}' | grep -E '^meep-(auth-svc|virt-engine|platform-ctrl|mon-engine|webhook)-' \
  | xargs -r kubectl delete pod
echo "waiting up to 5 min for all pods ..."
for _ in $(seq 60); do
  [ "$(kubectl get pods --no-headers | grep meep- | grep -vc Running)" = "0" ] && break; sleep 5
done
kubectl get pods | grep meep-
