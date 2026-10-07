#!/bin/sh
# Prepare conf.json, the seal and the database, then run Mobius in the foreground.
set -e
cd /opt/mobius
node /opt/edgeguard/init.js
exec node mobius.js
