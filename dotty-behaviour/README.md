# dotty-behaviour

Unraid-resident successor to the RPi-hosted `zeroclaw-bridge`. Hosts
the perception event bus, the 11 ambient-perception consumers (running
set is env-gated), vision and audio explain endpoints, the proactive
greeter, and the per-device caches consumed by all of the above. It
**serves** the perception / vision / audio data endpoints that the
`bridge.py` admin dashboard (port 8081, `/ui`) consumes — it does not
host the dashboard itself; that stays in `bridge.py` per #115.

Sibling of [`dotty-pi`](../dotty-pi/) — together they replaced the RPi
bridge. Cutover executed and RPi powered off **2026-05-19** under
[#36](https://github.com/BrettKinny/dotty-stackchan/issues/36).

## What this is

A FastAPI app pinned to `python:3.12-slim-bookworm` running on Unraid
in the root `compose.yml`. xiaozhi-server talks to it on
`http://dotty-behaviour:8090` — loopback (`127.0.0.1`) only works if
xiaozhi-server is also on host networking, which it isn't in the
current deployment (it's on the Compose bridge network, so its loopback
resolves to itself). The container is a near-direct lift of
`bridge.py` + `bridge/*` minus the obsolete `/api/message` /
`/api/voice/*` / ZeroClaw stdio plumbing that PiVoiceLLM made
redundant in `#36`.

## Build + run

```bash
cd <XIAOZHI_PATH>
docker compose up -d --build dotty-behaviour
```

The root `compose.yml` is the only deployment entry point. The image contains
all application source; Compose mounts only state, logs, and secrets.

## Why a separate container

The bridge was a separate process on the RPi for the whole life of
this project, and that's been good — independent restart, debug,
profiling. Folding perception into xiaozhi-server would couple
event-driven background work with the latency-sensitive request path
(scene_synthesis fires 200-token narrative LLM calls; sleep_dreamer
fires multi-hundred-token calls; any of these blocking the xiaozhi
event loop is a voice-latency spike). Folding into `dotty-pi` would
make a polyglot container with two service managers. A peer container
preserves the operational shape that already works.

## Layout

Flat — this is an app that only runs inside its container, not a
distributable library. Modules sit at the top of the build context;
the Dockerfile copies them straight into `/app`.

```
dotty-behaviour/
├── Dockerfile
├── requirements.txt
├── README.md
├── conftest.py                  # pytest rootdir marker
├── main.py                      # FastAPI app + lifespan + route mount
├── config.py                    # Env var loading
├── perception/                  # Event bus + 4 caches + state machine
│   ├── state.py                 # Central PerceptionState dataclass
│   └── snapshot.py              # Read-only snapshot (ported from
│                                #   bridge/perception/cache.py)
├── routes/                      # FastAPI routers split by concern
│   ├── health.py
│   └── perception.py            # /api/perception/{event,state,feed}
└── tests/                       # pytest smoke tests
```

Subsequent slices land:

| Slice                       | What it adds                                          |
|-----------------------------|-------------------------------------------------------|
| Outbound dispatchers        | `dispatch/xiaozhi.py` (admin client) + `dispatch/llm.py` (llama-swap narrative) |
| 11 consumers                | `consumers/{face_greeter,wake_word_turner,sound_turner,face_lost_aborter,face_identified_refresher,purr_player,security_cycle,scene_synthesis,idle_photographer,sleep_dreamer,dance_reflector}.py` (running set env-gated) |
| Vision / audio explain      | `routes/vision.py` + `routes/audio.py` + OpenRouter VLM/ASR clients |
| Greeter + household         | `greeter/` + `household/` (ported from `bridge/`)     |
| Calendar + weather          | `routes/calendar.py` + cache loops                     |
| State files                 | kid-mode / smart-mode toggle files                    |
| NDJSON writers              | `logs/` package (scene-synth, dreams, dances, idle-perception, security) |

## What gets dropped (vs the bridge)

- `/api/message`, `/api/message/stream`, `ACPClient`, the entire
  ZeroClaw stdio path — PiVoiceLLM is live; bridge no longer routes
  voice turns.
- `/api/voice/escalate`, `/api/voice/memory_log`, `/api/voice/remember`
  — `dotty-pi-ext` handles these inside the agent loop now.
- `bridge/speaker.py` — only consumed by `/api/message`.
- Smart-mode model-swap (rewrote RPi-side `~/.zeroclaw/config.toml`)
  — no Unraid equivalent; v2 scope per #36 if it returns.

## Cutover (historical)

Cutover landed 2026-05-19. xiaozhi-server's `VISION_BRIDGE_URL` env
var was flipped from the old RPi bridge URL to
`http://dotty-behaviour:8090` (Compose DNS, not loopback — see
the networking note above), and the matching `plugins.vision_explain`
URL in `data/.config.yaml` was flipped the same way. Full runbook +
lessons-learned in [`docs/cutover-behaviour.md`](../docs/cutover-behaviour.md).
