"""Mocked Slurm submission uses per-experiment Bash files and truthful outcomes."""
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from naia.context import Project
from naia.demo import install
from naia.execution import launch
from naia.suites import Suites


class BashSubmissionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="naia quoted '")
        self.addCleanup(temporary.cleanup)
        self.project = Project(temporary.name)
        install(self.project)
        self.python = "/shared environment/manage'python"
        self.project.configure_backend("cluster", {
            "kind": "slurm", "management_python": self.python,
            "resources": {"partition": "training"},
            "evaluation_resources": {"partition": "evaluation"},
        }, confirmed=True)
        self.project.confirm("synthetic-user")
        self.calls = []

    def scheduler(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[0] == "sbatch":
            job = 9000 + sum(command[0] == "sbatch" for command in self.calls)
            return subprocess.CompletedProcess(argv, 0, f"{job}\n", "")
        if argv[0] == "squeue":
            return subprocess.CompletedProcess(argv, 0, "PENDING|Priority\n", "")
        raise AssertionError(f"Unexpected scheduler call: {argv}")

    def test_one_bash_training_job_per_experiment_with_dependent_evaluation(self):
        outcomes = []
        with patch("naia.execution.subprocess.run", side_effect=self.scheduler):
            result = launch(self.project, "DEMO", backend="cluster", on_outcome=outcomes.append)
        self.assertTrue(result["ok"])
        self.assertEqual(result["outcomes"], outcomes)
        self.assertEqual(result["backend_kind"], "slurm")
        submissions = [argv for argv in self.calls if argv[0] == "sbatch"]
        self.assertEqual(len(submissions), 4)
        self.assertEqual(len({argv[-1] for argv in submissions}), 4)
        for index, argv in enumerate(submissions):
            self.assertNotIn("--wrap", argv)
            script = Path(argv[-1])
            self.assertEqual(script.suffix, ".sh")
            lines = script.read_text().splitlines()
            self.assertEqual(lines[:2], ["#!/usr/bin/env bash", "set -euo pipefail"])
            worker = shlex.split(lines[2])
            self.assertEqual(worker[:4], ["exec", self.python, "-m", "naia.cli"])
            self.assertEqual(worker[4:6], ["--project", str(self.project.root)])
            self.assertIn("_worker", worker)
            self.assertEqual(subprocess.run(["bash", "-n", str(script)], capture_output=True).returncode, 0)
            if index % 2:
                self.assertEqual(script.name, "eval-validation.sh")
                self.assertIn(f"--dependency=afterok:{9000 + index}", argv)
                self.assertIn("--partition=evaluation", argv)
                self.assertEqual(worker[-2:], ["--profile", "validation"])
            else:
                self.assertEqual(script.name, "train.sh")
                self.assertIn("--partition=training", argv)
        for index, outcome in enumerate(outcomes):
            self.assertEqual(outcome["training"]["action"], "submitted")
            self.assertEqual(outcome["training"]["job_id"], str(9001 + 2 * index))
            self.assertEqual(outcome["evaluation"]["validation"]["job_id"], str(9002 + 2 * index))
            record = Suites(self.project).pointer("DEMO", outcome["cell"])
            self.assertTrue(self.project.path(record["training"]["submission_script"]).is_file())

    def test_live_jobs_are_reused_without_rewriting_scripts_or_submitting_again(self):
        with patch("naia.execution.subprocess.run", side_effect=self.scheduler):
            launch(self.project, "DEMO", backend="cluster")
            scripts = {path: path.read_bytes() for path in self.project.directory.rglob("*.sh")}
            result = launch(self.project, "DEMO", backend="cluster")
        self.assertTrue(result["ok"])
        self.assertEqual(sum(argv[0] == "sbatch" for argv in self.calls), 4)
        self.assertEqual(scripts, {path: path.read_bytes() for path in scripts})
        for outcome in result["outcomes"]:
            self.assertEqual(outcome["training"]["action"], "reused")
            self.assertEqual(outcome["evaluation"]["validation"]["action"], "reused")

    def test_partial_evaluation_failure_retains_submitted_training_job(self):
        def scheduler(argv, **kwargs):
            if "--partition=evaluation" in argv:
                self.calls.append(argv)
                return subprocess.CompletedProcess(argv, 1, "", "Evaluation resource denied")
            return self.scheduler(argv, **kwargs)
        outcomes = []
        with patch("naia.execution.subprocess.run", side_effect=scheduler):
            result = launch(self.project, "DEMO", backend="cluster", cell_id="value1", on_outcome=outcomes.append)
        self.assertFalse(result["ok"])
        outcome = outcomes[0]
        self.assertEqual(outcome["status"], "error")
        self.assertEqual(outcome["training"]["job_id"], "9001")
        self.assertEqual(outcome["training"]["action"], "submitted")
        self.assertEqual(outcome["evaluation"]["validation"]["action"], "failed")
        self.assertNotIn("job_id", outcome["evaluation"]["validation"])

    def test_script_creation_failure_is_failed_not_uncertain_submission(self):
        with patch("naia.execution.atomic_text", side_effect=OSError("disk full")), \
                patch("naia.execution.subprocess.run") as submit:
            result = launch(self.project, "DEMO", backend="cluster", cell_id="value1")
        self.assertFalse(result["ok"])
        submit.assert_not_called()
        outcome = result["outcomes"][0]
        self.assertEqual(outcome["training"]["status"], "failed")
        self.assertEqual(outcome["training"]["action"], "failed")
        self.assertNotIn("job_id", outcome["training"])
        self.assertIn("disk full", outcome["error"])

    def test_dry_run_filters_requested_profiles_without_creating_scripts(self):
        before = {path: path.read_bytes() for path in self.project.directory.rglob("*") if path.is_file()}
        with patch("naia.execution.subprocess.run") as submit:
            result = launch(self.project, "DEMO", backend="cluster", dry_run=True, auto_eval=False)
        self.assertTrue(result["dry_run"])
        submit.assert_not_called()
        self.assertTrue(all(plan["evaluation"] == {} for plan in result["plans"]))
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertFalse(list(self.project.directory.rglob("*.sh")))

    def test_uncertain_attempt_is_not_reported_as_reused(self):
        with patch("naia.execution.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "not-a-job-id", "")):
            launch(self.project, "DEMO", backend="cluster", cell_id="value1")
        with patch("naia.execution.subprocess.run") as submit:
            result = launch(self.project, "DEMO", backend="cluster", cell_id="value1")
        submit.assert_not_called()
        outcome = result["outcomes"][0]
        self.assertEqual(outcome["status"], "error")
        self.assertEqual(outcome["training"]["action"], "blocked")
        self.assertEqual(outcome["training"]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
