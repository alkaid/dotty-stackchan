---
title: Add a New Face Emoji
description: Add a new emoji to the expression system so the robot can show it.
---

# Add a New Face Emoji

The robot's face is driven by the leading emoji in each LLM reply.

## 1. Update the allowed emoji lists

**`custom-providers/textUtils.py`** -- edit `ALLOWED_EMOJIS`:

```python
ALLOWED_EMOJIS = ("😊", "😆", "😢", "😮", "🤔", "😠", "😐", "😍", "😴", "🥳")
```

Both `PiVoiceLLM` and `OpenAICompat` import this shared list.

## 2. Update the suffix prompt (rule 2)

In `custom-providers/textUtils.py`, add the emoji to rule 2 in `_BASE_SUFFIX`:

```
2. First character MUST be one of: 😊 😆 😢 😮 🤔 😠 😐 😍 😴 🥳
```

Also update Role prompts in Bridge when they list the set. Update
`personas/default.md` only when the first-Role initialization should change, and
the `prompt:` block in `data/.config.yaml` when generic providers list the set.

## 3. Check firmware support

The firmware must map the emoji to a face animation. If it does not
recognize the emoji, the face stays on the previous expression (no crash).
See [protocols.md](../protocols.md) and the upstream
[emotion docs](https://xiaozhi.dev/en/docs/development/emotion/).

## 4. Restart

```bash
docker compose up -d --build xiaozhi-esp32-server dotty-pi dotty-bridge
```

Current set: 😊 smile, 😆 laugh, 😢 sad, 😮 surprise, 🤔 thinking,
😠 angry, 😐 neutral, 😍 love, 😴 sleepy.
