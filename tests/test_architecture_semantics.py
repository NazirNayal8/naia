"""Explicit source-cited semantic names must not alter or invent measured flow."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
VIEWER = ROOT / "src/naia_arch/assets/viewer.js"


def fixture_graph():
    return {"schema_version": 1, "capture_mode": "runtime_observed", "nodes": [
        {"id": "root", "kind": "module", "parent": None, "module_path": "", "type": "Forecast",
         "label": "Private project alias", "visual_kind": "container"},
        {"id": "input:0", "kind": "input", "parent": "root", "type": "placeholder", "label": "args[0]",
         "outputs": {"shape": [2, 3, 16, 16], "dtype": "float32"}},
        {"id": "module:encoder", "kind": "module", "parent": "root", "module_path": "encoder",
         "type": "CustomEncoder", "label": "Unverified name", "visual_kind": "container"},
        {"id": "module:encoder.conv", "kind": "module", "parent": "module:encoder", "type": "Conv2d",
         "visual_kind": "conv", "config": {"in_channels": 3, "out_channels": 8, "kernel_size": [3, 3]},
         "inputs": {"shape": [2, 3, 16, 16]}, "outputs": {"shape": [2, 8, 8, 8]}},
        {"id": "operation:conv:1", "kind": "operation", "parent": "module:encoder.conv", "type": "call_function",
         "module_path": "encoder.conv", "operation": "aten.convolution.default", "visual_kind": "conv",
         "outputs": {"shape": [2, 8, 8, 8]}, "call": 1},
        {"id": "module:projector", "kind": "module", "parent": "root", "module_path": "projector",
         "type": "Linear", "visual_kind": "linear", "config": {"in_features": 2, "out_features": 8}},
        {"id": "module:predictor", "kind": "module", "parent": "root", "module_path": "predictor",
         "type": "Sequential", "visual_kind": "sequential"},
        {"id": "output:0", "kind": "output", "parent": "root", "type": "output", "label": "result[0]",
         "inputs": {"shape": [2, 8], "dtype": "float32"}}],
        "edges": [{"source": "input:0", "target": "operation:conv:1", "evidence": "observed",
                   "shape": {"shape": [2, 3, 16, 16], "dtype": "float32"}},
                  {"source": "operation:conv:1", "target": "output:0", "evidence": "observed",
                   "shape": {"shape": [2, 8, 8, 8]}}],
        "events": [{"node": "module:encoder.conv", "call": 1, "duration_ms": 0.25}],
        "warnings": ["Fixture output is partial"],
        "dataflow": {"engine": "torch_dispatch", "nodes": ["input:0", "operation:conv:1", "output:0"],
                     "complete": False}}


def annotation(name="Encoder", evidence=None, **extra):
    return {"name": name, "evidence": evidence if evidence is not None else
            ["model.py:12-24: convolutional observation encoder"], **extra}


class SemanticAPITest(unittest.TestCase):
    def annotate(self, graph, semantics):
        from naia_arch import annotate_graph
        return annotate_graph(graph, semantics)

    def test_annotations_are_deep_copied_metadata_only_and_exactly_targeted(self):
        graph = fixture_graph()
        semantics = {"module:encoder": annotation(), "module:projector": annotation("Action projector"),
                     "module:predictor": annotation("Dynamics", role="prediction"),
                     "input:0": annotation("Observation frames"), "output:0": annotation("Predicted state")}
        before, labels_before = deepcopy(graph), deepcopy(semantics)
        result = self.annotate(graph, semantics)
        self.assertIsNot(result, graph)
        self.assertEqual(graph, before)
        self.assertEqual(semantics, labels_before)
        for node in result["nodes"]:
            self.assertEqual(node.get("semantic"), semantics.get(node["id"]))
            node.pop("semantic", None)
        self.assertEqual(result, before)
        copied = self.annotate(graph, semantics)
        copied["nodes"][2]["semantic"]["evidence"].append("review.py:1: independent check")
        copied["nodes"][1]["outputs"]["shape"][0] = 999
        self.assertEqual(graph, before)
        self.assertEqual(semantics, labels_before)

    def test_legacy_fx_and_boundary_nodes_are_eligible_without_inferred_names(self):
        from naia_arch import validate_graph
        for fields in ({"kind": "module"}, {"kind": "input"}, {"kind": "output"},
                       {"kind": "placeholder"}, {"kind": "call_module"},
                       {"kind": "operation", "type": "call_module"},
                       {"type": "placeholder"}, {"type": "output"}, {"type": "call_module"}):
            with self.subTest(fields=fields):
                graph = {"schema_version": 1, "nodes": [{"id": "explicit", "parent": None, **fields}], "edges": []}
                result = self.annotate(graph, {"explicit": annotation()})
                self.assertEqual(result["nodes"][0]["semantic"]["name"], "Encoder")
                self.assertIs(validate_graph(result), result)
        with self.assertRaises(ValueError):
            self.annotate(fixture_graph(), {})

    def test_unknown_targets_paths_and_low_level_operations_are_rejected(self):
        graph = fixture_graph()
        for target in ("missing", "encoder", "operation:conv:1"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.annotate(graph, {target: annotation()})
        for fields in ({"kind": "operation", "type": "call_function"}, {"kind": "call_function"},
                       {"kind": "call_method"}, {"type": "call_function"}, {"type": "call_method"},
                       {"kind": "operation", "module_path": "encoder", "type": "Linear"},
                       {"type": "Conv2d", "module_path": "encoder"}, {"kind": "call"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.annotate({"schema_version": 1, "nodes": [{"id": "op", "parent": None, **fields}]},
                              {"op": annotation()})

    def test_malformed_and_unbounded_semantic_payloads_are_rejected_by_api_and_schema(self):
        from naia_arch import validate_graph
        invalid = [None, [], "Encoder", {}, {"name": "Encoder"}, {"evidence": ["model.py:1"]},
                   annotation(""), annotation(" "), annotation("a" * 81), annotation("a\nb"),
                   annotation("a\rb"), annotation("a\x00b"), annotation("a\u2028b"),
                   annotation("a\u200bb"), annotation("a\ud800b"),
                   {"name": "Encoder", "evidence": []}, {"name": "Encoder", "evidence": "model.py:1"},
                   annotation(evidence=[""]), annotation(evidence=["a" * 513]),
                   annotation(evidence=["model.py:1"] * 17), annotation(evidence=[None]),
                   annotation(evidence=["model.py:1\nmodel.py:2"]), annotation(role=""),
                   annotation(role="r" * 65), annotation(role="encoder\nblock"),
                   annotation(unapproved="value")]
        for payload in invalid:
            with self.subTest(payload=repr(payload)[:100]):
                with self.assertRaises(ValueError):
                    self.annotate(fixture_graph(), {"module:encoder": payload})
                graph = fixture_graph()
                graph["nodes"][2]["semantic"] = payload
                with self.assertRaises(ValueError):
                    validate_graph(graph)
        for mapping in (None, {}, [], "name", {None: annotation()}, {1: annotation()}):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                self.annotate(fixture_graph(), mapping)
        graph = fixture_graph()
        graph["nodes"][4]["semantic"] = annotation()
        with self.assertRaises(ValueError):
            validate_graph(graph)

    def test_maximum_valid_payload_and_existing_legacy_graph_are_accepted(self):
        from naia_arch import validate_graph
        graph = fixture_graph()
        self.assertIs(validate_graph(graph), graph)
        payload = annotation("N" * 80, evidence=["E" * 512] * 16, role="R" * 64)
        result = self.annotate(graph, {"module:encoder": payload})
        self.assertEqual(result["nodes"][2]["semantic"], payload)

    def test_reannotating_one_explicit_id_preserves_other_existing_annotations(self):
        graph = self.annotate(fixture_graph(), {"module:encoder": annotation(), "output:0": annotation("Predicted state")})
        before = deepcopy(graph)
        result = self.annotate(graph, {"module:encoder": annotation("Visual encoder", role="encoder")})
        self.assertEqual(graph, before)
        self.assertEqual(result["nodes"][2]["semantic"]["name"], "Visual encoder")
        self.assertEqual(result["nodes"][-1]["semantic"], before["nodes"][-1]["semantic"])


class SemanticCLITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.graph = self.directory / "raw.json"
        self.graph.write_text(json.dumps(fixture_graph()), encoding="utf-8")
        self.output = self.directory / "named.json"

    def run_cli(self, command, semantics, output=None):
        from naia.cli import main as unified
        from naia_arch.cli import main as legacy
        args = ["annotate", str(self.graph), "--semantics", semantics, "--output", str(output or self.output)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = (legacy(args) if command == "legacy" else unified([command, *args]))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_unified_alias_and_standalone_commands_need_no_project_or_torch(self):
        semantics = {"module:encoder": annotation(), "input:0": annotation("Observation frames")}
        source = self.graph.read_bytes()
        semantic_file = self.directory / "semantics.json"
        semantic_file.write_text(json.dumps(semantics), encoding="utf-8")
        for command, value in (("arch", json.dumps(semantics)), ("lens", "@" + str(semantic_file)),
                               ("legacy", json.dumps(semantics))):
            with self.subTest(command=command):
                output = self.directory / (command + ".json")
                code, stdout, stderr = self.run_cli(command, value, output)
                self.assertEqual(code, 0, stderr)
                self.assertTrue(json.loads(stdout))
                saved = json.loads(output.read_text())
                self.assertEqual(saved["nodes"][2]["semantic"], semantics["module:encoder"])
                self.assertEqual(self.graph.read_bytes(), source)
        script = """
import sys
from naia.cli import main
assert 'torch' not in sys.modules
code=main(sys.argv[1:])
assert 'torch' not in sys.modules
raise SystemExit(code)
"""
        result = subprocess.run([sys.executable, "-c", script, "arch", "annotate", str(self.graph),
                                 "--semantics", json.dumps(semantics), "--output", str(self.directory / "no-torch.json")],
                                cwd=self.directory, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.directory / ".lab").exists())

    def test_invalid_json_duplicates_nonfinite_and_oversized_are_rejected(self):
        from naia_arch.cli import parse_semantics
        values = ["[]", "null", "1", "not-json", '{"module:encoder":NaN}',
                  '{"module:encoder":Infinity}', '{"module:encoder":{},"module:encoder":{}}',
                  '{"module:encoder":{"name":"A","name":"B","evidence":["model.py:1"]}}',
                  "@", "@" + str(self.directory / "missing.json"), " " * (64 * 1024 + 1)]
        oversized = self.directory / "oversized.json"
        oversized.write_bytes(b" " * (64 * 1024 + 1))
        values.append("@" + str(oversized))
        for value in values:
            with self.subTest(value=value[:100]):
                with self.assertRaises((OSError, ValueError)):
                    parse_semantics(value)
                code, _, stderr = self.run_cli("arch", value)
                self.assertEqual(code, 2)
                self.assertIn("error", json.loads(stderr))
                self.assertFalse(self.output.exists())

    def test_existing_output_and_input_are_never_overwritten(self):
        self.output.write_text("immutable prior evidence", encoding="utf-8")
        before = self.graph.read_bytes()
        for output in (self.output, self.graph):
            with self.subTest(output=output):
                code, _, stderr = self.run_cli("arch", json.dumps({"module:encoder": annotation()}), output)
                self.assertEqual(code, 2)
                self.assertIn("exists", stderr.lower())
        self.assertEqual(self.graph.read_bytes(), before)
        self.assertEqual(self.output.read_text(), "immutable prior evidence")

    def test_annotation_cannot_import_a_model_or_execute_factory_and_writes_exclusively(self):
        import naia_arch
        import naia_arch.cli as cli
        implementation = naia_arch.annotate_graph
        def concurrent_writer(graph, semantics):
            result = implementation(graph, semantics)
            self.output.write_text("concurrent evidence", encoding="utf-8")
            return result
        with patch.object(cli.importlib, "import_module", side_effect=AssertionError("model import forbidden")), \
                patch.object(naia_arch, "capture", side_effect=AssertionError("factory capture forbidden")):
            code, _, stderr = self.run_cli("legacy", json.dumps({"module:encoder": annotation()}))
        self.assertEqual(code, 0, stderr)
        self.output.unlink()
        with patch.object(cli, "annotate_graph", side_effect=concurrent_writer):
            code, _, stderr = self.run_cli("legacy", json.dumps({"module:encoder": annotation()}))
        self.assertEqual(code, 2)
        self.assertEqual(self.output.read_text(), "concurrent evidence")


@unittest.skipUnless(importlib.util.find_spec("torch"), "Semantic capture needs a PyTorch environment")
class SemanticCaptureTest(unittest.TestCase):
    def test_capture_annotation_preserves_measured_shapes_aliases_and_operation_fallback(self):
        import torch
        from naia_arch import capture, validate_graph
        model = torch.nn.Sequential(torch.nn.Linear(4, 8), torch.nn.ReLU(), torch.nn.Linear(8, 2))
        baseline = capture(model, (torch.zeros(2, 4),), aliases={"0": "Private alias"})
        source = next(node for node in baseline["nodes"] if node.get("kind") == "input")
        semantics = {"module:0": annotation("Encoder"), source["id"]: annotation("Observation")}
        graph = capture(model, (torch.zeros(2, 4),), aliases={"0": "Private alias"}, semantics=semantics)
        self.assertIs(validate_graph(graph), graph)
        layer = next(node for node in graph["nodes"] if node["id"] == "module:0")
        self.assertEqual(layer["semantic"]["name"], "Encoder")
        self.assertEqual(layer["label"], "Private alias")
        self.assertEqual(layer["outputs"]["shape"], [2, 8])
        self.assertEqual(graph["edges"], baseline["edges"])
        self.assertEqual(graph["dataflow"], baseline["dataflow"])
        self.assertTrue(all("semantic" not in node for node in graph["nodes"] if node.get("kind") == "operation"))

    def test_actual_fx_fallback_uses_explicit_ids_without_propagating_module_annotations(self):
        import torch
        from naia_arch import annotate_graph, capture
        class Forecast(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = torch.nn.Linear(4, 2)
            def forward(self, observations):
                return self.linear(observations) + 1
        model = Forecast()
        with patch.dict(sys.modules, {"naia_arch._runtime": None}):
            graph = capture(model, (torch.zeros(2, 4),), aliases={"linear": "Private alias"},
                            semantics={"module:linear": annotation("Projector")})
        self.assertEqual(graph["capture_mode"], "fx_traced")
        self.assertEqual(graph["dataflow"]["engine"], "fx")
        call = next(node for node in graph["nodes"] if node.get("type") == "call_module")
        operation = next(node for node in graph["nodes"] if node.get("type") == "call_function")
        self.assertNotIn("semantic", call)
        self.assertEqual(call["label"], "Private alias")
        self.assertEqual(call["outputs"]["shape"], [2, 2])
        boundaries = [node for node in graph["nodes"] if node.get("kind") in ("input", "output")]
        mapping = {node["id"]: annotation("Observation" if node["kind"] == "input" else "Predicted state")
                   for node in boundaries}
        mapping[call["id"]] = annotation("Projector invocation")
        result = annotate_graph(graph, mapping)
        self.assertEqual(result["edges"], graph["edges"])
        self.assertEqual(result["dataflow"], graph["dataflow"])
        self.assertEqual(next(node for node in result["nodes"] if node["id"] == call["id"])["semantic"]["name"],
                         "Projector invocation")
        with self.assertRaises(ValueError):
            annotate_graph(graph, {operation["id"]: annotation("Unsupported low-level name")})


@unittest.skipUnless(shutil.which("node"), "Semantic viewer tests require Node")
class SemanticViewerTest(unittest.TestCase):
    def evaluate(self, source):
        script = "const lens=require(" + json.dumps(str(VIEWER)) + ");\n" + source
        result = subprocess.run([shutil.which("node"), "-e", script], check=True,
                                capture_output=True, text=True, timeout=10)
        return json.loads(result.stdout)

    def test_semantic_titles_apply_only_to_exact_eligible_nodes_and_types_remain_available(self):
        graph = fixture_graph()
        for node in graph["nodes"]:
            if node["id"] in ("module:encoder", "input:0", "output:0"):
                node["semantic"] = annotation({"module:encoder": "Encoder", "input:0": "Observation frames",
                                              "output:0": "Predicted state"}[node["id"]])
        result = self.evaluate("const graph=" + json.dumps(graph) + ";\n" + """
          const model=lens.prepareGraph(graph);
          console.log(JSON.stringify({titles:graph.nodes.map(n=>lens.nodeTitle(n)),
            types:graph.nodes.map(n=>lens.nodeType(n)),
            search:lens.nodeSearchValues(graph.nodes[2]),
            alias:lens.nodeTitle({kind:'module',label:'Secret encoder alias',type:'Linear',visual_kind:'linear'}),
            operation:lens.nodeTitle(graph.nodes[4]),untouched:JSON.stringify(graph.nodes[2].semantic)}));
        """)
        self.assertEqual(result["titles"][1:3], ["Observation frames", "Encoder"])
        self.assertEqual(result["titles"][-1], "Predicted state")
        self.assertEqual(result["types"][2], "Block")
        self.assertEqual(result["alias"], "Linear")
        self.assertNotIn("Encoder", result["operation"])
        self.assertIn("Encoder", json.dumps(result["search"]))

    def test_viewer_rejects_misplaced_and_malformed_annotations(self):
        cases = []
        for index, payload in ((4, annotation()), (2, annotation("")), (2, annotation("a\nb")),
                               (2, {"name": "Encoder", "evidence": []}), (2, annotation(role="r" * 65))):
            graph = fixture_graph()
            graph["nodes"][index]["semantic"] = payload
            cases.append(graph)
        result = self.evaluate("const cases=" + json.dumps(cases) + ";\n" + """
          console.log(JSON.stringify(cases.map(graph=>{try{lens.prepareGraph(graph);return false;}catch(error){return true;}})));
        """)
        self.assertEqual(result, [True] * len(cases))

    def test_comparison_keeps_per_capture_semantics_and_does_not_choose_one_variant_name(self):
        graph = fixture_graph()
        graph["nodes"][2]["semantic"] = annotation("Encoder", role="encoding")
        other = deepcopy(graph)
        other["nodes"][2]["semantic"] = annotation("Denoiser", role="denoising")
        result = self.evaluate("const first=" + json.dumps(graph) + ",second=" + json.dumps(other) + ";\n" + """
          const variants=[{id:'A',title:'A',data:first},{id:'B',title:'B',data:second}];
          const compared=lens.comparisonGraph(variants,'A');
          const node=compared.data.nodes.find(n=>n.module_path==='encoder');
          const agreed=lens.comparisonGraph([{id:'A',title:'A',data:first},{id:'B',title:'B',data:first}],'A');
          const common=agreed.data.nodes.find(n=>n.module_path==='encoder');
          console.log(JSON.stringify({title:lens.nodeTitle(node),variantNames:node.comparison.map(v=>v.node.semantic.name),
            common:lens.nodeTitle(common),search:lens.nodeSearchValues(node),changes:node.comparison_changes}));
        """)
        self.assertEqual(result["title"], "Block")
        self.assertEqual(result["variantNames"], ["Encoder", "Denoiser"])
        self.assertEqual(result["common"], "Encoder")
        self.assertIn("Denoiser", json.dumps(result["search"]))
        self.assertIn("semantic", result["changes"])


if __name__ == "__main__":
    unittest.main()
