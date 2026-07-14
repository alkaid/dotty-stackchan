---
title: Quickstart
description: From zero to first voice turn in 15 minutes.
---

# Quickstart

Get Dotty talking in 15 minutes. This is the single opinionated happy
path -- see [SETUP.md](SETUP.md) for build-from-source and
alternative configurations.

## What you need

| Item | Notes |
|------|-------|
| **M5Stack CoreS3 + StackChan servo kit** | The robot. See [hardware.md](hardware.md) for details. |
| **Linux or macOS host with Docker** | Runs all four server-side containers. Any distro works. **No GPU required** for the default stack — see [Server hardware](#server-hardware) below. |
| **2.4 GHz WiFi** | The ESP32-S3 does not support 5 GHz. |

### Server hardware

The default stack is **CPU-only — no GPU is required.** The voice pipeline
ships with [FunASR](https://github.com/modelscope/FunASR) SenseVoiceSmall for
ASR and [Piper](https://github.com/rhasspy/piper) (`LocalPiper`) for TTS, both
of which run comfortably on a modern multi-core x86-64 or Apple Silicon CPU.

| Scenario | Needs a GPU? | Notes |
|----------|--------------|-------|
| **Default** (FunASR ASR + LocalPiper TTS + a **cloud** LLM via OpenRouter/OpenAI-compatible key) | No | Any 64-bit Linux/macOS host with Docker and ~4 GB free RAM. This is the Quickstart happy path. |
| `WhisperLocal` ASR instead of FunASR | Yes | `faster-whisper` float16 needs CUDA. Set the ASR and NVIDIA runtime variables shown in [deployment.md](deployment.md#asr-配置). |
| **Self-hosting the LLM** locally (Ollama / llama-swap instead of a cloud key) | Recommended | VRAM scales with the model — roughly ~5 GB for an 8B model, ~18 GB for a 30B. See [run-fully-local.md](cookbook/run-fully-local.md) and [llama-swap-concurrent-models.md](cookbook/llama-swap-concurrent-models.md). CPU-only inference works but is slow. |

`make setup` reads `.env`, renders `data/.config.yaml`, downloads model
weights, and builds the tracked `compose.yml`. There is no interactive wizard.
The portable default is `FunASR/cpu/int8`; GPU ASR is an explicit `.env` choice.

## 1. Flash the firmware

Download the latest release from
[GitHub Releases](https://github.com/BrettKinny/dotty-stackchan/releases)
(look for a tag starting with `fw-v`). Grab all six binaries:
`bootloader.bin`, `partition-table.bin`, `ota_data_initial.bin`,
`stack-chan.bin`, `generated_assets.bin`, and `human_face_detect.espdl`.

Install esptool and flash over USB-C:

```bash
pip install esptool

python -m esptool --chip esp32s3 -b 460800 \
  --before default_reset --after hard_reset \
  write_flash --flash_mode dio --flash_size 16MB --flash_freq 80m \
  0x0      bootloader.bin \
  0x8000   partition-table.bin \
  0xd000   ota_data_initial.bin \
  0x20000  stack-chan.bin \
  0xa60000 generated_assets.bin \
  0xe70000 human_face_detect.espdl
```

Flashing the bootloader (`0x0`) and partition table (`0x8000`) is
**required** — skip them and the device keeps whatever partition layout
the previous firmware left behind. That layout won't match these
images, and the robot boot-loops on `No bootable app partitions`.

Verify checksums against `SHA256SUMS.txt` in the release if desired.

## 2. Clone the repo

```bash
git clone --recursive https://github.com/BrettKinny/dotty-stackchan.git
cd dotty-stackchan
```

## 3. Configure

```bash
cp .env.example .env
```

Edit `.env` and set the required public endpoint, admin-token, and sub2api
values: `XIAOZHI_PUBLIC_WS_BASE_URL`, `XIAOZHI_PUBLIC_OTA_BASE_URL`,
`DOTTY_ADMIN_TOKEN`, `DOTTY_PI_BASE_URL`, `DOTTY_PI_API_KEY`,
`DOTTY_PI_MODEL`, and `VOICE_THINKER_MODEL`.
You can skip the cloud key only if you're running fully local — either
via Ollama (single binary, simple) or via llama-swap (Docker, supports
multiple resident models). See
[cookbook/run-fully-local.md](cookbook/run-fully-local.md) and
[cookbook/llama-swap-concurrent-models.md](cookbook/llama-swap-concurrent-models.md).

The rendered `data/.config.yaml` selects `PiVoiceLLM` as the default
LLM provider, which runs the `dotty-pi` container on the same Docker
host. One alternate provider, `OpenAICompat`, is available via
`selected_module.LLM` if you intentionally switch away from dotty-pi.

## 4. Run setup

```bash
make setup
```

`make setup` validates `.env`, checks the selected container runtime,
downloads the ASR and TTS models, renders `data/.config.yaml`, and builds and
starts the containers. If a required value is missing or still contains a
placeholder, setup stops before starting anything.

Verify everything is healthy:

```bash
make doctor
```

All checks should pass (green). If any fail, see
[troubleshooting.md](troubleshooting.md).

## 5. Bring up the containers

`make setup` already starts all four server-side services. For later
restarts or updates, use the root compose file:

```bash
docker compose up -d --build
```

No separate host, no systemd bridge unit, no SSH to a second machine.

## 6. Connect the robot

1. Power on the robot (USB-C or battery).
2. On the device screen, navigate to **Settings > Advanced Options**.
3. Enter the OTA URL: `<XIAOZHI_PUBLIC_OTA_BASE_URL>/xiaozhi/ota/`
4. The robot connects via WebSocket and shows a face.

## 7. First voice turn

Tap the screen to enter voice mode and say "Hello Dotty!"

You should see:

| LED colour | State |
|------------|-------|
| Green | Listening -- you are speaking |
| Orange | Thinking -- waiting for LLM response |
| Blue | Talking -- playing the response |

The face expression changes to match the response emoji. First-turn
latency is roughly 5 seconds, dominated by the LLM round-trip.

## Next steps

- [Change the persona](cookbook/change-persona.md) -- give Dotty a different personality.
- [Swap the voice](cookbook/swap-voice.md) -- try a different TTS voice.
- [Run fully local](cookbook/run-fully-local.md) -- Ollama compose profile, zero cloud dependencies.
- [Run two local models concurrently](cookbook/llama-swap-concurrent-models.md) -- keep a small voice model and a big "think" model both resident via llama-swap's matrix DSL.
- [Disable Kid Mode](cookbook/disable-kid-mode.md) -- for unrestricted use.
- [Architecture overview](architecture.md) -- full data flow.
- [Kid Mode](kid-mode.md) -- on by default, what it enforces.

---

## Placeholders

This repo uses placeholders in place of real IPs, secrets, model ids, and filesystem paths. Put deployment values in `.env` before running `make setup`:

| Placeholder | Meaning |
|---|---|
| `<XIAOZHI_PUBLIC_WS_BASE_URL>` | Client-visible WebSocket origin including `ws://` or `wss://`, host, and optional port; no path. |
| `<XIAOZHI_PUBLIC_OTA_BASE_URL>` | Client-visible OTA origin including `http://` or `https://`, host, and optional port; no path. |
| `<DEPLOY_HOST>` | LAN IP or DNS name of the Docker host, used for SSH, dashboard access, and host-side diagnostics. |
| `<XIAOZHI_USER>` | SSH user for the server (whatever your distro defaults to: `root`, `ubuntu`, `dietpi`, etc.). |
| `<DEPLOY_HOSTNAME>` | Hostname or Tailscale name of the server (optional, IP works for everything). |
| `<XIAOZHI_PATH>` | Path on the server where you clone/install this repo (e.g. `/opt/xiaozhi-server/` or `/srv/xiaozhi-server/`). |
| `<YOUR_NAME>` | Your name / org, used in the persona prompt rendered to `data/.config.yaml`. |
| `<ROBOT_NAME>` | Name the robot introduces itself as, rendered to `data/.config.yaml`. |

Container ports `8000/8003` stay fixed. Published Compose ports may differ,
and public endpoints may point at a gateway instead of those published ports.

Files you will definitely need to edit before first run:

- `.env` — set public endpoint bases, published ports, admin token, sub2api URL/key, and model ids.
- `.config.yaml.template` — optional only if you want to customise the rendered persona prompt.

---

## Deployment layout

All four containers run on the single Docker host (`<DEPLOY_HOST>`):

| Container | Purpose | Port |
|---|---|---|
| `xiaozhi-esp32-server` | Voice pipeline: ASR, TTS, WebSocket to StackChan | 8000 (WS), 8003 (OTA/HTTP) |
| `dotty-pi` | pi coding agent, the voice-tool brain | internal `8091`, host-local `127.0.0.1:8091` |
| `dotty-behaviour` | Perception bus + ambient consumers + calendar | 8090 |
| `dotty-bridge` | Admin dashboard (`bridge.py`) | 8081 |

Runtime mounts for `xiaozhi-esp32-server`:

| Host path | Container path | Purpose |
|---|---|---|
| `data/.config.yaml` | `/opt/xiaozhi-esp32-server/data/.config.yaml` | Config override (read-only mount) |
| `models/SenseVoiceSmall/` | `/opt/xiaozhi-esp32-server/models/SenseVoiceSmall/` | ASR weights |
| `models/piper/` | `/opt/xiaozhi-esp32-server/models/piper/` | Piper TTS voice models (`.onnx` + `.json`) |
| `models/whisper-small.en-ct2/` | `/opt/xiaozhi-esp32-server/models/whisper-small.en-ct2/` | Optional Whisper ASR weights |
| `data/bin/` | `/opt/xiaozhi-esp32-server/data/bin/` | OTA firmware files |
| `tmp/` | `/opt/xiaozhi-esp32-server/tmp/` | Scratch |

Custom providers, xiaozhi patches, personas, and built-in assets are copied
into the image by the root Dockerfile and are not mounted from the checkout.

The full file inventory lives in [architecture.md](./architecture.md#deployment-files-this-repo).

---

## Endpoints

| What | URL | Who calls it |
|---|---|---|
| OTA (enter into StackChan settings) | `<XIAOZHI_PUBLIC_OTA_BASE_URL>/xiaozhi/ota/` | The robot on boot |
| WebSocket | `<XIAOZHI_PUBLIC_WS_BASE_URL>/xiaozhi/v1/` | The robot after OTA handshake |
| Perception / ambient events | `http://dotty-behaviour:8090` | Internal Compose DNS |
| Admin dashboard | `http://<DEPLOY_HOST>:8081/ui` | Humans (LAN-only HTMX UI) |
| Bridge health | `http://<DEPLOY_HOST>:8081/health` | Humans, monitoring |

---

## Reboot survival

All containers use `restart: unless-stopped`. Ensure dockerd starts at
boot on your distro. Use `docker compose restart <service>` for transient
restarts rather than `docker compose down`.

---

## Common operations

```bash
# Tail xiaozhi-server logs (voice pipeline)
ssh <XIAOZHI_USER>@<DEPLOY_HOST> 'cd <XIAOZHI_PATH> && docker compose logs -f xiaozhi-esp32-server'

# Tail dotty-behaviour logs (perception + dashboard)
ssh <XIAOZHI_USER>@<DEPLOY_HOST> 'cd <XIAOZHI_PATH> && docker compose logs -f dotty-behaviour'

# Tail dotty-pi logs (brain container)
ssh <XIAOZHI_USER>@<DEPLOY_HOST> 'cd <XIAOZHI_PATH> && docker compose logs -f dotty-pi'

# Restart voice pipeline after config change
ssh <XIAOZHI_USER>@<DEPLOY_HOST> 'cd <XIAOZHI_PATH> && docker compose restart xiaozhi-esp32-server'

# Admin dashboard
open http://<DEPLOY_HOST>:8081/ui

# Bridge health
curl http://<DEPLOY_HOST>:8081/health
```

### Changing voice
The default TTS is `LocalPiper` (offline, runs inside the container). To change the Piper voice, edit `TTS.LocalPiper.voice` and the corresponding `model_path` / `config_path` in `data/.config.yaml`. To switch to cloud EdgeTTS instead, set `selected_module.TTS: EdgeTTS` and edit `TTS.EdgeTTS.voice` (any Microsoft Edge Neural voice ID works, e.g. `en-US-AvaNeural`). Restart the container after changes.

### Changing persona (the robot's personality)
Edit `personas/dotty_voice.md`, then rebuild `dotty-pi` because persona files
are image content: `docker compose up -d --build dotty-pi`. The `prompt:` key
in `data/.config.yaml` remains the generic-provider prompt. Full instructions:
[cookbook/change-persona.md](cookbook/change-persona.md).

### Changing VAD sensitivity
`VAD.SileroVAD.min_silence_duration_ms` in `data/.config.yaml`. Default: 700 ms. Lower = cuts off quicker. Higher = waits longer for slow speakers.

### Changing the LLM model
For the default `PiVoiceLLM` path, set `DOTTY_PI_MODEL` for normal turns and
`VOICE_THINKER_MODEL` for `think_hard` in `.env`, then run
`docker compose up -d dotty-pi`. For `OpenAICompat`, edit its model, URL, or
API key in `data/.config.yaml`, then restart `xiaozhi-esp32-server`. Smart mode
does not swap either backend model.

---

## Troubleshooting

```bash
make doctor          # health checks
make logs            # tail server logs
curl http://<DEPLOY_HOST>:8081/health   # test the bridge/dashboard
```

See [troubleshooting.md](troubleshooting.md) for common issues.
