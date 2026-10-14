"""Launch output is concise for people and explicit JSON for automation."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naia.cli import main, parser
from naia.context import Project
from naia.demo import install
from naia.storage import NAIAError
from naia.suites import Suites


class LaunchOutputTest(unittest.TestCase):
    def invoke(self, argv, result=None, error=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            if result is None and error is None:
                code = main(argv)
            else:
                with patch("naia.cli.dispatch", return_value=result, side_effect=error) as dispatch:
                    code = main(argv)
                    self.last_args = dispatch.call_args.args[0]
        return code, stdout.getvalue(), stderr.getvalue()

    def test_submissions_show_job_ids_reuse_and_small_summary(self):
        result = {
            "suite": "TEST", "backend": "gpu", "backend_kind": "slurm", "ok": True,
            "outcomes": [
                {"cell": "new", "status": "tracked", "record_path": "long/private/path",
                 "training": {"status": "queued", "job_id": "101", "action": "submitted"},
                 "evaluation": {"moderate": {"status": "queued", "job_id": "102", "action": "submitted"}}},
                {"cell": "existing", "status": "tracked",
                 "training": {"status": "running", "job_id": "103", "action": "reused"},
                 "evaluation": {"moderate": {"status": "complete", "action": "completed"}}},
            ],
        }
        code, stdout, stderr = self.invoke(["suite", "launch", "TEST", "--backend", "gpu"], result)
        self.assertEqual((code, stderr), (0, ""))
        self.assertIn("Suite TEST | gpu (slurm)", stdout)
        self.assertIn("new: train submitted #101; eval moderate submitted #102", stdout)
        self.assertIn("existing: train reused #103 (running); eval moderate complete", stdout)
        self.assertIn("training: 1 submitted, 1 reused", stdout)
        self.assertIn("evaluations: 1 submitted, 1 complete", stdout)
        self.assertNotIn("record_path", stdout)
        self.assertNotIn("long/private/path", stdout)
        self.assertEqual(len(stdout.splitlines()), 4)

    def test_evaluation_only_says_training_is_not_requested(self):
        result = {"suite": "TEST", "backend": "gpu", "backend_kind": "slurm",
                  "evaluate_only": True, "ok": True,
                  "outcomes": [{"cell": "one", "status": "tracked",
                                "training": {"status": "complete", "action": "not-requested"},
                                "evaluation": {"strict": {"status": "queued", "job_id": "202", "action": "submitted"}}}]}
        code, stdout, stderr = self.invoke(["suite", "evaluate", "TEST", "--backend", "gpu"], result)
        self.assertEqual((code, stderr), (0, ""))
        self.assertIn("evaluation only", stdout)
        self.assertIn("train not requested; eval strict submitted #202", stdout)
        self.assertNotIn("training:", stdout)

    def test_old_outcomes_still_print_and_error_exit_is_nonzero(self):
        result = {"suite": "TEST", "ok": False,
                  "outcomes": [{"cell": "ok", "status": "tracked"},
                               {"cell": "bad", "status": "error", "error": "sbatch failed\npartition unavailable"}]}
        code, stdout, stderr = self.invoke(["suite", "launch", "TEST"], result)
        self.assertEqual((code, stderr), (1, ""))
        self.assertIn("ok: tracked", stdout)
        self.assertIn("bad: error; ERROR: sbatch failed partition unavailable", stdout)
        self.assertIn("1 error(s)", stdout)

    def test_partial_failure_keeps_submitted_job_and_readable_error(self):
        result = {"suite": "TEST", "ok": False, "outcomes": [{
            "cell": "one", "status": "error", "error": "quota reached",
            "training": {"status": "queued", "job_id": "301", "action": "submitted"},
            "evaluation": {"strict": {"status": "failed", "error": "quota reached"}},
        }]}
        code, stdout, stderr = self.invoke(["suite", "launch", "TEST"], result)
        self.assertEqual((code, stderr), (1, ""))
        self.assertIn("train submitted #301; eval strict failed; ERROR: quota reached", stdout)
        self.assertEqual(stdout.count("quota reached"), 1)

    def test_json_flag_keeps_full_result_and_failure_exit(self):
        result = {"suite": "TEST", "ok": False,
                  "outcomes": [{"cell": "one", "status": "error", "error": "failed"}],
                  "stored_metadata": {"records": ["a", "b"]}}
        for action in ("launch", "evaluate"):
            with self.subTest(action=action):
                code, stdout, stderr = self.invoke(["suite", action, "TEST", "--json"], result)
                self.assertEqual((code, stderr), (1, ""))
                self.assertEqual(json.loads(stdout), result)

    def test_sbatch_error_cause_is_not_repeated(self):
        result = {"suite": "TEST", "ok": False, "outcomes": [{
            "cell": "one", "status": "error", "error": "sbatch failed: quota reached",
            "training": {"status": "queued", "job_id": "301", "action": "submitted"},
            "evaluation": {"strict": {"status": "failed", "action": "failed", "error": "quota reached"}},
        }]}
        code, stdout, stderr = self.invoke(["suite", "launch", "TEST"], result)
        self.assertEqual((code, stderr), (1, ""))
        self.assertEqual(stdout.count("quota reached"), 1)
        self.assertIn("eval strict failed; ERROR: sbatch failed: quota reached", stdout)

    def test_streamed_header_keeps_backend_kind(self):
        outcome = {"suite": "TEST", "backend": "cluster", "backend_kind": "slurm",
                   "cell": "one", "status": "tracked", "evaluate_only": False,
                   "auto_evaluate": False, "training": {"status": "queued", "job_id": "301", "action": "submitted"}}
        def dispatch(args):
            args._launch_progress(outcome)
            return {"suite": "TEST", "backend": "cluster", "backend_kind": "slurm",
                    "auto_evaluate": False, "ok": True, "outcomes": [outcome]}
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("naia.cli.dispatch", side_effect=dispatch), redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["suite", "launch", "TEST", "--backend", "cluster", "--no-auto-eval"])
        self.assertEqual((code, stderr.getvalue()), (0, ""))
        self.assertEqual(stdout.getvalue().splitlines()[0], "Suite TEST | cluster (slurm) | training only")

    def test_launch_errors_are_plain_unless_json_is_requested(self):
        for json_output in (False, True):
            with self.subTest(json_output=json_output):
                argv = ["suite", "launch", "TEST"] + (["--json"] if json_output else [])
                code, stdout, stderr = self.invoke(argv, error=NAIAError("Confirm backend\nbefore launching"))
                self.assertEqual((code, stdout), (2, ""))
                if json_output:
                    self.assertEqual(json.loads(stderr), {"error": "Confirm backend\nbefore launching"})
                else:
                    self.assertEqual(stderr, "Error: Confirm backend before launching\n")

    def test_other_commands_still_return_json(self):
        for argv in (["doctor"], ["suite", "show", "TEST"], ["task", "list"]):
            with self.subTest(argv=argv):
                result = {"ok": True, "items": [1, 2]}
                code, stdout, stderr = self.invoke(argv, result)
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(json.loads(stdout), result)

    def test_selected_dry_run_hides_full_commands_and_context(self):
        result = {"suite": "TEST", "backend": "gpu", "backend_kind": "slurm",
                  "dry_run": True, "auto_evaluate": True,
                  "plans": [{"cell": "one", "training": {"argv": ["a", "very-long-command"]},
                             "run_dir": "private/run/path", "artifact": "model.bin",
                             "evaluation": {"moderate": {"argv": ["eval-moderate"]},
                                            "strict": {"argv": ["eval-strict"]}}}]}
        argv = ["suite", "launch", "TEST", "--backend", "gpu", "--dry-run", "--cell", "one", "--profile", "strict"]
        code, stdout, stderr = self.invoke(argv, result)
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual((self.last_args.cell, self.last_args.profile, self.last_args.dry_run), ("one", "strict", True))
        self.assertIn("one: train; eval strict", stdout)
        self.assertIn("no jobs submitted", stdout)
        for hidden in ("moderate", "argv", "model.bin", "very-long-command", "private/run/path"):
            self.assertNotIn(hidden, stdout)

    def test_no_auto_eval_and_evaluation_only_dry_runs(self):
        result = {"suite": "TEST", "dry_run": True, "auto_evaluate": False,
                  "plans": [{"cell": "one", "training": {"argv": ["train"]},
                             "evaluation": {"validation": {"argv": ["eval"]}}}]}
        _, stdout, _ = self.invoke(["suite", "launch", "TEST", "--dry-run", "--no-auto-eval"], result)
        self.assertIn("training only", stdout)
        self.assertIn("one: train\n", stdout)
        self.assertNotIn("eval validation", stdout)
        result.update(auto_evaluate=True, evaluate_only=True)
        _, stdout, _ = self.invoke(["suite", "evaluate", "TEST", "--dry-run"], result)
        self.assertIn("evaluation only", stdout)
        self.assertIn("one: eval validation\n", stdout)
        self.assertNotIn("one: train", stdout)

    def test_parser_keeps_existing_launch_selectors_and_json_option(self):
        args = parser().parse_args(["suite", "launch", "TEST", "--backend", "gpu", "--cell", "one",
                                    "--profile", "strict", "--retry", "--no-auto-eval", "--json"])
        self.assertEqual((args.backend, args.cell, args.profile), ("gpu", "one", "strict"))
        self.assertTrue(args.retry and args.no_auto_eval and args.json)

    def test_progress_streams_each_cell_once_before_dispatch_returns(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        outcomes = [{"cell": "one", "status": "tracked",
                     "training": {"status": "queued", "job_id": "101", "action": "submitted"}},
                    {"cell": "two", "status": "error", "error": "quota reached"}]
        def dispatch(args):
            for outcome in outcomes:
                args._launch_progress(outcome)
                self.assertIn(outcome["cell"] + ":", stdout.getvalue())
                self.assertNotIn("2 experiment(s)", stdout.getvalue())
            return {"suite": "TEST", "outcomes": outcomes, "ok": False}
        with redirect_stdout(stdout), redirect_stderr(stderr), patch("naia.cli.dispatch", side_effect=dispatch):
            code = main(["suite", "launch", "TEST"])
        self.assertEqual((code, stderr.getvalue()), (1, ""))
        self.assertEqual(stdout.getvalue().count("Suite TEST"), 1)
        self.assertEqual(stdout.getvalue().count("one:"), 1)
        self.assertEqual(stdout.getvalue().count("two:"), 1)
        self.assertIn("2 experiment(s)", stdout.getvalue().splitlines()[-1])

    def test_json_and_dry_run_do_not_attach_progress_callbacks(self):
        for flags in (["--json"], ["--dry-run"], ["--dry-run", "--json"]):
            with self.subTest(flags=flags):
                self.invoke(["suite", "launch", "TEST"] + flags,
                            {"suite": "TEST", "outcomes": [], "ok": True})
                self.assertFalse(hasattr(self.last_args, "_launch_progress"))

    def test_cpu_demo_runs_and_evaluates_without_json_dump(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Project(directory)
            install(project)
            prefix = ["--project", directory, "suite", "launch", "DEMO"]
            code, stdout, stderr = self.invoke(prefix)
            self.assertEqual((code, stderr), (0, ""))
            self.assertIn("value1:", stdout)
            self.assertIn("value2:", stdout)
            self.assertIn("2 experiment(s)", stdout)
            self.assertNotIn('"outcomes"', stdout)
            self.assertTrue(Suites(project).sync()["suites"][0]["results_ready"])
            code, stdout, stderr = self.invoke(prefix + ["--json"])
            self.assertEqual((code, stderr), (0, ""))
            self.assertTrue(json.loads(stdout)["ok"])
            self.assertEqual(len(list(project.directory.glob("state/runs/*/*/*/record.json"))), 2)

    def test_cpu_demo_dry_run_and_evaluation_only_are_non_mutating(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Project(directory)
            install(project)
            def snapshot():
                return {str(path.relative_to(project.root)): path.read_bytes()
                        for path in project.root.rglob("*") if path.is_file()}
            before = snapshot()
            prefix = ["--project", directory, "suite"]
            code, stdout, stderr = self.invoke(prefix + ["launch", "DEMO", "--dry-run", "--cell", "value1", "--profile", "validation"])
            self.assertEqual((code, stderr), (0, ""))
            self.assertIn("value1: train; eval validation", stdout)
            self.assertNotIn("value2:", stdout)
            self.assertEqual(snapshot(), before)
            code, stdout, stderr = self.invoke(prefix + ["evaluate", "DEMO", "--dry-run", "--cell", "value1"])
            self.assertEqual((code, stderr), (0, ""))
            self.assertIn("value1: eval validation", stdout)
            self.assertNotIn("value1: train", stdout)
            self.assertEqual(snapshot(), before)

    def test_cpu_failure_returns_nonzero_with_short_message(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Project(directory)
            install(project)
            definition = copy.deepcopy(Suites(project).load("DEMO"))
            definition["id"] = "FAIL"
            definition["cells"] = definition["cells"][:1]
            definition["training"] = {"argv": ["{python}", "-c", "raise SystemExit(3)"]}
            Suites(project).add(definition, "test-user")
            code, stdout, stderr = self.invoke(["--project", directory, "suite", "launch", "FAIL"])
            self.assertEqual((code, stderr), (1, ""))
            self.assertIn("train exited 3", stdout)
            self.assertIn("1 error(s)", stdout)


if __name__ == "__main__":
    unittest.main()
