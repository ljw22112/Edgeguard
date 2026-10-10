#!/usr/bin/env bash
# Local end-to-end demo: ACME oneM2M CSE + EdgeGuard MEC app + virtual devices.
#   scripts/run_local_demo.sh [scenario]     (default: crossing_conflict)
# Scenarios: crossing_conflict crossing_clear head_on adjacent_aisle
#            roadside_picker turn_into_worker turn_away worker_yields
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"

scripts/acme.sh start in          # ACME CSE with the EdgeGuard SDT domain (clones and installs it the first time)

scripts/mec.sh restart
$PY devices/device_sim.py --scenario "${1:-crossing_conflict}" --start-delay 4 &
SIM=$!
sleep 1.5
$PY tools/setup_resources.py --reset
wait $SIM
curl -s localhost:9090/health; echo
