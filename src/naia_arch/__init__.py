"""Graph inspection without torch; capture imports torch only when called."""
from .schema import validate_graph

__version__ = "0.1.0a5"


def capture(*args, **kwargs):
    from ._capture import capture as implementation
    return implementation(*args, **kwargs)
