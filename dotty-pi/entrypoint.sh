#!/bin/sh
set -eu

: "${PI_HOME:=/root/.pi}"

mkdir -p \
  "$PI_HOME/agent" \
  "$PI_HOME/memory" \
  "$PI_HOME/sessions" \
  "$PI_HOME/extensions"

if [ ! -e "$PI_HOME/extensions/dotty-pi-ext" ] && [ ! -L "$PI_HOME/extensions/dotty-pi-ext" ]; then
  ln -s /opt/dotty-pi/extensions/dotty-pi-ext "$PI_HOME/extensions/dotty-pi-ext"
fi

node /usr/local/bin/render-models-json.mjs

exec "$@"
