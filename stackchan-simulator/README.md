# StackChan Simulator

LAN-only test console for one simulated StackChan device. It connects to the
real Xiaozhi WebSocket endpoint and exposes the repository's machine HTTP APIs
through a fixed service allowlist.

Production-style startup is opt-in from the repository root:

```bash
make simulator
```

Open `http://<compose-host>:${STACKCHAN_SIMULATOR_PORT:-8082}`. Normal
`docker compose up -d` does not start this profile.

For local development:

```bash
npm install
npm run build
npm test
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/google-chrome npm run test:e2e
npm start
```

Local `dev` and `start` commands load the repository-root `.env`. The device
connection prefers `XIAOZHI_WS_URL`, then the host-published
`XIAOZHI_WS_PORT`, and only then `XIAOZHI_PUBLIC_WS_BASE_URL`. Compose supplies
its internal DNS addresses explicitly.

The backend provides `/health`, `/api/catalog`, `/api/execute/:id`,
`/api/smoke`, `/api/device/*`, `/api/logs/*`, and `/ws/ui`. Upstream base URLs
come only from server environment variables. `DOTTY_ADMIN_TOKEN` is injected
by the backend for the Xiaozhi and bridge admin surfaces and is redacted from
the in-memory log.
