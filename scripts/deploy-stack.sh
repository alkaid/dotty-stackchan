#!/usr/bin/env bash
# Deploy one clean Git revision to the Docker host.

set -euo pipefail

DOTTY_HOST="${DOTTY_HOST:?set DOTTY_HOST=user@host}"
REMOTE_DIR="${REMOTE_DIR:-/mnt/user/appdata/dotty-stackchan-src}"
TGZ="$(mktemp -t dotty-stackchan.XXXXXX.tgz)"
trap 'rm -f "$TGZ"' EXIT

cd "$(git rev-parse --show-toplevel)"
DEPLOY_SHA="$(git rev-parse --short HEAD)"
REMOTE_TGZ="/tmp/dotty-stackchan-${DEPLOY_SHA}-$$.tgz"

if ! git diff --quiet || ! git diff --cached --quiet \
    || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    echo "error: deploy-stack.sh requires a clean worktree" >&2
    exit 1
fi

git archive --format=tar.gz --output "$TGZ" HEAD

ssh "$DOTTY_HOST" "mkdir -p '$REMOTE_DIR'"
ssh "$DOTTY_HOST" "cat > '$REMOTE_TGZ'" < "$TGZ"

ssh "$DOTTY_HOST" "
    set -euo pipefail
    trap 'rm -f -- \"$REMOTE_TGZ\"' EXIT
    find '$REMOTE_DIR' -mindepth 1 -maxdepth 1 \
        ! -name .env ! -name data ! -name models ! -name songs ! -name tmp \
        -exec rm -rf -- {} +
    mkdir -p '$REMOTE_DIR/data/bin' '$REMOTE_DIR/models' '$REMOTE_DIR/tmp'
    tar -xzf '$REMOTE_TGZ' -C '$REMOTE_DIR'
    cd '$REMOTE_DIR'
    if [ ! -f .env ]; then
        echo 'error: $REMOTE_DIR/.env does not exist' >&2
        exit 1
    fi
    BRIDGE_VERSION='$DEPLOY_SHA' make setup
    docker compose ps
"
