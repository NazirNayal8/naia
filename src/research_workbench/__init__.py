"""Compatibility imports for the development alpha; use naia instead."""

from importlib import import_module
import sys

from naia import __version__

for _name in ("storage", "context", "tasks", "suites", "execution", "demo", "ui"):
    _module = import_module(f"naia.{_name}")
    globals()[_name] = _module
    sys.modules[f"{__name__}.{_name}"] = _module
