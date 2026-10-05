"""Dependency-free capture CLI and assistant contracts; never execute a real model."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naia.cli import parser as workflow_parser
from naia.context import ASSISTANT_RULES, Project
import naia_arch
import naia_arch.cli as architecture_cli
from naia_arch.cli import dispatch, parse_aliases, parser


class CaptureCLIFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "graph.json"
        self.model = object()
        self.example_args = (object(),)
        self.example_kwargs = {"scale": 2}
        self.builder = Mock(return_value=(self.model, self.example_args, self.example_kwargs))
        self.factory = SimpleNamespace(build=self.builder)
        self.graph = {"schema_version": 1, "capture_mode": "fixture", "nodes": [{"id": "root", "parent": None}],
                      "edges": [], "events": [], "warnings": []}

    def arguments(self, *extra):
        return parser().parse_args(["capture", "--factory", "fixture:build", "--output", str(self.output), *extra])

    def run_capture(self, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(naia_arch, "capture", return_value=self.graph) as captured, \
                patch.object(architecture_cli.importlib, "import_module", return_value=self.factory) as imported, \
                patch.object(sys, "path", list(sys.path)), redirect_stdout(stdout), redirect_stderr(stderr):
            code = dispatch(self.arguments(*extra))
        return code, imported, captured, stdout.getvalue(), stderr.getvalue()

    def test_dataflow_is_default_and_shared_by_unified_and_legacy_commands(self):
        for flags in ([], ["--trace"], ["--no-trace"], ["--structure-only"]):
            with self.subTest(flags=flags):
                standalone = self.arguments(*flags)
                for command in ("arch", "lens"):
                    unified = workflow_parser().parse_args([command, "capture", "--factory", "fixture:build",
                                                           "--output", str(self.output), *flags])
                    self.assertEqual(unified.trace, standalone.trace)
                    self.assertEqual(unified.structure_only, standalone.structure_only)
                self.assertEqual(standalone.trace, "--no-trace" not in flags)
                self.assertEqual(standalone.structure_only, "--structure-only" in flags)

    def test_conflicting_evidence_options_are_rejected(self):
        for flags in (("--trace", "--no-trace"), ("--trace", "--structure-only"), ("--no-trace", "--structure-only")):
            with self.subTest(flags=flags), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.arguments(*flags)

    def test_default_capture_forwards_sample_and_enables_dataflow(self):
        code, imported, captured, stdout, stderr = self.run_capture()
        self.assertEqual(code, 0, stderr)
        imported.assert_called_once_with("fixture")
        self.builder.assert_called_once_with()
        captured.assert_called_once_with(self.model, self.example_args, self.example_kwargs, trace=True, aliases={})
        self.assertEqual(json.loads(self.output.read_text()), self.graph)
        self.assertEqual(json.loads(stdout)["mode"], "fixture")
        self.assertFalse((self.root / ".lab").exists())

    def test_no_trace_keeps_sample_calls_and_shapes(self):
        code, _, captured, _, stderr = self.run_capture("--no-trace")
        self.assertEqual(code, 0, stderr)
        captured.assert_called_once_with(self.model, self.example_args, self.example_kwargs, trace=False, aliases={})

    def test_structure_only_ignores_sample_without_skipping_trusted_construction(self):
        code, _, captured, _, stderr = self.run_capture("--structure-only")
        self.assertEqual(code, 0, stderr)
        self.builder.assert_called_once_with()
        captured.assert_called_once_with(self.model, None, None, trace=False, aliases={})

    def test_empty_no_argument_sample_is_not_treated_as_missing(self):
        self.builder.return_value = (self.model, (), {})
        code, _, captured, _, stderr = self.run_capture()
        self.assertEqual(code, 0, stderr)
        captured.assert_called_once_with(self.model, (), {}, trace=True, aliases={})

    def test_json_and_file_labels_are_data_only(self):
        aliases = {"": "Forecast model", "encoder": "Token encoder", "encoder.0": "Input projection"}
        alias_file = self.root / "labels.json"
        alias_file.write_text(json.dumps(aliases), encoding="utf-8")
        for value in (json.dumps(aliases), "@" + str(alias_file)):
            with self.subTest(value=value):
                self.assertEqual(parse_aliases(value), aliases)
        code, _, captured, _, stderr = self.run_capture("--aliases", "@" + str(alias_file))
        self.assertEqual(code, 0, stderr)
        captured.assert_called_once_with(self.model, self.example_args, self.example_kwargs, trace=True, aliases=aliases)

    def test_invalid_labels_fail_before_factory_import_or_execution(self):
        values = ["[]", "null", "1", "not-json", '{"encoder":""}', '{"encoder":[]}',
                  '{"encoder":"first","encoder":"second"}', '{"encoder":NaN}',
                  '{"encoder":"a\\nb"}', '{"enc\\u0000oder":"x"}', "@", "@" + str(self.root / "missing.json"),
                  "x" * (64 * 1024 + 1)]
        oversized = self.root / "oversized.json"
        oversized.write_bytes(b" " * (64 * 1024 + 1))
        values.append("@" + str(oversized))
        for value in values:
            with self.subTest(value=value[:80]):
                code, imported, captured, _, stderr = self.run_capture("--aliases", value)
                self.assertEqual(code, 2)
                self.assertIn("error", json.loads(stderr))
                imported.assert_not_called()
                captured.assert_not_called()
                self.assertFalse(self.output.exists())
        self.builder.assert_not_called()

    def test_existing_graph_is_never_overwritten_or_recaptured(self):
        self.output.write_text("Existing immutable evidence", encoding="utf-8")
        code, imported, captured, _, stderr = self.run_capture()
        self.assertEqual(code, 2)
        self.assertIn("Output exists", stderr)
        imported.assert_not_called()
        captured.assert_not_called()
        self.builder.assert_not_called()
        self.assertEqual(self.output.read_text(), "Existing immutable evidence")

    def test_factory_requires_nonempty_module_and_function(self):
        for factory in ("fixture", ":build", "fixture:"):
            with self.subTest(factory=factory):
                args = self.arguments()
                args.factory = factory
                with patch("naia_arch.cli.importlib.import_module") as imported, redirect_stderr(io.StringIO()):
                    self.assertEqual(dispatch(args), 2)
                imported.assert_not_called()
                self.assertFalse(self.output.exists())


class ArchitectureAssistantFlowTest(unittest.TestCase):
    def test_rules_require_source_grounded_flow_and_preserve_execution_boundaries(self):
        text = ASSISTANT_RULES.lower()
        for phrase in ("permitted model, config, and forward", "sample-input shapes", "uncertain details",
                       "trusted factory", "real sample dataflow", "validate the saved graph", "module-path aliases",
                       "tensor dimensions", "intermediate sizes", "observed, traced, and declared",
                       "hook order do not prove dependencies", "cited source/config evidence", "not invented flow",
                       "separate graph files and ids", "never run factories from the browser"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_updated_block_preserves_user_rules_and_reinstall_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Project(directory)
            custom = Path(directory) / "AGENTS.md"
            prefix = "Existing project restrictions.\nKeep the project configuration.\n\n"
            custom.write_text(prefix, encoding="utf-8")
            project.initialize(assistant="codex", scan=False)
            first = custom.read_bytes()
            self.assertTrue(first.decode().startswith(prefix))
            self.assertIn("real sample dataflow", first.decode())
            project.install_instructions(["AGENTS.md"])
            self.assertEqual(custom.read_bytes(), first)
            self.assertFalse((Path(directory) / "CLAUDE.md").exists())


if __name__ == "__main__":
    unittest.main()
