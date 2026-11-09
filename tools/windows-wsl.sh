#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
export IDEMU_WSL=1
export IDEMU_ENVS="${IDEMU_ENVS:-${XDG_DATA_HOME:-$HOME/.local/share}/idemu/environments}"
if [ "${IDEMU_PORTABLE:-}" = 1 ]; then
    export IDEMU_STATE_DIR="${IDEMU_STATE_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/idemu}"
fi
exec python3 -m idemu gui "$@"
