"""UI setup guidance is read-only and distinct from existing context errors."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naia.cli import main
from naia.context import Project


class UIStartupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def cli(self, *args, cwd=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        previous = Path.cwd()
        try:
            os.chdir(cwd or self.root)
            with redirect_stdout(stdout), redirect_stderr(stderr), patch("naia.ui.serve") as serve:
                code = main(list(args))
        finally:
            os.chdir(previous)
        return code, stdout.getvalue(), stderr.getvalue(), serve

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def assert_setup_message(self, result):
        code, stdout, stderr, serve = result
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("NAIA isn't set up in this project yet.", stderr)
        self.assertIn("AI assistant", stderr)
        self.assertIn("naia ui", stderr)
        self.assertNotIn("No such file", stderr)
        self.assertNotIn('"error"', stderr)
        serve.assert_not_called()
        return stderr

    def test_missing_project_shows_guidance_without_initializing(self):
        before = self.snapshot()
        message = self.assert_setup_message(self.cli("ui"))
        self.assertIn("  naia init\n", message)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / ".lab").exists())

    def test_explicit_project_guidance_targets_quoted_path(self):
        target = self.root / "project with 'quotes'"
        message = self.assert_setup_message(self.cli("--project", str(target), "ui"))
        command = next(line.strip() for line in message.splitlines() if line.startswith("  naia"))
        self.assertEqual(shlex.split(command), ["naia", "--project", str(target), "init"])
        self.assertFalse(target.exists())

    def test_missing_context_keeps_existing_records_untouched(self):
        records = self.root / ".lab"
        records.mkdir()
        (records / "tasks.json").write_text('{"keep": "existing records"}')
        before = self.snapshot()
        self.assert_setup_message(self.cli("ui"))
        self.assertEqual(self.snapshot(), before)

    def test_pending_onboarding_still_opens_ui(self):
        project = Project(self.root)
        project.initialize(scan=False)
        self.assertEqual(project.load()["onboarding"]["status"], "pending")
        before = self.snapshot()
        code, stdout, stderr, serve = self.cli("ui", "--port", "8769")
        self.assertEqual((code, stdout, stderr), (0, "", ""))
        serve.assert_called_once()
        self.assertEqual(serve.call_args.args[0].root, self.root)
        self.assertEqual(serve.call_args.args[1], 8769)
        self.assertEqual(self.snapshot(), before)

    def test_initialized_ancestor_is_discovered(self):
        project = Project(self.root)
        project.initialize(scan=False)
        child = self.root / "src" / "nested"
        child.mkdir(parents=True)
        code, stdout, stderr, serve = self.cli("ui", cwd=child)
        self.assertEqual((code, stdout, stderr), (0, "", ""))
        serve.assert_called_once()
        self.assertEqual(serve.call_args.args[0].root, self.root)
        self.assertFalse((child / ".lab").exists())

    def test_explicit_uninitialized_child_does_not_open_ancestor(self):
        Project(self.root).initialize(scan=False)
        child = self.root / "another project"
        child.mkdir()
        before = self.snapshot()
        self.assert_setup_message(self.cli("--project", str(child), "ui", cwd=child))
        self.assertEqual(self.snapshot(), before)

    def test_other_commands_keep_existing_error_contract(self):
        code, stdout, stderr, serve = self.cli("context", "show")
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("Cannot read", json.loads(stderr)["error"])
        serve.assert_not_called()

    def test_existing_context_directory_keeps_error(self):
        context = self.root / ".lab" / "project.json"
        context.mkdir(parents=True)
        code, stdout, stderr, serve = self.cli("ui")
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("Cannot read", json.loads(stderr)["error"])
        self.assertNotIn("isn't set up", stderr)
        serve.assert_not_called()
        self.assertTrue(context.is_dir())

    @unittest.skipIf(os.name == "nt", "Symlink creation may need additional Windows permissions")
    def test_broken_context_symlink_keeps_error(self):
        context = self.root / ".lab" / "project.json"
        context.parent.mkdir()
        context.symlink_to("missing-context.json")
        code, stdout, stderr, serve = self.cli("ui")
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("Cannot read", json.loads(stderr)["error"])
        self.assertNotIn("isn't set up", stderr)
        serve.assert_not_called()
        self.assertTrue(context.is_symlink())

    def test_existing_invalid_context_is_not_reported_as_uninitialized(self):
        context = self.root / ".lab" / "project.json"
        context.parent.mkdir()
        for content, expected in (("not json", "Cannot read"),
                                  ('{"schema_version": 999}', "Unsupported project context version")):
            with self.subTest(content=content):
                context.write_text(content)
                before = self.snapshot()
                code, stdout, stderr, serve = self.cli("ui")
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn(expected, json.loads(stderr)["error"])
                self.assertNotIn("isn't set up", stderr)
                serve.assert_not_called()
                self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
