"""Read-only readiness checks for confirmed and unused backend profiles."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naia.cli import main
from naia.context import Project, QUESTIONS
from naia.execution import launch
from naia.storage import NAIAError, write_json


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(self.temp.name)
        self.project.initialize(scan=False)
        self.manager = self.project.root / "management-python"
        self.manager.touch()

    def answers(self):
        for question in QUESTIONS:
            self.project.answer(question["field"], {"setting": "test fixture"}, confirmed=True)

    def backend(self, identifier, kind, *, confirmed=True, manager=None):
        profile = {"kind": kind}
        if kind == "slurm":
            profile["management_python"] = str(manager or self.manager)
        self.project.configure_backend(identifier, profile, confirmed=confirmed)

    def ready(self, kind="local"):
        self.answers()
        self.backend(kind, kind)
        self.project.confirm("test-user")

    def snapshot(self):
        return {str(path.relative_to(self.project.root)): path.read_bytes()
                for path in self.project.root.rglob("*") if path.is_file()}

    def cli(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--project", str(self.project.root), "doctor"])
        self.assertEqual(stderr.getvalue(), "")
        return code, json.loads(stdout.getvalue())

    def assert_status(self, expected):
        result = self.project.doctor()
        self.assertIs(result["ok"], expected)
        code, cli_result = self.cli()
        self.assertEqual(code, 0 if expected else 1)
        self.assertEqual(cli_result, result)
        return result

    def test_slurm_only_is_ready_without_authorizing_unused_local(self):
        self.ready("slurm")
        before = self.snapshot()
        with patch("naia.context.shutil.which", return_value="/mock/scheduler"), \
                patch("subprocess.run", side_effect=AssertionError("No submission or probe execution")):
            result = self.assert_status(True)
            self.assertTrue(result["warnings"])
            self.assertTrue(all(check["ok"] for check in result["checks"]))
            self.assertFalse(self.project.load()["backends"]["local"]["confirmed"])
            with self.assertRaises(NAIAError):
                self.project.execution_ready("local")
            # The launch gate must fail before plan construction or any worker runs.
            with patch("naia.execution.Suites.load", return_value={}):
                with self.assertRaises(NAIAError):
                    launch(self.project, "TEST", backend="local")
        self.assertEqual(before, self.snapshot())

    def test_confirmed_local_ignores_unused_slurm_without_scheduler_probes(self):
        self.answers()
        self.backend("local", "local")
        self.backend("draft-cluster", "slurm", confirmed=False,
                     manager=self.project.root / "not-installed-python")
        self.project.confirm("test-user")
        with patch("naia.context.shutil.which", side_effect=AssertionError("Unused backend probed")):
            result = self.assert_status(True)
        self.assertTrue(result["warnings"])
        self.assertFalse(any(check["name"].startswith("backend:draft-cluster:")
                             for check in result["checks"]))
        with self.assertRaises(NAIAError):
            self.project.execution_ready("draft-cluster")

    def test_no_confirmed_backend_blocks_doctor_even_with_confirmed_onboarding(self):
        self.answers()
        data = self.project.load()
        data["onboarding"] = {"status": "confirmed", "confirmed_by": "test-user"}
        write_json(self.project.context_path, data)
        with patch("naia.context.shutil.which", side_effect=AssertionError("No confirmed backend")):
            result = self.assert_status(False)
        self.assertTrue(any(not check["ok"] and check["name"].startswith("backend:")
                            for check in result["checks"]))
        with self.assertRaises(NAIAError):
            self.project.confirm("test-user")

    def test_empty_backend_registry_is_not_ready(self):
        self.answers()
        data = self.project.load()
        data["backends"] = {}
        data["onboarding"] = {"status": "confirmed", "confirmed_by": "test-user"}
        write_json(self.project.context_path, data)
        result = self.assert_status(False)
        self.assertTrue(any(not check["ok"] and check["name"].startswith("backend:")
                            for check in result["checks"]))

    def test_pending_onboarding_blocks_confirmed_backend(self):
        self.answers()
        self.backend("local", "local")
        result = self.assert_status(False)
        self.assertFalse(next(check["ok"] for check in result["checks"]
                              if check["name"] == "onboarding"))
        with self.assertRaises(NAIAError):
            self.project.execution_ready("local")

    def test_each_missing_confirmed_slurm_command_blocks_doctor(self):
        self.ready("slurm")
        commands = ("sbatch", "squeue", "sacct")
        for missing in commands:
            with self.subTest(missing=missing):
                with patch("naia.context.shutil.which", side_effect=lambda command: (
                        None if command == missing else "/mock/" + command)) as which:
                    result = self.assert_status(False)
                self.assertEqual({call.args[0] for call in which.call_args_list}, set(commands))
                self.assertFalse(next(check["ok"] for check in result["checks"]
                                      if check["name"] == "backend:slurm:" + missing))

    def test_missing_confirmed_slurm_management_python_blocks_doctor(self):
        self.answers()
        self.backend("slurm", "slurm", manager=self.project.root / "missing-python")
        self.project.confirm("test-user")
        with patch("naia.context.shutil.which", return_value="/mock/scheduler"):
            result = self.assert_status(False)
        self.assertFalse(next(check["ok"] for check in result["checks"]
                              if check["name"] == "backend:slurm:management_python"))

    def test_all_confirmed_backends_must_pass_readiness_checks(self):
        self.answers()
        self.backend("local", "local")
        self.backend("cluster-a", "slurm")
        self.backend("cluster-b", "slurm")
        self.project.confirm("test-user")
        with patch("naia.context.shutil.which", return_value="/mock/scheduler"):
            self.assert_status(True)
        self.backend("cluster-b", "slurm", manager=self.project.root / "missing-python")
        self.project.confirm("test-user")
        with patch("naia.context.shutil.which", return_value="/mock/scheduler"):
            result = self.assert_status(False)
        self.assertTrue(next(check["ok"] for check in result["checks"]
                             if check["name"] == "backend:cluster-a:management_python"))
        self.assertFalse(next(check["ok"] for check in result["checks"]
                              if check["name"] == "backend:cluster-b:management_python"))

    def test_doctor_does_not_change_records_or_confirmation(self):
        self.ready("slurm")
        before = self.snapshot()
        with patch("naia.context.shutil.which", return_value="/mock/scheduler"):
            self.assert_status(True)
        self.assertEqual(before, self.snapshot())
        with patch("naia.context.shutil.which", return_value=None):
            self.assert_status(False)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.project.load()["onboarding"]["confirmed_by"], "test-user")

    def test_unconfirmed_incomplete_slurm_profile_is_not_probed(self):
        self.ready()
        data = self.project.load()
        data["backends"]["draft-cluster"] = {"kind": "slurm", "confirmed": False}
        write_json(self.project.context_path, data)
        with patch("naia.context.shutil.which", side_effect=AssertionError("Unused backend probed")):
            result = self.assert_status(True)
        self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()
