---
title: Troubleshooting
description: Symptom-first lookup table for common and obscure failure modes.
---

# Troubleshooting

Symptom-first lookup table covering common and obscure failure modes. Pair with [quickstart.md](./quickstart.md) for happy-path commands and [voice-pipeline.md](./voice-pipeline.md) for ASR/TTS internals.

---

## No audio / empty TTS response

**Symptom:** The robot appears to process the utterance (logs show ASR text and an LLM response), but no audio plays back. The TTS stage produces zero-length or near-zero-length audio.

**Cause:** Language mismatch between the TTS voice and the response text. The response language follows ASR, but a fixed-language TTS voice cannot synthesize every language. The default local Piper voice is `en_GB-cori-medium`; it does not select another voice automatically.

**Fix:**
1. Check the xiaozhi-server logs for the ASR language tag and LLM response text.
2. Check `data/.config.yaml` to confirm the TTS voice supports that response language.
3. If using Piper, install and select a model for the required language; one Piper model does not provide automatic multilingual routing.
4. If using EdgeTTS, select a voice compatible with the response language.

---

## Reply language does not match the speaker

**Symptom:** ASR detects one language, but the LLM reply uses another language.

**Cause:** The ASR language marker was not propagated to the LLM prompt, or a stale image still contains the retired `ENGLISH ONLY` per-turn constraint.

**Fix:**
1. Confirm `ASR.FunASR.language` is `auto` and the xiaozhi log reports the expected detected language.
2. Confirm the submitted prompt contains `[RESPONSE_LANGUAGE:<tag>]` and the per-turn suffix says `SAME PRIMARY LANGUAGE`.
3. Rebuild the Xiaozhi application image after changing `receiveAudioHandle.py` or `custom-providers/textUtils.py`.
4. Watch the live path while testing: `docker compose logs -f dotty-pi xiaozhi-esp32-server`.

---

## Audio choppy or cutting out

**Symptom:** The robot responds but the audio is choppy, stuttery, or cuts off mid-sentence.

**Possible causes:**

- **WiFi signal.** The robot's ESP32-S3 is 2.4 GHz only. Check RSSI — anything below -70 dBm will cause packet loss on the WebSocket stream. Move the robot closer to the access point, or reduce 2.4 GHz interference.
- **WebSocket abnormal close.** Check xiaozhi-server logs for WS disconnect/reconnect events. The device will silently reconnect, but audio in flight is lost.
- **TTS chunk timing.** If using EdgeTTS (cloud), network jitter between the server and Microsoft's edge servers can cause uneven audio delivery. Switching to Piper (local) eliminates this variable entirely.
- **Server CPU contention.** If other containers are competing for CPU during the ASR or TTS stages, audio processing can stall. Check `docker stats` on the server.

---

## "No bootable app partitions" boot loop after flashing

**Symptom:** After flashing the firmware the screen is frozen or black. A serial monitor shows the bootloader looping on `E boot: No bootable app partitions in the partition table`, or `Image length ... doesn't fit in partition length ...`.

**Cause:** The device was flashed without a partition table, so it kept the layout left by whatever firmware was on it before (the M5Burner StackChan demo, Home Assistant Voice, etc.). That layout doesn't match Dotty's images.

**Fix:** Re-flash with the **full six-file command** in [Quickstart step 1](quickstart.md#1-flash-the-firmware). It writes `bootloader.bin` at `0x0` and `partition-table.bin` at `0x8000` — with those in place the partition offsets line up. If your downloaded release is missing either file, grab the latest `fw-v` release, which ships all six binaries.

---

## Robot not responding after OTA / firmware update

**Symptom:** The robot boots and connects to WiFi, but never responds to voice. May show a face but no indication of listening.

**Fix:**
1. Check the bridge health endpoint: `curl http://<DEPLOY_HOST>:8081/health`. If the bridge is down, run `docker compose restart dotty-bridge`.
2. Check xiaozhi-server logs: `docker compose logs -f xiaozhi-esp32-server` on the server. Look for connection attempts from the robot.
3. Verify the robot's OTA URL hasn't changed. After a firmware update, re-enter `<XIAOZHI_PUBLIC_OTA_BASE_URL>/xiaozhi/ota/` in Advanced Options if needed.
4. Open the browser test page (`repo/main/xiaozhi-server/test/test_page.html`) and point it at `<XIAOZHI_PUBLIC_WS_BASE_URL>/xiaozhi/v1/`. If the browser page works but the robot doesn't, it's a robot-side configuration issue.

---

## ModuleNotFoundError on docker compose up

**Symptom:** The xiaozhi-server container starts but immediately fails with a Python `ModuleNotFoundError` in the logs.

**Cause:** The xiaozhi image is stale, a provider was omitted from the root
Dockerfile, or an upstream image change moved the target package path. Runtime
provider source is not bind-mounted.

**Fix:**
1. Check `docker compose logs xiaozhi-esp32-server` for the exact missing module name.
2. Verify the root Dockerfile copies the provider to the expected path:
   - `custom-providers/pi_voice/` -> `/opt/xiaozhi-esp32-server/core/providers/llm/pi_voice/`
   - `custom-providers/edge_stream/` -> `/opt/xiaozhi-esp32-server/core/providers/tts/edge_stream/`
   - `custom-providers/asr/fun_local.py` -> `/opt/xiaozhi-esp32-server/core/providers/asr/fun_local.py`
3. If the missing module is a Python dependency, add it to the Dockerfile's
   build-time install step.
4. Rebuild and recreate the service:
   `docker compose up -d --build xiaozhi-esp32-server`.

---

## No facial expression change on the robot

**Symptom:** The robot speaks but its face stays neutral. No smile, laugh, or other expression.

**Cause:** The LLM response doesn't start with a supported emoji. The xiaozhi firmware parses the leading emoji to select a face animation. If the first character isn't a recognized emoji, no animation triggers.

**Supported emoji map:**

| Emoji | Expression |
|---|---|
| `😊` | Smile |
| `😆` | Laugh |
| `😢` | Sad |
| `😮` | Surprise |
| `🤔` | Thinking |
| `😠` | Angry |
| `😐` | Neutral |
| `😍` | Love |
| `😴` | Sleepy |

**Fix:**
1. Check the xiaozhi-server logs for the raw LLM response. Two enforcement layers apply: (a) the configured persona prompt (`personas/dotty_voice.md`), (b) the `prompt:` key in `data/.config.yaml`. If the response still has no emoji after both layers, something is fundamentally wrong with the response path.
2. If the response has an emoji but the face doesn't change, it may be an unsupported emoji. Only the nine listed above are mapped to animations.
3. On the `PiVoiceLLM` path the `_ensure_emoji_prefix` fallback in `bridge.py` is not active — emoji enforcement relies entirely on the persona prompt and the `.config.yaml` `prompt:` block.

---

## Servo snaps violently / startling head movement

**Symptom:** The robot's head jerks abruptly when changing position, instead of moving smoothly.

**Cause:** Known limitation. The current firmware does not implement a velocity or acceleration cap on servo commands. The feedback servos move at their maximum speed, which can be startling — especially in a household with kids.

**Workaround:** There is no software workaround at this time. This is tracked as a firmware-level fix. See [hardware.md](./hardware.md#safety-relevant-hardware-facts) for context.

---

## Bridge unreachable / "(no response)" in the robot's voice

**Symptom:** The robot says something like "no response" or goes silent after you speak. xiaozhi-server logs show a failed HTTP call to `dotty-pi` or `dotty-behaviour`.

**Fix:**
1. Check that the stack containers are running: `docker compose ps`
2. Test the bridge dashboard health endpoint: `curl http://<DEPLOY_HOST>:8081/health`
3. For `PiVoiceLLM` failures, check the dotty-pi RPC endpoint: `curl http://127.0.0.1:8091/health`
4. If a service crashes on startup, check its logs: `docker compose logs --tail=100 <service>`

---

## Docker image upgrade breaks things

**Symptom:** After pulling a new xiaozhi-esp32-server image, the container fails to start or behaves differently.

**Fix:**
1. Pin the upstream xiaozhi base image by digest in the root Dockerfile before upgrading.
2. Check the upstream changelog for breaking config changes — `data/.config.yaml` keys may have been renamed or removed.
3. If custom providers fail after an upgrade, the upstream Python module structure may have changed. Check that the Dockerfile copy target paths still exist in the new base image.
4. Roll back to the previous Git revision and run `docker compose up -d --build`.

---

## See also

- [quickstart.md](./quickstart.md) — happy-path setup + common ops + reboot survival.
- [voice-pipeline.md](./voice-pipeline.md) — details on ASR, TTS, VAD tuning.
- [protocols.md](./protocols.md) — WebSocket wire format for debugging.
- [hardware.md](./hardware.md) — hardware specs and safety notes.

Last verified: 2026-05-17.
