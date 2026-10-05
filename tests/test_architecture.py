import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from naia_arch import capture, validate_graph


class NamingTest(unittest.TestCase):
    def test_legacy_import_remains_torch_free(self):
        code = "import sys; import naia_arch, workbench_arch; assert workbench_arch.capture is naia_arch.capture; assert 'torch' not in sys.modules"
        subprocess.run([sys.executable, "-c", code], check=True, env={**os.environ, "PYTHONPATH": str(ROOT / "src")})


class SchemaTest(unittest.TestCase):
    def test_valid_hierarchy_without_torch(self):
        graph = {"schema_version": 1, "nodes": [{"id": "model", "parent": None}, {"id": "block", "parent": "model"}],
                 "edges": [], "events": [{"node": "block"}]}
        self.assertIs(validate_graph(graph), graph)

    def test_cycles_and_unproven_edges_are_rejected(self):
        graph = {"schema_version": 1, "nodes": [{"id": "a", "parent": "b"}, {"id": "b", "parent": "a"}]}
        with self.assertRaises(ValueError):
            validate_graph(graph)
        graph = {"schema_version": 1, "nodes": [{"id": "a", "parent": None}], "edges": [{"source": "a", "target": "a", "evidence": "guessed"}]}
        with self.assertRaises(ValueError):
            validate_graph(graph)

    def test_package_import_does_not_import_torch(self):
        import subprocess
        code = "import sys; import naia_arch; assert 'torch' not in sys.modules"
        env = {**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")}
        subprocess.run([sys.executable, "-c", code], env=env, check=True)


@unittest.skipUnless(importlib.util.find_spec("torch"), "Run runtime capture tests in a PyTorch environment")
class CaptureTest(unittest.TestCase):
    def test_unified_cli_captures_a_real_model_without_project_setup(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "model.json"
            env = {**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + str(ROOT)}
            result = subprocess.run([sys.executable, "-m", "naia.cli", "arch", "capture",
                                     "--factory", "examples.architecture_factory:build",
                                     "--output", str(output), "--trace"],
                                    cwd=directory, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            graph = validate_graph(json.loads(output.read_text()))
            self.assertEqual(graph["events"][-1]["outputs"]["shape"], [1, 2])
            self.assertTrue(graph["edges"])
            self.assertFalse((Path(directory) / ".lab").exists())

    def test_capture_api_remains_callable_after_repeated_capture(self):
        import naia_arch
        import torch

        model = torch.nn.Linear(4, 2)
        for _ in range(2):
            graph = naia_arch.capture(model, (torch.zeros(1, 4),))
            self.assertEqual(graph["events"][-1]["outputs"]["shape"], [1, 2])
            self.assertTrue(callable(naia_arch.capture))

    def test_shape_capture_preserves_model_and_rng(self):
        import torch
        model = torch.nn.Sequential(torch.nn.Linear(4, 8), torch.nn.BatchNorm1d(8), torch.nn.ReLU(), torch.nn.Linear(8, 2))
        original = {k: v.clone() for k, v in model.state_dict().items()}
        rng = torch.get_rng_state().clone()
        graph = capture(model, (torch.zeros(2, 4),), trace=False)
        self.assertTrue(model.training)
        self.assertTrue(torch.equal(rng, torch.get_rng_state()))
        self.assertTrue(all(torch.equal(original[k], v) for k, v in model.state_dict().items()))
        self.assertEqual(graph["capture_mode"], "sample_observed")
        self.assertEqual(graph["events"][-1]["outputs"]["shape"], [2, 2])
        self.assertEqual(graph["edges"], [])

    def test_shared_modules_repeated_calls_and_kwargs(self):
        import torch
        class Model(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.block = torch.nn.Linear(4, 4)
                self.shared = self.block
            def forward(self, x, scale=1):
                return self.shared(self.block(x)) * scale
        graph = capture(Model(), (torch.zeros(2, 4),), {"scale": 2})
        self.assertEqual(len([e for e in graph["events"] if e["node"] == "module:block"]), 2)
        self.assertEqual(next(n for n in graph["nodes"] if n["id"] == "module:shared")["shared_with"], "module:block")

    def test_fx_traces_functional_residual_edges(self):
        import torch
        class Model(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = torch.nn.Linear(4, 4)
            def forward(self, x):
                return self.linear(x) + x
        graph = capture(Model(), (torch.zeros(2, 4),), trace=True)
        self.assertTrue(any(n["type"] == "call_function" for n in graph["nodes"]))
        self.assertTrue(graph["edges"])


if __name__ == "__main__":
    unittest.main()
