// First-start preparation for the Mobius container (runs before `node mobius.js`):
//   1. conf.json from the environment (MOBIUS_*), then the seal Mobius checks at boot
//      (mobius/conf_seal.js: an HMAC over dbpass/superUser - portable, no terminal needed)
//   2. wait for MariaDB/MySQL on localhost:3306, create `mobiusdb`, import the schema once
//      (MySQL 8 collations rewritten so MariaDB accepts them)
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = '/opt/mobius';
const env = process.env;

if (!env.MOBIUS_DB_PASS) {
  console.error('[init] MOBIUS_DB_PASS is not set');
  process.exit(1);
}

const confFile = path.join(ROOT, 'conf.json');
const conf = {
  db: 'mysql',
  cseBase: env.MOBIUS_CSE_BASE,
  cseId: env.MOBIUS_CSE_ID,
  spId: env.MOBIUS_SP_ID,
  superUser: env.MOBIUS_SUPERUSER,
  csebaseport: String(env.MOBIUS_PORT),
  dbpass: env.MOBIUS_DB_PASS,
  // MQTT broker for MQTT-bound notifications (Mobius always connects one; the compose stack
  // runs Mosquitto as service `mqtt`)
  mqttBroker: env.MOBIUS_MQTT_BROKER || 'localhost',
  mqttPort: String(env.MOBIUS_MQTT_PORT || 1883),
};
fs.writeFileSync(confFile, JSON.stringify(conf, null, 4) + '\n');
require(path.join(ROOT, 'mobius', 'conf_seal')).seal(confFile, conf);
console.log('[init] conf.json written and sealed');

const mysql = require(path.join(ROOT, 'node_modules', 'mysql2', 'promise'));

async function connectWithRetry() {
  const deadline = Date.now() + 120000;
  for (;;) {
    try {
      return await mysql.createConnection({ host: '127.0.0.1', port: 3306, user: 'root',
                                            password: env.MOBIUS_DB_PASS, multipleStatements: true });
    } catch (e) {
      if (Date.now() > deadline) throw e;
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
}

(async () => {
  const db = await connectWithRetry();
  await db.query('CREATE DATABASE IF NOT EXISTS mobiusdb');
  const [rows] = await db.query(
    "SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema = 'mobiusdb'");
  if (rows[0].n === 0) {
    const sql = fs.readFileSync(path.join(ROOT, 'mobius', 'db', 'mobiusdb.sql'), 'utf8')
      .replace(/utf8mb4_0900_ai_ci/g, 'utf8mb4_general_ci')
      .replace(/utf8mb4_0900_bin/g, 'utf8mb4_bin');
    await db.query('USE mobiusdb');
    await db.query(sql);
    console.log('[init] schema imported');
  } else {
    console.log(`[init] schema present (${rows[0].n} tables)`);
  }
  await db.end();
})().catch((e) => {
  console.error('[init] database preparation failed:', e.message);
  process.exit(1);
});
