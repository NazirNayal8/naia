"""Project links to immutable architecture evidence; never import or execute a model."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from naia_arch import validate_graph

from .storage import NAIAError, locked, name, now, read_json, write_json
from .suites import Suites
from .tasks import Tasks


MAX_GRAPH_BYTES = 16 * 1024 * 1024


def read_graph(path):
    """Validate and hash the same bounded snapshot, rather than reopening the file."""
    try:
        with Path(path).open("rb") as stream:
            content = stream.read(MAX_GRAPH_BYTES + 1)
        if len(content) > MAX_GRAPH_BYTES:
            raise NAIAError("Architecture graph exceeds the 16 MiB limit")
        def reject_constant(value):
            raise ValueError(f"Non-finite JSON value: {value}")
        graph = validate_graph(json.loads(content, parse_constant=reject_constant))
    except (OSError, ValueError, TypeError, AttributeError, RecursionError) as exc:
        raise NAIAError(f"Cannot read a valid architecture graph: {exc}") from exc
    return graph, hashlib.sha256(content).hexdigest()


class Architectures:
    def __init__(self, project):
        self.project = project
        self.path = project.path(".lab/architectures.json")

    def load(self):
        if not self.path.exists():
            return {"schema_version": 1, "items": {}}
        data = read_json(self.path)
        if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("items"), dict):
            raise NAIAError("Expected architecture registry schema_version=1")
        for key, entry in data["items"].items():
            name(key)
            if not isinstance(entry, dict) or entry.get("id") != key:
                raise NAIAError("Architecture registry identity mismatch")
            if not isinstance(entry.get("title"), str) or not entry["title"].strip():
                raise NAIAError("Architecture record requires a title")
            graph = entry.get("graph")
            if not isinstance(graph, str) or not graph or Path(graph).is_absolute():
                raise NAIAError("Architecture graph reference must be project-relative")
            checksum = entry.get("graph_sha256")
            if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
                raise NAIAError("Architecture record requires a SHA-256 checksum")
            for field in ("suite", "task"):
                if entry.get(field) is not None:
                    name(entry[field])
        return data

    def graph(self, architecture_id):
        name(architecture_id)
        entry = self.load()["items"].get(architecture_id)
        if entry is None:
            raise NAIAError(f"Unknown architecture: {architecture_id}")
        graph, checksum = read_graph(self.project.path(entry["graph"]))
        if checksum != entry["graph_sha256"]:
            raise NAIAError("Architecture graph changed; capture and register a new graph/ID")
        return graph

    def list(self):
        entries = []
        for entry in self.load()["items"].values():
            item = dict(entry, available=True)
            try:
                self.graph(entry["id"])
            except NAIAError as exc:
                item.update(available=False, error=str(exc))
            entries.append(item)
        return entries

    def add(self, architecture_id, graph, title, *, suite=None, task=None):
        name(architecture_id)
        if not isinstance(title, str) or not title.strip():
            raise NAIAError("Architecture requires a nonempty title")
        self.project.load()
        if not isinstance(graph, str) or not graph:
            raise NAIAError("Architecture requires a saved graph path")
        # Absolute paths within the project are accepted, but records are portable.
        path = self.project.path(graph)
        _, checksum = read_graph(path)
        relative = path.relative_to(self.project.root).as_posix()
        if suite is not None:
            Suites(self.project).load(name(suite))
        if task is not None and name(task) not in Tasks(self.project).load()["items"]:
            raise NAIAError(f"Unknown task: {task}")
        entry = {"id": architecture_id, "title": title.strip(), "graph": relative,
                 "graph_sha256": checksum, "suite": suite, "task": task, "created_at": now()}
        with locked(self.project.path(".lab/state/locks/architectures.lock")):
            data = self.load()
            if architecture_id in data["items"]:
                raise NAIAError("Architecture ID already exists; choose a new ID")
            data["items"][architecture_id] = entry
            write_json(self.path, data)
        return entry
