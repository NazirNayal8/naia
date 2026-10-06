"""Reusable visual semantics for saved model graphs and their block glossary."""
import importlib.util
from importlib.resources import files
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
BLOCKS = ROOT / "src/naia_arch/assets/blocks.js"
VIEWER = ROOT / "src/naia_arch/assets/viewer.js"


def path_points(path):
    """Read absolute SVG coordinates, including curve controls, for bounds checks."""
    tokens = re.findall(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?", path)
    sizes = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}
    points, current, origin, command, index = [], (0., 0.), (0., 0.), None, 0
    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
            if command.upper() == "Z":
                current = origin
                continue
        if command is None or command.upper() not in sizes:
            raise AssertionError(f"Unsupported SVG command in {path!r}")
        count = sizes[command.upper()]
        values = [float(value) for value in tokens[index:index + count]]
        if len(values) != count or not all(math.isfinite(value) for value in values):
            raise AssertionError(f"Invalid SVG coordinates in {path!r}")
        index += count
        relative = command.islower()
        upper = command.upper()
        if upper == "H":
            coordinate = (values[0] + (current[0] if relative else 0), current[1])
            segment = [coordinate]
        elif upper == "V":
            coordinate = (current[0], values[0] + (current[1] if relative else 0))
            segment = [coordinate]
        elif upper == "A":
            if values[0] < 0 or values[1] < 0 or values[3] not in (0, 1) or values[4] not in (0, 1):
                raise AssertionError(f"Invalid SVG arc in {path!r}")
            segment = [(values[5] + (current[0] if relative else 0),
                        values[6] + (current[1] if relative else 0))]
        else:
            segment = [(values[i] + (current[0] if relative else 0),
                        values[i + 1] + (current[1] if relative else 0)) for i in range(0, count, 2)]
        current = segment[-1]
        if upper == "M":
            origin = current
            command = "l" if relative else "L"
        points.extend(segment)
    return points


@unittest.skipUnless(shutil.which("node"), "Block design tests require Node")
class BlockDesignTest(unittest.TestCase):
    def evaluate(self, source):
        script = "const blocks=require(" + json.dumps(str(BLOCKS)) + ");\n" + source
        result = subprocess.run([shutil.which("node"), "-e", script], check=True,
                                capture_output=True, text=True, timeout=10)
        return json.loads(result.stdout)

    def test_catalog_has_complete_unique_designs_and_is_browser_reusable(self):
        result = self.evaluate("""
          const fs=require('fs'),vm=require('vm'),context={};
          vm.runInNewContext(fs.readFileSync(require.resolve(process.argv[1]),'utf8'),context);
          console.log(JSON.stringify({catalog:blocks.catalog,
            browser:context.NAIABlocks && typeof context.NAIABlocks.resolve==='function'}));
        """.replace("process.argv[1]", json.dumps(str(BLOCKS))))
        catalog = result["catalog"]
        self.assertTrue(result["browser"])
        expected = {"input", "output", "linear", "bilinear", "conv", "conv_transpose", "attention",
                    "layer_norm", "batch_norm", "group_norm", "instance_norm", "rms_norm", "embedding",
                    "recurrent", "relu", "gelu", "sigmoid", "tanh", "softmax", "activation", "dropout",
                    "pool_max", "pool_avg", "pool", "reshape", "transpose", "concat", "stack", "split",
                    "slice", "gather", "scatter", "indexing", "add", "subtract", "multiply", "divide",
                    "matmul", "sum", "mean", "reduction", "comparison", "stop_gradient", "copy",
                    "identity", "sequential", "container", "custom", "operation", "padding", "upsample",
                    "maximum", "minimum", "negate"}
        ids = [entry["id"] for entry in catalog]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(expected.issubset(ids), expected.difference(ids))
        self.assertEqual(len(catalog), len({entry["color"] for entry in catalog}))
        for entry in catalog:
            with self.subTest(block=entry["id"]):
                for field in ("label", "family", "category", "color", "shape", "icon", "description"):
                    self.assertIsInstance(entry[field], str)
                    self.assertTrue(entry[field].strip(), field)
                self.assertRegex(entry["color"], r"^#[0-9a-fA-F]{6}$")

    def test_every_catalog_outline_and_icon_has_finite_bounded_paths(self):
        result = self.evaluate("""
          console.log(JSON.stringify(blocks.catalog.map(entry=>({id:entry.id,
            outline:blocks.outline(entry.shape,240,120),icons:blocks.iconPaths(entry.icon)}))));
        """)
        for entry in result:
            with self.subTest(block=entry["id"]):
                self.assertIsInstance(entry["outline"], str)
                self.assertNotRegex(entry["outline"], r"NaN|Infinity|undefined")
                self.assertTrue(path_points(entry["outline"]))
                for x, y in path_points(entry["outline"]):
                    self.assertGreaterEqual(x, 0)
                    self.assertLessEqual(x, 240)
                    self.assertGreaterEqual(y, 0)
                    self.assertLessEqual(y, 120)
                self.assertIsInstance(entry["icons"], list)
                self.assertTrue(entry["icons"])
                for path in entry["icons"]:
                    self.assertNotRegex(path, r"NaN|Infinity|undefined")
                    for x, y in path_points(path):
                        self.assertGreaterEqual(x, 0)
                        self.assertLessEqual(x, 24)
                        self.assertGreaterEqual(y, 0)
                        self.assertLessEqual(y, 24)

    def test_math_operators_keep_distinct_semantics_and_icons(self):
        result = self.evaluate("""
          console.log(JSON.stringify(['add','sub','mul','div','matmul','sum','mean','maximum','minimum','neg'].map(op=>
            blocks.resolve({kind:'operation',operation:'aten.'+op+'.default'}))));
        """)
        self.assertEqual([item["id"] for item in result],
                         ["add", "subtract", "multiply", "divide", "matmul", "sum", "mean",
                          "maximum", "minimum", "negate"])
        self.assertEqual(len(result), len({item["icon"] for item in result}))
        self.assertEqual(len(result), len({item["title"] for item in result}))

    def test_module_aliases_do_not_replace_type_labels(self):
        result = self.evaluate("""
          const node={id:'module:projector',label:'State projection',module_path:'projector',
            type:'Linear',display_type:'Linear',family:'linear',config:{in_features:48,out_features:192}};
          const before=JSON.stringify(node);
          console.log(JSON.stringify({design:blocks.resolve(node),unchanged:before===JSON.stringify(node),
            input:blocks.resolve({kind:'input',label:'Actions',type:'placeholder'}),
            output:blocks.resolve({kind:'output',label:'World state',type:'output'})}));
        """)
        self.assertEqual(result["design"]["title"], "Linear 48 → 192")
        self.assertEqual(result["input"]["title"], "Input")
        self.assertEqual(result["output"]["title"], "Output")
        self.assertTrue(result["unchanged"])

    def test_saved_legacy_graphs_resolve_without_new_metadata(self):
        result = self.evaluate("""
          console.log(JSON.stringify([
            {type:'Linear',display_type:'Linear',family:'linear',config:{in_features:4,out_features:8}},
            {type:'Conv2d',display_type:'Convolution 2d',family:'convolution',config:{kernel_size:[3,3]}},
            {type:'LayerNorm',display_type:'Layer normalization',family:'normalization'},
            {type:'call_function',operation:'aten.cat.default',family:'merge'},
            {type:'call_function',operation:'aten.detach.default',family:'identity'}
          ].map(node=>blocks.resolve(node).id)));
        """)
        self.assertEqual(result, ["linear", "conv", "layer_norm", "concat", "stop_gradient"])

    def test_legacy_operator_representations_and_overloads_keep_exact_semantics(self):
        result = self.evaluate("""
          console.log(JSON.stringify([
            'aten::add.Tensor', '<built-in function add>', 'operator.add',
            'aten.max.other', 'aten.min.other', 'aten.max.dim', 'aten.min.dim'
          ].map(operation=>blocks.resolve({kind:'operation',type:'call_function',operation}).id)));
        """)
        self.assertEqual(result, ["add", "add", "add", "maximum", "minimum", "reduction", "reduction"])

    def test_unknown_operator_never_exposes_alias_or_implementation_path_as_title(self):
        result = self.evaluate("""
          const node={kind:'operation',type:'call_function',operation:'aten.project_custom.default',
            visual_kind:'operation',family:'operation',display_type:'project.internal.CustomThing',
            module_path:'project.internal.stage',label:'Hand-written alias'};
          const before=JSON.stringify(node),design=blocks.resolve(node);
          console.log(JSON.stringify({design,unchanged:JSON.stringify(node)===before}));
        """)
        self.assertEqual(result["design"]["id"], "operation")
        self.assertEqual(result["design"]["title"], "Operation")
        self.assertIsNone(result["design"]["dimensional_change"])
        self.assertTrue(result["unchanged"])

    def test_known_subtypes_retain_their_distinguishing_type_label(self):
        result = self.evaluate("""
          console.log(JSON.stringify([
            {type:'LeakyReLU',display_type:'LeakyReLU',visual_kind:'relu'},
            {type:'Hardtanh',display_type:'Hardtanh',visual_kind:'tanh'},
            {type:'LogSoftmax',display_type:'LogSoftmax',visual_kind:'softmax'},
            {type:'GRU',display_type:'GRU',visual_kind:'recurrent'},
            {type:'EmbeddingBag',display_type:'Embedding bag',visual_kind:'embedding'},
            {type:'MyActivation',display_type:'LeakyReLU',visual_kind:'relu'}
          ].map(node=>blocks.resolve({...node,label:'A project alias'}).title)));
        """)
        for title, distinguishing_type in zip(result, ["leaky", "hard", "log", "gru", "bag", "leaky"]):
            with self.subTest(title=title):
                self.assertIn(distinguishing_type, title.lower())
                self.assertNotIn("alias", title.lower())
                self.assertNotIn("MyActivation", title)

    def test_custom_names_and_unknown_visual_kinds_have_honest_fallbacks(self):
        result = self.evaluate("""
          console.log(JSON.stringify([
            {type:'ResidualConv',display_type:'ResidualConv',family:'container'},
            {type:'FancyLayerNorm',display_type:'FancyLayerNorm',family:'operation'},
            {type:'CustomAttentionThing',label:'Linear 100→1',family:'operation'},
            {type:'FutureLayer',visual_kind:'unrecognized-v99',family:'operation'},
            {type:'Conv2d',visual_kind:'custom',display_type:'Custom operation',family:'operation'}
          ].map(node=>blocks.resolve(node))));
        """)
        self.assertEqual(result[0]["id"], "container")
        self.assertEqual(result[0]["title"], "Block")
        for item in result[1:]:
            self.assertEqual(item["id"], "custom")
            self.assertEqual(item["title"], "Custom operation")
            self.assertIsNone(item["dimensional_change"])

    def test_feature_projection_dimensions_use_valid_config(self):
        result = self.evaluate("""
          console.log(JSON.stringify([
            {in_features:192,out_features:48}, {in_features:48,out_features:192},
            {in_features:48,out_features:48}, {}, {in_features:'192',out_features:48},
            {in_features:-1,out_features:48}, {in_features:0,out_features:48}
          ].map(config=>blocks.resolve({visual_kind:'linear',display_type:'Linear',config}))));
        """)
        self.assertEqual(result[0]["dimensional_change"], "Features 192 → 48")
        self.assertEqual(result[1]["dimensional_change"], "Features 48 → 192")
        self.assertNotEqual(result[0]["shape"], result[1]["shape"])
        for item in result[3:]:
            self.assertIsNone(item["dimensional_change"])
            self.assertNotEqual(item["shape"], result[0]["shape"])
            self.assertNotEqual(item["shape"], result[1]["shape"])

    def test_spatial_resize_comes_from_tensor_shapes_and_not_operation_names(self):
        result = self.evaluate("""
          const shape=value=>({shape:value,dtype:'float32'});
          console.log(JSON.stringify({
            measured:blocks.resolve({visual_kind:'conv',config:{kernel_size:[3,3]}},
              {inputs:shape([2,3,32,32]),outputs:shape([2,8,16,16])}),
            same:blocks.resolve({visual_kind:'conv',config:{stride:[2,2]}},
              {inputs:shape([2,3,16,16]),outputs:shape([2,8,16,16])}),
            unknown:blocks.resolve({visual_kind:'pool_max',display_type:'MaxPool2d',config:{stride:2}}),
            missing:blocks.resolve({visual_kind:'conv'},
              {inputs:shape([2,3,32,32]),outputs:{shape:null}}),
            symbolic:blocks.resolve({visual_kind:'conv'},
              {inputs:shape([2,3,'height','width']),outputs:shape([2,8,16,16])})}));
        """)
        self.assertEqual(result["measured"]["dimensional_change"], "Spatial 32 × 32 → 16 × 16")
        for key in ("unknown", "missing", "symbolic"):
            self.assertIsNone(result[key]["dimensional_change"])
            self.assertNotEqual(result[key]["shape"], result["measured"]["shape"])
        self.assertNotEqual(result["same"]["shape"], result["measured"]["shape"])

    def test_observed_feature_sizes_take_priority_over_stale_config(self):
        result = self.evaluate("""
          const before=JSON.stringify(blocks.catalog);
          const design=blocks.resolve({visual_kind:'linear',config:{in_features:48,out_features:192}},
            {inputs:{shape:[2,12]},outputs:{shape:[2,6]}});
          console.log(JSON.stringify({design,unchanged:before===JSON.stringify(blocks.catalog)}));
        """)
        self.assertEqual(result["design"]["dimensional_change"], "Features 12 → 6")
        self.assertTrue(result["unchanged"])

    def test_reshape_does_not_claim_contraction_from_changed_rank(self):
        result = self.evaluate("""
          console.log(JSON.stringify({
            reshape:blocks.resolve({visual_kind:'reshape'},
              {inputs:{shape:[2,3,4,4]},outputs:{shape:[2,48]}}),
            smaller:blocks.resolve({visual_kind:'linear',config:{in_features:48,out_features:12}})}));
        """)
        self.assertEqual(result["reshape"]["id"], "reshape")
        self.assertNotEqual(result["reshape"]["shape"], result["smaller"]["shape"])
        self.assertNotIn("Features", result["reshape"]["dimensional_change"] or "")

    def test_viewer_uses_catalog_for_type_labels_without_mutating_graph(self):
        result = self.evaluate("""
          const lens=require(VIEWER_PATH);
          const node={id:'projection',parent:null,label:'State projection',display_type:'Linear',
            type:'Linear',family:'linear',config:{in_features:48,out_features:192}};
          const graph={schema_version:1,nodes:[node],edges:[],events:[]},before=JSON.stringify(graph);
          lens.prepareGraph(graph);
          console.log(JSON.stringify({title:lens.nodeTitle(node),type:lens.nodeType(node),
            unchanged:JSON.stringify(graph)===before}));
        """.replace("VIEWER_PATH", json.dumps(str(VIEWER))))
        self.assertEqual(result["title"], "Linear 48 → 192")
        self.assertEqual(result["type"], "Linear 48 → 192")
        self.assertTrue(result["unchanged"])


class BlockAssetTest(unittest.TestCase):
    def test_packaged_page_loads_glossary_before_viewer(self):
        assets = files("naia_arch").joinpath("assets")
        self.assertEqual(assets.joinpath("blocks.js").read_bytes(), BLOCKS.read_bytes())
        page = assets.joinpath("index.html").read_text()
        self.assertIn('src="/blocks.js"', page)
        self.assertLess(page.index('src="/blocks.js"'), page.index('src="/viewer.js"'))


@unittest.skipUnless(importlib.util.find_spec("torch"), "Module semantics need a PyTorch environment")
class BlockDescriptionTest(unittest.TestCase):
    def test_known_module_types_and_subclasses_have_specific_designs(self):
        import torch.nn as nn
        from naia_arch._describe import describe_module

        class ProjectNamedConv(nn.Conv2d):
            pass

        modules = [(nn.Linear(4, 8), "linear", "Linear"),
                   (nn.Bilinear(4, 3, 8), "bilinear", "Bilinear"),
                   (nn.Conv2d(3, 8, 3), "conv", None),
                   (ProjectNamedConv(3, 8, 3), "conv", None),
                   (nn.ConvTranspose2d(3, 8, 3), "conv_transpose", None),
                   (nn.LayerNorm(8), "layer_norm", None),
                   (nn.BatchNorm2d(8), "batch_norm", None),
                   (nn.GroupNorm(2, 8), "group_norm", None),
                   (nn.InstanceNorm2d(8), "instance_norm", None),
                   (nn.ReLU(), "relu", "ReLU"), (nn.GELU(), "gelu", "GELU"),
                   (nn.Sigmoid(), "sigmoid", "Sigmoid"), (nn.Tanh(), "tanh", "Tanh"),
                   (nn.Softmax(dim=-1), "softmax", "Softmax"),
                   (nn.MaxPool2d(2), "pool_max", None),
                   (nn.AvgPool2d(2), "pool_avg", None),
                   (nn.Sequential(nn.Linear(4, 8)), "sequential", "Sequential")]
        if hasattr(nn, "RMSNorm"):
            modules.append((nn.RMSNorm(8), "rms_norm", None))
        for module, visual_kind, display_type in modules:
            with self.subTest(module=type(module).__name__):
                description = describe_module(module)
                self.assertEqual(description["visual_kind"], visual_kind)
                self.assertIsInstance(description["display_type"], str)
                self.assertTrue(description["display_type"].strip())
                if display_type is not None:
                    self.assertEqual(description["display_type"], display_type)
                self.assertNotEqual(description["display_type"], "ProjectNamedConv")

    def test_misleading_custom_classes_do_not_masquerade_as_framework_layers(self):
        import torch.nn as nn
        from naia_arch._describe import describe_module

        class ResidualConv(nn.Module):
            def __init__(self):
                super().__init__()
                self.projection = nn.Linear(4, 4)

        class FancyLayerNorm(nn.Module):
            pass

        class Linear(nn.Module):
            pass

        description = describe_module(ResidualConv())
        self.assertEqual(description["visual_kind"], "container")
        self.assertEqual(description["display_type"], "Block")
        self.assertEqual(description["family"], "container")
        for module in (FancyLayerNorm(), Linear()):
            with self.subTest(module=type(module).__name__):
                description = describe_module(module)
                self.assertEqual(description["visual_kind"], "custom")
                self.assertEqual(description["display_type"], "Custom operation")
                self.assertEqual(description["config"], {})

    def test_symbolic_math_and_tensor_routing_are_not_one_merge_kind(self):
        from naia_arch._describe import describe_operation
        operations = {"add": "add", "sub": "subtract", "mul": "multiply", "div": "divide",
                      "matmul": "matmul", "cat": "concat", "stack": "stack", "sum": "sum",
                      "mean": "mean", "view": "reshape", "transpose": "transpose", "slice": "slice",
                      "gather": "gather", "scatter": "scatter", "split": "split", "detach": "stop_gradient",
                      "clone": "copy", "eq": "comparison", "maximum": "maximum",
                      "minimum": "minimum", "neg": "negate"}
        for operation, expected in operations.items():
            with self.subTest(operation=operation):
                self.assertEqual(describe_operation("aten." + operation + ".default")["visual_kind"], expected)

    def test_elementwise_selection_unary_negation_and_reduction_are_distinct(self):
        import torch
        from naia_arch import capture
        from naia_arch._describe import describe_operation

        for operation, expected in [(torch.ops.aten.max.other, "maximum"),
                                    (torch.ops.aten.min.other, "minimum"),
                                    (torch.ops.aten.max.dim, "reduction"),
                                    (torch.ops.aten.min.dim, "reduction")]:
            with self.subTest(operation=str(operation)):
                self.assertEqual(describe_operation(operation)["visual_kind"], expected)

        class Selection(torch.nn.Module):
            def forward(self, x, y):
                return torch.maximum(x, y), torch.minimum(x, y), -x, x.max(dim=-1).values, x > y

        graph = capture(Selection(), (torch.zeros(2, 4), torch.ones(2, 4)))
        operations = {node["visual_kind"]: node for node in graph["nodes"] if node.get("kind") == "operation"}
        for kind in ("maximum", "minimum", "negate", "reduction", "comparison"):
            self.assertIn(kind, operations)
        for kind in ("maximum", "minimum", "negate"):
            self.assertEqual(operations[kind]["outputs"]["shape"], [2, 4])
            self.assertIn("float", operations[kind]["outputs"]["dtype"])
        self.assertIn("bool", operations["comparison"]["outputs"]["dtype"])

    def test_containing_module_does_not_overwrite_an_internal_operator(self):
        import torch.nn as nn
        from naia_arch._describe import describe_operation
        for operation, module, expected in [("mul", nn.Linear(4, 4), "multiply"),
                                            ("detach", nn.Identity(), "stop_gradient"),
                                            ("view", nn.Conv2d(3, 8, 3), "reshape")]:
            with self.subTest(operation=operation):
                description = describe_operation("aten." + operation + ".default", module)
                self.assertEqual(description["visual_kind"], expected)
                self.assertEqual(description["config"], {})

    def test_capture_retains_alias_and_project_type_as_inspector_evidence(self):
        import torch
        from naia_arch import capture

        class ProjectNamedConv(torch.nn.Conv2d):
            pass

        model = torch.nn.Sequential(ProjectNamedConv(3, 8, 3))
        graph = capture(model, (torch.zeros(1, 3, 8, 8),), aliases={"0": "Image encoder"})
        node = next(node for node in graph["nodes"] if node["id"] == "module:0")
        self.assertEqual(node["visual_kind"], "conv")
        self.assertNotEqual(node["display_type"], "ProjectNamedConv")
        self.assertEqual(node["type"], "ProjectNamedConv")
        self.assertEqual(node["label"], "Image encoder")
        self.assertEqual(node["module_path"], "0")
        self.assertEqual(node["outputs"]["shape"], [1, 8, 6, 6])


if __name__ == "__main__":
    unittest.main()
