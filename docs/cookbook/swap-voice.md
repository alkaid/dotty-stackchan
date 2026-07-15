---
title: Swap Voice
description: Change the ChatTTS speaker or switch to Piper/EdgeTTS.
---

# Swap Voice

Three TTS backends are configured in `.config.yaml`. For a curated list
of voices that suit Dotty's persona (with character notes and best-for
hints) see the [Voice Catalog](../voice-catalog.md).

## ChatTTS (default, bilingual)

ChatTTS uses one speaker for Chinese, English, and mixed text. Change the
integer `TTS.ChatTTS.seed` to choose another deterministic speaker, then
restart xiaozhi-server. Its official model weights are CC BY-NC 4.0.

## Piper (local, offline)

The fastest path is the install helper, which downloads any catalog
voice into `models/piper/` and (optionally) rewrites `.config.yaml` for
you:

```bash
make voice-list                                       # see the catalog
make voice-install VOICE=en_US-kristin-medium APPLY=1
docker compose restart xiaozhi-esp32-server
```

Or do it by hand:

1. Download a voice `.onnx` + `.onnx.json` from
   [Piper samples](https://rhasspy.github.io/piper-samples/) into `models/piper/`.

2. Update `.config.yaml`:

```yaml
selected_module:
  TTS: LocalPiper
TTS:
  LocalPiper:
    model_path: models/piper/en_US-lessac-medium.onnx
```

3. Restart: `docker compose restart xiaozhi-esp32-server`

## EdgeTTS (cloud, many voices)

1. List voices: `pip install edge-tts && edge-tts --list-voices | grep en-`
2. Update `.config.yaml`:

```yaml
selected_module:
  TTS: EdgeTTS            # or StreamingEdgeTTS
TTS:
  EdgeTTS:
    voice: en-AU-WilliamNeural    # change to your pick
```

3. Restart: `docker compose restart xiaozhi-esp32-server`

## Tips

- Piper is fully offline with no latency jitter. Prefer it for reliability.
- EdgeTTS has more variety but needs internet and occasionally throttles.
- **English voices only** -- non-English voices produce empty audio. See
  [voice-pipeline.md](../voice-pipeline.md).
