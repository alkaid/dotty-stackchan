---
title: Change Persona
description: Swap Dotty's personality by editing the persona prompt or pointing the LLM provider at a different persona file.
---

# Change Persona

Dotty's personality comes from a persona file loaded as the LLM system prompt. **Where** that file lives depends on which LLM provider is active.

Three personas ship in `personas/`:

| File | Style | Used by |
|---|---|---|
| `default.md` | Cheerful, curious desktop robot. The general-purpose persona for generic providers. | `OpenAICompat` |
| `dotty_voice.md` | Voice-tuned variant of `default.md` — same character but pruned for short replies, with the tool catalogue and `[REMEMBER: ...]` markers baked in. | `PiVoiceLLM` |
| `smart.md` | More capable, allowed longer answers — for when `smart_mode` is on and the cloud model is doing the heavy lifting. | optional override |

## Which file controls the persona?

Check `selected_module.LLM` in `.config.yaml`, then read the matching block:

| Provider | Persona source |
|---|---|
| `PiVoiceLLM` (current default) | `DOTTY_PI_SYSTEM_PROMPT_FILE`; defaults to `/opt/dotty-pi/personas/dotty_voice.md` in the `dotty-pi` image. |
| `OpenAICompat` (and similar generic providers) | `LLM.OpenAICompat.persona_file` in `.config.yaml`. |

## Switch to a different shipped persona

For `PiVoiceLLM`, select one of the persona files already baked into the image:

```env
DOTTY_PI_SYSTEM_PROMPT_FILE=/opt/dotty-pi/personas/smart.md
```

Then apply the changed environment:

```bash
docker compose up -d dotty-pi
```

For `OpenAICompat`, change `LLM.OpenAICompat.persona_file` in
`data/.config.yaml`, then restart `xiaozhi-esp32-server`.

## Create your own persona

1. Copy an existing file: `cp personas/dotty_voice.md personas/pirate.md`.
2. Edit the new file. **Keep the emoji instruction line** — the firmware needs it to animate the face. See [emoji-mapping.md](../emoji-mapping.md) for the allowlist (😊😆😢😮🤔😠😐😍😴).
3. Rebuild the relevant image so the new file is included:

   ```bash
   docker compose up -d --build dotty-pi xiaozhi-esp32-server
   ```

4. Point the active provider at `/opt/dotty-pi/personas/pirate.md` for
   `PiVoiceLLM`, or `personas/pirate.md` for `OpenAICompat`.

## Quick inline edit (no file swap)

Edit the top-level `prompt:` block in `data/.config.yaml` directly. This is the
xiaozhi-server system prompt used by generic providers. On the `PiVoiceLLM`
path, the `dotty-pi` image persona is the primary source, so persona source
changes require an image rebuild.

## Notes

- Always keep the emoji-leader rule in any persona — removing it breaks face animations. The persona prompt and the xiaozhi-server system prompt are the two enforcement layers.
- See [protocols.md](../protocols.md) for the emoji → face frame mapping.
