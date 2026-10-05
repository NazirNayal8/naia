"""Observed tensor provenance. Records metadata, never tensor values or owners."""
from __future__ import annotations

import itertools
import math
import weakref

import torch
from torch.utils._python_dispatch import TorchDispatchMode

from ._describe import describe_operation


def tensor_metadata(value):
    if isinstance(value, torch.Tensor):
        return {"shape": list(value.shape), "dtype": str(value.dtype), "device": str(value.device)}
    if isinstance(value, dict):
        return {str(key): tensor_metadata(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [tensor_metadata(item) for item in value]
    return {"type": type(value).__name__}


def tensors(value, path=""):
    if isinstance(value, torch.Tensor):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from tensors(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            yield from tensors(item, f"{path}.{index}" if path else str(index))


def _storage(tensor):
    try:
        return (str(tensor.device), tensor.untyped_storage()._cdata)
    except (RuntimeError, NotImplementedError, AttributeError):
        return None


def _region(tensor):
    """Metadata-only byte region; dense transposes also cover one exact span."""
    try:
        shape, strides = tuple(tensor.shape), tuple(tensor.stride())
        if any(size == 0 for size in shape):
            return None
        item_size, offset = tensor.element_size(), tensor.storage_offset()
        axes = [(size, stride) for size, stride in zip(shape, strides) if size > 1]
        low = offset + sum(min(0, (size - 1) * stride) for size, stride in axes)
        high = offset + sum(max(0, (size - 1) * stride) for size, stride in axes)
        expected, dense = 1, True
        for size, stride in sorted(axes, key=lambda axis: abs(axis[1])):
            if abs(stride) != expected:
                dense = False
                break
            expected *= size
        lattice = math.gcd(*(abs(stride) * item_size for size, stride in axes)) if axes else 0
        return {"start": low * item_size, "end": (high + 1) * item_size,
                "base": offset * item_size, "item_size": item_size, "axes": axes,
                "dense": dense, "lattice": lattice}
    except (RuntimeError, NotImplementedError, TypeError):
        return False


def _exact_bytes(region):
    axes = [(size, stride) for size, stride in region["axes"] if stride]
    count = math.prod(size for size, _ in axes)
    if count * region["item_size"] > 16384:
        return None
    offsets = (region["base"] + sum(index * stride * region["item_size"]
               for index, (_, stride) in zip(indices, axes))
               for indices in itertools.product(*(range(size) for size, _ in axes)))
    return {offset + byte for offset in offsets for byte in range(region["item_size"])}


def _overlap(written, alias):
    left, right = _region(written), _region(alias)
    if left is None or right is None:
        return False
    if left is False or right is False:
        return None
    if left["end"] <= right["start"] or right["end"] <= left["start"]:
        return False
    if left["dense"] and right["dense"]:
        return True
    lattice = math.gcd(left["lattice"], right["lattice"])
    if lattice and not any((left["base"] + a - right["base"] - b) % lattice == 0
                           for a in range(left["item_size"]) for b in range(right["item_size"])):
        return False
    left_bytes = _exact_bytes(left) if not left["dense"] else None
    right_bytes = _exact_bytes(right) if not right["dense"] else None
    if left_bytes is not None and right_bytes is not None:
        return bool(left_bytes & right_bytes)
    if left["dense"] and right_bytes is not None:
        return any(left["start"] <= byte < left["end"] for byte in right_bytes)
    if right["dense"] and left_bytes is not None:
        return any(right["start"] <= byte < right["end"] for byte in left_bytes)
    return None


class RuntimeFlow(TorchDispatchMode):
    def __init__(self, graph, modules, scopes, aliases, max_nodes):
        super().__init__()
        self.graph, self.modules, self.scopes = graph, modules, scopes
        self.aliases, self.max_nodes = aliases, max_nodes
        self.producers, self.storage_aliases = {}, {}
        self.operations = 0
        self.omitted = 0
        self.budget_exhausted = False
        self.uncertain_aliases = False
        graph["dataflow"] = {"engine": "torch_dispatch", "nodes": [], "complete": True,
                             "max_nodes": max_nodes, "omitted_operations": 0}
        graph["trace_engine"] = "torch_dispatch"

    def producer(self, tensor):
        item = self.producers.get(id(tensor))
        return item[1] if item is not None and item[0]() is tensor else None

    def remember(self, tensor, producer):
        identity = id(tensor)
        storage = _storage(tensor)
        item = self.producers.get(identity)
        if item is not None and item[0]() is tensor:
            if item[2] != storage:
                previous = self.storage_aliases.get(item[2], {})
                previous.pop(identity, None)
                if not previous:
                    self.storage_aliases.pop(item[2], None)
                if storage is not None:
                    self.storage_aliases.setdefault(storage, {})[identity] = item[0]
            self.producers[identity] = item[0], producer, storage
            return

        def gone(reference):
            current = self.producers.get(identity)
            current_storage = storage
            if current is not None and current[0] is reference:
                current_storage = current[2]
                self.producers.pop(identity, None)
            if current_storage is not None:
                group = self.storage_aliases.get(current_storage)
                if group is not None and group.get(identity) is reference:
                    group.pop(identity, None)
                    if not group:
                        self.storage_aliases.pop(current_storage, None)

        reference = weakref.ref(tensor, gone)
        self.producers[identity] = reference, producer, storage
        if storage is not None:
            self.storage_aliases.setdefault(storage, {})[identity] = reference

    def forget(self, tensor):
        item = self.producers.get(id(tensor))
        if item is not None and item[0]() is tensor:
            self.producers[id(tensor)] = item[0], None, item[2]

    def add_node(self, node):
        self.graph["nodes"].append(node)
        self.graph["dataflow"]["nodes"].append(node["id"])

    def edge(self, producer, target, port, metadata):
        self.graph["edges"].append({"source": producer[0], "target": target, "evidence": "observed",
                                    "source_port": producer[1], "target_port": port,
                                    "shape": metadata["shape"], "dtype": metadata["dtype"]})

    def add_inputs(self, args, kwargs, names=None):
        seen = {}
        for path, tensor in tensors({"args": args, "kwargs": kwargs}):
            existing = seen.get(id(tensor))
            if existing is not None and existing[0] is tensor:
                existing[1]["input_paths"].append(path)
                continue
            node_id = f"input:{len(seen)}"
            meta = tensor_metadata(tensor)
            node = {"id": node_id, "parent": "root", "kind": "input", "type": "input",
                    "family": "input", "display_type": "Input", "shape_symbol": "pill", "config": {},
                    "label": f"Input {(names or {}).get(path, path)}", "evidence": "observed", "input_paths": [path],
                    "outputs": meta, "shape": meta["shape"]}
            seen[id(tensor)] = tensor, node
            self.add_node(node)
            self.remember(tensor, (node_id, "output"))

    def add_outputs(self, output):
        for index, (path, tensor) in enumerate(tensors(output, "output")):
            node_id = f"output:{index}"
            meta = tensor_metadata(tensor)
            self.add_node({"id": node_id, "parent": "root", "kind": "output", "type": "output",
                           "family": "output", "display_type": "Output", "shape_symbol": "pill", "config": {},
                           "label": "Output" if path == "output" else f"Output {path}", "evidence": "observed",
                           "output_path": path, "inputs": meta, "outputs": meta, "shape": meta["shape"]})
            producer = self.producer(tensor)
            if producer is not None:
                self.edge(producer, node_id, "input", meta)
            else:
                self.graph["dataflow"]["complete"] = False
                self.graph["warnings"].append(f"{path} has no observed tensor producer; it may be constant, outside dispatch, or beyond the capture budget")
        self.graph["inputs"] = [node["id"] for node in self.graph["nodes"] if node.get("kind") == "input"]
        self.graph["outputs"] = [node["id"] for node in self.graph["nodes"] if node.get("kind") == "output"]
        self.graph["dataflow"]["omitted_operations"] = self.omitted

    def written_tensors(self, operation, args, kwargs):
        schema = getattr(operation, "_schema", None)
        if schema is None:
            return []
        result = []
        for index, argument in enumerate(schema.arguments):
            if argument.alias_info is not None and argument.alias_info.is_write:
                value = args[index] if index < len(args) else kwargs.get(argument.name)
                result.extend(tensor for _, tensor in tensors(value))
        return result

    def rebind_aliases(self, tensor, producer, *, metadata_only=False, indexed=False, node=None):
        storage = _storage(tensor)
        if storage is None or metadata_only:
            self.remember(tensor, producer)
            return
        for reference in tuple(self.storage_aliases.get(storage, {}).values()):
            alias = reference()
            if alias is None:
                continue
            overlap = True if alias is tensor else _overlap(tensor, alias)
            if indexed and alias is not tensor and overlap is True:
                # A tensor-valued index/mask gives no metadata-only evidence
                # about which subregion was written. Do not invent an arrow.
                overlap = None
            if overlap is True:
                if producer is None and self.producer(alias) is not None and self.graph["dataflow"]["complete"]:
                    self.graph["dataflow"]["complete"] = False
                    self.graph["warnings"].append("An unrecorded mutation invalidated tensor alias provenance; affected dependencies were left unrecorded")
                self.remember(alias, producer)
            elif overlap is None:
                self.forget(alias)
                self.graph["dataflow"]["complete"] = False
                if node is not None:
                    node["alias_analysis"] = "possible"
                if not self.uncertain_aliases:
                    self.uncertain_aliases = True
                    self.graph["warnings"].append("Some mutation alias regions cannot be established from tensor metadata; possible dependencies were left unrecorded")

    def __torch_dispatch__(self, operation, types, args=(), kwargs=None):
        kwargs = kwargs or {}
        dependencies = [(path, tensor, producer, tensor_metadata(tensor)) for path, tensor in tensors({"args": args, "kwargs": kwargs})
                        if (producer := self.producer(tensor)) is not None]
        # Lazy weight initialization can dispatch with uninitialized Parameters.
        # Constant-only calls need no shapes; inspect dynamic inputs before writes.
        if dependencies:
            input_metadata, keyword_metadata = tensor_metadata(args), tensor_metadata(kwargs)
        writes = self.written_tensors(operation, args, kwargs)
        name = str(operation).split(".")[1]
        metadata_only = name in {"transpose_", "t_", "squeeze_", "unsqueeze_", "as_strided_", "resize_", "resize_as_", "set_", "detach_", "requires_grad_"}
        indexed = name.startswith(("index_put_", "index_copy_", "index_fill_", "scatter_", "scatter_add_", "scatter_reduce_", "masked_fill_", "masked_scatter_"))
        output = operation(*args, **kwargs)
        if not dependencies:
            # Constant/parameter transforms do not become per-weight graph nodes.
            for tensor in writes:
                self.rebind_aliases(tensor, None, metadata_only=metadata_only, indexed=indexed)
            for _, tensor in tensors(output):
                self.forget(tensor)
            return output
        if self.operations >= self.max_nodes:
            self.omitted += 1
            if not self.budget_exhausted:
                self.budget_exhausted = True
                self.graph["warnings"].append(f"Runtime operation budget ({self.max_nodes}) reached; remaining dependencies are unrecorded")
                self.graph["dataflow"]["complete"] = False
            for tensor in writes:
                self.rebind_aliases(tensor, None, metadata_only=metadata_only, indexed=indexed)
            for _, tensor in tensors(output):
                self.forget(tensor)
            return output
        node_id = f"op:{self.operations}"
        self.operations += 1
        scope = self.scopes[-1] if self.scopes else {"path": "", "call": 1}
        path = scope["path"]
        description = describe_operation(operation, self.modules.get(path))
        node = {"id": node_id, "parent": "module:" + path if path else "root",
                "kind": "operation", "type": "call_function", "operation": str(operation),
                "label": self.aliases.get(path, description["display_type"]), "evidence": "observed",
                "module_path": path, "scope": "module:" + path if path else "root", "call": scope["call"],
                "inputs": input_metadata, "kwargs": keyword_metadata, "outputs": tensor_metadata(output),
                "sequence": self.operations - 1, "inplace": bool(writes), **description}
        output_leaves = list(tensors(output))
        if len(output_leaves) == 1:
            node["shape"] = list(output_leaves[0][1].shape)
        self.add_node(node)
        for port, tensor, producer, metadata in dependencies:
            self.edge(producer, node_id, port, metadata)
        for tensor in writes:
            self.rebind_aliases(tensor, (node_id, "output"), metadata_only=metadata_only, indexed=indexed, node=node)
        for port, tensor in output_leaves:
            self.remember(tensor, (node_id, port or "output"))
        return output
