"""Dependency-free capture CLI and assistant contracts; never execute a real model."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shlex
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naia.cli import main as workflow_main, parser as workflow_parser
from naia.context import ASSISTANT_RULES, INSTRUCTIONS_BEGIN, INSTRUCTIONS_END, Project
from naia.tasks import Tasks
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
    def assert_model_visualization_workflow(self, text):
        example = text.split("```bash\n", 1)[1].split("\n```", 1)[0]
        commands = [shlex.split(line) for line in example.splitlines() if line.strip()]
        self.assertEqual([command[:3] for command in commands],
                         [["naia", "arch", "capture"], ["naia", "arch", "validate"],
                          ["naia", "arch", "add"], ["naia", "ui"]])
        arguments = [workflow_parser().parse_args(command[1:]) for command in commands]
        self.assertEqual(arguments[0].output, arguments[1].graph)
        self.assertEqual(arguments[1].graph, arguments[2].graph)
        for argument in ("--factory", "--output"):
            self.assertIn(argument, commands[0])
        for argument in ("--graph", "--title"):
            self.assertIn(argument, commands[2])
        for phrase in ("Tensor tracing is on by default", "do not silently substitute",
                       "`--no-trace`", "`--structure-only`", "Verify input-to-output connectivity",
                       "branches/residuals", "representative shapes against the forward code",
                       "Schema validity alone", "Flag unknown shapes and partial capture",
                       "Never overwrite registered graphs", "Architecture tab",
                       "`naia instructions install`",
                       "package upgrades alone do not refresh project files"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_rules_require_source_grounded_flow_and_preserve_execution_boundaries(self):
        text = ASSISTANT_RULES.lower()
        for phrase in ("permitted model, config, and forward", "sample-input shapes", "uncertain details",
                       "trusted factory", "real sample dataflow", "validate the saved graph",
                       "compact pictograms", "short computational-type captions",
                       "module paths and aliases in the inspector", "block glossary",
                       "tensor dimensions and intermediate sizes on arrows",
                       "image glyphs need explicit image/layout metadata",
                       "expansion/contraction glyphs need verified dimensions",
                       "unfamiliar custom modules must not be guessed from their class names",
                       "tensor dimensions", "intermediate sizes", "observed, traced, and declared",
                       "hook order do not prove dependencies", "cited source/config evidence", "not invented flow",
                       "separate graph files and ids", "never run factories from the browser"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_each_assistant_selection_installs_ordered_visualization_workflow(self):
        selections = {"codex": {"AGENTS.md"}, "claude": {"CLAUDE.md"},
                      "both": {"AGENTS.md", "CLAUDE.md"}}
        with tempfile.TemporaryDirectory() as directory:
            for choice, expected in selections.items():
                with self.subTest(assistant=choice):
                    project = Project(Path(directory) / choice)
                    project.initialize(assistant=choice, scan=False)
                    self.assertEqual(project.load()["assistants"]["selection"], choice)
                    self.assertEqual({path.name for path in project.root.glob("*.md")}, expected)
                    for filename in expected:
                        self.assert_model_visualization_workflow((project.root / filename).read_text())

    def test_refresh_stale_selected_blocks_preserves_project_and_unselected_files(self):
        selections = {"codex": {"AGENTS.md"}, "claude": {"CLAUDE.md"},
                      "both": {"AGENTS.md", "CLAUDE.md"}}
        prefix = "User rules: café.\r\nKeep trailing spaces.  \r\n\r\n"
        suffix = "\r\n\r\nFinal user restriction: λ.\r\n"
        with tempfile.TemporaryDirectory() as directory:
            for choice, selected in selections.items():
                with self.subTest(assistant=choice):
                    project = Project(Path(directory) / choice)
                    project.initialize(assistant=choice, scan=False)
                    project.answer("project", {"goal": "Inspect the existing model"}, confirmed=True)
                    project.answer("evaluation", {"metrics": ["score"]}, confirmed=False)
                    project.configure_backend("local", {"kind": "local", "command_python": "/existing/python"},
                                              confirmed=True)
                    tasks = Tasks(project)
                    tasks.add("REVIEW-MODEL", "Inspect model evidence", "Check the sample flow",
                              "Choose whether the capture is sufficient", owner="researcher", top=True)
                    context_before = project.context_path.read_bytes()
                    tasks_before = tasks.path.read_bytes()
                    unselected_before = {}
                    for filename in ("AGENTS.md", "CLAUDE.md"):
                        path = project.root / filename
                        if filename in selected:
                            text = prefix + INSTRUCTIONS_BEGIN + "\nStale visualization rules.\n" + INSTRUCTIONS_END + suffix
                        else:
                            text = "Unselected assistant's own rules.\r\nKeep these bytes.  \r\n"
                        path.write_bytes(text.encode("utf-8"))
                        if filename not in selected:
                            unselected_before[filename] = path.read_bytes()

                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        code = workflow_main(["--project", str(project.root), "instructions", "install"])
                    self.assertEqual(code, 0)
                    self.assertEqual({item["file"] for item in json.loads(stdout.getvalue())["files"]}, selected)
                    self.assertEqual(project.context_path.read_bytes(), context_before)
                    self.assertEqual(tasks.path.read_bytes(), tasks_before)
                    for filename in selected:
                        text = (project.root / filename).read_bytes().decode("utf-8")
                        self.assertEqual(text[:text.index(INSTRUCTIONS_BEGIN)], prefix)
                        self.assertEqual(text[text.index(INSTRUCTIONS_END) + len(INSTRUCTIONS_END):], suffix)
                        self.assertNotIn("Stale visualization rules.", text)
                        self.assert_model_visualization_workflow(text)
                    for filename, content in unselected_before.items():
                        self.assertEqual((project.root / filename).read_bytes(), content)

                    files_before = {filename: (project.root / filename).read_bytes()
                                    for filename in ("AGENTS.md", "CLAUDE.md")}
                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        code = workflow_main(["--project", str(project.root), "instructions", "install"])
                    self.assertEqual(code, 0)
                    self.assertFalse(any(item["changed"] for item in json.loads(stdout.getvalue())["files"]))
                    self.assertEqual(project.context_path.read_bytes(), context_before)
                    self.assertEqual(tasks.path.read_bytes(), tasks_before)
                    for filename, content in files_before.items():
                        self.assertEqual((project.root / filename).read_bytes(), content)

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
