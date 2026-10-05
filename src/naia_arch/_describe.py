"""Small, JSON-safe descriptions of modules and observed tensor operations."""
from __future__ import annotations


def _value(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (tuple, list)):
        return [_value(item) for item in value]
    return type(value).__name__


def describe_module(module):
    # Names such as ResidualConv describe user containers, not evidence that
    # the object is a convolution. Use framework ancestry for actual layer types.
    import torch.nn as nn

    kind = type(module).__name__
    framework_kind = next((base.__name__ for base in type(module).__mro__
                           if base.__module__.startswith("torch.nn.") and not base.__name__.startswith("_")), kind)
    family, symbol, fields = "operation", "rectangle", ()
    display = kind
    activation_names = ("ReLU", "ReLU6", "GELU", "SiLU", "Mish", "Sigmoid", "Tanh", "Softmax", "LogSoftmax", "LeakyReLU", "PReLU", "ELU", "CELU", "SELU", "Softplus", "Softsign", "Hardswish", "Hardsigmoid", "Hardtanh", "Threshold")
    pooling_names = ("MaxPool1d", "MaxPool2d", "MaxPool3d", "AvgPool1d", "AvgPool2d", "AvgPool3d", "AdaptiveMaxPool1d", "AdaptiveMaxPool2d", "AdaptiveMaxPool3d", "AdaptiveAvgPool1d", "AdaptiveAvgPool2d", "AdaptiveAvgPool3d", "LPPool1d", "LPPool2d", "LPPool3d", "FractionalMaxPool2d", "FractionalMaxPool3d")
    norm_names = ("LayerNorm", "GroupNorm", "RMSNorm", "BatchNorm1d", "BatchNorm2d", "BatchNorm3d", "SyncBatchNorm", "InstanceNorm1d", "InstanceNorm2d", "InstanceNorm3d", "LazyBatchNorm1d", "LazyBatchNorm2d", "LazyBatchNorm3d", "LazyInstanceNorm1d", "LazyInstanceNorm2d", "LazyInstanceNorm3d")

    def known(names):
        return tuple(getattr(nn, name) for name in names if hasattr(nn, name))

    if isinstance(module, (nn.Linear, nn.Bilinear)):
        family, fields = "linear", ("in_features", "out_features", "bias")
        display = "Bilinear" if isinstance(module, nn.Bilinear) else "Linear"
    elif isinstance(module, nn.modules.conv._ConvNd):
        family, symbol = "convolution", "hexagon"
        fields = ("in_channels", "out_channels", "kernel_size", "stride", "padding", "dilation", "groups", "bias", "output_padding")
        display = framework_kind.replace("Lazy", "").replace("Conv", "Convolution ").replace("Transpose", "transposed ")
    elif isinstance(module, nn.MultiheadAttention):
        family, symbol = "attention", "ellipse"
        fields = ("embed_dim", "num_heads", "kdim", "vdim", "batch_first", "dropout")
        display = "Multi-head attention"
    elif isinstance(module, known(norm_names)):
        family, symbol = "normalization", "pill"
        fields = ("normalized_shape", "num_features", "num_groups", "num_channels", "eps", "affine", "elementwise_affine")
        display = framework_kind.replace("Lazy", "").replace("Norm", " normalization")
    elif isinstance(module, (nn.Embedding, nn.EmbeddingBag)):
        family, fields = "embedding", ("num_embeddings", "embedding_dim", "padding_idx")
        display = "Embedding"
    elif isinstance(module, known(pooling_names)):
        family, symbol = "pooling", "trapezoid"
        fields = ("kernel_size", "stride", "padding", "output_size", "ceil_mode")
        display = framework_kind.replace("Pool", " pooling ")
    elif isinstance(module, known(activation_names)):
        family, symbol, fields = "activation", "diamond", ("dim", "negative_slope", "inplace", "approximate")
        display = framework_kind
    elif isinstance(module, nn.modules.dropout._DropoutNd):
        family, symbol, fields = "dropout", "diamond", ("p", "inplace")
        display = "Dropout"
    elif isinstance(module, (nn.Flatten, nn.Unflatten)):
        family, symbol = "reshape", "parallelogram"
        fields = ("start_dim", "end_dim", "dim", "unflattened_size")
        display = framework_kind
    elif isinstance(module, nn.Identity):
        family, display = "identity", "Identity"
    elif any(True for _ in module.children()):
        family, symbol = "container", "rectangle"
    config = {}
    for field in fields:
        if hasattr(module, field):
            value = getattr(module, field)
            config[field] = value is not None if field == "bias" else _value(value)
    return {"family": family, "display_type": display, "shape_symbol": symbol, "config": config}


def describe_operation(operation, module=None):
    name = str(operation).split(".")
    name = name[1] if len(name) > 1 else name[0]
    lower = name.lower()
    family, symbol = "operation", "rectangle"
    display = name.replace("_", " ").strip().capitalize()
    if lower in {"linear", "addmm", "mm", "bmm", "matmul", "mv", "dot", "baddbmm"}:
        family, display = "linear", "Matrix multiplication"
    elif "convolution" in lower or lower.startswith("conv"):
        family, symbol, display = "convolution", "hexagon", "Convolution"
    elif "attention" in lower:
        family, symbol, display = "attention", "ellipse", "Attention"
    elif "norm" in lower:
        family, symbol, display = "normalization", "pill", "Normalization"
    elif any(token in lower for token in ("relu", "gelu", "silu", "sigmoid", "tanh", "softmax", "softplus")):
        family, symbol = "activation", "diamond"
        display = name.rstrip("_").replace("_", " ").capitalize()
    elif "pool" in lower:
        family, symbol, display = "pooling", "trapezoid", "Pooling"
    elif "embedding" in lower:
        family, display = "embedding", "Embedding lookup"
    elif lower.rstrip("_") in {"add", "sub", "mul", "div", "cat", "concat", "stack", "maximum", "minimum"}:
        family, symbol = "merge", "circle"
        display = {"add": "Add", "sub": "Subtract", "mul": "Multiply", "div": "Divide", "cat": "Concatenate", "concat": "Concatenate", "stack": "Stack", "maximum": "Maximum", "minimum": "Minimum"}[lower.rstrip("_")]
    elif any(token in lower for token in ("view", "reshape", "flatten", "permute", "transpose", "squeeze", "expand", "t_")) or lower == "t":
        family, symbol = "reshape", "parallelogram"
    elif any(token in lower for token in ("sum", "mean", "amax", "amin", "argmax", "argmin", "prod")):
        family, symbol = "reduction", "trapezoid"
    elif lower in {"gt", "lt", "ge", "le", "eq", "ne", "is_nonzero", "_local_scalar_dense"}:
        family, symbol = "control", "diamond"
    elif any(token in lower for token in ("slice", "select", "index", "gather", "scatter", "split", "unbind", "chunk")):
        family, symbol = "indexing", "parallelogram"
    elif lower in {"detach", "alias", "clone", "copy_", "_to_copy", "to"}:
        family, display = "identity", name.replace("_", " ").strip().capitalize()
    config = {}
    if module is not None:
        description = describe_module(module)
        # Parameterized layers retain human names; internal reshapes and merges
        # stay individually visible rather than masquerading as whole layers.
        if description["family"] == family and family not in {"operation", "container", "identity"}:
            display, symbol, config = description["display_type"], description["shape_symbol"], description["config"]
    return {"family": family, "display_type": display, "shape_symbol": symbol, "config": config}
