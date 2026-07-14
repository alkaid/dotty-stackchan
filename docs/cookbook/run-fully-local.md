---
title: Run Fully Local
description: Run the full stack without cloud model calls by using the Ollama profile in compose.yml.
---

# Run Fully Local

ASR and TTS already run locally. The optional `local-llm` profile starts
Ollama from the same root `compose.yml`, so `dotty-pi` can use local models for
both the normal route and `think_hard`.

## Prerequisites

- An NVIDIA GPU with enough VRAM for the selected model.
- NVIDIA Container Toolkit installed on the Docker host.

## Configure

Add these values to the root `.env`:

```env
COMPOSE_PROFILES=local-llm
DOTTY_PI_BASE_URL=http://ollama:11434/v1
DOTTY_PI_API_KEY=ollama
DOTTY_PI_PROVIDER=ollama
DOTTY_PI_MODEL=qwen3:8b
VOICE_THINKER_MODEL=qwen3:8b
NARRATIVE_LLM_URL=http://ollama:11434/v1
NARRATIVE_MODEL=qwen3:8b
```

The normal and `think_hard` routes can use different Ollama model IDs when
there is enough VRAM to keep or swap both models. `dotty-behaviour` reaches the
same container through `http://ollama:11434`; no host-published port is used for
container-to-container narrative calls.

## Start and pull the model

```bash
make setup

curl -fsS http://127.0.0.1:11434/api/pull \
  -H 'Content-Type: application/json' \
  -d '{"name":"qwen3:8b","stream":false}'
```

No alternate Compose file or manual edit to `data/.config.yaml` is needed.
After the model download, ASR, LLM, and TTS can run without cloud API calls.

See [llm-backends.md](../llm-backends.md) for backend comparisons.
