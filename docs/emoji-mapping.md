---
title: Emoji → Expression Mapping
description: How emoji characters in LLM responses map to face animations on the StackChan.
---

# Emoji → Expression Mapping

Every LLM response starts with an emoji. The xiaozhi-server parses this
emoji and sends an emotion frame to the StackChan firmware, which renders
the corresponding face animation.

## Active Mapping

| Emoji | Emotion ID | Face Animation | Source |
|-------|-----------|----------------|--------|
| 😊 | `happy` | Smiling face | Dotty patch |
| 😆 | `laughing` | Laughing face | Upstream |
| 😢 | `sad` | Sad face | Dotty patch |
| 😮 | `surprised` | Surprised face | Dotty patch |
| 🤔 | `thinking` | Thinking face | Upstream |
| 😠 | `angry` | Angry face | Upstream |
| 😐 | `neutral` | Neutral face | Dotty patch |
| 😍 | `loving` | Love face | Upstream |
| 😴 | `sleepy` | Sleepy face | Upstream |

"Dotty patch" means the emoji was added to the upstream `EMOJI_MAP` in
`custom-providers/textUtils.py`. "Upstream" means it exists in the base
xiaozhi-server code.

## Enforcement on the live PiVoiceLLM path

`build_turn_suffix()` requests one of the nine allowed emojis on every turn.
`PiVoiceLLM._enforce_leading_emoji()` then enforces the wire contract: it
preserves an allowed prefix or prepends neutral `😐` before TTS. Persona files
and xiaozhi's top-level `.config.yaml` prompt are not forwarded by PiVoiceLLM;
Pi runs with `--no-context-files`.

If the model omits the prefix, the neutral fallback is used. A newly allowed
emoji must be added consistently to `ALLOWED_EMOJIS`, `EMOJI_MAP`, and the
firmware mapping or it will not select the intended face.

## How to Add a New Emoji

See [docs/cookbook/add-emoji.md](cookbook/add-emoji.md).

## Where the Code Lives

| Component | File | What it does |
|-----------|------|-------------|
| Per-turn emoji + rules suffix | `custom-providers/textUtils.py` | `build_turn_suffix()` (appended on the live `PiVoiceLLM` path) |
| Leading-emoji enforcement | `custom-providers/pi_voice/pi_voice.py` | `_enforce_leading_emoji()` |
| Emoji → emotion | `custom-providers/textUtils.py` | `EMOJI_MAP` dict, `get_emotion()` |
| Emotion → face | StackChan firmware | Avatar renderer, expression assets |

## Upstream Emojis Not Used by Dotty

The upstream `EMOJI_MAP` includes additional emojis that Dotty doesn't
use in its 9-emoji set: 😂 😭 😲 😱 😌 😜 🙄 😶 🙂 😳 😉 😎 🤤 😘 😏.
PiVoiceLLM's per-turn suffix constrains responses to the nine emojis above,
and its `ALLOWED_EMOJIS` check replaces any other leading emoji with `😐`.
