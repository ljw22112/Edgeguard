#!/usr/bin/env bash
# Per-device client certificates for the MQTT broker's mutual-TLS listener (:8884), signed by the site CA
# from scripts/certs.sh.  The certificate's CN is the device's oneM2M originator: the broker takes it as the
# username, so the per-originator ACL applies without any password on the device.
#
#   scripts/device_cert.sh issue  SWorker01 [days]   -> .certs/devices/SWorker01.{crt,key} (a new key each time)
#   scripts/device_cert.sh revoke SWorker01          -> revokes the current certificate, regenerates the CRL
#   scripts/device_cert.sh crl                       -> .certs/crl.pem (the broker reloads it on SIGHUP)
#
# Rotation = issue (new key and certificate on the device) + revoke the old serial.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
C="$ROOT/.certs"; D="$C/devices"
bash "$ROOT/scripts/certs.sh" >/dev/null
mkdir -p "$D" "$C/ca-db"
[ -f "$C/ca-db/index.txt" ] || { : > "$C/ca-db/index.txt"; echo 1000 > "$C/ca-db/serial"; echo 1000 > "$C/ca-db/crlnumber"; }
cat > "$C/ca.cnf" <<CNF
[ca]
default_ca = site
[site]
dir = $C/ca-db
database = \$dir/index.txt
serial = \$dir/serial
crlnumber = \$dir/crlnumber
new_certs_dir = \$dir
certificate = $C/ca.crt
private_key = $C/ca.key
default_md = sha256
default_crl_days = 30
policy = any
unique_subject = no
copy_extensions = none
[any]
commonName = supplied
[client]
basicConstraints = CA:FALSE
keyUsage = digitalSignature
extendedKeyUsage = clientAuth
CNF
crl() { openssl ca -config "$C/ca.cnf" -gencrl -out "$C/crl.pem" 2>/dev/null; }
case "$1" in
  issue)
    o="$2"; days="${3:-30}"
    [ -f "$D/$o.crt" ] && { cp "$D/$o.crt" "$D/$o.prev.crt"; cp "$D/$o.key" "$D/$o.prev.key"; }   # until revoked
    openssl req -newkey rsa:2048 -nodes -subj "/CN=$o" -keyout "$D/$o.key" -out "$D/$o.csr" 2>/dev/null
    openssl ca -batch -config "$C/ca.cnf" -extensions client -days "$days" -in "$D/$o.csr" -out "$D/$o.crt" -notext 2>/dev/null
    rm -f "$D/$o.csr"; chmod 600 "$D/$o.key"; crl
    echo "$D/$o.crt (serial $(openssl x509 -in "$D/$o.crt" -noout -serial | cut -d= -f2))" ;;
  revoke)
    o="$2"; f="${3:-$D/$o.crt}"
    openssl ca -config "$C/ca.cnf" -revoke "$f" 2>/dev/null; crl
    echo "revoked $(openssl x509 -in "$f" -noout -serial | cut -d= -f2) ($o)" ;;
  crl) crl; echo "$C/crl.pem" ;;
  *) echo "usage: $0 issue|revoke <originator> | crl"; exit 2 ;;
esac
