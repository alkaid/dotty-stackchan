# pi_voice

xiaozhi-server custom LLM provider that routes voice turns through the
[`dotty-pi`](../../dotty-pi/) container instead of bridge.py. The
RPi-replacement path per [#36](https://github.com/BrettKinny/dotty-stackchan/issues/36).

**Status: production — the live default.** Wired into xiaozhi-server via `selected_module.LLM: PiVoiceLLM`.

What works:
- `pi_client.py` — HTTP client for the `dotty-pi` RPC service. The RPC
  service owns the long-lived `pi --mode rpc` process, filters
  `thinking_delta`, auto-cancels dialog `extension_ui_request`s, and throws
  `PiClientError` on rejected prompts or timeouts.
- `pi_voice.py` — `LLMProvider` subclass that translates xiaozhi's
  `(session_id, dialogue)` → pi prompt and yields text deltas back as
  a sync generator (the shape xiaozhi's voice loop expects).
- `tests/test_pi_client.py` — pure-Python unit tests with a fake
  subprocess for the 3 Step-5 invariants + prompt-rejection +
  timeout. Run with `python3 -m unittest custom-providers.pi_voice.tests.test_pi_client`.

The HARD-CONSTRAINTS sandwich ships: every turn is wrapped server-side
via `_wrap_with_sandwich` / `build_turn_suffix(KID_MODE)` (from
`core.utils.textUtils`) before the prompt reaches pi.

Memory persistence is owned by `dotty-pi-ext`: explicit remember tools write
facts, and its `agent_end` hook records completed conversations in `brain.db`.

## Architecture

```
xiaozhi-server (Docker)                     dotty-pi (Docker, same compose network)
┌────────────────────────────┐              ┌──────────────────────────────┐
│  selected_module.LLM:      │              │  pi (idling via sleep ∞)     │
│    PiVoiceLLM              │              │                              │
│       │                    │              │  HTTP wrapper starts:        │
│       ↓ async call         │              │    pi --provider sub2api     │
│  custom-providers/         │  HTTP RPC    │      --model dotty-simple    │
│    pi_voice/               │  ───────────→│      --mode rpc              │
│      pi_voice.py           │              │      --thinking off          │
│      pi_client.py          │  ←─────────  │      <prompt>                │
│                            │  text stream │                              │
└────────────────────────────┘              └──────────────────────────────┘
                                                          ↓
                                                ┌──────────────────────┐
                                                │ dotty-pi-ext         │
                                                │   7 voice tools      │
                                                │   (memory_lookup,    │
                                                │    think_hard, …)    │
                                                └──────────────────────┘
                                                          ↓
                                            sub2api thinker (dotty-think)
                                            xiaozhi-admin (songs, MCP)
                                            brain.db (FTS5)
```

## Components

### `pi_voice.py` — xiaozhi LLMProviderBase subclass

Translates xiaozhi's chat-completion interface to a pi RPC turn. Async
`chat_stream` shape so xiaozhi can pipe text deltas straight to TTS
without buffering the full reply.

### `pi_client.py` — HTTP RPC client

Calls the RPC wrapper exposed by `dotty-pi` on `http://dotty-pi:8091`.
The wrapper owns the long-lived pi process. Per #36's Step-5 constraints:

- **Single persistent pi process** spawned once per dotty-pi boot.
- **Auto-cancel `extension_ui_request`** with `{cancelled: true}` to
  prevent pi from blocking on UI prompts no one will answer.
- **Filter `assistantMessageEvent.type == "thinking_delta"`** out of the
  event stream the provider yields back to xiaozhi (per spike: 19
  thinking deltas vs 3 text deltas per turn; only text reaches TTS).

### `__init__.py` — package marker

So xiaozhi-server's `core.providers.llm.pi_voice` import path resolves.

## Wiring into xiaozhi-server

The root Dockerfile copies the provider package into the xiaozhi image, while
`compose.yml` supplies only runtime configuration:

```yaml
environment:
  DOTTY_PI_URL: http://dotty-pi:8091
```

Then in `data/.config.yaml`:

```yaml
selected_module:
  LLM: PiVoiceLLM

LLM:
  PiVoiceLLM:
    type: pi_voice
    url: http://dotty-pi:8091
```

The model + extension wiring lives container-side: `dotty-pi` renders
`/root/.pi/agent/models.json` from compose `.env`, and `dotty-pi-ext` is baked
into the image. xiaozhi-server only needs its outer route env to match the
simple model id:

```env
DOTTY_PI_PROVIDER=sub2api
DOTTY_PI_MODEL=dotty-simple
```

The `bridge.py` admin dashboard service continues to run independently;
it is no longer in the voice path. Its former `/api/voice/*` and
`/api/message` routes were retired in #36.

### Recovery: known-good rollback

If PiVoiceLLM misbehaves, flip to the `OpenAICompat` provider in
`data/.config.yaml` (`selected_module.LLM: OpenAICompat`, pointed at a local
sub2api or any OpenAI-compatible endpoint) and `docker compose restart
xiaozhi-esp32-server`. The former `Tier1Slim` rollback provider was removed
in the 2026-05-29 alignment pass because its tool escalation depended on the
retired ZeroClaw bridge.

## Open questions resolved during this slice

- **Stream shape.** xiaozhi expects `response()` to be a *sync generator
  yielding strings* (the same contract every xiaozhi LLM provider follows).
  `LLMProvider.response()` here matches that exactly.
- **Tool-call surfacing.** Pi owns the agent loop; tool calls happen
  *inside* pi (via `dotty-pi-ext`) and only their text-shape result ever
  leaves the container. xiaozhi never sees `tool_calls` from this
  provider — unlike a plain OpenAI-style provider, which parses them itself.
- **Wire-protocol details.** `extension_ui_response` cancel shape from
  pi's `docs/rpc.md`; `assistantMessageEvent` filtering rule from the
  spike telemetry.

## Runtime prompt policy and persona state

- **Memory write-back.** `remember` / `remember_person` handle explicit writes,
  and the extension's `agent_end` hook records each completed conversation.
- **Persona file location.** Persona files are baked into the `dotty-pi`
  image under `/opt/dotty-pi/personas/`; `DOTTY_PI_SYSTEM_PROMPT_FILE`
  selects the active file when the pi process starts.

## See also

- [`../../dotty-pi/README.md`](../../dotty-pi/README.md) — the runtime image.
- [`../../dotty-pi-ext/README.md`](../../dotty-pi-ext/README.md) — voice-tool extension.
- [`../textUtils.py`](../textUtils.py) — the shared `build_turn_suffix` sandwich + emoji map.
- [#36](https://github.com/BrettKinny/dotty-stackchan/issues/36) — cutover plan + soak rule.
