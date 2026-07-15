# dotty-bridge — admin dashboard service (FastAPI, served at /ui).
#
# Post-#36 the bridge.py module survived as the dashboard; its voice +
# perception-bus roles moved to dotty-pi / dotty-behaviour. This image
# is the Unraid-resident deploy home for that dashboard, alongside
# dotty-behaviour and dotty-pi.
#
# Layout reminder: bridge.py lives at the repo ROOT (legacy from the
# zeroclaw-bridge era), while bridge/ holds supporting modules
# (dashboard.py, csrf.py, metrics.py, speaker.py, templates/, static/,
# requirements.txt, …). bridge.py also imports textUtils from
# custom-providers/textUtils.py via a sys.path shim, so that shared module
# ships in the image too.
#
# Pinned base — bump deliberately, not via floating tags.
FROM python:3.12-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b
ARG PIP_INDEX_URL

WORKDIR /app

# Install deps first so iterative source edits don't bust the pip layer.
COPY bridge/requirements.txt ./bridge/requirements.txt
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir -i "$PIP_INDEX_URL" -r bridge/requirements.txt; \
    else \
        pip install --no-cache-dir -r bridge/requirements.txt; \
    fi

# Source. bridge.py at /app/bridge.py (its `__file__`-relative resolution
# of bridge/static/, bridge/templates/, and custom-providers/ then lines
# up with the in-container layout).
COPY bridge.py ./bridge.py
COPY bridge ./bridge
COPY custom-providers/textUtils.py ./custom-providers/textUtils.py
COPY personas /app/personas

# Stamp the deployed git SHA so the dashboard version chip reads it
# (the image has no .git checkout, so dashboard.py's git fallback can't
# resolve a version). scripts/deploy-stack.sh passes the HEAD short SHA.
ARG BRIDGE_VERSION=unknown
RUN printf '%s' "$BRIDGE_VERSION" > /app/.bridge-version

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8081

EXPOSE 8081

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2).read(1)" || exit 1

CMD ["python", "bridge.py"]
