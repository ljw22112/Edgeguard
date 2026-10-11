#!/usr/bin/env bash
# Demo PKI and credentials for the secured transport (docs/transport-security.md), generated locally and
# never committed (.certs/ is git-ignored):
#   .certs/ca.crt, ca.key              site CA
#   .certs/server.crt, server.key      CSE (HTTPS :8443) and MQTT broker (:8883), SAN localhost/127.0.0.1
#   .certs/mqtt.env                    random broker passwords: CSE and one per device
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
D="$ROOT/.certs"; mkdir -p "$D"; cd "$D"
[ -f server.crt ] && [ -f mqtt.env ] && exit 0
openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=EdgeGuard demo site CA" \
  -keyout ca.key -out ca.crt 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=localhost" -keyout server.key -out server.csr 2>/dev/null
printf "subjectAltName=DNS:localhost,IP:127.0.0.1\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n" > ext.cnf
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 30 -extfile ext.cnf \
  -out server.crt 2>/dev/null
rm -f server.csr ext.cnf
pw() { openssl rand -hex 12; }
{ echo "MQTT_CSE_PW=$(pw)"; echo "MQTT_DEV_PW=$(pw)"; } > mqtt.env
chmod 600 ca.key server.key mqtt.env
echo "demo PKI in $D"
