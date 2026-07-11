#!/usr/bin/env bash
# UAT session log capture — companion to docs/uat-runbook.md.
#
# `start`: background-tails the four service containers on the Docker host
# (timestamped) into uat-sessions/<date>/logs/, writes a session manifest,
# and prints the serial-monitor command to run in a second terminal.
# `stop`: kills the tails, pulls the day's NDJSON logs out of the
# containers, and snapshots the health/perception endpoints.
#
# Usage:
#   XIAOZHI_SSH=<XIAOZHI_USER>@<XIAOZHI_HOST> scripts/uat-capture.sh start
#   XIAOZHI_SSH=<XIAOZHI_USER>@<XIAOZHI_HOST> scripts/uat-capture.sh stop
#   scripts/uat-capture.sh start --dry-run     # print commands, run nothing
#
# Environment overrides:
#   XIAOZHI_SSH    SSH user@host for the Docker host (required unless --dry-run)
#   XIAOZHI_HOST   LAN host for HTTP snapshots (default: host part of XIAOZHI_SSH)
#   SESSION_DIR    Session directory (default: uat-sessions/<YYYY-MM-DD>)
#
# Containers tailed: xiaozhi-esp32-server, dotty-behaviour, dotty-bridge, dotty-pi.

set -euo pipefail

CONTAINERS=(xiaozhi-esp32-server dotty-behaviour dotty-bridge dotty-pi)
CMD="${1:?usage: uat-capture.sh start|stop [--dry-run]}"
DRY_RUN=0
[[ "${2:-}" == "--dry-run" ]] && DRY_RUN=1

cd "$(git rev-parse --show-toplevel)"

TODAY="$(date +%Y-%m-%d)"
SESSION_DIR="${SESSION_DIR:-uat-sessions/$TODAY}"
LOG_DIR="$SESSION_DIR/logs"
PID_FILE="$SESSION_DIR/.capture-pids"

if [[ $DRY_RUN -eq 1 ]]; then
    XIAOZHI_SSH="${XIAOZHI_SSH:-<XIAOZHI_USER>@<XIAOZHI_HOST>}"
else
    XIAOZHI_SSH="${XIAOZHI_SSH:?set XIAOZHI_SSH=user@host (the Docker host)}"
fi
XIAOZHI_HOST="${XIAOZHI_HOST:-${XIAOZHI_SSH#*@}}"

run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "DRY-RUN: $*"
    else
        "$@"
    fi
}

case "$CMD" in
start)
    run mkdir -p "$LOG_DIR"

    # Session manifest: what exactly was under test.
    if [[ $DRY_RUN -eq 0 ]]; then
        {
            echo "session_start: $(date -Is)"
            echo "workstation_head: $(git rev-parse --short HEAD) ($(git branch --show-current))"
            echo "docker_host: $XIAOZHI_SSH"
            echo "containers:"
            ssh "$XIAOZHI_SSH" 'docker ps --format "  {{.Names}}: {{.Image}} up {{.Status}}"' \
                || echo "  (docker ps failed — record versions manually)"
        } > "$SESSION_DIR/manifest.txt"
        echo "Manifest written to $SESSION_DIR/manifest.txt"
    else
        echo "DRY-RUN: write manifest to $SESSION_DIR/manifest.txt"
    fi

    # Background tails, one log file per container.
    [[ $DRY_RUN -eq 0 ]] && : > "${PID_FILE}.tmp"
    for c in "${CONTAINERS[@]}"; do
        if [[ $DRY_RUN -eq 1 ]]; then
            echo "DRY-RUN: ssh $XIAOZHI_SSH 'docker logs -f --timestamps --since 1m $c' >> $LOG_DIR/$c.log &"
        else
            ssh -o BatchMode=yes "$XIAOZHI_SSH" "docker logs -f --timestamps --since 1m $c" \
                >> "$LOG_DIR/$c.log" 2>&1 &
            echo "$! $c" >> "${PID_FILE}.tmp"
            echo "Tailing $c → $LOG_DIR/$c.log (pid $!)"
        fi
    done
    [[ $DRY_RUN -eq 0 ]] && mv "${PID_FILE}.tmp" "$PID_FILE"

    cat <<EOF

Capture running. Optional but recommended — serial monitor in a second
terminal (re-plug USB-C if /dev/ttyACM0 is missing):

  docker run --rm -v "\$PWD/firmware/firmware:/project" -w /project \\
    --device=/dev/ttyACM0 espressif/idf:v5.5.4 \\
    bash -lc 'idf.py -p /dev/ttyACM0 monitor' | tee $LOG_DIR/serial.log

When the session ends: XIAOZHI_SSH=$XIAOZHI_SSH scripts/uat-capture.sh stop
EOF
    ;;

stop)
    # 1. Kill the tails.
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "DRY-RUN: kill pids listed in $PID_FILE"
    elif [[ -f "$PID_FILE" ]]; then
        while read -r pid name; do
            kill "$pid" 2>/dev/null && echo "Stopped tail: $name (pid $pid)" || true
        done < "$PID_FILE"
        rm -f "$PID_FILE"
    else
        echo "No $PID_FILE — tails already stopped or never started."
    fi

    # 2. Pull the day's NDJSON logs out of the containers.
    run mkdir -p "$SESSION_DIR/ndjson"
    declare -A NDJSON_SOURCES=(
        [dotty-bridge]="/var/lib/dotty-bridge/logs"
        [dotty-behaviour]="/var/lib/dotty-behaviour/logs"
    )
    for c in "${!NDJSON_SOURCES[@]}"; do
        src="${NDJSON_SOURCES[$c]}"
        if [[ $DRY_RUN -eq 1 ]]; then
            echo "DRY-RUN: ssh $XIAOZHI_SSH 'docker exec $c sh -c \"cd $src && tar cf - *-$TODAY.ndjson\"' | tar xf - -C $SESSION_DIR/ndjson"
        else
            if ssh "$XIAOZHI_SSH" "docker exec $c sh -c 'cd $src && tar cf - *-$TODAY.ndjson 2>/dev/null'" \
                | tar xf - -C "$SESSION_DIR/ndjson" 2>/dev/null; then
                echo "Pulled $c NDJSON logs for $TODAY"
            else
                echo "NOTE: no $TODAY NDJSON files in $c:$src (fine if those consumers never fired)"
            fi
        fi
    done

    # 3. Endpoint snapshots.
    run mkdir -p "$SESSION_DIR/snapshots"
    declare -A SNAPSHOTS=(
        [bridge-health.json]="http://$XIAOZHI_HOST:8081/health"
        [behaviour-health.json]="http://$XIAOZHI_HOST:8090/health"
        [perception-state.json]="http://$XIAOZHI_HOST:8090/api/perception/state"
    )
    for f in "${!SNAPSHOTS[@]}"; do
        if [[ $DRY_RUN -eq 1 ]]; then
            echo "DRY-RUN: curl -fsS ${SNAPSHOTS[$f]} > $SESSION_DIR/snapshots/$f"
        else
            curl -fsS --max-time 10 "${SNAPSHOTS[$f]}" > "$SESSION_DIR/snapshots/$f" \
                && echo "Snapshot: $f" \
                || echo "WARN: snapshot failed: ${SNAPSHOTS[$f]}"
        fi
    done

    if [[ $DRY_RUN -eq 0 ]]; then
        echo
        echo "Done. Session artifacts in $SESSION_DIR/:"
        find "$SESSION_DIR" -type f | sort
        echo
        echo "Next: copy phone + screen recordings into $SESSION_DIR/video/,"
        echo "fill results.csv, then run scripts/uat-slice.py."
    fi
    ;;

*)
    echo "usage: uat-capture.sh start|stop [--dry-run]" >&2
    exit 1
    ;;
esac
