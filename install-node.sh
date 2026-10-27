#!/usr/bin/env bash
# Additional inbounds only. Bootstrap the Node with reviewed original eGames first.
set -Eeuo pipefail
umask 077
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -x "${SCRIPT_DIR}/.venv/bin/python" ]]; then
    PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"
fi
if ! "${PYTHON_BIN}" -c 'import requests, yaml, cryptography' 2>/dev/null; then
    echo 'Install dependencies: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt' >&2
    exit 1
fi
exec "${PYTHON_BIN}" "${SCRIPT_DIR}/egames_node.py" "$@"
