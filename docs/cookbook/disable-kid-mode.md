---
title: Disable Kid Mode
description: Turn off child-safety guardrails to use Dotty as a general-purpose assistant.
---

# Disable Kid Mode

Kid Mode is **on by default** (`DOTTY_KID_MODE=true`). Disabling it
removes child-specific rules while keeping core voice constraints.

## How to disable

Set the environment variable (in `.env` or the shell environment):

```bash
DOTTY_KID_MODE=false
```

Recreate the xiaozhi-server container so the LLM provider reads the new
environment snapshot.

## What changes (removed)

| Rule | Description |
|---|---|
| 4 | Age-appropriate audience (4-8) constraint |
| 5 | Topic blocklist (violence, drugs, sex, horror, hate) |
| 6 | Self-harm gentle redirect |
| 7 | Jailbreak resistance ("ignore previous", "DAN", etc.) |
| 8 | Picture-book vocabulary only |
| 9 | Fail-toward-safer default |

`VISION_SYSTEM_PROMPT` switches to general-purpose image descriptions
(no child-safe filtering, no restriction on identifying people).

## What stays the same

| Rule | Description |
|---|---|
| 1 | English-only replies |
| 2 | Emoji prefix (one of the 9 allowed emojis) |
| 3 | Default 1-2 short sentences, up to 6 for open-ended asks; TTS-friendly |

The TTS-bound blocked-words filter is disabled with Kid Mode. Emoji-prefix,
English-only, and response-length constraints remain active.

## See also

- [kid-mode.md](../kid-mode.md) -- full guardrail architecture.
