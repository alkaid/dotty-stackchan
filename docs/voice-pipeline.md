---
title: Voice Pipeline
description: xiaozhi-esp32-server pipeline stages -- VAD, ASR, LLM proxy, and TTS.
---

# Voice pipeline — xiaozhi-esp32-server

## TL;DR

- **Server** is `xinnan-tech/xiaozhi-esp32-server` running in Docker on a Linux host. Plugin-based: each of VAD, ASR, LLM, TTS, Memory, Intent is a swappable provider picked via `data/.config.yaml`'s `selected_module:` block.
- Our live pipeline: **SileroVAD** (speech-end) → **FunASR SenseVoiceSmall** (`auto` language, CUDA when available), opt-in **SenseVoiceOnnx** (int8, no PyTorch), or manual **WhisperLocal** → **PiVoiceLLM** custom provider (current default; HTTP RPC to the `dotty-pi` container) or **OpenAICompat** → bilingual **ChatTTS** (CUDA when available; Piper and EdgeTTS fallbacks).
- The xiaozhi container also runs a perception relay (`EventTextMessageHandler`) that forwards firmware `face_detected` / `face_lost` / `sound_event` / `state_changed` frames to `dotty-behaviour`'s `/api/perception/event`.
- **Emotion** is not a pipeline stage — it's extracted post-hoc from the LLM's emoji prefix and emitted as a separate WS frame. See [protocols.md](./protocols.md#emotion-protocol).
- Custom providers are copied into the image by the root Dockerfile at `/opt/xiaozhi-esp32-server/core/providers/{asr,tts,llm}/…`.
- **Lots of upstream features are unused** — voiceprint speaker-ID, VLLM vision, knowledge-base RAG, PowerMem, multi-user routing. See [latent-capabilities.md](./latent-capabilities.md#voice-pipeline-unused).

## Provider catalog (upstream)

From the `xinnan-tech/xiaozhi-esp32-server` README (see [references.md](./references.md#voice)):

| Stage | Provider options |
|---|---|
| **VAD** | SileroVAD (local, free) |
| **ASR (local)** | FunASR, SherpaASR, SenseVoiceOnnx (our opt-in no-torch int8 sherpa-onnx provider, #135) |
| **ASR (cloud)** | FunASRServer, Volcano Engine, iFLYTEK, Tencent Cloud, Alibaba Cloud, Baidu Cloud, OpenAI |
| **LLM** | OpenAI-compatible (Alibaba Bailian, Volcano, DeepSeek, Zhipu, Gemini, iFLYTEK), Ollama, Dify, FastGPT, Coze, Xinference, HomeAssistant |
| **VLLM** (vision) | Alibaba Bailian, Zhipu ChatGLM |
| **TTS (local)** | FishSpeech, GPT_SOVITS_V2/V3, Index-TTS, PaddleSpeech |
| **TTS (cloud)** | EdgeTTS, iFLYTEK, Volcano, Tencent, Alibaba, CosyVoice, OpenAI TTS |
| **Memory** | mem0ai, PowerMem, mem_local_short, nomem |
| **Intent** | intent_llm, function_call, nointent |
| **Knowledge base** | RagFlow |

**What we use:** SileroVAD + FunASR (patched) + custom PiVoiceLLM + ChatTTS (Piper or EdgeTTS on rollback). Every other row is unused.

## Our deployed stages

### VAD — SileroVAD

SileroVAD v6.x, JIT model ~2 MB, runs on the server CPU, <1 ms per chunk in practice. 8 kHz or 16 kHz sample rates supported; xiaozhi-server uses 16 kHz to match the device Opus stream.

Tunables live under `VAD.SileroVAD.*` in `data/.config.yaml`:

| Tunable | Meaning | Our value |
|---|---|---|
| `min_silence_duration_ms` | Silence length after speech to call it "end" | 700 |
| `threshold` | Speech-confidence threshold (0–1) | upstream default |
| `speech_pad_ms` | Extra audio captured either side of detected speech | upstream default |
| `neg_threshold` | Below-this-probability = definitely silence | upstream default |

Known limit: **whispered speech under-triggers**. If the robot stops responding to a quieter speaker, this is the first thing to check.

### ASR — FunASR SenseVoiceSmall (patched)

Model: `FunAudioLLM/SenseVoiceSmall` on HuggingFace. From the model card:

- Supports 50+ languages total; the five *tested* languages are Mandarin (`zh`), Cantonese (`yue`), English (`en`), Japanese (`ja`), Korean (`ko`). Plus `nospeech`.
- Parameter count ~= Whisper-Small.
- **70 ms to process 10 s of audio — 15× faster than Whisper-Large, 5× faster than Whisper-Small.**
- Non-autoregressive end-to-end architecture (fast, no decode loop).

**Our patch.** The repo-hosted `fun_local.py` reads both `language` and `device` from `ASR.FunASR` in `.config.yaml`. `ASR_LANGUAGE=auto` is the default for mixed Chinese/English input; deployments that intentionally accept one language can pin it. `device=cuda` is normalized to `cuda:0` and passed to FunASR's `AutoModel`.

Deployment: mounted as a file-level override at `/opt/xiaozhi-esp32-server/core/providers/asr/fun_local.py`.

**Model assets.** `make fetch-models` downloads the five files SenseVoiceSmall needs into `models/SenseVoiceSmall/`: `model.pt`, `config.yaml`, `configuration.json`, `am.mvn`, and the SentencePiece tokenizer `chn_jpn_yue_eng_ko_spectok.bpe.model`. The tokenizer asset is load-bearing — without it funasr fails to build with `sentencepiece … bpemodel=None` and the container crash-loops (issue #124). `make doctor` size-checks each of these.

### ASR — SenseVoiceOnnx (sherpa-onnx int8, opt-in) (#135)

Same SenseVoiceSmall model family as the FunASR provider above, but run through the **sherpa-onnx / ONNX Runtime** int8 export instead of FunASR's PyTorch path — **no `torch` dependency**, and the on-disk model is ~230 MB versus the ~900 MB `model.pt`. This makes it the better fit for Pi-class / low-RAM hosts. It coexists with FunASR, which stays the no-GPU default; flipping the default to this provider is a separate, benchmark-gated follow-up (#135).

- **Select:** `selected_module.ASR: SenseVoiceOnnx` in `.config.yaml` (type `sensevoice_onnx`).
- **Provider:** mounted as a file-level override at `/opt/xiaozhi-esp32-server/core/providers/asr/sensevoice_onnx.py`.
- **Model assets:** `make fetch-models` downloads `model.int8.onnx` + `tokens.txt` into `models/SenseVoiceSmall-onnx/`; `make doctor` size-checks them.
- **Language:** `language: en` is preserved — sherpa-onnx takes the language natively, so no English-pin patch is needed.
- **RTF (CPU):** measured on the Docker host (Intel i5-3570, 4-core, 2012-era — *weaker* than the Pi-5 target, so a conservative floor) on a 7.15 s English utterance: **RTF ≈ 0.12 at `num_threads: 2`** (~8× real-time), 0.23 at 1 thread. Comfortably real-time without a GPU. (Transcript verified correct.) The Pi 5 / RK3588-class A76 number the issue targets (~0.05–0.10) is still pending and gates the eventual default-flip; the provider logs an `ASR-RTF` line per utterance so the on-target figure can be read straight from production logs after deploy.

### LLM — provider selected at a time

Pick one via `selected_module.LLM` in `.config.yaml`. The default is `PiVoiceLLM`; `OpenAICompat` is the alternate. See [llm-backends.md](./llm-backends.md) for the full comparison.

#### `PiVoiceLLM` (default)

Custom provider at `custom-providers/pi_voice/`, baked into `/opt/xiaozhi-esp32-server/core/providers/llm/pi_voice/`. It doesn't run a model itself; it hands each voice turn to the **`dotty-pi` container** over HTTP RPC. The pi agent owns the conversation loop (`DOTTY_PI_MODEL`, default `dotty-simple`) and the seven `dotty-pi-ext` voice tools (`memory_lookup`, `remember`, `recall_person`, `remember_person`, `think_hard`, `take_photo`, `play_song`); only TTS-bound text streams back. See [brain.md](./brain.md).

#### `OpenAICompat` (alternate)

Custom provider at `custom-providers/openai_compat/openai_compat.py`. Talks directly to any OpenAI-compatible `/v1/chat/completions` endpoint — a cloud provider (OpenAI, OpenRouter) or a local llama-swap instance. Stateless and tool-less: no memory and no voice tools, so it's a chitchat-only alternate to the full `PiVoiceLLM` path. See [llm-backends.md](./llm-backends.md).

### Perception relay (xiaozhi → dotty-behaviour)

`custom-providers/xiaozhi-patches/textMessageHandlerRegistry.py` adds an `EventTextMessageHandler` that intercepts firmware `event` frames over the WS and POSTs each one to `dotty-behaviour`'s `/api/perception/event`. This is what feeds the `dotty-behaviour` perception consumers — see [architecture.md](./architecture.md#perception-event-bus).

### TTS — ChatTTS (active) / LocalPiper and EdgeTTS (rollback)

**Active: ChatTTS local.**

- One model handles Chinese, English, and mixed-language sentences without a
  language selector. It outputs 24 kHz PCM, which the provider incrementally
  converts into the device protocol's 60 ms Opus frames.
- `device: auto` selects CUDA when available and CPU otherwise. On the reference
  RTX 5070 Ti, the model uses about 1.14 GB peak VRAM; measured synthesis was
  0.59 s for a 2.20 s English sample and 1.55 s for the first 2.19 s Chinese
  sample, including first-run warm-up.
- The speaker is stable across restarts through `TTS.ChatTTS.seed`. Model files
  live under `models/chattts/` and are SHA-256 validated at load time.
- License: code AGPLv3+; official model weights CC BY-NC 4.0. This configuration
  is for personal, non-commercial use.

**Rollback: Piper local.**
- Engine: piper-tts 1.4.2 on ONNX runtime.
- Voice: `en_GB-cori-medium` (Piper "medium" quality tier, British English).
- Voice files (~63 MB total): `.onnx` + `.onnx.json` sibling, fetched from `huggingface.co/rhasspy/piper-voices`.
- Measured on a modest i5-3570 Docker host: 0.22 s synth for 2.8 s of audio — 12.7× realtime.
- Piper remains installed in `xiaozhi-esp32-server-chattts:local` for config-only rollback.
- Runs fully offline — no external HTTP calls.
- **License note (unverified).** Piper voices are MIT-licensed as a repo, but individual voices carry their own upstream license depending on training data. Verify the Cori-specific voice license before redistributing your robot's recordings beyond personal use. Starting point: [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices).

**Rollback: EdgeTTS (`type: edge`).**
- Uses Microsoft's unofficial Edge "Read aloud" endpoint (reverse-engineered; no official API key).
- Voice: `en-US-AnaNeural` (our previous child-sounding voice).
- Streaming supported; non-streaming is the default that ships with the upstream image.
- **Known failure mode**: returns silent audio when the input text is not in the voice's language. This is the symptom we chased for the Qwen-Chinese-leak bug — an `en-US-*` voice with Chinese text = empty buffer, not an error.
- **Risk**: MS can rate-limit, change endpoints, or kill the product. Keep an eye on [rany2/edge-tts](https://github.com/rany2/edge-tts) for ecosystem signals.

One-line rollback command is in `../README.md` → "Common ops".

## Custom provider mechanism

xiaozhi-server discovers providers by module path. `selected_module.TTS: ChatTTS`
uses `TTS.ChatTTS.type: chattts_local`, which resolves to
`core/providers/tts/chattts_local.py`. Provider source is baked into the image;
model weights remain a read-only runtime mount.

**Implication for upgrades.** When the upstream image changes, the mount still works as long as:
1. The provider-directory convention hasn't changed.
2. The provider base-class signature hasn't changed.

Both of those do occasionally break on upstream major bumps. Pin the image tag in `compose.yml` and test an upgrade on a branch before merging.

## Emotion handling inside the pipeline

xiaozhi-server doesn't run an emotion classifier. It **strips the leading emoji** from the LLM response text, maps it to an emotion identifier from the Xiaozhi emotion catalog (see [protocols.md](./protocols.md#emotion-protocol)), and emits two separate WS frames to the device:
- `{"type":"llm","emotion":"…","text":"😊"}`
- `{"type":"tts","state":"sentence_start","text":"Sure, the weather…"}`

The TTS provider receives text **with the emoji already stripped**. The device receives the emotion and sets the face animation; the speaker plays the clean text.

**Wire consequence**: the text reaching emotion dispatch must begin with an allowed emoji. On PiVoiceLLM, the per-turn suffix requests one and `_enforce_leading_emoji()` guarantees an allowed prefix, using neutral `😐` when the model omits it. Persona files and `.config.yaml`'s system prompt are not forwarded on this path. See [protocols.md](./protocols.md#emotion-protocol).

**Note — we don't use SenseVoice's built-in SER.** The model card advertises speech emotion recognition and audio-event detection (bgm / applause / laughter / crying / coughing / sneezing). xiaozhi-server's FunASR provider returns only the transcription text; the SER/AED fields aren't piped through. That's a genuine latent capability — see [latent-capabilities.md](./latent-capabilities.md#voice-pipeline-unused).

## See also

- [protocols.md](./protocols.md#xiaozhi-websocket) — how audio gets in and out (and the `/api/perception/event` wire format).
- [brain.md](./brain.md) — the pi agent, model matrix, and dotty-pi-ext voice tools.
- [latent-capabilities.md](./latent-capabilities.md#voice-pipeline-unused) — unused upstream features.
- [references.md](./references.md#voice) — all upstream voice-stack links.

Last verified: 2026-05-17.
