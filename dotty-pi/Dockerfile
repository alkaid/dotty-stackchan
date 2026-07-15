# Production image for the dotty-pi runtime — the pi coding agent
# running as Dotty's voice-tool brain on Unraid (replacing the RPi
# zeroclaw-bridge per #36).
#
# Pins are intentional:
# - node:22.17-alpine3.22 — LTS runtime with prebuilt better-sqlite3 support.
# - @earendil-works/pi-coding-agent@0.74.0 — the version the spike was
#   measured against (3.2–3.7 s warm-turn latency).
# Bump these deliberately, not via floating tags.
FROM node:22.17-alpine3.22@sha256:5539840ce9d013fa13e3b9814c9353024be7ac75aca5db6d039504a56c04ea59 AS extension-builder
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org

WORKDIR /opt/dotty-pi/extensions/dotty-pi-ext
COPY dotty-pi-ext/package*.json ./
RUN npm ci --omit=dev --omit=peer --registry=${NPM_CONFIG_REGISTRY} \
    && npm prune --omit=dev --omit=peer \
    && npm cache clean --force

FROM node:22.17-alpine3.22@sha256:5539840ce9d013fa13e3b9814c9353024be7ac75aca5db6d039504a56c04ea59
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org

RUN npm install -g --registry=${NPM_CONFIG_REGISTRY} @earendil-works/pi-coding-agent@0.74.0 \
    && pi --version \
    && npm cache clean --force

ENV PI_HOME=/root/.pi
WORKDIR /root

WORKDIR /opt/dotty-pi/extensions/dotty-pi-ext
COPY dotty-pi-ext/package*.json ./
COPY --from=extension-builder /opt/dotty-pi/extensions/dotty-pi-ext/node_modules ./node_modules
COPY dotty-pi-ext/src ./src

COPY personas /opt/dotty-pi/personas
COPY dotty-pi/render-models-json.mjs /usr/local/bin/render-models-json.mjs
COPY dotty-pi/runtime-config.mjs /usr/local/bin/runtime-config.mjs
COPY dotty-pi/rpc-server.mjs /usr/local/bin/dotty-pi-rpc-server.mjs
COPY dotty-pi/entrypoint.sh /usr/local/bin/dotty-pi-entrypoint
RUN chmod +x /usr/local/bin/render-models-json.mjs /usr/local/bin/dotty-pi-rpc-server.mjs /usr/local/bin/dotty-pi-entrypoint \
    && mkdir -p /root/.pi/extensions \
    && ln -s /opt/dotty-pi/extensions/dotty-pi-ext /root/.pi/extensions/dotty-pi-ext

ENV DOTTY_PI_SYSTEM_PROMPT_FILE=/opt/dotty-pi/personas/default.md

# Run a small HTTP wrapper around pi RPC. xiaozhi-server reaches it over
# the compose network, so no Docker socket or Docker CLI is needed.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:8091/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" \
    && pi --version >/dev/null \
    && test -f /root/.pi/agent/models.json \
    && test -f /root/.pi/extensions/dotty-pi-ext/src/tools/think_hard.ts \
    || exit 1

ENTRYPOINT ["dotty-pi-entrypoint"]
CMD ["node", "/usr/local/bin/dotty-pi-rpc-server.mjs"]
