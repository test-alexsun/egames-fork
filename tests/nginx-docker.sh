#!/usr/bin/env bash
set -Eeuo pipefail
# Only disposable CI validation; bind the synthetic temporary cert/config directory.
exec docker run --rm --network none -v /tmp:/tmp nginx:1.30 nginx "$@"
