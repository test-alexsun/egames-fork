#!/usr/bin/env bash
# Compatibility entrypoint. Diagnostics only by default; no forced restarts/deletions.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/install.sh" "$@"
