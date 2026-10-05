"""Compatibility entry point; use naia-arch instead."""

from naia_arch.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
