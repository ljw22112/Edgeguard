#!/usr/bin/env bash
# Reacting live demo on a local ACME CSE: MEC app + devices that obey WAIT / STEP ASIDE / GO.
#   scripts/run_live_demo.sh            # loop the scenes; dashboard http://localhost:9090/
#   scripts/run_live_demo.sh record     # record results/edgeguard_demo_v1.3.mp4 instead
#   HW=1 scripts/run_live_demo.sh       # with real ESP32 boards (docs/hardware-demo.md)
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
# HW=1: real boards take over the actuators of worker_01 / forklift_01 (config/hw-demo.yaml, docs/hardware-demo.md)
export EDGEGUARD_CONFIG=config/site.yaml EDGEGUARD_OVERRIDES=config/local-acme.yaml,config/live-demo.yaml${HW:+,config/hw-demo.yaml}
curl -sf -H "X-M2M-Origin: CAdmin" -H "X-M2M-RI: 1" -H "X-M2M-RVI: 3" localhost:8080/cse-in >/dev/null \
  || { echo "start ACME first (scripts/run_local_demo.sh starts it)"; exit 1; }
scripts/mec.sh restart
# the devices' alert listener must be up before the subscriptions are created (ACME verifies them)
$PY -c "import http.server,socketserver,threading,time
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(s): s.send_response(200); s.send_header('X-M2M-RSC','2000'); s.end_headers()
    def log_message(s,*a): pass
socketserver.TCPServer.allow_reuse_address=True; srv=socketserver.TCPServer(('0.0.0.0',9091),H); threading.Thread(target=srv.serve_forever,daemon=True).start()
import subprocess,sys; subprocess.run([sys.executable,'tools/setup_resources.py','--reset'],check=True,stdout=subprocess.DEVNULL)
srv.shutdown(); srv.server_close()"
if [ "$1" = "record" ]; then
  $PY tools/record_live_demo.py
else
  $PY devices/live_devices.py --scene all --loop
fi
