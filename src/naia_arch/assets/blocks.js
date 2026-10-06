/* NAIA's reusable visual vocabulary. No DOM, PyTorch, or project-name heuristics. */
(function (root, factory) {
  'use strict';
  const blocks = factory();
  if (typeof module === 'object' && module.exports) module.exports = blocks;
  else root.NAIABlocks = blocks;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  // Colour identifies a type, not its owner or position in a particular model.
  // Shape and pictogram remain usable without colour. Extend this list for new types.
  const rows = [
    ['input', 'Input', 'boundary', 'Data', '#729FC9', 'input', 'input', 'A supplied tensor or structured input.'],
    ['output', 'Output', 'boundary', 'Data', '#B29A76', 'output', 'output', 'A returned tensor or structured output.'],
    ['linear', 'Linear', 'linear', 'Layers', '#C3A06B', 'linear', 'linear', 'An affine feature projection; taper follows verified feature dimensions.'],
    ['bilinear', 'Bilinear', 'linear', 'Layers', '#B9946A', 'linear', 'bilinear', 'A learned interaction between two feature vectors.'],
    ['conv', 'Convolution', 'convolution', 'Layers', '#6D9FB3', 'conv', 'conv', 'A local learned filter; taper follows observed spatial dimensions.'],
    ['conv_transpose', 'Transposed convolution', 'convolution', 'Layers', '#7296B9', 'conv', 'conv_transpose', 'A transposed filter; expansion is shown only when supported by tensor sizes.'],
    ['attention', 'Attention', 'attention', 'Layers', '#9B89B5', 'attention', 'attention', 'Weighted mixing of values using query–key similarity.'],
    ['embedding', 'Embedding', 'embedding', 'Layers', '#869CBA', 'embedding', 'embedding', 'Lookup of learned vectors from discrete indices.'],
    ['recurrent', 'Recurrent', 'recurrent', 'Layers', '#AA8FA7', 'recurrent', 'recurrent', 'A layer that propagates a recurrent hidden state.'],
    ['padding', 'Padding', 'padding', 'Shapes', '#9EAC83', 'padding', 'padding', 'Adds border values without learning new semantic features.'],
    ['upsample', 'Upsampling', 'upsample', 'Shapes', '#81A9AE', 'upsample', 'upsample', 'Resamples spatial axes; direction is determined from observed sizes.'],
    ['layer_norm', 'Layer normalization', 'normalization', 'Normalization', '#75AB99', 'norm', 'layer_norm', 'Normalizes the configured trailing feature axes.'],
    ['batch_norm', 'Batch normalization', 'normalization', 'Normalization', '#84AD93', 'norm', 'batch_norm', 'Uses per-channel batch statistics in training.'],
    ['group_norm', 'Group normalization', 'normalization', 'Normalization', '#96AD88', 'norm', 'group_norm', 'Normalizes groups of channels within each sample.'],
    ['instance_norm', 'Instance normalization', 'normalization', 'Normalization', '#A3AD86', 'norm', 'instance_norm', 'Normalizes individual samples and channels.'],
    ['rms_norm', 'RMS normalization', 'normalization', 'Normalization', '#6EA397', 'norm', 'rms_norm', 'Rescales features by their root mean square.'],
    ['normalization', 'Normalization', 'normalization', 'Normalization', '#7AAB96', 'norm', 'normalization', 'A normalization layer whose specific variant is not classified.'],
    ['relu', 'ReLU', 'activation', 'Activations', '#C88B79', 'activation', 'relu', 'Rectifies negative activations.'],
    ['gelu', 'GELU', 'activation', 'Activations', '#C49086', 'activation', 'gelu', 'A smooth activation using Gaussian gating.'],
    ['sigmoid', 'Sigmoid', 'activation', 'Activations', '#BB8790', 'activation', 'sigmoid', 'Maps scalar values to the interval (0, 1).'],
    ['tanh', 'Tanh', 'activation', 'Activations', '#B28E99', 'activation', 'tanh', 'Maps scalar values to the interval (−1, 1).'],
    ['softmax', 'Softmax', 'activation', 'Activations', '#A992B0', 'activation', 'softmax', 'Normalizes exponentials along a configured axis.'],
    ['activation', 'Activation', 'activation', 'Activations', '#BC9580', 'activation', 'activation', 'A known nonlinear activation; inspect its recorded type and settings.'],
    ['dropout', 'Dropout', 'dropout', 'Layers', '#A39B79', 'dropout', 'dropout', 'Randomly masks activations in training, not during evaluation.'],
    ['pool_max', 'Max pooling', 'pooling', 'Pooling', '#8AACAE', 'pool', 'pool_max', 'Keeps the maximum value in each pooling region.'],
    ['pool_avg', 'Average pooling', 'pooling', 'Pooling', '#91B4A6', 'pool', 'pool_avg', 'Averages values within each pooling region.'],
    ['pool', 'Pooling', 'pooling', 'Pooling', '#82AAB1', 'pool', 'pool', 'Aggregates spatial regions; no downsampling is assumed without sizes.'],
    ['reshape', 'Reshape', 'reshape', 'Shapes', '#7AA8BA', 'reshape', 'reshape', 'Reinterprets axes; fewer axes do not imply less information.'],
    ['transpose', 'Transpose', 'reshape', 'Shapes', '#86A3BC', 'reshape', 'transpose', 'Reorders tensor axes, not the amount of data.'],
    ['concat', 'Concatenate', 'merge', 'Routing', '#AD9C72', 'merge', 'concat', 'Joins tensors along an existing axis.'],
    ['stack', 'Stack', 'merge', 'Routing', '#B39A82', 'merge', 'stack', 'Joins tensors by introducing a new axis.'],
    ['split', 'Split', 'indexing', 'Routing', '#A997B3', 'split', 'split', 'Separates one tensor into multiple pieces.'],
    ['slice', 'Slice', 'indexing', 'Routing', '#9198B8', 'indexing', 'slice', 'Selects a range of tensor entries.'],
    ['gather', 'Gather', 'indexing', 'Routing', '#849CAF', 'indexing', 'gather', 'Reads entries selected by indices.'],
    ['scatter', 'Scatter', 'indexing', 'Routing', '#82A2A4', 'indexing', 'scatter', 'Writes or accumulates entries at selected indices.'],
    ['indexing', 'Index selection', 'indexing', 'Routing', '#909BAD', 'indexing', 'indexing', 'Selects or rearranges entries using indices.'],
    ['add', 'Add', 'merge', 'Arithmetic', '#85AA8B', 'arithmetic', 'add', 'Elementwise addition; a residual update only when the graph establishes that role.'],
    ['subtract', 'Subtract', 'merge', 'Arithmetic', '#A1AB7D', 'arithmetic', 'subtract', 'Elementwise subtraction.'],
    ['multiply', 'Multiply', 'merge', 'Arithmetic', '#C19B77', 'arithmetic', 'multiply', 'Elementwise multiplication, distinct from matrix multiplication.'],
    ['divide', 'Divide', 'merge', 'Arithmetic', '#BA8D7B', 'arithmetic', 'divide', 'Elementwise division.'],
    ['negate', 'Negate', 'merge', 'Arithmetic', '#B99883', 'arithmetic', 'negate', 'Unary negation, not a two-input subtraction.'],
    ['maximum', 'Maximum', 'merge', 'Arithmetic', '#97AD7F', 'merge', 'maximum', 'Elementwise maximum of inputs, not a Boolean comparison or axis reduction.'],
    ['minimum', 'Minimum', 'merge', 'Arithmetic', '#A6AD8D', 'merge', 'minimum', 'Elementwise minimum of inputs, not an axis reduction.'],
    ['matmul', 'Matrix multiplication', 'linear', 'Arithmetic', '#B99D62', 'linear', 'matmul', 'Contracts tensor axes by matrix multiplication.'],
    ['sum', 'Sum', 'reduction', 'Reductions', '#BAA179', 'reduction', 'sum', 'Sums over one or more tensor axes.'],
    ['mean', 'Mean', 'reduction', 'Reductions', '#AAA87D', 'reduction', 'mean', 'Averages over one or more tensor axes.'],
    ['reduction', 'Reduction', 'reduction', 'Reductions', '#9FAC87', 'reduction', 'reduction', 'Aggregates one or more axes; inspect the recorded operation.'],
    ['comparison', 'Comparison', 'control', 'Arithmetic', '#B3A1AA', 'comparison', 'comparison', 'A comparison or scalar control operation, not an inferred neural layer.'],
    ['stop_gradient', 'Stop gradient', 'identity', 'Control', '#B58584', 'stop', 'stop_gradient', 'Keeps tensor values while detaching their gradient path.'],
    ['copy', 'Copy', 'identity', 'Control', '#90A5AD', 'copy', 'copy', 'Copies or converts a tensor; inspect dtype and device metadata.'],
    ['identity', 'Identity', 'identity', 'Control', '#91A69E', 'identity', 'identity', 'Passes the tensor through without a learned transform.'],
    ['sequential', 'Sequential', 'container', 'Groups', '#97A6B1', 'container', 'sequential', 'Owns a sequence of modules; arrows still require execution evidence.'],
    ['container', 'Block', 'container', 'Groups', '#929CAB', 'container', 'container', 'A module ownership group, not evidence of a particular computation.'],
    ['custom', 'Custom operation', 'operation', 'Other', '#93989F', 'custom', 'custom', 'An unclassified custom layer. Its name is not used to guess what it does.'],
    ['operation', 'Operation', 'operation', 'Other', '#A49A94', 'custom', 'operation', 'A recorded tensor operation not yet covered by this catalogue.'],
    ['encoder', 'Encoder', 'container', 'Groups', '#8B9EBE', 'container', 'encoder', 'An explicitly declared encoding block; taper requires verified size change.'],
    ['projector', 'Projector', 'linear', 'Groups', '#BDAC7F', 'linear', 'projector', 'An explicitly declared feature projection.'],
    ['predictor', 'Predictor', 'container', 'Groups', '#A48DA4', 'container', 'predictor', 'An explicitly declared prediction block.'],
    ['tokens', 'Tokens', 'data', 'Data', '#81A7B9', 'embedding', 'tokens', 'A structured set of latent vectors.'],
    ['parameter', 'Learned parameter', 'data', 'Data', '#9FA3B4', 'embedding', 'parameter', 'A learned tensor, distinct from a runtime input.'],
    ['budget', 'Budget selection', 'indexing', 'Routing', '#B4AC86', 'indexing', 'budget', 'Selects the explicitly declared token budget.'],
    ['memory', 'Memory', 'data', 'Data', '#8AA79C', 'memory', 'memory', 'An explicitly declared stored context or state.'],
    ['loss', 'Loss', 'reduction', 'Objectives', '#B29489', 'loss', 'loss', 'An explicitly declared training objective.'],
    ['position', 'Position embedding', 'embedding', 'Data', '#A0A1B8', 'embedding', 'position', 'A learned or fixed positional signal, when explicitly declared.'],
  ];
  const catalog = Object.freeze(rows.map(([id, label, family, category, color, shape, icon, description]) =>
    Object.freeze({ id, label, family, category, color, shape, icon, description })));
  const byId = new Map(catalog.map(entry => [entry.id, entry]));

  const operations = {
    add: 'add', sub: 'subtract', subtract: 'subtract', mul: 'multiply', multiply: 'multiply', div: 'divide', divide: 'divide',
    neg: 'negate', negative: 'negate', maximum: 'maximum', minimum: 'minimum', fmax: 'maximum', fmin: 'minimum',
    linear: 'linear', addmm: 'matmul', mm: 'matmul', bmm: 'matmul', matmul: 'matmul', mv: 'matmul', dot: 'matmul', baddbmm: 'matmul',
    cat: 'concat', concat: 'concat', concatenate: 'concat', stack: 'stack', split: 'split', split_with_sizes: 'split', chunk: 'split', unbind: 'split',
    view: 'reshape', reshape: 'reshape', flatten: 'reshape', unflatten: 'reshape', squeeze: 'reshape', unsqueeze: 'reshape', expand: 'reshape', expand_as: 'reshape',
    permute: 'transpose', transpose: 'transpose', t: 'transpose',
    slice: 'slice', select: 'slice', narrow: 'slice', gather: 'gather', scatter: 'scatter', scatter_add: 'scatter',
    index: 'indexing', index_select: 'indexing', index_put: 'scatter',
    sum: 'sum', mean: 'mean', amax: 'reduction', amin: 'reduction', argmax: 'reduction', argmin: 'reduction', prod: 'reduction', max: 'reduction', min: 'reduction',
    detach: 'stop_gradient', clone: 'copy', copy: 'copy', _to_copy: 'copy', to: 'copy', alias: 'identity',
    gt: 'comparison', lt: 'comparison', ge: 'comparison', le: 'comparison', eq: 'comparison', ne: 'comparison',
    relu: 'relu', relu6: 'relu', gelu: 'gelu', sigmoid: 'sigmoid', tanh: 'tanh', softmax: 'softmax', _softmax: 'softmax', log_softmax: 'activation', _log_softmax: 'activation',
    silu: 'activation', mish: 'activation', leaky_relu: 'activation', softplus: 'activation', hardswish: 'activation',
    convolution: 'conv', conv1d: 'conv', conv2d: 'conv', conv3d: 'conv', conv_transpose1d: 'conv_transpose', conv_transpose2d: 'conv_transpose', conv_transpose3d: 'conv_transpose',
    layer_norm: 'layer_norm', native_layer_norm: 'layer_norm', batch_norm: 'batch_norm', native_batch_norm: 'batch_norm', group_norm: 'group_norm', native_group_norm: 'group_norm', instance_norm: 'instance_norm', rms_norm: 'rms_norm',
    embedding: 'embedding', embedding_bag: 'embedding', dropout: 'dropout', native_dropout: 'dropout',
    scaled_dot_product_attention: 'attention', _scaled_dot_product_flash_attention: 'attention', _scaled_dot_product_flash_attention_for_cpu: 'attention',
  };
  const modules = {
    Linear: 'linear', LazyLinear: 'linear', Bilinear: 'bilinear', MultiheadAttention: 'attention',
    Embedding: 'embedding', EmbeddingBag: 'embedding',
    LayerNorm: 'layer_norm', BatchNorm1d: 'batch_norm', BatchNorm2d: 'batch_norm', BatchNorm3d: 'batch_norm', SyncBatchNorm: 'batch_norm',
    LazyBatchNorm1d: 'batch_norm', LazyBatchNorm2d: 'batch_norm', LazyBatchNorm3d: 'batch_norm',
    GroupNorm: 'group_norm', InstanceNorm1d: 'instance_norm', InstanceNorm2d: 'instance_norm', InstanceNorm3d: 'instance_norm', RMSNorm: 'rms_norm',
    ReLU: 'relu', ReLU6: 'relu', GELU: 'gelu', Sigmoid: 'sigmoid', Tanh: 'tanh', Softmax: 'softmax', Softmax2d: 'softmax', LogSoftmax: 'activation', Softmin: 'activation',
    SiLU: 'activation', Mish: 'activation', ELU: 'activation', LeakyReLU: 'activation', PReLU: 'activation', Hardswish: 'activation', Softplus: 'activation',
    Dropout: 'dropout', Dropout1d: 'dropout', Dropout2d: 'dropout', Dropout3d: 'dropout', AlphaDropout: 'dropout', FeatureAlphaDropout: 'dropout',
    Flatten: 'reshape', Unflatten: 'reshape', Identity: 'identity', Sequential: 'sequential', ModuleList: 'container', ModuleDict: 'container',
    RNN: 'recurrent', LSTM: 'recurrent', GRU: 'recurrent', RNNCell: 'recurrent', LSTMCell: 'recurrent', GRUCell: 'recurrent', Upsample: 'upsample',
  };
  const families = { linear: 'linear', projection: 'projector', convolution: 'conv', attention: 'attention', normalization: 'normalization',
    embedding: 'embedding', pooling: 'pool', activation: 'activation', dropout: 'dropout', reshape: 'reshape', reduction: 'reduction',
    indexing: 'indexing', identity: 'identity', control: 'comparison', container: 'container', operation: 'operation', padding: 'padding', upsample: 'upsample', recurrent: 'recurrent' };
  function operationName(value) {
    const raw = String(value || ''), callable = /^<(?:built-in (?:function|method)|function|method)\s+(\w+)/.exec(raw);
    if (callable) return callable[1];
    if (raw.includes('::')) return raw.split('::').at(-1).split('.')[0].replace(/_$/, '');
    const parts = raw.replace(/^torch\.ops\./, '').split('.');
    for (const space of ['aten', 'prims', 'quantized', 'mkldnn', 'onednn', 'mkl', 'higher_order']) {
      const index = parts.indexOf(space);
      if (index >= 0) return String(parts[index + 1] || '').replace(/_$/, '');
    }
    return parts.at(-1).replace(/_$/, '');
  }
  function kind(node) {
    if (node.kind === 'input' || node.type === 'placeholder') return 'input';
    if (node.kind === 'output' || node.type === 'output') return 'output';
    if (byId.has(node.visual_kind)) return node.visual_kind;
    if (node.visual_kind) return 'custom';
    if (node.operation) {
      const name = operationName(node.operation);
      if (['max', 'min'].includes(name) && String(node.operation).endsWith('.other')) return name === 'max' ? 'maximum' : 'minimum';
      if (operations[name]) return operations[name];
      if (/^(adaptive_)?max_pool[123]d(_with_indices)?$/.test(name)) return 'pool_max';
      if (/^(adaptive_)?avg_pool[123]d$/.test(name)) return 'pool_avg';
      if (/^upsample_(nearest|linear|bilinear|bicubic|trilinear)[123]d$/.test(name)) return 'upsample';
    }
    const rawType = String(node.type || '');
    const type = !rawType || /^call_(module|function|method)$/.test(rawType) ? String(node.display_type || rawType) : rawType;
    if (modules[type]) return modules[type];
    if (/^(Lazy)?Conv[123]d$/.test(type)) return 'conv';
    if (/^(Lazy)?ConvTranspose[123]d$/.test(type)) return 'conv_transpose';
    if (/^(Adaptive|Fractional)?MaxPool[123]d$/.test(type)) return 'pool_max';
    if (/^(Adaptive)?AvgPool[123]d$/.test(type)) return 'pool_avg';
    if (/^(Reflection|Replication|Zero|Constant|Circular)Pad[123]d$/.test(type)) return 'padding';
    if (!node.operation && node.family === 'operation' && type && !/^call_/.test(type)) return 'custom';
    // Legacy metadata has reliable families even when the raw class is custom.
    if (node.family && families[node.family]) return families[node.family];
    if (node.kind === 'module') return 'custom';
    return 'operation';
  }
  function shapes(value, found = [], depth = 0) {
    if (depth > 10 || value == null || found.length > 8) return found;
    if (typeof value !== 'object') return found;
    if (Array.isArray(value.shape)) found.push(value.shape);
    else if (Array.isArray(value) && value.every(v => Number.isFinite(v))) found.push(value);
    else Object.values(value).forEach(child => shapes(child, found, depth + 1));
    return found;
  }
  function singleShape(value) {
    const found = shapes(value);
    return found.length === 1 && found[0].length && found[0].every(v => Number.isInteger(v) && v > 0) ? found[0] : null;
  }
  function resolve(node = {}, metadata = {}) {
    const entry = byId.get(kind(node)), config = node.config || {};
    const result = { ...entry, title: entry.label, dimensional_change: null };
    // The capture backend supplies framework-derived names, not module aliases.
    // Preserve known subtypes (GRU, SiLU, LogSoftmax, etc.) without guessing custom ones.
    if (node.visual_kind === entry.id && !['input', 'output', 'container', 'custom', 'operation'].includes(entry.id)
        && typeof node.display_type === 'string' && node.display_type.trim() && node.display_type.length <= 80
        && !/[\x00-\x1f\x7f]/.test(node.display_type)) result.title = node.display_type.trim();
    const input = singleShape(metadata.inputs ?? node.inputs), output = singleShape(metadata.outputs ?? node.outputs);
    let a, b, axis;
    if (['linear', 'projector'].includes(entry.id)) {
      if (input && output && input.length === output.length && input.slice(0, -1).every((v, i) => v === output[i])) {
        a = input.at(-1); b = output.at(-1);
      } else if (!input && !output && Number.isInteger(config.in_features) && config.in_features > 0
          && Number.isInteger(config.out_features) && config.out_features > 0) {
        a = config.in_features; b = config.out_features;
      }
      if (a && b) { axis = 'Features'; result.title += ' ' + a + ' → ' + b; }
    } else if (['conv', 'conv_transpose', 'pool', 'pool_max', 'pool_avg', 'upsample', 'encoder'].includes(entry.id)) {
      if (input && output && input.length === output.length && input.length >= 3 && input[0] === output[0]) {
        const before = input.slice(2), after = output.slice(2);
        const directions = after.map((v, i) => Math.sign(v - before[i]));
        if (directions.every(v => v <= 0) || directions.every(v => v >= 0)) {
          a = before.reduce((p, v) => p * v, 1); b = after.reduce((p, v) => p * v, 1);
          axis = 'Spatial ' + before.join(' × ') + ' → ' + after.join(' × ');
        }
      }
      const spatial = /^Conv(?:Transpose)?([123])d$/.exec(String(node.type || '').replace(/^Lazy/, ''));
      if (spatial && !/\b[123]d\b/.test(result.title)) result.title += ' ' + spatial[1] + 'd';
      if (['conv', 'conv_transpose'].includes(entry.id) && config.kernel_size != null) {
        const kernel = Array.isArray(config.kernel_size) ? config.kernel_size : [config.kernel_size];
        if (kernel.every(v => Number.isInteger(v) && v > 0)) result.title += ' ' + kernel.join('×');
      }
    }
    if (a && b) {
      result.dimensional_change = axis === 'Features' ? axis + ' ' + a + ' → ' + b : axis;
      if (a !== b) result.shape = b > a ? 'expand' : 'contract';
    }
    return result;
  }

  function outline(shape, w, h) {
    if (!(Number.isFinite(w) && w > 0 && Number.isFinite(h) && h > 0)) throw Error('Positive finite glyph dimensions required');
    const r = Math.min(12, w * .12, h * .2), k = Math.min(w * .13, h * .24);
    const round = `M ${r} 0 H ${w - r} Q ${w} 0 ${w} ${r} V ${h - r} Q ${w} ${h} ${w - r} ${h} H ${r} Q 0 ${h} 0 ${h - r} V ${r} Q 0 0 ${r} 0 Z`;
    switch (shape) {
      case 'contract': return `M 0 0 L ${w} ${h * .16} L ${w} ${h * .84} L 0 ${h} Z`;
      case 'expand': return `M 0 ${h * .16} L ${w} 0 L ${w} ${h} L 0 ${h * .84} Z`;
      case 'input': return `M 0 ${r} Q 0 0 ${r} 0 H ${w - k} L ${w} ${h / 2} L ${w - k} ${h} H ${r} Q 0 ${h} 0 ${h - r} Z`;
      case 'output': return `M ${k} 0 H ${w - r} Q ${w} 0 ${w} ${r} V ${h - r} Q ${w} ${h} ${w - r} ${h} H ${k} L 0 ${h / 2} Z`;
      case 'conv': return `M ${k} 0 H ${w - k} L ${w} ${h / 2} L ${w - k} ${h} H ${k} L 0 ${h / 2} Z`;
      case 'linear': return `M ${k} 0 H ${w - k} L ${w} ${k} V ${h - k} L ${w - k} ${h} H ${k} L 0 ${h - k} V ${k} Z`;
      case 'attention': { const q = Math.min(w * .25, h * .24); return `M ${q} 0 H ${w - q} Q ${w} 0 ${w} ${h / 2} Q ${w} ${h} ${w - q} ${h} H ${q} Q 0 ${h} 0 ${h / 2} Q 0 0 ${q} 0 Z`; }
      case 'norm': return `M ${r} 0 H ${w - r} Q ${w} 0 ${w} ${r} V ${h - r} Q ${w} ${h} ${w - r} ${h} H ${r} Q 0 ${h} 0 ${h - r} V ${r} Q 0 0 ${r} 0 Z M ${k} 0 V ${h} M ${w - k} 0 V ${h}`;
      case 'activation': return `M ${k} 0 H ${w - r} Q ${w} 0 ${w} ${r} V ${h - r} Q ${w} ${h} ${w - r} ${h} H ${k} L 0 ${h / 2} Z`;
      case 'arithmetic': return `M 0 ${h / 2} C 0 0 ${w} 0 ${w} ${h / 2} C ${w} ${h} 0 ${h} 0 ${h / 2} Z`;
      case 'merge': return `M 0 0 L ${w - k} 0 L ${w} ${h / 2} L ${w - k} ${h} L 0 ${h} L ${k} ${h / 2} Z`;
      case 'split': return `M ${k} 0 L ${w} 0 L ${w - k} ${h / 2} L ${w} ${h} L ${k} ${h} L 0 ${h / 2} Z`;
      case 'reshape': return `M ${k} 0 L ${w} 0 L ${w - k} ${h} L 0 ${h} Z`;
      case 'indexing': return `M ${k} 0 H ${w} V ${h} H ${k} L 0 ${h / 2} Z M ${w - k} 0 V ${h}`;
      case 'pool': case 'reduction': return `M 0 0 H ${w} V ${h} H 0 Z M ${w * .12} ${h * .14} L ${w * .12} ${h * .86} M ${w * .88} ${h * .14} V ${h * .86}`;
      case 'memory': case 'embedding': return `M 0 ${r} Q ${w / 2} 0 ${w} ${r} V ${h - r} Q ${w / 2} ${h} 0 ${h - r} Z M 0 ${r} Q ${w / 2} ${r * 2} ${w} ${r}`;
      case 'loss': case 'comparison': return `M ${k} 0 H ${w - k} L ${w} ${h / 2} L ${w - k} ${h} H ${k} L 0 ${h / 2} Z`;
      case 'stop': return `M ${k} 0 H ${w - k} L ${w} ${k} V ${h - k} L ${w - k} ${h} H ${k} L 0 ${h - k} V ${k} Z`;
      case 'dropout': return round + ` M ${k} ${h * .2} V ${h * .8} M ${w - k} ${h * .2} V ${h * .8}`;
      case 'padding': return round + ` M ${k} ${h * .18} H ${w - k} V ${h * .82} H ${k} Z`;
      case 'recurrent': return round + ` M ${k} 0 V ${h} M ${w - k} 0 V ${h}`;
      case 'copy': return round + ` M ${k} ${h * .12} H ${w - k} V ${h * .88}`;
      case 'custom': return round + ` M ${w * .1} ${h * .12} H ${w * .2} M ${w * .8} ${h * .88} H ${w * .9}`;
      default: return round;
    }
  }

  const icons = {
    input: ['M3 5H12V19H3Z M9 12H21 M17 8L21 12L17 16'],
    output: ['M12 5H21V19H12Z M3 12H15 M11 8L15 12L11 16'],
    linear: ['M4 5V19 M20 5V19 M4 6L20 9 M4 12H20 M4 18L20 15'],
    bilinear: ['M3 5V10 M3 14V19 M21 7V17 M3 7L21 12 M3 17L21 12'],
    conv: ['M3 3H17V17H3Z M7 3V17 M12 3V17 M3 7H17 M3 12H17 M12 12H21V21H12Z'],
    conv_transpose: ['M7 7H21V21H7Z M11 7V21 M16 7V21 M7 11H21 M7 16H21 M3 3H12V12H3Z'],
    attention: ['M3 4H7V8H3Z M3 16H7V20H3Z M17 10H21V14H17Z M7 6L17 12 M7 18L17 12 M7 12H17'],
    embedding: ['M3 3H10V21H3Z M3 9H10 M3 15H10 M13 5H21 M13 12H18 M13 19H20'],
    recurrent: ['M6 6C18 0 24 14 16 18 M18 15L16 18L20 19 M18 18C6 24 0 10 8 6 M4 5L8 6L6 9'],
    layer_norm: ['M5 3H3V21H5 M19 3H21V21H19 M7 12H17 M9 7V17 M15 7V17'],
    batch_norm: ['M5 3H3V21H5 M19 3H21V21H19 M7 7H17 M7 12H17 M7 17H17'],
    group_norm: ['M5 3H3V21H5 M19 3H21V21H19 M7 6V18 M10 6V18 M14 6V18 M17 6V18'],
    instance_norm: ['M5 3H3V21H5 M19 3H21V21H19 M7 7H10V17H7Z M14 7H17V17H14Z'],
    rms_norm: ['M5 3H3V21H5 M19 3H21V21H19 M7 13L10 17L13 7H17'],
    normalization: ['M5 3H3V21H5 M19 3H21V21H19 M7 9H17 M7 15H17'],
    relu: ['M3 4V20H21 M3 15H12L20 6'],
    gelu: ['M3 4V20H21 M3 15C8 15 9 19 12 14L20 5'],
    sigmoid: ['M3 4V20H21 M3 17C15 17 8 7 21 7'],
    tanh: ['M3 12H21 M12 3V21 M3 18C15 18 9 6 21 6'],
    softmax: ['M4 16V20 M9 11V20 M14 5V20 M19 14V20 M3 3H21'],
    activation: ['M3 4V20H21 M3 14Q7 3 12 13T21 6'],
    dropout: ['M4 4H8V8H4Z M16 4H20V8H16Z M10 10H14V14H10Z M4 16H8V20H4Z M16 16H20V20H16Z M3 21L21 3'],
    pool_max: ['M3 3H21V21H3Z M3 9H21 M3 15H21 M9 3V21 M15 3V21 M10 10H14V14H10Z'],
    pool_avg: ['M3 3H21V21H3Z M3 9H21 M3 15H21 M9 3V21 M15 3V21 M7 12H17'],
    pool: ['M3 4L12 10L21 4 M12 10V20 M8 16L12 20L16 16'],
    reshape: ['M3 3H10V10H3Z M14 14H21V21H14Z M14 5H20V11 M20 5L13 12 M4 14V20H10 M4 20L11 13'],
    transpose: ['M3 5H19L15 2 M19 5L15 8 M5 21V5 M5 21L2 17 M5 21L8 17'],
    concat: ['M3 5H8L14 12 M3 19H8L14 12 M14 12H21 M18 9L21 12L18 15'],
    stack: ['M3 5H9V11H3Z M3 14H9V20H3Z M15 4H21V10H15Z M13 7H19V13H13Z M11 10H17V16H11Z'],
    split: ['M3 12H10L16 5H21 M10 12L16 19H21 M18 2L21 5L18 8 M18 16L21 19L18 22'],
    slice: ['M3 5H21V19H3Z M9 5V19 M15 5V19 M9 3H15V21H9Z'],
    gather: ['M3 5H7 M3 12H7 M3 19H7 M7 5L17 12 M7 12H17 M7 19L17 12 M17 9H21V15H17Z'],
    scatter: ['M3 9H7V15H3Z M7 12L17 5 M7 12H17 M7 12L17 19 M17 3H21V7H17Z M17 10H21V14H17Z M17 17H21V21H17Z'],
    indexing: ['M3 4H17V20H3Z M3 9H17 M3 15H17 M14 12H22 M18 8L22 12L18 16'],
    add: ['M12 4V20 M4 12H20'],
    subtract: ['M4 12H20'],
    multiply: ['M5 5L19 19 M19 5L5 19'],
    divide: ['M4 12H20 M11 5H13 M11 19H13'],
    negate: ['M3 12H10 M14 5H21V19H14Z M16 12H19'],
    maximum: ['M3 18L9 12L13 16L21 5 M17 5H21V9'],
    minimum: ['M3 6L9 12L13 8L21 19 M17 19H21V15'],
    matmul: ['M4 3H2V21H4 M20 3H22V21H20 M7 7H9V9H7Z M15 7H17V9H15Z M7 15H9V17H7Z M15 15H17V17H15Z M10 10L14 14 M14 10L10 14'],
    sum: ['M20 4H5L13 12L5 20H20'],
    mean: ['M4 5H20 M6 9L18 19 M18 9L6 19'],
    reduction: ['M3 5L12 11L21 5 M12 11V20 M8 16L12 20L16 16 M6 2H18'],
    comparison: ['M4 8H10 M4 16H10 M14 5L21 12L14 19'],
    stop_gradient: ['M4 12H10 M14 12H20 M10 4V20 M14 4V20'],
    copy: ['M3 3H16V16H3Z M8 8H21V21H8Z'],
    identity: ['M3 12H21 M17 8L21 12L17 16'],
    sequential: ['M2 8H7V16H2Z M10 8H15V16H10Z M18 8H23V16H18Z M7 12H10 M15 12H18'],
    container: ['M3 4H21V20H3Z M7 8H17V16H7Z'],
    custom: ['M8 5C9 1 18 2 18 8C18 12 12 11 12 16 M11 21H13'],
    operation: ['M4 4H20V20H4Z M8 8L16 16 M16 8L8 16'],
    padding: ['M3 3H21V21H3Z M7 7H17V17H7Z M3 12H7 M17 12H21 M12 3V7 M12 17V21'],
    upsample: ['M9 3H3V9 M3 3L10 10 M15 3H21V9 M21 3L14 10 M3 15V21H9 M3 21L10 14 M15 21H21V15 M21 21L14 14'],
    encoder: ['M3 3V21 M21 7V17 M3 4L21 8 M3 12H21 M3 20L21 16'],
    projector: ['M3 7V17 M21 3V21 M3 8L21 4 M3 12H21 M3 16L21 20'],
    predictor: ['M3 5H10V19H3Z M14 5H21V19H14Z M10 12H14 M11 9L14 12L11 15'],
    tokens: ['M3 4H8V20H3Z M10 4H15V20H10Z M17 4H22V20H17Z'],
    parameter: ['M3 5H21V19H3Z M7 9L10 15L14 9L17 15'],
    budget: ['M3 4H8V20H3Z M10 4H15V20H10Z M18 6V18 M21 6V18 M2 2H16V22H2Z'],
    memory: ['M3 6Q12 1 21 6V18Q12 23 3 18Z M3 6Q12 11 21 6 M3 12Q12 17 21 12'],
    loss: ['M3 4V20H21 M6 7L11 14L17 10L21 15'],
    position: ['M3 18V6 M8 18V9 M13 18V4 M18 18V11 M2 21H22'],
  };
  function iconPaths(icon) { return [...(icons[icon] || icons.custom)]; }
  return Object.freeze({ catalog, resolve, outline, iconPaths });
});
