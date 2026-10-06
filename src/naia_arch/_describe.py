"""Small, JSON-safe descriptions of modules and observed tensor operations."""
from __future__ import annotations

import re


def _value(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (tuple, list)):
        return [_value(item) for item in value]
    return type(value).__name__


def _description(visual_kind, family, display, symbol="rectangle", config=None):
    return {"visual_kind": visual_kind, "family": family, "display_type": display,
            "shape_symbol": symbol, "config": config or {}}


def describe_module(module):
    # User class names are not layer evidence. Framework ancestry identifies
    # subclasses; original project class names remain in the graph's type field.
    import torch.nn as nn

    def known(*names):
        return tuple(getattr(nn, name) for name in names if hasattr(nn, name))

    framework_kind = next((base.__name__ for base in type(module).__mro__
                           if base.__module__.startswith("torch.nn.") and not base.__name__.startswith("_")), "")
    visual_kind, family, display, symbol, fields = "custom", "operation", "Custom operation", "rectangle", ()
    if isinstance(module, nn.Bilinear):
        visual_kind, family, display = "bilinear", "linear", "Bilinear"
        fields = ("in1_features", "in2_features", "out_features", "bias")
    elif isinstance(module, nn.Linear):
        visual_kind, family, display = "linear", "linear", "Linear"
        fields = ("in_features", "out_features", "bias")
    elif isinstance(module, nn.modules.conv._ConvNd):
        transposed = isinstance(module, nn.modules.conv._ConvTransposeNd)
        visual_kind, family, symbol = "conv_transpose" if transposed else "conv", "convolution", "hexagon"
        display = f"{'Transposed convolution' if transposed else 'Convolution'} {len(module.kernel_size)}d"
        fields = ("in_channels", "out_channels", "kernel_size", "stride", "padding", "dilation", "groups", "bias", "output_padding")
    elif isinstance(module, nn.MultiheadAttention):
        visual_kind, family, display, symbol = "attention", "attention", "Multi-head attention", "ellipse"
        fields = ("embed_dim", "num_heads", "kdim", "vdim", "batch_first", "dropout")
    elif isinstance(module, known("LayerNorm")):
        visual_kind, family, display, symbol = "layer_norm", "normalization", "Layer normalization", "pill"
        fields = ("normalized_shape", "eps", "elementwise_affine", "bias")
    elif isinstance(module, known("RMSNorm")):
        visual_kind, family, display, symbol = "rms_norm", "normalization", "RMS normalization", "pill"
        fields = ("normalized_shape", "eps", "elementwise_affine")
    elif isinstance(module, known("GroupNorm")):
        visual_kind, family, display, symbol = "group_norm", "normalization", "Group normalization", "pill"
        fields = ("num_groups", "num_channels", "eps", "affine")
    elif isinstance(module, known("BatchNorm1d", "BatchNorm2d", "BatchNorm3d", "SyncBatchNorm", "LazyBatchNorm1d", "LazyBatchNorm2d", "LazyBatchNorm3d")):
        visual_kind, family, symbol = "batch_norm", "normalization", "pill"
        dimensions = next((f" {dim}d" for dim in (1, 2, 3) if framework_kind in {f"BatchNorm{dim}d", f"LazyBatchNorm{dim}d"}), "")
        display = "Synchronized batch normalization" if isinstance(module, known("SyncBatchNorm")) else "Batch normalization" + dimensions
        fields = ("num_features", "eps", "momentum", "affine", "track_running_stats")
    elif isinstance(module, known("InstanceNorm1d", "InstanceNorm2d", "InstanceNorm3d", "LazyInstanceNorm1d", "LazyInstanceNorm2d", "LazyInstanceNorm3d")):
        visual_kind, family, symbol = "instance_norm", "normalization", "pill"
        dimensions = next((f" {dim}d" for dim in (1, 2, 3) if framework_kind in {f"InstanceNorm{dim}d", f"LazyInstanceNorm{dim}d"}), "")
        display = "Instance normalization" + dimensions
        fields = ("num_features", "eps", "momentum", "affine", "track_running_stats")
    elif isinstance(module, (nn.Embedding, nn.EmbeddingBag)):
        visual_kind, family, display = "embedding", "embedding", "Embedding bag" if isinstance(module, nn.EmbeddingBag) else "Embedding"
        fields = ("num_embeddings", "embedding_dim", "padding_idx", "max_norm", "norm_type", "mode")
    elif isinstance(module, known("RNN", "GRU", "LSTM", "RNNCell", "GRUCell", "LSTMCell")):
        visual_kind, family, display = "recurrent", "recurrent", {"RNN": "RNN", "GRU": "GRU", "LSTM": "LSTM", "RNNCell": "RNN cell", "GRUCell": "GRU cell", "LSTMCell": "LSTM cell"}[framework_kind]
        fields = ("input_size", "hidden_size", "num_layers", "bias", "batch_first", "dropout", "bidirectional", "proj_size", "nonlinearity")
    elif isinstance(module, known(*(f"{prefix}{dim}d" for prefix in ("MaxPool", "AdaptiveMaxPool", "FractionalMaxPool") for dim in (1, 2, 3)))):
        visual_kind, family, display, symbol = "pool_max", "pooling", "Max pooling", "trapezoid"
        fields = ("kernel_size", "stride", "padding", "dilation", "output_size", "output_ratio", "ceil_mode", "return_indices")
    elif isinstance(module, known(*(f"{prefix}{dim}d" for prefix in ("AvgPool", "AdaptiveAvgPool") for dim in (1, 2, 3)))):
        visual_kind, family, display, symbol = "pool_avg", "pooling", "Average pooling", "trapezoid"
        fields = ("kernel_size", "stride", "padding", "output_size", "ceil_mode", "count_include_pad", "divisor_override")
    elif isinstance(module, known("LPPool1d", "LPPool2d", "LPPool3d")):
        visual_kind, family, display, symbol = "pool", "pooling", "Lp pooling", "trapezoid"
        fields = ("norm_type", "kernel_size", "stride", "ceil_mode")
    elif isinstance(module, known("ReLU", "ReLU6", "LeakyReLU", "PReLU", "RReLU", "GELU", "Sigmoid", "Hardsigmoid", "LogSigmoid", "Tanh", "Hardtanh", "Softmax", "Softmax2d", "LogSoftmax", "Softmin", "SiLU", "Mish", "ELU", "CELU", "SELU", "Softplus", "Softsign", "Hardswish", "Threshold", "Hardshrink", "Softshrink", "Tanhshrink", "GLU")):
        visual_kind = {"ReLU": "relu", "ReLU6": "relu", "GELU": "gelu", "Sigmoid": "sigmoid", "Tanh": "tanh", "Softmax": "softmax", "Softmax2d": "softmax"}.get(framework_kind, "activation")
        family, display, symbol = "activation", framework_kind, "diamond"
        fields = ("dim", "negative_slope", "inplace", "approximate", "alpha", "beta", "threshold", "value", "min_val", "max_val")
    elif isinstance(module, nn.modules.dropout._DropoutNd):
        visual_kind, family, display, symbol = "dropout", "dropout", "Dropout", "diamond"
        fields = ("p", "inplace")
    elif isinstance(module, known(*(f"{prefix}Pad{dim}d" for prefix in ("Constant", "Reflection", "Replication", "Zero", "Circular") for dim in (1, 2, 3)))):
        visual_kind, family, display, symbol = "padding", "padding", "Padding", "parallelogram"
        fields = ("padding", "value")
    elif isinstance(module, known("Upsample", "UpsamplingNearest2d", "UpsamplingBilinear2d")):
        visual_kind, family, display, symbol = "upsample", "reshape", "Upsample", "parallelogram"
        fields = ("size", "scale_factor", "mode", "align_corners", "recompute_scale_factor")
    elif isinstance(module, (nn.Flatten, nn.Unflatten)):
        visual_kind, family, display, symbol = "reshape", "reshape", framework_kind, "parallelogram"
        fields = ("start_dim", "end_dim", "dim", "unflattened_size")
    elif isinstance(module, nn.Identity):
        visual_kind, family, display = "identity", "identity", "Identity"
    elif isinstance(module, nn.Sequential):
        visual_kind, family, display = "sequential", "container", "Sequential"
    elif isinstance(module, known("ModuleList", "ModuleDict", "ParameterList", "ParameterDict")) or any(True for _ in module.children()):
        visual_kind, family, display = "container", "container", "Block"
    config = {}
    for field in fields:
        if hasattr(module, field):
            value = getattr(module, field)
            config[field] = value is not None if field == "bias" else _value(value)
    return _description(visual_kind, family, display, symbol, config)


# Exact operation aliases avoid false classifications such as ``normalize`` or
# ``conv_custom``. Keep the fine visual vocabulary separate from legacy families.
_OPERATION_GROUPS = (
    ("input", "input", "pill", "Input", "input placeholder"),
    ("output", "output", "pill", "Output", "output"),
    ("linear", "linear", "rectangle", "Linear", "linear"),
    ("bilinear", "linear", "rectangle", "Bilinear", "bilinear"),
    ("matmul", "linear", "rectangle", "Matrix multiplication", "mm bmm matmul mv dot vdot addmm baddbmm addmv addr einsum tensordot linalg_matmul linalg_multi_dot"),
    ("conv", "convolution", "hexagon", "Convolution", "convolution _convolution _convolution_mode convolution_overrideable conv1d conv2d conv3d conv_tbc cudnn_convolution miopen_convolution mkldnn_convolution slow_conv2d _slow_conv2d_forward slow_conv3d slow_conv_dilated2d slow_conv_dilated3d"),
    ("conv_transpose", "convolution", "hexagon", "Transposed convolution", "conv_transpose1d conv_transpose2d conv_transpose3d cudnn_convolution_transpose miopen_convolution_transpose slow_conv_transpose2d slow_conv_transpose3d"),
    ("attention", "attention", "ellipse", "Attention", "scaled_dot_product_attention _scaled_dot_product_flash_attention _scaled_dot_product_flash_attention_for_cpu _scaled_dot_product_efficient_attention _scaled_dot_product_cudnn_attention _native_multi_head_attention _triton_multi_head_attention multi_head_attention_forward"),
    ("layer_norm", "normalization", "pill", "Layer normalization", "layer_norm native_layer_norm"),
    ("batch_norm", "normalization", "pill", "Batch normalization", "batch_norm native_batch_norm _native_batch_norm_legit _native_batch_norm_legit_no_training _batch_norm_with_update _batch_norm_no_update _batch_norm_impl_index cudnn_batch_norm miopen_batch_norm"),
    ("group_norm", "normalization", "pill", "Group normalization", "group_norm native_group_norm"),
    ("instance_norm", "normalization", "pill", "Instance normalization", "instance_norm"),
    ("rms_norm", "normalization", "pill", "RMS normalization", "rms_norm"),
    ("relu", "activation", "diamond", None, "relu relu6"),
    ("gelu", "activation", "diamond", "GELU", "gelu"),
    ("sigmoid", "activation", "diamond", None, "sigmoid"),
    ("tanh", "activation", "diamond", None, "tanh"),
    ("softmax", "activation", "diamond", None, "softmax _softmax _safe_softmax softmax2d"),
    ("activation", "activation", "diamond", None, "silu mish elu celu selu softplus softsign hardswish threshold hardshrink softshrink tanhshrink glu leaky_relu prelu _prelu_kernel rrelu rrelu_with_noise hardsigmoid log_sigmoid log_sigmoid_forward hardtanh log_softmax _log_softmax softmin"),
    ("dropout", "dropout", "diamond", "Dropout", "dropout native_dropout _fused_dropout feature_dropout alpha_dropout feature_alpha_dropout"),
    ("pool", "pooling", "trapezoid", "Lp pooling", "lp_pool1d lp_pool2d lp_pool3d"),
    ("embedding", "embedding", "rectangle", "Embedding lookup", "embedding embedding_bag _embedding_bag _embedding_bag_forward_only"),
    ("recurrent", "recurrent", "rectangle", "Recurrent operation", "rnn_tanh rnn_relu gru lstm rnn_tanh_cell rnn_relu_cell gru_cell lstm_cell _thnn_fused_lstm_cell _thnn_fused_gru_cell _cudnn_rnn miopen_rnn"),
    ("concat", "merge", "parallelogram", "Concatenate", "cat concat concatenate hstack vstack dstack column_stack row_stack"),
    ("stack", "merge", "parallelogram", "Stack", "stack"),
    ("add", "merge", "circle", "Add", "add"),
    ("subtract", "merge", "circle", "Subtract", "sub subtract rsub"),
    ("negate", "merge", "circle", "Negate", "neg negative"),
    ("maximum", "merge", "circle", "Maximum", "maximum fmax"),
    ("minimum", "merge", "circle", "Minimum", "minimum fmin"),
    ("multiply", "merge", "circle", "Multiply", "mul multiply"),
    ("divide", "merge", "circle", "Divide", "div divide true_divide floor_divide"),
    ("transpose", "reshape", "parallelogram", "Transpose", "t transpose permute movedim moveaxis swapaxes swapdims adjoint mt mh transpose_copy permute_copy t_copy"),
    ("reshape", "reshape", "parallelogram", None, "view view_as view_copy _unsafe_view reshape reshape_as _reshape_alias _reshape_alias_copy flatten unflatten squeeze squeeze_copy unsqueeze unsqueeze_copy expand expand_as expand_copy broadcast_to broadcast_tensors repeat repeat_interleave tile as_strided as_strided_copy resize resize_as"),
    ("sum", "reduction", "trapezoid", None, "sum nansum sum_to_size"),
    ("mean", "reduction", "trapezoid", None, "mean nanmean"),
    ("reduction", "reduction", "trapezoid", None, "amax amin max min argmax argmin prod nanprod all any logsumexp norm linalg_norm linalg_vector_norm linalg_matrix_norm frobenius_norm nuclear_norm var std var_mean std_mean count_nonzero quantile nanquantile median nanmedian mode aminmax"),
    ("comparison", "control", "diamond", None, "gt lt ge le eq ne greater less greater_equal less_equal equal not_equal is_nonzero isfinite isinf isnan isin allclose logical_and logical_or logical_xor logical_not"),
    ("split", "indexing", "parallelogram", None, "split split_with_sizes split_with_sizes_copy split_copy chunk unbind unbind_copy tensor_split hsplit vsplit dsplit"),
    ("slice", "indexing", "parallelogram", None, "slice slice_copy narrow narrow_copy select select_copy diagonal diagonal_copy"),
    ("gather", "indexing", "parallelogram", None, "gather take take_along_dim index_select masked_select"),
    ("scatter", "indexing", "parallelogram", None, "scatter scatter_add scatter_reduce index_put _unsafe_index_put index_copy index_add index_reduce index_fill masked_scatter masked_fill select_scatter slice_scatter diagonal_scatter"),
    ("indexing", "indexing", "parallelogram", None, "index _unsafe_index __getitem__ getitem sort argsort topk searchsorted bucketize"),
    ("stop_gradient", "identity", "rectangle", "Stop gradient", "detach detach_copy"),
    ("copy", "identity", "rectangle", "Copy", "clone copy _to_copy to type_as contiguous _pin_memory pin_memory alias_copy lift_fresh_copy"),
    ("identity", "identity", "rectangle", "Identity", "alias identity positive lift lift_fresh"),
    ("padding", "padding", "parallelogram", "Padding", "pad constant_pad_nd _pad_circular"),
    ("upsample", "reshape", "parallelogram", "Interpolation", "interpolate"),
)
_OPERATION_TYPES = {alias: (kind, family, symbol, display)
                    for kind, family, symbol, display, aliases in _OPERATION_GROUPS for alias in aliases.split()}
for _dim in (1, 2, 3):
    for _prefix in ("max_pool", "adaptive_max_pool", "fractional_max_pool"):
        for _suffix in ("", "_with_indices"):
            _OPERATION_TYPES[f"{_prefix}{_dim}d{_suffix}"] = ("pool_max", "pooling", "trapezoid", "Max pooling")
    for _prefix in ("avg_pool", "adaptive_avg_pool", "_adaptive_avg_pool"):
        _OPERATION_TYPES[f"{_prefix}{_dim}d"] = ("pool_avg", "pooling", "trapezoid", "Average pooling")
    for _prefix in ("reflection", "replication", "circular"):
        _OPERATION_TYPES[f"{_prefix}_pad{_dim}d"] = ("padding", "padding", "parallelogram", "Padding")
    for _prefix in ("upsample_", "_upsample_"):
        for _mode in ("nearest", "nearest_exact", "linear", "bilinear", "bicubic", "trilinear"):
            for _suffix in ("", "_aa"):
                _OPERATION_TYPES[f"{_prefix}{_mode}{_dim}d{_suffix}"] = ("upsample", "reshape", "parallelogram", "Interpolation")

_OPERATION_LABELS = {
    "addmm": "Matrix multiply and add", "baddbmm": "Batched matrix multiply and add", "addmv": "Matrix vector multiply and add", "addr": "Outer product and add", "einsum": "Tensor contraction", "tensordot": "Tensor contraction", "dot": "Dot product", "vdot": "Dot product",
    "relu": "ReLU", "relu6": "ReLU6", "leaky_relu": "Leaky ReLU", "prelu": "PReLU", "_prelu_kernel": "PReLU", "rrelu": "RReLU", "rrelu_with_noise": "RReLU", "silu": "SiLU", "glu": "GLU", "elu": "ELU", "celu": "CELU", "selu": "SELU", "_softmax": "Softmax", "_safe_softmax": "Softmax", "_log_softmax": "Log softmax", "log_sigmoid_forward": "Log sigmoid",
    "rnn_tanh": "RNN", "rnn_relu": "RNN", "gru": "GRU", "lstm": "LSTM", "rnn_tanh_cell": "RNN cell", "rnn_relu_cell": "RNN cell", "gru_cell": "GRU cell", "lstm_cell": "LSTM cell",
    "rsub": "Reverse subtract", "neg": "Negate", "negative": "Negate", "floor_divide": "Floor divide", "permute": "Permute", "permute_copy": "Permute", "_unsafe_view": "View", "_reshape_alias": "Reshape", "_reshape_alias_copy": "Reshape", "view_copy": "View", "squeeze_copy": "Squeeze", "unsqueeze_copy": "Unsqueeze", "expand_copy": "Expand", "as_strided_copy": "Strided view",
    "gt": "Greater than", "lt": "Less than", "ge": "Greater or equal", "le": "Less or equal", "eq": "Equal", "ne": "Not equal", "fmax": "Maximum", "fmin": "Minimum", "__getitem__": "Index", "getitem": "Index", "_unsafe_index": "Index", "_unsafe_index_put": "Index put", "to": "Copy / cast", "type_as": "Copy / cast", "_to_copy": "Copy / cast",
}


def _operation_name(operation):
    """Accept dispatcher overloads, callable FX targets, and their string forms."""
    schema = getattr(operation, "_schema", None)
    if schema is not None:
        return schema.name.rsplit("::", 1)[-1]
    if callable(operation) and hasattr(operation, "__name__"):
        return operation.__name__
    text = str(operation)
    match = re.match(r"<(?:built-in (?:function|method)|function|method)\s+([\w]+)", text)
    if match:
        return match.group(1)
    if "::" in text:
        return text.rsplit("::", 1)[-1].split(".")[0]
    parts = text.split(".")
    for namespace in ("aten", "prims", "quantized", "mkldnn", "onednn", "mkl", "higher_order"):
        if namespace in parts and parts.index(namespace) + 1 < len(parts):
            return parts[parts.index(namespace) + 1]
    return parts[-1]


def describe_operation(operation, module=None):
    name = _operation_name(operation)
    lower = name.lower()
    if lower.endswith("_") and not lower.endswith("__"):
        lower = lower[:-1]
    visual_kind, family, symbol, display = _OPERATION_TYPES.get(lower, ("operation", "operation", "rectangle", None))
    display = _OPERATION_LABELS.get(lower, display) or lower.replace("_", " ").strip().capitalize() or "Operation"
    # max.other/min.other are elementwise; dimension overloads are reductions.
    schema = getattr(operation, "_schema", None)
    overload = getattr(schema, "overload_name", "") or str(operation).rsplit(".", 1)[-1]
    if lower in {"max", "min"} and overload == "other":
        visual_kind, family, symbol = "maximum" if lower == "max" else "minimum", "merge", "circle"
        display = "Maximum" if lower == "max" else "Minimum"
    config = {}
    if module is not None:
        description = describe_module(module)
        # Shared dispatcher kernels do not encode transposition in their name;
        # a known ConvTranspose scope supplies that structural fact.
        if lower in {"convolution", "_convolution", "convolution_overrideable"} and description["visual_kind"] == "conv_transpose":
            visual_kind = "conv_transpose"
        # Scope must not turn mul into Linear or addmm into a whole layer.
        if description["visual_kind"] == visual_kind and visual_kind not in {"operation", "custom", "container", "sequential", "identity", "copy", "stop_gradient"}:
            display, symbol, config = description["display_type"], description["shape_symbol"], description["config"]
    return _description(visual_kind, family, display, symbol, config)
