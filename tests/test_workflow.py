"""CPU-only integration and contract tests; never submit real scheduler jobs."""
import copy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naia.context import Project, QUESTIONS
from naia.demo import install
from naia.execution import launch, scheduler_state
from naia.storage import NAIAError, inside, read_json, write_json
from naia.suites import BEGIN, END, Suites, import_analysis, validate_definition
from naia.tasks import Tasks
from naia.ui import handler


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(self.temp.name)

    def demo(self):
        install(self.project)
        return Suites(self.project)

    def snapshot(self):
        return {str(p.relative_to(self.project.root)): p.read_bytes() for p in self.project.directory.rglob("*") if p.is_file()}

    def test_init_is_idempotent_and_does_not_create_instruction_files(self):
        self.project.initialize()
        first = self.snapshot()
        self.project.initialize()
        self.assertEqual(first, self.snapshot())
        self.assertFalse((self.project.root / "AGENTS.md").exists())
        self.assertFalse(self.project.doctor()["ok"])
        self.assertFalse(self.project.load()["policies"]["unsolicited_documents"])

    def test_demo_cannot_overwrite_an_existing_project(self):
        existing = self.project.root / "demo_worker.py"
        existing.write_text("user's existing work")
        with self.assertRaises(NAIAError):
            install(self.project)
        self.assertEqual(existing.read_text(), "user's existing work")
        self.assertFalse(self.project.context_path.exists())

    def test_unconfirmed_assumptions_block_execution(self):
        self.demo()
        self.project.answer("evaluation", "unspecified", confirmed=False)
        with self.assertRaises(NAIAError):
            launch(self.project, "DEMO")
        with self.assertRaises(NAIAError):
            self.project.confirm("user")
        self.assertFalse((self.project.directory / "state/runs").exists())

    def test_backend_changes_invalidate_confirmation(self):
        self.demo()
        self.project.configure_backend("local", {"kind": "local"}, confirmed=True)
        self.assertEqual(self.project.load()["onboarding"]["status"], "pending")

    def test_instructions_preserve_original_and_are_opt_in_idempotent(self):
        self.project.initialize()
        target = self.project.root / "AGENTS.md"
        target.write_text("Existing rules.\n")
        self.project.install_instructions(["AGENTS.md"])
        first = target.read_text()
        self.assertTrue(first.startswith("Existing rules.\n"))
        self.project.install_instructions(["AGENTS.md"])
        self.assertEqual(first, target.read_text())

    def test_naia_branding_preserves_legacy_imports_and_workspace(self):
        from naia.cli import parser
        from naia.storage import WorkbenchError
        from research_workbench.context import Project as LegacyProject
        from research_workbench.storage import WorkbenchError as LegacyError

        self.assertEqual(parser().prog, "naia")
        self.assertIs(LegacyProject, Project)
        self.assertIs(LegacyError, NAIAError)
        self.assertIs(WorkbenchError, NAIAError)
        self.demo()
        self.assertEqual(self.project.directory.name, ".lab")
        self.assertIn("naia suite launch", (Suites(self.project).location("DEMO") / "card.md").read_text())

    def test_instruction_rename_updates_only_the_legacy_managed_block(self):
        self.project.initialize()
        target = self.project.root / "AGENTS.md"
        target.write_text("User rules.\n<!-- research-workbench:instructions -->\nFollow `lab policy`.\n<!-- /research-workbench:instructions -->\nMore user rules.\n")
        self.project.install_instructions(["AGENTS.md"])
        updated = target.read_text()
        self.assertTrue(updated.startswith("User rules.\n"))
        self.assertTrue(updated.endswith("\nMore user rules.\n"))
        self.assertEqual(updated.count("<!-- naia:instructions -->"), 1)
        self.assertIn("`naia policy`", updated)
        self.assertNotIn("research-workbench:instructions", updated)
        self.project.install_instructions(["AGENTS.md"])
        self.assertEqual(updated, target.read_text())

    def test_dry_run_creates_no_launch_records_or_other_mutations(self):
        self.demo()
        first = self.snapshot()
        result = launch(self.project, "DEMO", dry_run=True)
        self.assertTrue(result["auto_evaluate"])
        self.assertEqual(first, self.snapshot())
        self.assertIn("validation", result["plans"][0]["evaluation"])

    def test_local_runs_auto_evaluate_and_queue_exactly_one_review(self):
        suites = self.demo()
        self.assertTrue(launch(self.project, "DEMO")["ok"])
        registry = suites.sync()
        self.assertTrue(registry["suites"][0]["results_ready"])
        card = (suites.location("DEMO") / "card.md").read_text()
        self.assertIn("| value1 | validation | complete | 0.5 |", card)
        self.assertIn("| value2 | validation | complete | 1 |", card)
        self.assertEqual(Tasks(self.project).next()["id"], "REVIEW-DEMO")
        self.assertEqual(len(Tasks(self.project).load()["items"]), 1)
        records = list(self.project.directory.glob("state/runs/*/*/*/record.json"))
        self.assertEqual(len(records), 2)
        launch(self.project, "DEMO")
        suites.sync()
        self.assertEqual(len(list(self.project.directory.glob("state/runs/*/*/*/record.json"))), 2)
        self.assertEqual(len(Tasks(self.project).load()["items"]), 1)

    def test_manual_evaluation_does_not_retrain(self):
        suites = self.demo()
        launch(self.project, "DEMO", auto_eval=False)
        self.assertFalse(suites.sync()["suites"][0]["results_ready"])
        launch(self.project, "DEMO", evaluate_only=True)
        self.assertTrue(suites.sync()["suites"][0]["results_ready"])
        self.assertEqual(len(list(self.project.directory.glob("state/runs/*/*/*/record.json"))), 2)

    def test_sealing_preserves_result_identity_and_blocks_new_training(self):
        suites = self.demo()
        launch(self.project, "DEMO")
        suites.seal("DEMO", "test-user")
        self.assertTrue(suites.sync()["suites"][0]["results_ready"])
        with self.assertRaises(NAIAError):
            launch(self.project, "DEMO")
        self.assertTrue(launch(self.project, "DEMO", evaluate_only=True)["ok"])

    def test_unknown_placeholder_is_rejected_before_submission(self):
        suites = self.demo()
        data = suites.load("DEMO")
        data["training"]["argv"].append("{missing_parameter}")
        with self.assertRaises(NAIAError):
            validate_definition(data)

    def test_training_and_evaluation_can_use_different_environments(self):
        self.demo()
        self.project.configure_backend("local", {"kind": "local", "command_python": "/train/python",
                                                "evaluation_python": "/evaluate/python"}, confirmed=True)
        self.project.confirm("test-user")
        plan = launch(self.project, "DEMO", dry_run=True)["plans"][0]
        self.assertEqual(plan["training"]["argv"][0], "/train/python")
        self.assertEqual(plan["evaluation"]["validation"]["argv"][0], "/evaluate/python")

    def test_training_failure_requires_explicit_retry(self):
        suites = self.demo()
        data = suites.load("DEMO")
        data["id"] = "TRAINRETRY"
        data["cells"] = data["cells"][:1]
        data["training"] = {"argv": ["{python}", "-c", "raise SystemExit(1)"]}
        suites.add(data, "test-user")
        self.assertFalse(launch(self.project, "TRAINRETRY")["ok"])
        before = suites.pointer("TRAINRETRY", "value1")["attempt"]
        self.assertFalse(launch(self.project, "TRAINRETRY")["ok"])
        self.assertEqual(before, suites.pointer("TRAINRETRY", "value1")["attempt"])
        launch(self.project, "TRAINRETRY", retry=True)
        self.assertNotEqual(before, suites.pointer("TRAINRETRY", "value1")["attempt"])

    def test_different_checkpoint_or_identity_never_enters_table(self):
        suites = self.demo()
        launch(self.project, "DEMO")
        record = suites.pointer("DEMO", "value1")
        self.project.path(record["artifact"]).write_text("different checkpoint")
        self.assertFalse(suites.sync()["suites"][0]["results_ready"])
        self.assertIn("invalid_provenance", (suites.location("DEMO") / "card.md").read_text())

    def test_result_identity_mismatch_is_rejected(self):
        suites = self.demo()
        launch(self.project, "DEMO")
        record = suites.pointer("DEMO", "value1")
        path = self.project.path(record["evaluation"]["validation"]["result"])
        data = read_json(path)
        data["identity"]["cell"] = "value2"
        write_json(path, data)
        with self.assertRaises(NAIAError):
            suites.checked_result(record, record["definition"]["evaluation"][0])

    def test_card_refresh_preserves_authored_text(self):
        suites = self.demo()
        path = suites.location("DEMO") / "card.md"
        path.write_text(path.read_text() + "\nUser-approved conclusion.\n")
        launch(self.project, "DEMO")
        self.assertTrue(path.read_text().endswith("\nUser-approved conclusion.\n"))

    def test_changed_definition_cannot_reuse_old_results(self):
        suites = self.demo()
        launch(self.project, "DEMO")
        path = suites.location("DEMO") / "suite.json"
        definition = read_json(path)
        definition["cells"][0]["parameters"]["value"] = 7
        write_json(path, definition)
        self.assertFalse(launch(self.project, "DEMO")["ok"])
        self.assertIn("definition_changed", (suites.location("DEMO") / "card.md").read_text())

    def test_successful_exit_without_artifact_is_failed(self):
        suites = self.demo()
        definition = suites.load("DEMO")
        definition["id"] = "NOARTIFACT"
        definition["training"] = {"argv": ["{python}", "-c", "pass"]}
        suites.add(definition, "test-user")
        result = launch(self.project, "NOARTIFACT")
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["outcomes"]), 2)
        self.assertEqual(suites.pointer("NOARTIFACT", "value1")["training"]["status"], "failed")

    def test_failed_evaluation_retry_uses_new_files_without_retraining(self):
        suites = self.demo()
        definition = suites.load("DEMO")
        definition["id"] = "RETRY"
        definition["cells"] = definition["cells"][:1]
        definition["evaluation"][0]["command"] = {"argv": ["{python}", "retry_eval.py", "{metrics}"]}
        worker = self.project.root / "retry_eval.py"
        worker.write_text("import pathlib, sys\npathlib.Path(sys.argv[1]).write_text('{}')\n")
        suites.add(definition, "test-user")
        self.assertFalse(launch(self.project, "RETRY")["ok"])
        previous = suites.pointer("RETRY", "value1")
        worker.write_text("import pathlib, sys\npathlib.Path(sys.argv[1]).write_text('{\"score\": 0.75}')\n")
        self.assertTrue(launch(self.project, "RETRY", retry=True)["ok"])
        current = suites.pointer("RETRY", "value1")
        self.assertEqual(current["attempt"], previous["attempt"])
        self.assertNotEqual(current["evaluation"]["validation"]["raw_metrics"], previous["evaluation"]["validation"]["raw_metrics"])
        self.assertTrue(self.project.path(previous["evaluation"]["validation"]["raw_metrics"]).exists())
        self.assertEqual(len(current["evaluation"]["validation"]["history"]), 1)

    def test_bad_schema_paths_and_duplicate_cells_rejected(self):
        suites = self.demo()
        definition = suites.load("DEMO")
        for invalid in ("../escape", "/outside", "x/../../y"):
            other = copy.deepcopy(definition)
            other["artifact"] = invalid
            with self.assertRaises(NAIAError):
                validate_definition(other)
        other = copy.deepcopy(definition)
        other["cells"].append(other["cells"][0])
        with self.assertRaises(NAIAError):
            validate_definition(other)
        with self.assertRaises(NAIAError):
            inside(self.project.root, "../outside")

    def test_pending_results_and_partial_completion_are_valid(self):
        suites = self.demo()
        self.assertFalse(suites.sync()["suites"][0]["results_ready"])
        launch(self.project, "DEMO", cell_id="value1")
        registry = suites.sync()
        self.assertFalse(registry["suites"][0]["results_ready"])
        self.assertFalse(Tasks(self.project).load()["items"])

    def test_task_order_single_active_and_soft_dependencies(self):
        self.project.initialize()
        tasks = Tasks(self.project)
        tasks.add("A", "A", "Goal", "Decision")
        tasks.add("B", "B", "Goal", "Decision", dependencies=["A"], top=True)
        self.assertEqual(tasks.next()["id"], "B")
        tasks.action("B", "start")
        with self.assertRaises(NAIAError):
            tasks.action("A", "start")
        tasks.action("B", "pause")
        tasks.action("A", "start")
        tasks.action("A", "done", note="Decision recorded")
        tasks.action("B", "resume")
        self.assertEqual(tasks.next()["id"], "B")

    def test_slurm_options_dependency_and_reuse_live_job(self):
        suites = self.demo()
        self.project.configure_backend("cluster", {"kind": "slurm", "management_python": "/shared/python",
                                                "resources": {"partition": "training"},
                                                "evaluation_resources": {"partition": "evaluation"}}, confirmed=True)
        self.project.confirm("test-user")
        calls = []
        def scheduler(argv, **kwargs):
            calls.append(argv)
            if argv[0] == "sbatch":
                return subprocess.CompletedProcess(argv, 0, str(9000 + len([a for a in calls if a[0] == 'sbatch'])) + "\n", "")
            if argv[0] == "squeue":
                return subprocess.CompletedProcess(argv, 0, "PENDING|Priority\n", "")
            raise AssertionError(argv)
        with patch("naia.execution.subprocess.run", side_effect=scheduler):
            self.assertTrue(launch(self.project, "DEMO", backend="cluster")["ok"])
            submitted = [a for a in calls if a[0] == "sbatch"]
            self.assertEqual(len(submitted), 4)
            self.assertIn("--dependency=afterok:9001", submitted[1])
            self.assertIn("--partition=evaluation", submitted[1])
            self.assertTrue(launch(self.project, "DEMO", backend="cluster")["ok"])
            self.assertEqual(len([a for a in calls if a[0] == "sbatch"]), 4)

    def test_unknown_submission_response_is_not_resubmitted(self):
        self.demo()
        self.project.configure_backend("cluster", {"kind": "slurm", "management_python": "/shared/python"}, confirmed=True)
        self.project.confirm("test-user")
        response = subprocess.CompletedProcess([], 0, "unexpected response", "")
        with patch("naia.execution.subprocess.run", return_value=response) as run:
            launch(self.project, "DEMO", backend="cluster", cell_id="value1")
            self.assertEqual(run.call_count, 1)
            result = launch(self.project, "DEMO", backend="cluster", cell_id="value1", retry=True)
            self.assertFalse(result["ok"])
            self.assertEqual(run.call_count, 1)

    def test_slurm_dry_run_no_side_effects(self):
        self.demo()
        self.project.configure_backend("cluster", {"kind": "slurm", "management_python": "/shared/python"}, confirmed=True)
        self.project.confirm("test-user")
        before = self.snapshot()
        with patch("naia.execution.subprocess.run") as run:
            launch(self.project, "DEMO", backend="cluster", dry_run=True)
            run.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def test_analysis_assignment_is_record_not_markdown(self):
        self.demo()
        record = import_analysis(self.project, {"id": "PROBE", "question": "What is represented?",
                                                "instructions": "Run the approved probe.", "inputs": ["demo_worker.py"],
                                                "outputs": ["evidence/probe.json"], "owner": "assistant"}, "test-user")
        self.assertEqual(record["approved_by"], "test-user")
        self.assertEqual(Tasks(self.project).next()["owner"], "assistant")
        self.assertEqual(list((self.project.directory / "analyses").glob("*.md")), [])

    def test_ui_assets_and_write_protection(self):
        self.project.initialize()
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.project, "secret-test-token"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        with urlopen(base + "/") as response:
            self.assertIn(b"NAIA", response.read())
        request = Request(base + "/api/sync", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 403)
        request = Request(base + "/api/sync", data=b"{}", method="POST", headers={"Content-Type": "application/json", "Origin": base, "X-NAIA-Token": "secret-test-token"})
        with urlopen(request) as response:
            self.assertEqual(response.status, 200)
        request = Request(base + "/api/sync", data=b"{}", method="POST", headers={"Content-Type": "application/json", "Origin": base, "X-Lab-Token": "secret-test-token"})
        with urlopen(request) as response:
            self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
