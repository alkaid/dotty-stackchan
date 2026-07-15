---
title: Manage Roles
description: Create, edit, activate, and assign voices to independent robot Roles.
---

# Manage Roles

A Role is an independently selectable system prompt plus a saved voice. Roles
do not correspond to Kid Mode, Smart Mode, or robot state.

## Create or edit a Role

Open the Bridge **Role** card and choose **Manage**. From there you can:

- add a named Role;
- edit its system prompt;
- select any saved voice from the Voice dropdown;
- activate it for subsequent turns;
- delete an inactive Role.

At least one Role must remain, and the active Role cannot be deleted. Changes
are atomically saved to:

```text
${DOTTY_BRIDGE_STATE_DIR}/state/roles.json
```

Role activation takes effect on the next voice turn without restarting a
container. The assigned voice is resolved again for every spoken sentence.

## Initialization

When `roles.json` does not exist, the first Role is named `Dotty` and uses
`personas/default.md` plus the default ChatTTS voice. The Markdown file is only
an initialization fallback; it does not overwrite saved Roles.

## Modes

Kid Mode appends its safety prompt sandwich and enables output filtering around
the active Role. It never replaces the Role prompt. Smart Mode remains an
independent sticky toggle and does not select a Role.

Keep the emoji-leader instruction in Role prompts so the firmware can animate
the face. PiVoiceLLM also guarantees a neutral emoji fallback.

Generic providers still use `LLM.OpenAICompat.persona_file` and the top-level
`prompt:` block in `data/.config.yaml`.
