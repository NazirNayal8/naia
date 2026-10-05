"""NAIA Lens capture internals; isolated sample execution and FX tracing."""
from __future__ import annotations

import copy
import inspect

from .schema import validate_graph


def capture(model, example_args=None, example_kwargs=None, *, aliases=None, trace=False):
    """Returns JSON data, never a live model or activation values.

    A deep copy protects parameters, buffers, mode, and custom forward state.
    Module hooks report call events, NOT fabricated tensor-dependency edges.
    Only the supplied sample path is observed. FX tracing is best-effort.
    """
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("Capture must run in the project's PyTorch environment; graph viewing does not need torch") from exc
    if not isinstance(model, torch.nn.Module):
        raise TypeError("capture requires a torch.nn.Module")
    aliases = aliases or {}
    modules = list(model.named_modules(remove_duplicate=False))
    nodes, module_ids = [], {}
    for path, module in modules:
        node_id = "module:" + path if path else "root"
        module_ids.setdefault(id(module), node_id)
        parent_path = path.rpartition(".")[0]
        parent = ("module:" + parent_path if parent_path else "root") if path else None
        nodes.append({"id": node_id, "parent": parent, "label": aliases.get(path, path.rsplit(".", 1)[-1] if path else type(model).__name__),
                      "module_path": path, "type": type(module).__name__, "evidence": "structural",
                      "parameters": sum(p.numel() for p in module.parameters(recurse=False)),
                      "shared_with": module_ids[id(module)] if module_ids[id(module)] != node_id else None})
    graph = {"schema_version": 1, "nodes": nodes, "edges": [], "events": [], "warnings": [],
             "parameters": sum(p.numel() for p in model.parameters()), "capture_mode": "structure_only"}
    if example_args is None:
        if trace:
            graph["warnings"].append("FX tracing requires sample inputs in this first implementation")
        return validate_graph(graph)
    args = example_args if isinstance(example_args, tuple) else (example_args,)
    kwargs = example_kwargs or {}
    def shape(value):
        if isinstance(value, torch.Tensor):
            return {"shape": list(value.shape), "dtype": str(value.dtype), "device": str(value.device)}
        if isinstance(value, dict):
            return {str(k): shape(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [shape(v) for v in value]
        return {"type": type(value).__name__}
    probe = copy.deepcopy(model)
    probe.eval()
    handles = []
    sequence = []
    calls = {}
    devices = sorted({p.device.index for p in probe.parameters() if p.is_cuda} | {b.device.index for b in probe.buffers() if b.is_cuda})
    probe_modules = dict(probe.named_modules())
    def before(path, _module, inputs, keywords):
        calls[path] = calls.get(path, 0) + 1
        event = {"node": "module:" + path if path else "root", "call": calls[path], "inputs": shape(inputs), "kwargs": shape(keywords), "evidence": "observed"}
        graph["events"].append(event)
        sequence.append(event)
    def after(path, _module, _inputs, _keywords, output):
        # Postorder is different from invocation order for nested modules.
        event = next(e for e in reversed(sequence) if e["node"] == ("module:" + path if path else "root") and "outputs" not in e)
        event["outputs"] = shape(output)
    try:
        for path, module in probe_modules.items():
            handles.append(module.register_forward_pre_hook(lambda m, a, k, path=path: before(path, m, a, k), with_kwargs=True))
            handles.append(module.register_forward_hook(lambda m, a, k, o, path=path: after(path, m, a, k, o), with_kwargs=True))
        with torch.random.fork_rng(devices=devices), torch.no_grad():
            probe(*copy.deepcopy(args), **copy.deepcopy(kwargs))
        graph["capture_mode"] = "sample_observed"
    finally:
        for hook in handles:
            hook.remove()
    graph["warnings"].append("Observed calls cover this input path only; calls do not establish tensor data-flow edges")
    if trace:
        try:
            with torch.random.fork_rng(devices=devices):
                traced = torch.fx.symbolic_trace(copy.deepcopy(model).eval())
            try:
                from torch.fx.passes.shape_prop import ShapeProp
                bound = inspect.signature(traced.forward).bind(*copy.deepcopy(args), **copy.deepcopy(kwargs))
                bound.apply_defaults()
                ordered_inputs = [bound.arguments[n.target] for n in traced.graph.nodes if n.op == "placeholder"]
                with torch.random.fork_rng(devices=devices), torch.no_grad():
                    ShapeProp(traced).propagate(*ordered_inputs)
            except Exception as exc:
                graph["warnings"].append(f"FX shape propagation unavailable: {type(exc).__name__}: {exc}")
            def metadata(value):
                if hasattr(value, "shape") and hasattr(value, "dtype"):
                    return {"shape": list(value.shape), "dtype": str(value.dtype)}
                if isinstance(value, dict):
                    return {str(k): metadata(v) for k, v in value.items()}
                if isinstance(value, (list, tuple)):
                    return [metadata(v) for v in value]
                return None
            # Functional nodes are separate from the nn.Module ownership tree.
            fx_ids = {}
            for operation in traced.graph.nodes:
                node_id = "fx:" + operation.name
                fx_ids[operation] = node_id
                nodes.append({"id": node_id, "parent": "root", "label": str(operation.target), "type": operation.op,
                              "module_path": str(operation.target) if operation.op == "call_module" else None, "evidence": "traced",
                              "outputs": metadata(operation.meta.get("tensor_meta"))})
                for dependency in operation.all_input_nodes:
                    graph["edges"].append({"source": fx_ids[dependency], "target": node_id, "evidence": "traced"})
        except Exception as exc:
            graph["warnings"].append(f"FX unavailable for this model: {type(exc).__name__}: {exc}")
    return validate_graph(graph)
