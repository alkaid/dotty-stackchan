# dotty-pi

Production Docker image for the **pi coding agent** running as Dotty's
voice-tool brain on Unraid. Replaces the RPi-hosted `zeroclaw-bridge`
per [#36](https://github.com/BrettKinny/dotty-stackchan/issues/36).

## What this is

A pinned `node:22.17-alpine3.22` LTS image with `@earendil-works/pi-coding-agent`
installed globally. The image also bakes in `dotty-pi-ext` and renders
`/root/.pi/agent/models.json` from compose `.env` variables at container
start. It exposes a small HTTP RPC service on port 8091; xiaozhi-server calls
that service over the compose network.

The runtime contract is:

- **xiaozhi-server** routes voice-LLM calls to the `PiVoiceLLM` provider.
- **PiVoiceLLM / PiHttpClient** translates each turn into an HTTP request to
  `dotty-pi:8091`.
- **pi** (this container) runs the prompt against the `sub2api`
  OpenAI-compatible provider (`dotty-simple` by default), with
  the [`dotty-pi-ext`](../dotty-pi-ext/) extension loaded for the seven
  voice tools (`memory_lookup`, `remember`, `recall_person`,
  `remember_person`, `think_hard`, `take_photo`, `play_song`).

## Build + run

`dotty-pi` is started by the root stack compose file:

```bash
docker compose up -d --build dotty-pi
```

For remote Unraid deployment, use the single stack deploy wrapper from the
repo root:

```bash
DOTTY_HOST=root@<UNRAID_HOST> bash scripts/deploy-stack.sh
```

On-box layout (build context and live state are **separate** directories):

```
/mnt/user/appdata/
├── dotty-stackchan-src/         # repo checkout and compose.yml
└── dotty-pi/                    # persistent state (STATE_DIR)
    ├── agent/                   # bind-mount → /root/.pi/agent
    │   ├── models.json          # rendered from .env at container start
    │   ├── auth.json            # live — never touched by deploy
    │   └── sessions/            # live — never touched by deploy
    ├── memory/                  # bind-mount → /root/.pi/memory
    │   └── brain.db             # FTS5 store — migrated from RPi (live)
    └── sessions/                # bind-mount → /root/.pi/sessions
```

## Model selection — sub2api split routes

`dotty-pi/render-models-json.mjs` renders a `sub2api` provider with two
model entries. `dotty-pi/models.json` is the checked-in example shape; the
live file is generated from `.env` each time the container starts.

The voice model split is:

| Loop | Model | Why |
|---|---|---|
| Outer agent (`pi --model ...`) | `dotty-simple` | Fast/simple chat and tool-routing model. This is the default in `dotty-pi` RPC. |
| `think_hard` escalation | `dotty-think` | Larger or reasoning-capable model. Called directly by the extension; no agent overhead. |

Host `.env` example:

```env
DOTTY_PI_BASE_URL=https://DOTTY_PI_BASE_URL_PLACEHOLDER/v1
DOTTY_PI_API_KEY=sk-...
DOTTY_PI_PROVIDER=sub2api
DOTTY_PI_MODEL=dotty-simple
DOTTY_PI_SIMPLE_REASONING=false
DOTTY_PI_THINK_REASONING=true
DOTTY_PI_THINK_REASONING_EFFORT=high
DOTTY_PI_THINK_MAX_TOKENS=4096
VOICE_THINKER_MODEL=dotty-think
# Optional when the thinker endpoint or key differs from the simple route.
VOICE_THINKER_URL=
VOICE_THINKER_API_KEY=sk-...
```

When `VOICE_THINKER_URL` is empty, the extension appends
`/chat/completions` to `DOTTY_PI_BASE_URL`. The direct request uses
`DOTTY_PI_THINK_REASONING`, `DOTTY_PI_THINK_REASONING_EFFORT`, and
`DOTTY_PI_THINK_MAX_TOKENS`.

The dotty-pi RPC server owns the outer `pi --model ...` argument, so the
stack `.env` must match the simple route:

```env
DOTTY_PI_PROVIDER=sub2api
DOTTY_PI_MODEL=dotty-simple
```

The extension dependencies are built in a separate image stage so native
modules can use their Node 22 prebuilt binaries without shipping a compiler.
The image bakes in `personas/default.md` as the first-Role fallback. The RPC
server reads the active Role from the shared `roles.json`; Kid and Smart mode
state do not select or modify the Role prompt.
Pi starts with `--no-builtin-tools`; voice turns can use only
the tools registered by `dotty-pi-ext`, not shell or file-editing tools.

See [`../docs/deployment.md`](../docs/deployment.md) for the full runbook and
the maintenance rule for future deployment changes.

## Versioning

| Tag | Pi version | Notes |
|---|---|---|
| `dotty-pi:0.1.0` | `0.74.0` | Production-grade promotion of the 2026-05-15 spike. |
| `dotty-pi:spike` | `0.74.0` | The original day-0 spike (`audits/pi-rpc-spike-report.md`). Keep until production is soaked. |

Bump the image tag deliberately when pi or node moves; do not use floating
tags. Cutover testing depends on a known-good image.

## See also

- [`../dotty-pi-ext/README.md`](../dotty-pi-ext/README.md) — voice-tool extension contract.
- [`../custom-providers/pi_voice/README.md`](../custom-providers/pi_voice/README.md) — xiaozhi-side glue.
- [#36](https://github.com/BrettKinny/dotty-stackchan/issues/36) — the cutover plan + soak rule.
