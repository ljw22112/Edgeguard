#!/usr/bin/env bash
# Install and start KETI Mobius 3 (MySQL/MariaDB backend) on the MEC host.
#
#   MOBIUS_DB_PASS=secret scripts/setup_mobius.sh            # install + start
#   scripts/setup_mobius.sh start | stop | status
#
# What it does (each step is skipped if already done):
#   1. clone IoTKETI/Mobius into $MOBIUS_DIR and npm install
#   2. start MariaDB/MySQL, create database `mobiusdb`, set the root password
#   3. import the schema (MySQL 8 collations rewritten for MariaDB)
#   4. write conf.json (cseBase Mobius, cseId /Mobius2, port 7579) and seal the secrets
#   5. start Mobius in the background and wait for the CSEBase to answer
# Requirements: git, node (>= 18) + npm, mariadb-server (or mysql-server), python3.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MOBIUS_DIR="${MOBIUS_DIR:-$ROOT/../Mobius}"
DB_PASS="${MOBIUS_DB_PASS:-mobiuspw}"
PORT="${MOBIUS_PORT:-7579}"
LOG="${MOBIUS_LOG:-$MOBIUS_DIR/mobius.out}"
PIDFILE="$MOBIUS_DIR/.mobius.pid"

probe() { curl -s -m 2 -o /dev/null -w "%{http_code}" -H "X-M2M-Origin: SProbe" -H "X-M2M-RI: probe" \
          -H "X-M2M-RVI: 2a" "http://127.0.0.1:$PORT/Mobius" 2>/dev/null || true; }

start() {
  if [ "$(probe)" = "200" ]; then echo "Mobius already answering on :$PORT"; return; fi
  (cd "$MOBIUS_DIR"; nohup node mobius.js < /dev/null > "$LOG" 2>&1 & echo $! > "$PIDFILE")
  for _ in $(seq 1 60); do [ "$(probe)" = "200" ] && { echo "Mobius up on :$PORT"; return; }; sleep 1; done
  echo "Mobius did not start; see $LOG"; exit 1
}
stop() {
  [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"
  for _ in $(seq 1 20); do [ "$(probe)" = "200" ] || return 0; sleep 0.5; done
  echo "warning: something else still answers on :$PORT (started outside this script?)"
}

case "${1:-install}" in
  start) start; exit ;;
  stop) stop; exit ;;
  status) echo "HTTP $(probe)"; exit ;;
  install) ;;
  *) echo "usage: $0 [install|start|stop|status]"; exit 2 ;;
esac

# 1. sources
if [ ! -f "$MOBIUS_DIR/mobius.js" ]; then
  git clone --depth 1 https://github.com/IoTKETI/Mobius.git "$MOBIUS_DIR"
fi
[ -d "$MOBIUS_DIR/node_modules" ] || (cd "$MOBIUS_DIR" && npm install --no-audit --no-fund)

# 2. database server
mysql_root() { mysql -uroot -p"$DB_PASS" "$@" 2>/dev/null || mysql -uroot "$@"; }
if ! mysqladmin ping >/dev/null 2>&1 && ! mysqladmin -uroot -p"$DB_PASS" ping >/dev/null 2>&1; then
  (mysqld_safe --user=mysql > /tmp/mysqld_safe.log 2>&1 &)
  for _ in $(seq 1 30); do mysqladmin ping >/dev/null 2>&1 && break; mysqladmin -uroot -p"$DB_PASS" ping >/dev/null 2>&1 && break; sleep 1; done
fi
mysql_root -e "CREATE DATABASE IF NOT EXISTS mobiusdb;"
if mysql -uroot -e "SELECT 1" >/dev/null 2>&1; then         # no password yet: set it
  if mysql -uroot -e "SELECT VERSION()" | grep -qi mariadb; then
    mysql -uroot -e "ALTER USER 'root'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('$DB_PASS'); FLUSH PRIVILEGES;"
  else
    mysql -uroot -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '$DB_PASS'; FLUSH PRIVILEGES;"
  fi
fi

# 3. schema (only into an empty database)
TABLES=$(mysql -uroot -p"$DB_PASS" -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='mobiusdb';")
if [ "$TABLES" = "0" ]; then
  sed -e 's/utf8mb4_0900_ai_ci/utf8mb4_general_ci/g' -e 's/utf8mb4_0900_bin/utf8mb4_bin/g' \
      "$MOBIUS_DIR/mobius/db/mobiusdb.sql" | mysql -uroot -p"$DB_PASS" mobiusdb
  echo "schema imported"
fi

# 4. configuration + sealed secrets
if [ ! -f "$MOBIUS_DIR/conf.json" ]; then
  cat > "$MOBIUS_DIR/conf.json" <<EOF
{
    "db": "mysql",
    "cseBase": "Mobius",
    "cseId": "/Mobius2",
    "spId": "//keti.re.kr",
    "superUser": "Sponde",
    "csebaseport": "$PORT"
}
EOF
fi
if [ ! -f "$MOBIUS_DIR/conf.seal.json" ]; then
  python3 "$ROOT/scripts/_mobius_seal.py" "$MOBIUS_DIR" --superuser
fi
python3 "$ROOT/scripts/_mobius_seal.py" "$MOBIUS_DIR" --dbpass "$DB_PASS"

# 5. run
stop
start
