"""Bind local browser servers without racing other project dashboards."""
from __future__ import annotations

import argparse
import errno
from http.server import ThreadingHTTPServer
from pathlib import Path
import secrets


PORT_POOL = range(8760, 8860)


def project_title(root):
    name = " ".join(Path(root).name.split()) or "Project"
    return f"NAIA - {name}"


def port_number(value):
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("Port must be an integer from 0 to 65535") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("Port must be an integer from 0 to 65535")
    return port


def bind_loopback(request_handler, port=None, *, host="127.0.0.1"):
    """Reserve the port by binding, not with a separate availability probe.

    Explicit ports are exact: errors propagate rather than silently moving a
    user's SSH tunnel. Zero asks the OS for an available ephemeral port. The
    default tries a random permutation of the pool, then falls back to zero.
    """
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("NAIA's browser interface binds to loopback only")
    if port is not None:
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("Port must be an integer from 0 to 65535")
        return ThreadingHTTPServer((host, port), request_handler)
    ports = list(PORT_POOL)
    secrets.SystemRandom().shuffle(ports)
    for candidate in ports:
        try:
            return ThreadingHTTPServer((host, candidate), request_handler)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
    return ThreadingHTTPServer((host, 0), request_handler)
