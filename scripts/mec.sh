#!/usr/bin/env bash
# Start / stop the MEC app in the background.  Usage: scripts/mec.sh start|stop|restart
cd "$(dirname "$0")/.."
PIDFILE=.mec.pid
LOG=${MEC_LOG:-mec.log}
stop() { [ -f $PIDFILE ] && kill "$(cat $PIDFILE)" 2>/dev/null; rm -f $PIDFILE; }
start() {
  nohup python3 -m uvicorn mec_app.app:app --host 0.0.0.0 --port 9090 --log-level warning \
    > "$LOG" 2>&1 &
  echo $! > $PIDFILE
  for _ in $(seq 1 30); do curl -sf localhost:9090/health >/dev/null && { echo "MEC app up"; return; }; sleep 0.2; done
  echo "MEC app did not start; see $LOG"; return 1
}
case "$1" in
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 0.5; start ;;
  *) echo "usage: $0 start|stop|restart"; exit 2 ;;
esac
