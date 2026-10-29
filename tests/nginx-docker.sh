#!/usr/bin/env bash
set -Eeuo pipefail
# Only disposable CI validation; bind the synthetic temporary cert/config directory.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
image=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["nginx_image"])' "$SCRIPT_DIR/validation-manifest.json")
exec docker run --rm --network none -v /tmp:/tmp "$image" nginx "$@"
