#!/usr/bin/env bash
# Start / stop local ACME CSEs with the EdgeGuard SDT domain installed.
#
#   scripts/acme.sh start [in|mn-a|mn-b ...]     (default: in)
#   scripts/acme.sh stop  [in|mn-a|mn-b ...]
#
#   in    IN-CSE  cse-in      :8080   (scripts/acme.ini)
#   mn-a  MN-CSE  zone A      :8081   (scripts/acme-mn-a.ini, registers with the IN-CSE)
#   mn-b  MN-CSE  zone B      :8082   (scripts/acme-mn-b.ini)
#   sec   IN-CSE  cse-sec     :8443   HTTPS + MQTT over TLS (scripts/acme-sec.ini; needs scripts/mqtt.sh start)
#   ACME_MQTT=1 scripts/acme.sh start in    adds the MQTT binding (TLS, site broker) to a CSE
#
# Every start copies config/onem2m/edgeguard.fcp (flexContainer specializations, docs/data-model.md)
# next to ACME's own .fcp files, so the CSE knows the egs:* device and module classes.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACME_DIR="${ACME_DIR:-$ROOT/../ACME-oneM2M-CSE}"
ACME_PY="${ACME_PYTHON:-python3}"
cmd="${1:-start}"; shift || true
names="${*:-in}"

port_of() { case "$1" in in) echo 8080;; mn-a) echo 8081;; mn-b) echo 8082;; sec) echo 8443;; *) echo "unknown CSE $1" >&2; exit 2;; esac; }
ini_of() { case "$1" in in) echo acme.ini;; *) echo "acme-$1.ini";; esac; }
rn_of() { case "$1" in in) echo cse-in;; mn-a) echo cse-mn-a;; mn-b) echo cse-mn-b;; sec) echo cse-sec;; esac; }
up() {
  if [ "$1" = sec ]; then u="https://localhost:8443"; tls=(--cacert "$ROOT/.certs/ca.crt"); else u="http://localhost:$(port_of "$1")"; tls=(); fi
  curl -sf "${tls[@]}" -H "X-M2M-Origin: CAdmin" -H "X-M2M-RI: 1" -H "X-M2M-RVI: 3" "$u/$(rn_of "$1")" >/dev/null; }

case "$cmd" in
  start)
    if [ ! -d "$ACME_DIR" ]; then
      git clone --depth 1 https://github.com/ankraft/ACME-oneM2M-CSE.git "$ACME_DIR"
      $ACME_PY -m pip install -r "$ACME_DIR/requirements.txt"
    fi
    cp "$ROOT/config/onem2m/edgeguard.fcp" "$ACME_DIR/acmecse/init/"
    for n in $names; do
      if up "$n"; then echo "ACME $n already up on :$(port_of "$n")"; continue; fi
      d="$ROOT/.acme/$n"; mkdir -p "$d"; cp "$ROOT/scripts/$(ini_of "$n")" "$d/acme.ini"
      if [ "$n" != sec ] && [ "${ACME_MQTT:-0}" = 1 ]; then   # + oneM2M MQTT binding over TLS (scripts/mqtt.sh)
        bash "$ROOT/scripts/certs.sh" >/dev/null
        printf "\n[mqtt]\nenable=true\naddress=127.0.0.1\nport=8883\n\n[mqtt.security]\nuseTLS=true\nverifyCertificate=true\ncaCertificateFile=%s\n" \
          "$ROOT/.certs/ca.crt" >> "$d/acme.ini"
        . "$ROOT/.certs/mqtt.env"; export ACME_MQTT_SECURITY_USERNAME=cse ACME_MQTT_SECURITY_PASSWORD="$MQTT_CSE_PW"
      fi
      if [ "$n" = sec ]; then
        bash "$ROOT/scripts/certs.sh" >/dev/null; mkdir -p "$d/certs"
        cp "$ROOT/.certs/server.crt" "$d/certs/acme_cert.pem"; cp "$ROOT/.certs/server.key" "$d/certs/acme_key.pem"
        cp "$ROOT/.certs/ca.crt" "$d/certs/ca.crt"
        . "$ROOT/.certs/mqtt.env"; export ACME_MQTT_SECURITY_USERNAME=cse ACME_MQTT_SECURITY_PASSWORD="$MQTT_CSE_PW"
      fi
      for attempt in 1 2; do       # a CSE that dies while starting (port not yet free, plugin error) gets one retry
        (cd "$ACME_DIR" && nohup $ACME_PY -m acmecse --base-directory "$d" --config acme.ini \
            </dev/null > "$d/acme.out" 2>&1 & echo $! > "$d/acme.pid")
        # probe only after ACME logs "CSE started": a request that reaches its Flask app while the plugins
        # are still registering routes aborts the startup ("add_url_rule can no longer be called")
        for _ in $(seq 1 120); do
          grep -q "CSE started" "$d/acme.out" 2>/dev/null && up "$n" && break
          kill -0 "$(cat "$d/acme.pid")" 2>/dev/null || break; sleep 0.5
        done
        up "$n" && break
        [ $attempt = 1 ] && { cp "$d/acme.out" "$d/acme.out.1"; kill "$(cat "$d/acme.pid")" 2>/dev/null; sleep 2; echo "ACME $n: retrying"; }
      done
      up "$n" && echo "ACME $n up on :$(port_of "$n")" || { echo "ACME $n did not start, see $d/acme.out"; exit 1; }
    done ;;
  stop)
    for n in $names; do
      f="$ROOT/.acme/$n/acme.pid"; [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null || true; rm -f "$f"
      # python3 may be a wrapper that forks the interpreter: also stop the process serving this base directory
      for p in $(ps -eo pid,args | grep "[a]cmecse --base-directory $ROOT/.acme/$n " | awk '{print $1}'); do kill "$p" 2>/dev/null || true; done
      for _ in $(seq 1 40); do up "$n" || break; sleep 0.25; done
    done ;;
  *) echo "usage: $0 start|stop [in|mn-a|mn-b|sec ...]"; exit 2 ;;
esac
