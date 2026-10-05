"""Real tensor-flow regressions; hierarchy alone must never imply execution."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from naia_arch import capture, validate_graph


def reachable(graph, source, target):
    next_nodes = {}
    for edge in graph["edges"]:
        next_nodes.setdefault(edge["source"], []).append(edge["target"])
    todo, seen = [source], set()
    while todo:
        current = todo.pop()
        if current == target:
            return True
        if current not in seen:
            seen.add(current)
            todo.extend(next_nodes.get(current, []))
    return False


class FlowSchemaTest(unittest.TestCase):
    def test_runtime_evidence_is_valid_without_torch(self):
        graph = {"schema_version": 1,
                 "nodes": [{"id": "x", "parent": None}, {"id": "y", "parent": None}],
                 "edges": [{"source": "x", "target": "y", "evidence": "observed"}],
                 "dataflow": {"engine": "torch_dispatch", "nodes": ["x", "y"], "complete": True}}
        self.assertIs(validate_graph(graph), graph)
        graph["dataflow"]["nodes"] = ["missing"]
        with self.assertRaises(ValueError):
            validate_graph(graph)


@unittest.skipUnless(importlib.util.find_spec("torch"), "Tensor flow needs a PyTorch environment")
class TensorFlowTest(unittest.TestCase):
    def test_default_capture_connects_real_inputs_layers_and_outputs(self):
        import torch
        model = torch.nn.Sequential(torch.nn.Linear(4, 8), torch.nn.ReLU(), torch.nn.Linear(8, 2))
        graph = capture(model, (torch.zeros(3, 4),))
        self.assertEqual(graph["dataflow"]["engine"], "torch_dispatch")
        self.assertTrue(graph["dataflow"]["complete"])
        self.assertTrue(graph["edges"])
        self.assertEqual({e["evidence"] for e in graph["edges"]}, {"observed"})
        inputs = [n for n in graph["nodes"] if n.get("kind") == "input"]
        outputs = [n for n in graph["nodes"] if n.get("kind") == "output"]
        self.assertEqual(len(inputs), 1)
        self.assertEqual(len(outputs), 1)
        self.assertTrue(reachable(graph, inputs[0]["id"], outputs[0]["id"]))
        linear = next(n for n in graph["nodes"] if n["id"] == "module:0")
        self.assertIn("Linear", linear["label"])
        self.assertEqual(linear["config"]["in_features"], 4)
        self.assertEqual(linear["config"]["out_features"], 8)
        self.assertEqual(linear["outputs"]["shape"], [3, 8])
        self.assertTrue(linear.get("shape_symbol"))
        self.assertEqual(capture(model, (torch.zeros(2, 4),))["nodes"][1]["outputs"]["shape"], [2, 8])

    def test_data_dependent_branch_records_only_executed_path(self):
        import torch
        class Branch(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.positive = torch.nn.Linear(4, 2)
                self.negative = torch.nn.Linear(4, 2)
            def forward(self, x):
                return self.positive(x) if x.sum().item() > 0 else self.negative(x)
        for value, active, inactive in [(1., "positive", "negative"), (-1., "negative", "positive")]:
            graph = capture(Branch(), (torch.full((2, 4), value),))
            operations = [n for n in graph["nodes"] if n.get("kind") == "operation"]
            self.assertTrue(any(n.get("module_path") == active for n in operations))
            self.assertFalse(any(n.get("module_path") == inactive for n in operations))
            self.assertTrue(graph["dataflow"]["complete"])

    def test_parallel_branches_concat_and_residual_are_not_a_fake_chain(self):
        import torch
        class Branches(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.left = torch.nn.Linear(4, 4)
                self.right = torch.nn.Linear(4, 4)
                self.output = torch.nn.Linear(8, 4)
            def forward(self, x):
                left, right = self.left(x), self.right(x)
                return self.output(torch.cat((left, right), dim=-1)) + x
        graph = capture(Branches(), (torch.zeros(2, 4),))
        operations = [n for n in graph["nodes"] if n.get("kind") == "operation"]
        left = [n for n in operations if n.get("module_path") == "left"][-1]
        right = [n for n in operations if n.get("module_path") == "right"][-1]
        concat = next(n for n in operations if "cat" in n.get("operation", ""))
        self.assertFalse(reachable(graph, left["id"], right["id"]))
        self.assertFalse(reachable(graph, right["id"], left["id"]))
        self.assertTrue(reachable(graph, left["id"], concat["id"]))
        self.assertTrue(reachable(graph, right["id"], concat["id"]))
        self.assertEqual(concat["outputs"]["shape"], [2, 8])
        output = next(n for n in graph["nodes"] if n.get("kind") == "output")
        source = next(n for n in graph["nodes"] if n.get("kind") == "input")
        self.assertTrue(reachable(graph, source["id"], output["id"]))

    def test_repeated_module_uses_distinct_operation_instances(self):
        import torch
        class Repeated(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.shared = torch.nn.Linear(4, 4)
            def forward(self, x):
                return self.shared(self.shared(x))
        graph = capture(Repeated(), (torch.zeros(2, 4),))
        operations = [n for n in graph["nodes"] if n.get("kind") == "operation" and n.get("module_path") == "shared"]
        self.assertEqual({n.get("call") for n in operations}, {1, 2})
        self.assertEqual(len({n["id"] for n in operations}), len(operations))
        self.assertFalse(any(e["source"] == e["target"] for e in graph["edges"]))

    def test_view_inplace_mutation_retains_real_storage_dependency(self):
        import torch
        class Inplace(torch.nn.Module):
            def forward(self, x):
                y = x.clone()
                y.view(-1).add_(2)
                return y * 3
        graph = capture(Inplace(), (torch.zeros(2, 4),))
        operations = [n for n in graph["nodes"] if n.get("kind") == "operation"]
        add = next(n for n in operations if "add_" in n.get("operation", ""))
        mul = next(n for n in operations if "mul" in n.get("operation", ""))
        self.assertTrue(reachable(graph, add["id"], mul["id"]))

    def test_capture_isolated_and_budget_truncation_explicit(self):
        import torch
        model = torch.nn.Sequential(torch.nn.Linear(4, 8), torch.nn.Dropout(), torch.nn.Linear(8, 2))
        weights = {key: value.clone() for key, value in model.state_dict().items()}
        rng = torch.get_rng_state().clone()
        sample = torch.zeros(2, 4)
        graph = capture(model, (sample,), max_nodes=1)
        self.assertTrue(model.training)
        self.assertTrue(torch.equal(rng, torch.get_rng_state()))
        self.assertTrue(all(torch.equal(value, model.state_dict()[key]) for key, value in weights.items()))
        self.assertTrue(torch.equal(sample, torch.zeros(2, 4)))
        self.assertFalse(graph["dataflow"]["complete"])
        self.assertTrue(any("budget" in warning.lower() for warning in graph["warnings"]))

    def test_alias_and_structure_only_are_preserved(self):
        import torch
        model = torch.nn.Sequential(torch.nn.Linear(4, 2))
        graph = capture(model, (torch.zeros(1, 4),), aliases={"0": "State projection"})
        self.assertEqual(next(n for n in graph["nodes"] if n["id"] == "module:0")["label"], "State projection")
        structure = capture(model)
        self.assertEqual(structure["capture_mode"], "structure_only")
        self.assertFalse(structure["edges"])
        observed = capture(model, (torch.zeros(1, 4),), trace=False)
        self.assertEqual(observed["capture_mode"], "sample_observed")
        self.assertFalse(observed["edges"])

    def test_convolution_sizes_follow_the_supplied_image_resolution(self):
        import torch
        model = torch.nn.Sequential(torch.nn.Conv2d(3, 8, 3, stride=2, padding=1),
                                    torch.nn.BatchNorm2d(8), torch.nn.ReLU(),
                                    torch.nn.AdaptiveAvgPool2d(1), torch.nn.Flatten(),
                                    torch.nn.Linear(8, 2))
        for size in (16, 32):
            graph = capture(model, (torch.zeros(2, 3, size, size),))
            conv = next(n for n in graph["nodes"] if n["id"] == "module:0")
            self.assertEqual(conv["config"]["in_channels"], 3)
            self.assertEqual(conv["config"]["out_channels"], 8)
            self.assertEqual(conv["config"]["kernel_size"], [3, 3])
            self.assertEqual(conv["outputs"]["shape"], [2, 8, size // 2, size // 2])
            self.assertNotEqual(conv["shape_symbol"], next(n for n in graph["nodes"] if n["id"] == "module:5")["shape_symbol"])
            self.assertTrue(graph["dataflow"]["complete"])

    def test_transformer_two_inputs_normalization_and_attention_preserve_flow(self):
        import torch
        class AttentionBlock(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.attention = torch.nn.MultiheadAttention(8, 2, batch_first=True)
                self.norm = torch.nn.LayerNorm(8)
                self.action = torch.nn.Linear(2, 8)
            def forward(self, tokens, action):
                attended, _ = self.attention(tokens, tokens, tokens, need_weights=False)
                return self.norm(tokens + attended + self.action(action).unsqueeze(1))
        model = AttentionBlock()
        graph = capture(model, (torch.zeros(2, 4, 8), torch.zeros(2, 2)))
        attention = next(n for n in graph["nodes"] if n["id"] == "module:attention")
        self.assertEqual(attention["config"]["num_heads"], 2)
        self.assertEqual(attention["config"]["embed_dim"], 8)
        norm = next(n for n in graph["nodes"] if n["id"] == "module:norm")
        self.assertNotEqual(attention["shape_symbol"], norm["shape_symbol"])
        output = next(n for n in graph["nodes"] if n.get("kind") == "output")
        inputs = [n for n in graph["nodes"] if n.get("kind") == "input"]
        self.assertEqual(len(inputs), 2)
        self.assertTrue(all(reachable(graph, n["id"], output["id"]) for n in inputs))
        self.assertEqual(output["outputs"]["shape"], [2, 4, 8])

    def test_lazy_materialization_preserves_original_model(self):
        import torch
        model = torch.nn.Sequential(torch.nn.LazyLinear(8), torch.nn.ReLU(), torch.nn.Linear(8, 2))
        graph = capture(model, (torch.zeros(2, 4),))
        self.assertTrue(model[0].has_uninitialized_params())
        node = next(n for n in graph["nodes"] if n["id"] == "module:0")
        self.assertEqual(node["config"]["in_features"], 4)
        self.assertEqual(node["config"]["out_features"], 8)
        self.assertEqual(node["outputs"]["shape"], [2, 8])
        self.assertIsInstance(graph["parameters"], int)

    def test_input_argument_aliases_and_names_are_preserved(self):
        import torch
        class Alias(torch.nn.Module):
            def forward(self, tokens, *, same):
                if tokens is not same:
                    raise AssertionError("Sample copies broke tensor identity")
                return tokens + same
        sample = torch.zeros(2, 4)
        graph = capture(Alias(), (sample,), {"same": sample})
        inputs = [n for n in graph["nodes"] if n.get("kind") == "input"]
        self.assertEqual(len(inputs), 1)
        self.assertIn("tokens", inputs[0]["label"])
        self.assertEqual(set(inputs[0]["input_paths"]), {"args.0", "kwargs.same"})

    def test_inplace_shape_change_edges_retain_input_shape_snapshot(self):
        import torch
        class Transpose(torch.nn.Module):
            def forward(self, x):
                return x.clone().transpose_(0, 1)
        sample = torch.zeros(2, 4)
        graph = capture(Transpose(), (sample,))
        transpose = next(n for n in graph["nodes"] if n.get("kind") == "operation" and "transpose_" in n.get("operation", ""))
        self.assertEqual(transpose["outputs"]["shape"], [4, 2])
        incoming = [e for e in graph["edges"] if e["target"] == transpose["id"]]
        shapes = [e["shape"].get("shape") if isinstance(e["shape"], dict) else e["shape"] for e in incoming]
        self.assertIn([2, 4], shapes)
        self.assertEqual(list(sample.shape), [2, 4])

    def test_custom_container_names_do_not_masquerade_as_layer_types(self):
        import torch
        class ResidualConv(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = torch.nn.Linear(4, 4)
            def forward(self, x):
                return self.linear(x) + x
        graph = capture(ResidualConv(), (torch.zeros(1, 4),))
        root = next(n for n in graph["nodes"] if n["id"] == "root")
        self.assertEqual(root["display_type"], "ResidualConv")
        self.assertEqual(root["family"], "container")

    def test_constant_outputs_are_explicitly_not_complete_flow(self):
        import torch
        class Constant(torch.nn.Module):
            def forward(self, x):
                return torch.ones(2, 4)
        graph = capture(Constant(), (torch.zeros(2, 4),))
        self.assertFalse(graph["dataflow"]["complete"])
        self.assertTrue(any("no observed tensor producer" in warning for warning in graph["warnings"]))

    def test_metadata_only_inplace_change_does_not_mutate_other_view(self):
        import torch
        class Metadata(torch.nn.Module):
            def forward(self, x):
                y = x.view(-1)
                x.transpose_(0, 1)
                return y * 2
        graph = capture(Metadata(), (torch.zeros(2, 4),))
        operations = [n for n in graph["nodes"] if n.get("kind") == "operation"]
        transpose = next(n for n in operations if "transpose_" in n.get("operation", ""))
        mul = next(n for n in operations if "mul" in n.get("operation", ""))
        self.assertFalse(reachable(graph, transpose["id"], mul["id"]))

    def test_disjoint_view_write_does_not_create_false_dependency(self):
        import torch
        for interleaved in (False, True):
            class Disjoint(torch.nn.Module):
                def forward(self, x):
                    left, right = (x[::2], x[1::2]) if interleaved else (x[:2], x[2:])
                    left.add_(1)
                    return right * 2
            graph = capture(Disjoint(), (torch.zeros(4, 2),))
            operations = [n for n in graph["nodes"] if n.get("kind") == "operation"]
            add = next(n for n in operations if "add_" in n.get("operation", ""))
            mul = next(n for n in operations if "mul" in n.get("operation", ""))
            with self.subTest(interleaved=interleaved):
                self.assertFalse(reachable(graph, add["id"], mul["id"]))


if __name__ == "__main__":
    unittest.main()
