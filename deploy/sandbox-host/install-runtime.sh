#!/usr/bin/env bash
# EdgeGuard - MEC Sandbox host, step 1 of 2: runtime (Docker/containerd, Kubernetes 1.27, Helm 3.7).
# Ubuntu 22.04 server, run as the normal user (sudo is used):  bash install-runtime.sh
# Follows the AdvantEDGE runtime setup (interdigitalinc.github.io/AdvantEDGE/docs/setup/env-runtime),
# the platform the ETSI MEC Sandbox is built on. Safe to re-run.
set -euo pipefail
NODE_IP="${NODE_IP:-192.168.200.10}"
ME="$(id -un)"
log() { printf '\n\033[1;32m== %s\033[0m\n' "$*"; }

[ "$(lsb_release -cs)" = "jammy" ] || { echo "Ubuntu 22.04 (jammy) expected"; exit 1; }
ip -4 addr | grep -q "inet $NODE_IP/" || { echo "this VM must have the static IP $NODE_IP (see README)"; exit 1; }

log "base packages, swap off, kernel modules"
sudo apt-get update -q
sudo apt-get install -y -q ca-certificates curl gnupg lsb-release apt-transport-https acl build-essential libssl-dev git
sudo swapoff -a
sudo sed -i '/ swap / s/^\(.*\)$/#\1/' /etc/fstab
sudo rm -f /swap.img || true
printf 'overlay\nbr_netfilter\n' | sudo tee /etc/modules-load.d/k8s.conf >/dev/null
sudo modprobe overlay; sudo modprobe br_netfilter
printf 'net.bridge.bridge-nf-call-iptables = 1\nnet.bridge.bridge-nf-call-ip6tables = 1\nnet.ipv4.ip_forward = 1\nfs.inotify.max_user_watches = 524288\n' \
  | sudo tee /etc/sysctl.d/k8s.conf >/dev/null
sudo sysctl --system >/dev/null

log "Docker 20.10 + containerd 1.6 (versions AdvantEDGE is tested with)"
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu jammy stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update -q
if ! dpkg -s docker-ce 2>/dev/null | grep -q '^Version: 5:20.10'; then
  sudo apt-get install -y -q --allow-downgrades docker-ce=5:20.10.22~3-0~ubuntu-jammy docker-ce-cli=5:20.10.22~3-0~ubuntu-jammy \
    containerd.io=1.6.14-1 docker-compose-plugin=2.14.1~ubuntu-jammy
fi
sudo apt-mark hold docker-ce docker-ce-cli containerd.io docker-compose-plugin >/dev/null
sudo usermod -aG docker "$ME"
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml >/dev/null
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sudo sed -i 's#sandbox_image = ".*"#sandbox_image = "registry.k8s.io/pause:3.9"#' /etc/containerd/config.toml
sudo systemctl restart containerd
sudo setfacl --modify "user:$ME:rw" /run/containerd/containerd.sock

log "Kubernetes 1.27 (kubeadm, single node)"
# v1.27 is end-of-life and its repository signing key has expired (EXPKEYSIG), so apt rejects it.
# The packages still come over HTTPS from the official pkgs.k8s.io CDN; trust that repository explicitly.
echo "deb [trusted=yes] https://pkgs.k8s.io/core:/stable:/v1.27/deb/ /" \
  | sudo tee /etc/apt/sources.list.d/kubernetes.list >/dev/null
sudo apt-get update -q
sudo apt-get install -y -q kubelet kubeadm kubectl kubernetes-cni
sudo apt-mark hold kubelet kubeadm kubectl >/dev/null
if [ ! -f /etc/kubernetes/admin.conf ]; then
  sudo kubeadm init --cri-socket unix:///run/containerd/containerd.sock --apiserver-advertise-address "$NODE_IP"
fi
mkdir -p "$HOME/.kube"
sudo cp /etc/kubernetes/admin.conf "$HOME/.kube/config"
sudo chown "$(id -u):$(id -g)" "$HOME/.kube/config"
kubectl taint nodes --all node-role.kubernetes.io/control-plane- 2>/dev/null || true
kubectl apply -f https://raw.githubusercontent.com/InterDigitalInc/AdvantEDGE/gh-pages/setup/weave-daemonset-k8s.yaml
grep -q "kubectl completion" "$HOME/.bashrc" || echo 'source <(kubectl completion bash)' >> "$HOME/.bashrc"

log "cluster registry name + Kubernetes CA"
grep -q "meep-docker-registry" /etc/hosts || echo "$NODE_IP   meep-docker-registry" | sudo tee -a /etc/hosts >/dev/null
sudo cp /etc/kubernetes/pki/ca.crt /usr/local/share/ca-certificates/kubernetes-ca.crt
sudo chmod 644 /usr/local/share/ca-certificates/kubernetes-ca.crt
sudo update-ca-certificates >/dev/null
sudo systemctl restart docker containerd
sudo setfacl --modify "user:$ME:rw" /run/containerd/containerd.sock

log "Helm 3.7"
sudo snap install helm --channel=3.7/stable --classic 2>/dev/null || sudo snap refresh helm --channel=3.7/stable --classic

log "waiting for the node to become Ready"
for _ in $(seq 60); do
  kubectl get nodes --no-headers 2>/dev/null | grep -q " Ready" && break; sleep 5
done
kubectl get nodes
echo
echo "Step 1 done. Log out and back in (docker group), then run:  bash install-advantedge.sh"
