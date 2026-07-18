---
title: Manage Voices
description: Save and preview ChatTTS or EdgeTTS profiles and assign them to Roles.
---

# Manage Voices

Open the Bridge **Voice** card and choose **Manage**. Voice profiles are named,
reusable configurations saved in:

```text
${DOTTY_BRIDGE_STATE_DIR}/state/voices.json
```

Each Role selects one saved voice. A voice that is still assigned to a Role
cannot be deleted.

## Preview

Edit the Preview text and press **Preview**. Bridge sends the unsaved form
values to the connected robot, which speaks the text without changing the
saved profile. Preview requires an online robot.

## ChatTTS

ChatTTS handles Chinese, English, and mixed text locally. Profiles expose:

- deterministic speaker `seed`;
- `temperature`, `top_p`, and `top_k` sampling;
- ChatTTS `refine_prompt` and `code_prompt` controls.

ChatTTS remains available for offline bilingual synthesis. New installations
instead initialize with the EdgeTTS profile described below.

## EdgeTTS

EdgeTTS uses Microsoft's cloud Read Aloud service. Profiles expose:

- the named voice, such as `zh-CN-XiaoxiaoNeural`;
- rate and volume percentages;
- pitch in Hz.

Edge voices are language-specific and require internet access. The Bridge form
includes a small curated list but also accepts another valid Edge voice name.
The initialized default is `zh-CN-XiaoxiaoNeural`, a warm Mandarin female
voice, with neutral rate, volume, and pitch settings.

## Runtime behavior

`selected_module.TTS: RoleTTS` is a combined provider. Before each sentence it
reads the active Role's `voice_id`, then uses either ChatTTS or EdgeTTS. Role and
voice changes therefore need no xiaozhi restart.

Piper remains available as a manual fallback through `selected_module.TTS:
LocalPiper`, but it bypasses the Role voice library and requires a server
restart. See the [Voice Catalog](../voice-catalog.md) for Piper models and Edge
voice names.
