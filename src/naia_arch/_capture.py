"""Protected sample execution with runtime tensor-flow tracing and FX fallback."""
from __future__ import annotations

import copy
from contextlib import contextmanager
import inspect
import random
import sys

from ._describe import describe_module, describe_operation
from .schema import validate_graph


@contextmanager
def _random_state(torch, devices):
    python_state = random.getstate()
    numpy = sys.modules.get("numpy")
    numpy_state = numpy.random.get_state() if numpy is not None else None
    try:
        with torch.random.fork_rng(devices=devices):
            yield
    finally:
        random.setstate(python_state)
        if numpy_state is not None:
            numpy.random.set_state(numpy_state)


def _metadata(torch, value):
    if isinstance(value, torch.Tensor):
        return {"shape": list(value.shape), "dtype": str(value.dtype), "device": str(value.device)}
    if isinstance(value, dict):
        return {str(key): _metadata(torch, item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_metadata(torch, item) for item in value]
    return {"type": type(value).__name__}


def _tensor_leaves(torch, value):
    if isinstance(value, torch.Tensor):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _tensor_leaves(torch, item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _tensor_leaves(torch, item)


def _parameter_count(module, recurse=True):
    try:
        return sum(parameter.numel() for parameter in module.parameters(recurse=recurse))
    except ValueError:
        # Lazy modules initialize only the protected copy when a sample arrives.
        return None


def _input_names(model, args, kwargs):
    try:
        signature = inspect.signature(model.forward)
        positional = [parameter.name for parameter in signature.parameters.values()
                      if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)]
        names = {f"args.{index}": name for index, name in enumerate(positional[:len(args)])}
        names.update({f"kwargs.{key}": key for key in kwargs})
        # Nested samples retain their container path after the argument name.
        from ._runtime import tensors
        return {path: name + path[len(prefix):] for path, _ in tensors({"args": args, "kwargs": kwargs})
                for prefix, name in names.items() if path == prefix or path.startswith(prefix + ".")}
    except (ValueError, TypeError, ImportError):
        return {}


def capture(model, example_args=None, example_kwargs=None, *, aliases=None, trace=True, max_nodes=10000):
    """Return shape/type metadata and observed tensor dependencies, never values.

    Execution uses an eval-mode deep copy, copied inputs, no_grad and restored
    RNG state. ``trace=False`` retains hierarchy plus observed module calls.
    ``max_nodes`` caps runtime operations; boundaries/hierarchy remain available.
    Model Python code is trusted; capture is not a sandbox for external effects.
    """
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("Capture must run in the project's PyTorch environment; graph viewing does not need torch") from exc
    if not isinstance(model, torch.nn.Module):
        raise TypeError("capture requires a torch.nn.Module")
    if isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or max_nodes < 1:
        raise ValueError("max_nodes must be a positive integer")
    if aliases is None:
        aliases = {}
    if not isinstance(aliases, dict) or any(not isinstance(path, str) or not isinstance(label, str) or not label.strip() for path, label in aliases.items()):
        raise ValueError("aliases must map module paths to nonempty labels")
    modules = list(model.named_modules(remove_duplicate=False))
    nodes, module_ids = [], {}
    for path, module in modules:
        node_id = "module:" + path if path else "root"
        module_ids.setdefault(id(module), node_id)
        parent_path = path.rpartition(".")[0]
        parent = ("module:" + parent_path if parent_path else "root") if path else None
        description = describe_module(module)
        nodes.append({"id": node_id, "parent": parent, "kind": "module",
                      "label": aliases.get(path, description["display_type"]),
                      "module_path": path, "type": type(module).__name__, "evidence": "structural",
                      "parameters": _parameter_count(module, recurse=False),
                      "shared_with": module_ids[id(module)] if module_ids[id(module)] != node_id else None,
                      **description})
    graph = {"schema_version": 1, "nodes": nodes, "edges": [], "events": [], "warnings": [],
             "parameters": _parameter_count(model), "capture_mode": "structure_only"}
    if example_args is None:
        if trace:
            graph["warnings"].append("Runtime data-flow tracing requires sample inputs")
        return validate_graph(graph)
    args = example_args if isinstance(example_args, tuple) else (example_args,)
    kwargs = example_kwargs or {}
    device_tensors = [*model.parameters(), *model.buffers(), *_tensor_leaves(torch, (args, kwargs))]
    devices = sorted({tensor.device.index for tensor in device_tensors if tensor.is_cuda})
    runtime_type = None
    if trace:
        try:
            from ._runtime import RuntimeFlow
            runtime_type = RuntimeFlow
        except (ImportError, AttributeError) as exc:
            graph["warnings"].append(f"Runtime dispatch tracing unavailable ({type(exc).__name__}); trying FX")
    structural = {node["id"]: node for node in nodes}
    calls, scopes, handles = {}, [], []
    with _random_state(torch, devices), torch.no_grad():
        probe = copy.deepcopy(model)
        probe.eval()
        sample_args, sample_kwargs = copy.deepcopy((args, kwargs))
        probe_modules = dict(probe.named_modules())

        def before(path, _module, inputs, keywords):
            calls[path] = calls.get(path, 0) + 1
            node_id = "module:" + path if path else "root"
            event = {"node": node_id, "call": calls[path], "inputs": _metadata(torch, inputs),
                     "kwargs": _metadata(torch, keywords), "evidence": "observed"}
            if len(graph["events"]) < max_nodes:
                graph["events"].append(event)
            elif graph.get("events_complete", True):
                graph["events_complete"] = False
                graph["warnings"].append(f"Module-call metadata budget ({max_nodes}) reached")
            description = describe_module(_module)
            structural[node_id].update(inputs=event["inputs"], kwargs=event["kwargs"], calls=calls[path],
                                       parameters=_parameter_count(_module, recurse=False), **description)
            scopes.append({"path": path, "call": calls[path], "event": event})

        def after(path, _module, _inputs, _keywords, output):
            scope = scopes.pop()
            scope["event"]["outputs"] = _metadata(torch, output)
            structural["module:" + path if path else "root"]["outputs"] = scope["event"]["outputs"]

        try:
            for path, module in probe_modules.items():
                handles.append(module.register_forward_pre_hook(lambda m, a, k, path=path: before(path, m, a, k), with_kwargs=True))
                handles.append(module.register_forward_hook(lambda m, a, k, o, path=path: after(path, m, a, k, o), with_kwargs=True))
            if runtime_type is not None:
                runtime = runtime_type(graph, probe_modules, scopes, aliases, max_nodes)
                runtime.add_inputs(sample_args, sample_kwargs, _input_names(probe, sample_args, sample_kwargs))
                with runtime:
                    output = probe(*sample_args, **sample_kwargs)
                runtime.add_outputs(output)
                graph["capture_mode"] = "runtime_observed"
                graph["warnings"].append("Observed tensor dependencies cover this sample path only; other branches and Python scalar dependencies are not inferred")
            else:
                probe(*sample_args, **sample_kwargs)
                graph["capture_mode"] = "sample_observed"
            graph["parameters"] = _parameter_count(probe)
        finally:
            for hook in handles:
                hook.remove()
    if not trace:
        graph["warnings"].append("Observed module calls do not establish tensor data-flow edges; enable tracing for those dependencies")
    elif runtime_type is None:
        _fx_fallback(torch, model, args, kwargs, aliases, graph, devices, max_nodes)
    return validate_graph(graph)


def _fx_fallback(torch, model, args, kwargs, aliases, graph, devices, max_nodes):
    try:
        with _random_state(torch, devices), torch.no_grad():
            traced = torch.fx.symbolic_trace(copy.deepcopy(model).eval())
            try:
                from torch.fx.passes.shape_prop import ShapeProp
                sample_args, sample_kwargs = copy.deepcopy((args, kwargs))
                bound = inspect.signature(traced.forward).bind(*sample_args, **sample_kwargs)
                bound.apply_defaults()
                ordered_inputs = [bound.arguments[node.target] for node in traced.graph.nodes if node.op == "placeholder"]
                ShapeProp(traced).propagate(*ordered_inputs)
            except Exception as exc:
                graph["warnings"].append(f"FX shape propagation unavailable: {type(exc).__name__}: {exc}")

        def metadata(value):
            if hasattr(value, "shape") and hasattr(value, "dtype"):
                return {"shape": list(value.shape), "dtype": str(value.dtype)}
            if isinstance(value, dict):
                return {str(key): metadata(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [metadata(item) for item in value]
            return None

        graph["dataflow"] = {"engine": "fx", "nodes": [], "complete": True, "max_nodes": max_nodes}
        graph["trace_engine"] = "fx"
        fx_ids = {}
        for index, operation in enumerate(traced.graph.nodes):
            if index >= max_nodes:
                graph["dataflow"]["complete"] = False
                graph["warnings"].append(f"FX node budget ({max_nodes}) reached; remaining dependencies are unrecorded")
                break
            node_id = "fx:" + operation.name
            fx_ids[operation] = node_id
            kind = "input" if operation.op == "placeholder" else "output" if operation.op == "output" else "operation"
            module = traced.get_submodule(str(operation.target)) if operation.op == "call_module" else None
            description = describe_module(module) if module is not None else describe_operation(str(operation.target))
            if kind in {"input", "output"}:
                description.update(family=kind, display_type=kind.capitalize(), shape_symbol="pill")
            graph["nodes"].append({"id": node_id, "parent": "root", "kind": kind,
                                   "label": aliases.get(str(operation.target), description["display_type"]), "type": operation.op,
                                   "operation": str(operation.target), "evidence": "traced", "sequence": index,
                                   "module_path": str(operation.target) if module is not None else None,
                                   "outputs": metadata(operation.meta.get("tensor_meta")), **description})
            graph["dataflow"]["nodes"].append(node_id)
            for dependency in operation.all_input_nodes:
                if dependency in fx_ids:
                    graph["edges"].append({"source": fx_ids[dependency], "target": node_id, "evidence": "traced"})
        graph["inputs"] = [node["id"] for node in graph["nodes"] if node.get("kind") == "input"]
        graph["outputs"] = [node["id"] for node in graph["nodes"] if node.get("kind") == "output"]
        graph["capture_mode"] = "fx_traced"
        graph["warnings"].append("FX fallback is symbolic; observed Python control flow may be unsupported")
    except Exception as exc:
        graph["trace_engine"] = "unavailable"
        graph.setdefault("dataflow", {"engine": "unavailable", "nodes": []})["complete"] = False
        graph["warnings"].append(f"Data-flow tracing unavailable: {type(exc).__name__}: {exc}")
