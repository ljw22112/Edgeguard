# KETI Mobius 3 (oneM2M IN-CSE) for the EdgeGuard MEC host.
#
# The Mobius source comes from the named build context `mobius-src`, pinned to a commit:
#   docker build -f deploy/mobius/Dockerfile \
#     --build-context mobius-src=https://github.com/IoTKETI/Mobius.git#3ddd305857c0bfadffa5ac88af47841365f722cb \
#     -t edgeguard-mobius deploy/mobius
# (deploy/docker-compose.yml passes it; MOBIUS_SRC overrides it, e.g. with a local checkout.)
#
# Mobius talks to MySQL/MariaDB at localhost:3306 as root (fixed in mobius/db/mysql.js), so the
# container runs in the database container's network namespace (see docker-compose.yml).
ARG NODE_IMAGE=node:20-bookworm-slim
FROM ${NODE_IMAGE}

WORKDIR /opt/mobius
COPY --from=mobius-src . /opt/mobius
# Upstream does not ship a lockfile; this one was resolved against the pinned commit, so every
# build installs the same dependency versions (npm ci).
COPY package-lock.json /opt/mobius/package-lock.json
RUN rm -rf node_modules conf.json conf.seal.json log/* .git \
 && npm ci --omit=dev --no-audit --no-fund \
 && npm cache clean --force
COPY init.js entrypoint.sh /opt/edgeguard/
RUN chmod +x /opt/edgeguard/entrypoint.sh

ENV MOBIUS_PORT=7579 MOBIUS_CSE_BASE=Mobius MOBIUS_CSE_ID=/Mobius2 MOBIUS_SP_ID=//keti.re.kr \
    MOBIUS_SUPERUSER=Sponde
EXPOSE 7579
HEALTHCHECK --interval=5s --timeout=3s --start-period=20s --retries=10 \
  CMD node -e "require('http').get({host:'127.0.0.1',port:process.env.MOBIUS_PORT,path:'/'+process.env.MOBIUS_CSE_BASE,headers:{'X-M2M-Origin':'SHealth','X-M2M-RI':'hc','X-M2M-RVI':'2a'}},r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"
ENTRYPOINT ["/opt/edgeguard/entrypoint.sh"]
