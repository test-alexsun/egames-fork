#!/usr/bin/env python3
"""Compatibility entrypoint: the former isolated repair is unsafe; use the transaction."""
import sys
from remnawave_injector import main
if __name__ == "__main__":
    apply = "--apply" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--apply"]
    sys.argv = [sys.argv[0], "--repair" if apply else "--dry-run", *args]
    raise SystemExit(main())
