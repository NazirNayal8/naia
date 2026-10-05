"""Atomic records and advisory locks; no package-location-derived project root."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone


class NAIAError(ValueError):
    pass


# Preserve the alpha API for existing integrations.
WorkbenchError = NAIAError


def now():
    return datetime.now(timezone.utc).isoformat()


def name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", value):
        raise NAIAError(f"Unsafe identifier: {value!r}")
    return value


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NAIAError(f"Cannot read {path}: {exc}") from exc


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_json(path, data):
    atomic_text(path, json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def inside(root, relative):
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise NAIAError(f"Path escapes project: {relative}")
    return target


@contextmanager
def locked(path, *, timeout=15):
    """Serialize writers. Network filesystems must support advisory locks."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            stream.write(b"0")
            stream.flush()
            def acquire():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            def release():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire()
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise NAIAError(f"Another writer holds {path}") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            release()
