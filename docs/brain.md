---
title: Brain
description: The pi agent runtime (dotty-pi container), the model matrix, and the admin dashboard service (bridge.py).
---

# Brain — the pi agent + the model matrix

## TL;DR

- The "brain" is the **`dotty-pi` Docker container** running the pi coding agent with the `dotty-pi-ext` extension.
- **`PiVoiceLLM`** (the default xiaozhi LLM provider) sends each voice turn to `dotty-pi` over HTTP RPC on the Compose network. TTS-bound text streams back to xiaozhi-server; tool dispatch happens entirely inside the container.
- The `dotty-pi-ext` extension exposes **seven voice tools** to the agent loop: `memory_lookup`, `remember`, `recall_person`, `remember_person`, `think_hard`, `take_photo`, `play_song`.
- **Which LLM runs which turn:** the pi outer loop targets `DOTTY_PI_MODEL` (default `dotty-simple`) through the `sub2api` provider; `think_hard` calls `VOICE_THINKER_MODEL` (default `dotty-think`) directly. The active Role selects prompt and voice independently. Smart-mode does not change the Role or backend model.
- One documented alternate voice provider exists: **`OpenAICompat`** (points straight at any OpenAI-compatible endpoint; stateless, no voice tools). See [llm-backends.md](./llm-backends.md).

> **Cutover note (2026-05-19, issue #36):** The brain previously ran as the ZeroClaw Rust agent on a Raspberry Pi, fronted by a FastAPI bridge (`bridge.py`) under systemd. ZeroClaw and the RPi host are retired. `bridge.py` survives as the admin dashboard service (port 8081, `/ui`) on the Docker host; its voice and perception roles moved to `PiVoiceLLM`/`dotty-pi` and `dotty-behaviour` respectively.

## Model matrix

| Path | Model | Where | When called |
|---|---|---|---|
| PiVoiceLLM outer agent loop | `DOTTY_PI_MODEL` (`dotty-simple`) | sub2api / OpenAI-compatible | Every voice turn; selected by the dotty-pi environment. |
| pi tool: `think_hard` | `VOICE_THINKER_MODEL` (`dotty-think`) | sub2api / OpenAI-compatible | Multi-step reasoning; direct POST from dotty-pi-ext, no agent overhead. |
| pi tool: `memory_lookup` | (no LLM call — FTS5) | brain.db inside dotty-pi | `"do you remember…"` queries. |
| pi tool: `take_photo` | `google/gemini-3.1-flash-lite` (`VLM_MODEL`) | dotty-behaviour → OpenRouter | Camera describe. |
| pi tool: `play_song` | (no LLM call) | Firmware via `/xiaozhi/admin/play-asset` | Song request. |
| Smart-mode display label (`SMART_MODEL`) | `VOICE_THINKER_MODEL` | dashboard only | Legacy display metadata; Smart Mode does not select a Role or swap the live PiVoiceLLM model. |
| Vision narrative (security/scene synthesis) | `VISION_MODEL` (`google/gemini-3.1-flash-lite`) | OpenRouter | dotty-behaviour internal — camera frame description. |
| Audio captioning (security mode) | `AUDIO_CAPTION_MODEL` (`google/gemini-2.5-flash`) | OpenRouter | dotty-behaviour internal — ambient sound description. |

## The pi agent runtime

### dotty-pi container

`dotty-pi` is a pinned `node:22.17-alpine3.22` LTS image with `@earendil-works/pi-coding-agent` installed globally. A separate build stage prepares the native extension dependencies without leaving a compiler in the runtime image. The image also contains `dotty-pi-ext`, a startup renderer for `/root/.pi/agent/models.json`, and a small HTTP RPC wrapper on port 8091.

The runtime contract:
1. **xiaozhi-server** calls `PiVoiceLLM.generate()` with the dialogue.
2. **PiHttpClient** posts the turn to `http://dotty-pi:8091/turn`.
3. **pi** runs the prompt against the provider/model selected by `DOTTY_PI_PROVIDER` and `DOTTY_PI_MODEL` with the `dotty-pi-ext` extension loaded.
4. Thinking deltas and extension UI requests are filtered by PiClient; only TTS-bound text chunks reach xiaozhi-server.
5. `PiVoiceLLM` holds one `PiHttpClient`; between turns it calls `/new_session` to reset pi's working state without re-spawning the process.

Appdata layout on the Docker host:

```
/mnt/user/appdata/dotty-pi/
├── agent/
│   └── models.json          # rendered provider config (sub2api/OpenAI-compatible)
├── sessions/                # pi session state
├── memory/
│   └── brain.db             # FTS5 full-text store
```

`dotty-pi-ext` is not stored in appdata anymore; it is baked into the image at
`/opt/dotty-pi/extensions/dotty-pi-ext` and exposed under `PI_HOME` by symlink.

### dotty-pi-ext — the seven voice tools

`dotty-pi-ext` is the pi extension that exposes Dotty's voice tools to the agent loop.

| Tool | What it does |
|---|---|
| `memory_lookup(query)` | FTS5 search against `brain.db`; returns top-3 snippets, ≤200 chars each. |
| `remember(fact)` | Stores a durable fact (≤300 codepoints) into `brain.db` with `category=core`, `importance=0.7`. |
| `recall_person(name)` | Reads approved per-person facts from `brain.db`. |
| `remember_person(name, fact)` | Stores a fact about a household member, with minor facts held for review. |
| `think_hard(question)` | Direct POST using `VOICE_THINKER_MODEL` and `DOTTY_PI_THINK_*`; `VOICE_THINKER_URL` and key are optional overrides. |
| `take_photo()` | GET to `dotty-behaviour /api/voice/take_photo` — returns latest cached vision description if ≤30 s old. |
| `play_song(name)` | Resolves free-form name against `/xiaozhi/admin/songs` catalogue (60 s cache), then POSTs `/xiaozhi/admin/play-asset`. |

In addition, an `agent_end` handler in the extension automatically writes a `category=conversation` row to `brain.db` after every completed user prompt — the agent does not decide to log; every successful turn is recorded.

### Model selection for dotty-pi

The outer pi loop and the `think_hard` escalation are deliberately separate:

| Route | Config owner | Key env |
|---|---|---|
| Outer agent and simple route | dotty-pi container | `DOTTY_PI_PROVIDER`, `DOTTY_PI_MODEL`, active Bridge Role |
| Rendered provider config | dotty-pi container | `DOTTY_PI_BASE_URL`, `DOTTY_PI_API_KEY`, `DOTTY_PI_SIMPLE_*`, `DOTTY_PI_THINK_*` |
| `think_hard` direct call | dotty-pi extension | `VOICE_THINKER_URL`, `VOICE_THINKER_MODEL`, `VOICE_THINKER_API_KEY` |

`DOTTY_PI_PROVIDER` is also the provider key rendered into `models.json`.
`DOTTY_PI_MODEL` is also the simple-route model id rendered into `models.json`.
See [deployment.md](./deployment.md) for the deployment contract.

## The bridge — `bridge.py` (dashboard service)

`bridge.py` was the original HTTP→ZeroClaw translator, running under systemd on the RPi. Post-cutover (#36) it runs as a Docker container on the same Docker host, port 8081. Its **voice path** (`/api/message`, `/api/voice/*`) and **perception relay** (`/api/perception/event`) roles are retired — those functions moved to `PiVoiceLLM`/`dotty-pi` and `dotty-behaviour`. What remains:

- **Admin dashboard** (`/ui`) — the operator web UI for monitoring turns, toggling kid-mode/smart-mode, viewing scene context, and LED state.
- **`/admin/*` endpoints** (`X-Admin-Token`) — runtime toggles for kid-mode, smart-mode, and robot state.

Dashboard perception and vision panels read from `dotty-behaviour` over Compose DNS.

See [protocols.md](./protocols.md) for the admin endpoint wire formats.

## The LLMs

### Qwen3-30B-A3B-Instruct-2507 (legacy path — retired)

Previously used by the ZeroClawLLM provider via OpenRouter. Not used in the current architecture.

### Qwen3 language routing

Qwen3 is multilingual. Voice turns should follow the language detected by ASR instead of defaulting to the language used by the system prompt.

**Routing in the current stack:**

1. FunASR emits a language tag such as `zh` or `en` when `ASR_LANGUAGE=auto`.
2. `receiveAudioHandle.py` attaches that tag as a private `RESPONSE_LANGUAGE` marker on every voice reply path.
3. `custom-providers/textUtils.py` appends a per-turn same-language constraint used by PiVoiceLLM and OpenAICompat.

This controls response text and subtitles. The default Xiaoxiao EdgeTTS voice targets Mandarin; switch the Role to ChatTTS when bilingual Chinese, English, and mixed text synthesis is required.

### dotty-simple / dotty-think (PiVoiceLLM path)

The default deployment uses sub2api aliases:

- `dotty-simple` for the outer pi agent loop.
- `dotty-think` for the `think_hard` direct call.

Both are placeholders. Set them to real model ids or provider-side aliases in
`.env`; `DOTTY_PI_MODEL` is the single source of truth for the simple route.

### Vision and audio models

- **VLM (`take_photo`, security camera frames):** `google/gemini-3.1-flash-lite` (`VLM_MODEL`). Served by dotty-behaviour.
- **Audio captioning (security mode):** `google/gemini-2.5-flash` (`AUDIO_CAPTION_MODEL`). Served by dotty-behaviour.

## OpenRouter

OpenRouter can front `VLM_MODEL` and `AUDIO_CAPTION_MODEL`, but both routes are
configurable OpenAI-compatible endpoints. Only `dotty-behaviour` receives the
related API keys.

Observability OpenRouter itself offers (not currently surfaced in this stack):
- Per-request latency + cost dashboards.
- Multi-model A/B routing.
- Per-provider failover for the same model.

## See also

- [voice-pipeline.md](./voice-pipeline.md) — what xiaozhi-server runs.
- [architecture.md](./architecture.md) — full topology and data-flow diagrams.
- [protocols.md](./protocols.md) — pi RPC mode wire format, admin endpoints.
- [llm-backends.md](./llm-backends.md) — choosing between PiVoiceLLM and OpenAICompat.
- [latent-capabilities.md](./latent-capabilities.md) — streaming, session reuse, tool-use, MCP-server mode.
- [references.md](./references.md) — Qwen3, OpenRouter, pi coding agent links.
- [cutover-behaviour.md](./cutover-behaviour.md) — historical runbook for the #36 ZeroClaw → pi-agent cutover.

Last verified: 2026-05-22.
