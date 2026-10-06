#!/usr/bin/env bash
# Local end-to-end demo: ACME oneM2M CSE + EdgeGuard MEC app + virtual devices.
#   scripts/run_local_demo.sh [scenario]     (default: crossing_conflict)
# Scenarios: crossing_conflict crossing_clear head_on adjacent_aisle
#            roadside_picker turn_into_worker turn_away worker_yields
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
ACME_DIR="${ACME_DIR:-$ROOT/../ACME-oneM2M-CSE}"
PY="${PYTHON:-python3}"

if ! curl -sf -H "X-M2M-Origin: CAdmin" -H "X-M2M-RI: 1" -H "X-M2M-RVI: 3" localhost:8080/cse-in >/dev/null; then
  if [ ! -d "$ACME_DIR" ]; then
    git clone --depth 1 https://github.com/ankraft/ACME-oneM2M-CSE.git "$ACME_DIR"
    $PY -m pip install -r "$ACME_DIR/requirements.txt"
  fi
  mkdir -p "$ROOT/.acme" && cp scripts/acme.ini "$ROOT/.acme/"
  (cd "$ACME_DIR" && nohup $PY -m acmecse --base-directory "$ROOT/.acme" --config acme.ini \
      </dev/null > "$ROOT/.acme/acme.out" 2>&1 & echo $! > "$ROOT/.acme.pid")
  echo -n "starting ACME CSE"
  for _ in $(seq 1 60); do
    curl -sf -H "X-M2M-Origin: CAdmin" -H "X-M2M-RI: 1" -H "X-M2M-RVI: 3" localhost:8080/cse-in >/dev/null && break
    echo -n "."; sleep 0.5
  done; echo
fi

scripts/mec.sh restart
$PY devices/device_sim.py --scenario "${1:-crossing_conflict}" --start-delay 4 &
SIM=$!
sleep 1.5
$PY tools/setup_resources.py --reset
wait $SIM
curl -s localhost:9090/health; echo
