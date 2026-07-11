---
title: Change Persona
description: Swap Dotty's personality by editing the persona prompt or pointing the LLM provider at a different persona file.
---

# Change Persona

Persona-file support depends on which LLM provider is active.

Three personas ship in `personas/`:

| File | Style | Used by |
|---|---|---|
| `default.md` | Cheerful, curious desktop robot. The general-purpose persona for generic providers. | `OpenAICompat` |
| `dotty_voice.md` | Voice-tuned reference persona retained for providers or future workflows that load context files. | Not loaded by current PiVoiceLLM |
| `smart.md` | More capable, allowed longer answers — for when `smart_mode` is on and the cloud model is doing the heavy lifting. | optional override |

## Which file controls the persona?

Check `selected_module.LLM` in `.config.yaml`, then read the matching block:

| Provider | Persona source |
|---|---|
| `PiVoiceLLM` (current default) | No persona file. It forwards the last user message plus versioned per-turn policy from `pi_voice.py`/`textUtils.py`; Pi runs with `--no-context-files`. |
| `OpenAICompat` (and similar generic providers) | `LLM.OpenAICompat.persona_file` in `.config.yaml`. |

## Switch to a different shipped persona

1. With `OpenAICompat` selected, edit `.config.yaml`:

   ```yaml
   LLM:
     OpenAICompat:
       persona_file: personas/smart.md   # was personas/default.md
   ```

2. Restart: `docker compose restart xiaozhi-server`.

## Create your own persona

1. Copy an existing file: `cp personas/default.md personas/pirate.md`.
2. Edit the new file. **Keep the emoji instruction line** — the firmware needs it to animate the face. See [emoji-mapping.md](../emoji-mapping.md) for the allowlist (😊😆😢😮🤔😠😐😍😴).
3. Point `OpenAICompat.persona_file` at the new file in `.config.yaml`, then restart.

## Quick inline edit (no file swap)

For OpenAICompat, edit the top-level `prompt:` block in `.config.yaml`; xiaozhi includes it with that provider's dialogue. PiVoiceLLM does not forward this dialogue. There is not yet an operator-facing hot-swap workflow for PiVoice personas; changing its behavior requires a reviewed change to the versioned per-turn policy and redeploying xiaozhi-server.

## Notes

- For persona-loading providers, retain the emoji-leader rule. PiVoiceLLM additionally guarantees a neutral leading fallback in code.
- See [protocols.md](../protocols.md) for the emoji → face frame mapping.
