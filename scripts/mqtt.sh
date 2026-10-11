#!/usr/bin/env bash
# Mosquitto broker for the oneM2M MQTT binding (TS-0010): TLS only (:8883), passwords, per-originator ACL.
#   scripts/mqtt.sh start|stop
# Users: "cse" (the CSE, all oneM2M topics) and the device originators listed in MQTT_DEVICES; a device
# may only send requests as itself and only read responses / notifications addressed to itself.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
D="$ROOT/.mqtt"; C="$ROOT/.certs"
DEVICES="${MQTT_DEVICES:-Cforklift01 Cworker01 SEdgeGuardSec}"
case "${1:-start}" in
  start)
    bash "$ROOT/scripts/certs.sh" >/dev/null
    . "$C/mqtt.env"
    mkdir -p "$D"; rm -f "$D/passwd"; touch "$D/passwd"; chmod 600 "$D/passwd"
    mosquitto_passwd -b "$D/passwd" cse "$MQTT_CSE_PW"
    for u in $DEVICES; do mosquitto_passwd -b "$D/passwd" "$u" "$MQTT_DEV_PW"; done
    cat > "$D/acl" <<ACL
user cse
topic readwrite /oneM2M/#

pattern write /oneM2M/req/%u/#
pattern write /oneM2M/reg_req/%u/#
pattern read /oneM2M/resp/%u/#
pattern read /oneM2M/reg_resp/%u/#
pattern read /oneM2M/req/+/%u/#
pattern write /oneM2M/resp/+/%u/#
ACL
    chmod 600 "$D/acl"
    cat > "$D/mosquitto.conf" <<CONF
pid_file $D/mosquitto.pid
user $(id -un)
persistence false
log_dest file $D/mosquitto.log
per_listener_settings false
allow_anonymous false
password_file $D/passwd
acl_file $D/acl
listener 8883 127.0.0.1
cafile $C/ca.crt
certfile $C/server.crt
keyfile $C/server.key
tls_version tlsv1.2
CONF
    "$0" stop >/dev/null 2>&1 || true
    mosquitto -c "$D/mosquitto.conf" -d
    for _ in $(seq 1 40); do (exec 3<>/dev/tcp/127.0.0.1/8883) 2>/dev/null && { echo "MQTT broker up on :8883 (TLS)"; exit 0; }; sleep 0.25; done
    echo "broker did not start, see $D/mosquitto.log"; exit 1 ;;
  stop)
    [ -f "$D/mosquitto.pid" ] && kill "$(cat "$D/mosquitto.pid")" 2>/dev/null || true
    rm -f "$D/mosquitto.pid"
    for _ in $(seq 1 40); do (exec 3<>/dev/tcp/127.0.0.1/8883) 2>/dev/null || break; sleep 0.25; done ;;
esac
