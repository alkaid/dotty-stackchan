# dotty-behaviour — the behaviour daemon for Dotty (Unraid-resident
# successor to the RPi-hosted zeroclaw-bridge).
#
# Hosts the perception event bus, 9 consumers, vision/audio explain
# endpoints, dashboard, proactive greeter, and per-device caches.
# Replaces bridge.py + bridge/* per the dotty-behaviour rehoming track
# of #36.
#
# Pinned base — bump deliberately, not via floating tags.
FROM python:3.12-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b
ARG PIP_INDEX_URL

WORKDIR /app

COPY requirements.txt ./
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

# Flat layout — top-level modules + subpackages, no outer Python package.
COPY config.py main.py role_identity.py ./
COPY perception ./perception
COPY routes ./routes
COPY dispatch ./dispatch
COPY vision ./vision
COPY consumers ./consumers
COPY greeter ./greeter
COPY household ./household
COPY logs ./logs
COPY calendar_ ./calendar_

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DOTTY_BEHAVIOUR_HOST=0.0.0.0 \
    DOTTY_BEHAVIOUR_PORT=8090

EXPOSE 8090

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=2).read(1)" || exit 1

CMD ["python", "-m", "uvicorn", "main:app", \
     "--host", "0.0.0.0", "--port", "8090", "--log-level", "info"]
