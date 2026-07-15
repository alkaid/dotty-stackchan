ARG XIAOZHI_BASE_IMAGE=dotty-xiaozhi-base:torch2.7.1-cu128
FROM ${XIAOZHI_BASE_IMAGE}

# Keep the optional ONNX provider runnable even when operators pull a custom
# prebuilt base image that predates the provider.
RUN pip install --no-cache-dir sherpa-onnx==1.13.2

# Custom providers and xiaozhi patches are immutable image content. Runtime
# mounts are reserved for generated config, model weights, state, and firmware.
COPY custom-providers/openai_compat/*.py /opt/xiaozhi-esp32-server/core/providers/llm/openai_compat/
COPY custom-providers/pi_voice/*.py /opt/xiaozhi-esp32-server/core/providers/llm/pi_voice/
COPY custom-providers/edge_stream/edge_stream.py /opt/xiaozhi-esp32-server/core/providers/tts/edge_stream.py
COPY custom-providers/piper_local/piper_local.py /opt/xiaozhi-esp32-server/core/providers/tts/piper_local.py
COPY custom-providers/chattts_local/chattts_local.py /opt/xiaozhi-esp32-server/core/providers/tts/chattts_local.py
COPY custom-providers/asr/fun_local.py /opt/xiaozhi-esp32-server/core/providers/asr/fun_local.py
COPY custom-providers/asr/sensevoice_onnx.py /opt/xiaozhi-esp32-server/core/providers/asr/sensevoice_onnx.py
COPY custom-providers/asr/whisper_local.py /opt/xiaozhi-esp32-server/core/providers/asr/whisper_local.py
COPY custom-providers/textUtils.py /opt/xiaozhi-esp32-server/core/utils/textUtils.py
COPY custom-providers/xiaozhi-patches/device_command.py /opt/xiaozhi-esp32-server/core/utils/device_command.py

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
