"""Compatibility imports for the development alpha; use naia_arch instead."""

from importlib import import_module
import sys

from naia_arch import __version__, capture, validate_graph

sys.modules[f"{__name__}.schema"] = import_module("naia_arch.schema")
sys.modules[f"{__name__}.capture"] = import_module("naia_arch._capture")
