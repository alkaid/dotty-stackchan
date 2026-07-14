# Pinned 2026-05-17 from :server_0.9.3.
FROM ghcr.io/xinnan-tech/xiaozhi-esp32-server@sha256:3accd82a7d1a6c01c58f32f6199400a11655d607780b80219493123dedbb347e

ARG PIP_INDEX_URL

RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir -i "$PIP_INDEX_URL" piper-tts scipy numpy mido faster-whisper; \
    else \
        pip install --no-cache-dir piper-tts scipy numpy mido faster-whisper; \
    fi

RUN apt-get update \
    && apt-get install -y --no-install-recommends fluidsynth fluid-soundfont-gm \
    && rm -rf /var/lib/apt/lists/*

# Custom providers and xiaozhi patches are immutable image content. Runtime
# mounts are reserved for generated config, model weights, state, and firmware.
COPY custom-providers/openai_compat/*.py /opt/xiaozhi-esp32-server/core/providers/llm/openai_compat/
COPY custom-providers/pi_voice/*.py /opt/xiaozhi-esp32-server/core/providers/llm/pi_voice/
COPY custom-providers/edge_stream/edge_stream.py /opt/xiaozhi-esp32-server/core/providers/tts/edge_stream.py
COPY custom-providers/piper_local/piper_local.py /opt/xiaozhi-esp32-server/core/providers/tts/piper_local.py
COPY custom-providers/asr/fun_local.py /opt/xiaozhi-esp32-server/core/providers/asr/fun_local.py
COPY custom-providers/asr/whisper_local.py /opt/xiaozhi-esp32-server/core/providers/asr/whisper_local.py
COPY custom-providers/textUtils.py /opt/xiaozhi-esp32-server/core/utils/textUtils.py

COPY receiveAudioHandle.py /opt/xiaozhi-esp32-server/core/handle/receiveAudioHandle.py
COPY dances.py /opt/xiaozhi-esp32-server/core/handle/dances.py
COPY custom-providers/xiaozhi-patches/textMessageHandlerRegistry.py /opt/xiaozhi-esp32-server/core/handle/textMessageHandlerRegistry.py
COPY custom-providers/xiaozhi-patches/ota_handler.py /opt/xiaozhi-esp32-server/core/api/ota_handler.py
COPY custom-providers/xiaozhi-patches/portal_bridge.py /opt/xiaozhi-esp32-server/core/portal_bridge.py
COPY custom-providers/xiaozhi-patches/websocket_server.py /opt/xiaozhi-esp32-server/core/websocket_server.py
COPY custom-providers/xiaozhi-patches/http_server.py /opt/xiaozhi-esp32-server/core/http_server.py

COPY personas /opt/xiaozhi-esp32-server/personas
COPY songs /opt/xiaozhi-esp32-server/config/assets/songs
COPY bridge/assets/purr.opus /opt/xiaozhi-esp32-server/config/assets/purr.opus

HEALTHCHECK --interval=15s --timeout=4s --start-period=20s --retries=4 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8003/xiaozhi/ota/', timeout=3).read(1)" || exit 1
