"""Explicit, cited graph annotations; no model imports or role inference."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path


MAX_SEMANTICS_BYTES = 64 * 1024


def _text(value, label, limit=None):
    if (not isinstance(value, str) or not value.strip()
            or (limit is not None and len(value) > limit)
            or any(not character.isprintable() for character in value)):
        bound = f" of at most {limit} characters" if limit is not None else ""
        raise ValueError(f"{label} must be nonempty, printable single-line text{bound}")


def supports_semantic(node):
    """Physical modules and boundaries, including explicit legacy FX records."""
    return (node.get("kind") in ("module", "input", "output", "placeholder", "call_module")
            or node.get("type") in ("placeholder", "output", "call_module"))


def validate_semantic(semantic):
    if not isinstance(semantic, dict) or set(semantic) - {"name", "evidence", "role"}:
        raise ValueError("Semantic annotations allow only name, evidence, and optional role")
    if not {"name", "evidence"} <= set(semantic):
        raise ValueError("Semantic annotations require name and evidence")
    _text(semantic["name"], "Semantic name", 80)
    evidence = semantic["evidence"]
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 16:
        raise ValueError("Semantic evidence must contain between 1 and 16 citations")
    for citation in evidence:
        _text(citation, "Semantic evidence citation", 512)
    if "role" in semantic:
        _text(semantic["role"], "Semantic role", 64)
    return semantic


def validate_semantics(semantics):
    if not isinstance(semantics, dict) or not semantics:
        raise ValueError("Semantics must be a nonempty mapping from exact node IDs to annotations")
    for identity, semantic in semantics.items():
        _text(identity, "Semantic target node ID")
        validate_semantic(semantic)
    return semantics


def _json(content):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(f"Non-finite JSON value: {value}")

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            reject_constant(value)
        return result

    return json.loads(content, object_pairs_hook=unique_object,
                      parse_constant=reject_constant, parse_float=finite_float)


def parse_semantics(value):
    """Parse bounded JSON or @FILE without reading model sources or executing code."""
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("--semantics requires JSON or @FILE")
    if value.startswith("@"):
        if not value[1:]:
            raise ValueError("--semantics requires JSON or @FILE")
        with Path(value[1:]).open("rb") as stream:
            content = stream.read(MAX_SEMANTICS_BYTES + 1)
    else:
        content = value.encode("utf-8")
    if len(content) > MAX_SEMANTICS_BYTES:
        raise ValueError("Semantics mapping exceeds the 64 KiB limit")
    return validate_semantics(_json(content))


def annotate_graph(graph, semantics):
    """Return an independent graph with annotations on explicitly selected nodes."""
    from .schema import validate_graph

    validate_semantics(semantics)
    validate_graph(graph)
    by_id = {node["id"]: node for node in graph["nodes"]}
    for identity in semantics:
        if identity not in by_id:
            raise ValueError(f"Unknown semantic target node ID: {identity}")
        if not supports_semantic(by_id[identity]):
            raise ValueError(f"Semantic target must be a module, input, or output node: {identity}")
    result = copy.deepcopy(graph)
    annotations = copy.deepcopy(semantics)
    for node in result["nodes"]:
        if node["id"] in annotations:
            node["semantic"] = annotations[node["id"]]
    return validate_graph(result)
