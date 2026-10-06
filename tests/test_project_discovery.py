"""Static onboarding evidence and explicit draft confirmation; never run jobs."""
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

from naia.cli import main
from naia.context import Project, QUESTIONS
from naia.storage import NAIAError


class ProjectDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(Path(self.temp.name) / "project")
        self.project.root.mkdir()

    def file(self, relative, text):
        path = self.project.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def existing_project(self):
        self.file("README.md", "# Existing training project\n"
                  "Train with python train.py --config config/base.yaml.\n"
                  "Evaluate with python eval.py --checkpoint outputs/model.pt.\n")
        self.file("train.py", "from pathlib import Path\n"
                  "Path(__file__).with_name('executed.txt').write_text('unsafe import')\n"
                  "import argparse\nparser = argparse.ArgumentParser()\n"
                  "parser.add_argument('--config')\n")
        self.file("eval.py", "import argparse\nparser = argparse.ArgumentParser()\n"
                  "parser.add_argument('--episodes', type=int, default=50)\n"
                  "parser.add_argument('--checkpoint')\n")
        self.file("config/base.yaml", "_target_: model.Model\nseed: 3072\nepisodes: 50\n")
        self.file("scripts/train.sbatch", "#!/bin/bash\n#SBATCH --gres=gpu:1\n"
                  "#SBATCH --mem=16G\npython train.py --config config/base.yaml\n")
        self.file("pyproject.toml", '[project]\nname = "existing-project"\n'
                  'dependencies = ["torch", "hydra-core"]\n')

    def cli(self, *arguments, expected=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--project", str(self.project.root), *arguments])
        self.assertEqual(code, expected, stderr.getvalue())
        return json.loads(stdout.getvalue() if expected == 0 else stderr.getvalue())

    def questions(self):
        return {item["field"]: item for item in self.project.questions()}

    def confirm_project(self):
        for question in QUESTIONS:
            self.project.answer(question["field"], {"approved": question["field"]}, confirmed=True)
        self.project.configure_backend("local", {"kind": "local", "command_python": sys.executable},
                                       confirmed=True)
        self.project.confirm("researcher")

    def test_first_init_collects_static_sources_without_running_project_code(self):
        self.existing_project()
        with patch("subprocess.run", side_effect=AssertionError("Scan ran a command")), \
                patch("subprocess.Popen", side_effect=AssertionError("Scan started a process")):
            data = self.project.initialize(assistant="both")
        discovery = data["discovery"]
        self.assertTrue(discovery["existing_project"])
        self.assertFalse((self.project.root / "executed.txt").exists())
        self.assertIn("train.py", discovery["detected"]["training_candidates"])
        self.assertIn("eval.py", discovery["detected"]["evaluation_candidates"])
        self.assertIn("hydra", json.dumps(discovery["detected"]["configuration"]).lower())
        self.assertIn("slurm", json.dumps(discovery["detected"]["scheduler"]).lower())
        paths = {item["path"] for item in discovery["sources"]}
        self.assertTrue({"README.md", "train.py", "eval.py", "config/base.yaml"} <= paths)
        for source in discovery["sources"]:
            with self.subTest(path=source["path"]):
                self.assertFalse(Path(source["path"]).is_absolute())
                self.assertNotIn("..", Path(source["path"]).parts)
                self.assertGreater(source["line"], 0)
                self.assertTrue(source["excerpt"])
                self.assertTrue(source["topics"])
        self.assertEqual(self.project.load()["discovery"], discovery)

    def test_detected_settings_cannot_confirm_answers_or_authorize_execution(self):
        self.existing_project()
        data = self.project.initialize()
        for field in ("project", "hardware", "execution", "evaluation", "configuration"):
            with self.subTest(field=field):
                self.assertFalse(data["answers"][field]["confirmed"])
        self.assertFalse(data["backends"]["local"]["confirmed"])
        self.assertEqual(data["onboarding"]["status"], "pending")
        with self.assertRaises(NAIAError):
            self.project.execution_ready("local")
        with self.assertRaises(NAIAError):
            self.project.confirm("researcher")
        self.assertFalse((self.project.directory / "state/runs").exists())

    def test_scan_and_reinitialize_preserve_confirmed_context_and_backend(self):
        self.existing_project()
        self.project.initialize(assistant="codex")
        self.confirm_project()
        before = self.project.load()
        instructions = (self.project.root / "AGENTS.md").read_bytes()
        self.file("config/new.json", '{"batch_size": 8}\n')
        discovery = self.project.scan()
        after = self.project.load()
        self.assertEqual(after["discovery"], discovery)
        for key in ("answers", "backends", "onboarding", "policies", "assistants"):
            self.assertEqual(after[key], before[key], key)
        stable = self.project.context_path.read_bytes()
        self.project.initialize(assistant="codex")
        self.assertEqual(self.project.context_path.read_bytes(), stable)
        self.assertEqual((self.project.root / "AGENTS.md").read_bytes(), instructions)
        self.assertEqual(self.project.execution_ready("local")["command_python"], sys.executable)

    def test_rescan_refreshes_evidence_instead_of_reusing_stale_sources(self):
        self.project.initialize()
        self.assertFalse(self.project.load()["discovery"]["existing_project"])
        self.file("train.py", "import argparse\nparser = argparse.ArgumentParser()\n")
        result = self.project.scan()
        self.assertTrue(result["existing_project"])
        self.assertIn("train.py", {item["path"] for item in result["sources"]})

    def test_empty_project_uses_missing_questions_and_ignores_managed_instructions(self):
        data = self.project.initialize(assistant="both")
        self.assertFalse(data["discovery"]["existing_project"])
        self.assertEqual(data["discovery"]["sources"], [])
        questions = self.questions()
        self.assertEqual(len(questions), 9)
        self.assertEqual(questions["assistant"]["mode"], "confirmed")
        self.assertEqual(questions["assistant_roles"]["mode"], "missing")
        self.assertTrue(questions["assistant_roles"]["optional"])
        for field in ("reporting", "governance"):
            self.assertEqual(questions[field]["mode"], "confirmed")
        for field in ("project", "hardware", "execution", "evaluation", "configuration"):
            self.assertEqual(questions[field]["mode"], "missing")
        self.assertFalse(self.project.scan()["existing_project"])

    def test_existing_evidence_changes_question_mode_without_inventing_a_draft(self):
        self.existing_project()
        self.project.initialize()
        questions = self.questions()
        self.assertEqual(len(questions), 8)
        self.assertEqual(questions["execution"]["mode"], "inspect_evidence")
        self.assertTrue(questions["execution"]["evidence"])
        self.assertFalse(questions["execution"]["answer"]["confirmed"])

    def test_explicit_exclusion_removes_nested_evidence(self):
        self.file("README.md", "Public project description.\n")
        self.file("scripts/private/train.py", "PRIVATE_SCAN_SENTINEL = 'python train.py'\n")
        self.file("scripts/private/nested/eval.py", "PRIVATE_SCAN_SENTINEL = 'evaluate'\n")
        data = self.project.initialize(excluded_paths=("scripts/private",))
        discovery = data["discovery"]
        self.assertIn("scripts/private", discovery["excluded_paths"])
        self.assertFalse(any(item["path"].startswith("scripts/private/") for item in discovery["sources"]))
        self.assertNotIn("PRIVATE_SCAN_SENTINEL", json.dumps(discovery))
        self.assertNotIn("scripts/private/train.py", discovery["detected"]["training_candidates"])

    def test_malformed_exclusions_are_rejected_before_initial_context_write(self):
        for excluded in ("../outside", str(Path(self.temp.name) / "outside"), "", "bad\x00path"):
            with self.subTest(excluded=excluded):
                with self.assertRaises(NAIAError):
                    self.project.initialize(excluded_paths=(excluded,))
                self.assertFalse(self.project.context_path.exists())

    def test_scan_respects_confirmed_governance_exclusions(self):
        self.project.initialize(scan=False)
        self.file("scripts/private/train.py", "GOVERNANCE_SCAN_SENTINEL = 'train'\n")
        self.project.answer("governance", {"excluded_paths": ["scripts/private"]}, confirmed=True)
        before = copy.deepcopy(self.project.load()["answers"])
        discovery = self.project.scan()
        self.assertNotIn("GOVERNANCE_SCAN_SENTINEL", json.dumps(discovery))
        self.assertEqual(self.project.load()["answers"], before)

    def test_reinitializing_with_new_exclusions_removes_cached_private_evidence(self):
        self.file("README.md", "Public project description.\n")
        self.file("scripts/private/train.py", "CACHED_PRIVATE_SCAN_SENTINEL = 'train'\n")
        self.project.initialize()
        self.assertIn("CACHED_PRIVATE_SCAN_SENTINEL", json.dumps(self.project.load()["discovery"]))
        data = self.project.initialize(excluded_paths=("scripts/private",))
        self.assertNotIn("CACHED_PRIVATE_SCAN_SENTINEL", json.dumps(data["discovery"]))
        self.assertNotIn("CACHED_PRIVATE_SCAN_SENTINEL", json.dumps(self.project.context_view()))
        self.assertNotIn("CACHED_PRIVATE_SCAN_SENTINEL", json.dumps(self.cli("context", "show")))

    def test_reinitializing_without_scan_hides_cached_newly_excluded_evidence(self):
        self.file("README.md", "Public project description.\n")
        self.file("scripts/private/train.py", "CACHED_NO_SCAN_SENTINEL = 'train'\n")
        self.project.initialize()
        with patch("naia.context.inspect_project", side_effect=AssertionError("Unexpected rescan")):
            self.project.initialize(scan=False, excluded_paths=("scripts/private",))
        self.assertNotIn("CACHED_NO_SCAN_SENTINEL", json.dumps(self.project.context_view()))
        self.assertNotIn("CACHED_NO_SCAN_SENTINEL", json.dumps(self.cli("context", "show")))
        result = self.cli("init", "--no-scan", "--exclude", "scripts/private")
        self.assertNotIn("CACHED_NO_SCAN_SENTINEL", json.dumps(result))

    def test_new_exclusion_hides_private_pending_draft_but_keeps_raw_audit_and_confirmed_answers(self):
        self.file("scripts/private/train.py", "PRIVATE_PROPOSAL_FILE_SENTINEL = 'train'\n")
        self.project.initialize()
        self.confirm_project()
        confirmed = copy.deepcopy(self.project.load()["answers"]["execution"])
        draft = {"training": "PRIVATE_DRAFT_SENTINEL"}
        self.project.propose("execution", draft, evidence=("scripts/private/train.py:1",))
        self.project.answer("governance", {"excluded_paths": ["scripts/private"]}, confirmed=True)
        raw = self.project.load()
        self.assertEqual(raw["answers"]["execution"], confirmed)
        self.assertEqual(raw["proposals"]["execution"]["value"], draft)
        question = self.questions()["execution"]
        self.assertEqual(question["mode"], "confirmed")
        self.assertNotIn("PRIVATE_DRAFT_SENTINEL", json.dumps(self.project.questions()))
        public = self.project.context_view()
        self.assertEqual(public["answers"]["execution"], confirmed)
        self.assertNotIn("PRIVATE_DRAFT_SENTINEL", json.dumps(public))
        self.assertNotIn("PRIVATE_PROPOSAL_FILE_SENTINEL", json.dumps(public))
        self.assertNotIn("PRIVATE_DRAFT_SENTINEL", json.dumps(self.cli("context", "show")))
        with self.assertRaises(NAIAError):
            self.project.accept_proposal("execution", "researcher")
        self.assertEqual(self.project.load()["answers"]["execution"], confirmed)

    def test_symlink_files_and_directories_are_not_followed(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "train.py").write_text("OUTSIDE_SCAN_SENTINEL = 'train'\n")
        (self.project.root / "train.py").symlink_to(outside / "train.py")
        (self.project.root / "scripts").mkdir()
        (self.project.root / "scripts/linked").symlink_to(outside, target_is_directory=True)
        self.file("README.md", "Safe project description.\n")
        discovery = self.project.initialize()["discovery"]
        self.assertNotIn("OUTSIDE_SCAN_SENTINEL", json.dumps(discovery))
        self.assertNotIn("train.py", {item["path"] for item in discovery["sources"]})
        self.assertFalse(any(item["path"].startswith("scripts/linked/") for item in discovery["sources"]))

    def test_sensitive_files_and_inline_credentials_are_not_persisted(self):
        self.file(".env", "API_KEY=ENV_SECRET_SENTINEL\n")
        self.file(".git/config", "password=GIT_SECRET_SENTINEL\n")
        self.file("README.md", "Train with python train.py.\n"
                  "api_key = 'INLINE_SECRET_SENTINEL'\n"
                  "password: PASSWORD_SECRET_SENTINEL\n"
                  "Authorization: Bearer BEARER_SECRET_SENTINEL\n")
        self.project.initialize()
        persisted = self.project.context_path.read_text()
        for secret in ("ENV_SECRET_SENTINEL", "GIT_SECRET_SENTINEL", "INLINE_SECRET_SENTINEL",
                       "PASSWORD_SECRET_SENTINEL", "BEARER_SECRET_SENTINEL"):
            self.assertNotIn(secret, persisted)
        paths = {item["path"] for item in self.project.load()["discovery"]["sources"]}
        self.assertNotIn(".env", paths)
        self.assertNotIn(".git/config", paths)

    def test_scan_bounds_individual_file_reads(self):
        self.file("README.md", "Train with python train.py.\n" + "filler line\n" * 2000
                  + "UNREAD_FILE_TAIL_SENTINEL\n")
        discovery = self.project.initialize()["discovery"]
        self.assertTrue(discovery["truncated"])
        self.assertNotIn("UNREAD_FILE_TAIL_SENTINEL", json.dumps(discovery))

    def test_scan_does_not_reach_beyond_directory_depth_limit(self):
        self.file("README.md", "Safe project description.\n")
        deep = "/".join(["scripts"] + ["nested"] * 8 + ["train.py"])
        self.file(deep, "DEEP_SCAN_SENTINEL = 'train'\n")
        discovery = self.project.initialize()["discovery"]
        self.assertNotIn("DEEP_SCAN_SENTINEL", json.dumps(discovery))
        self.assertNotIn(deep, discovery["detected"]["training_candidates"])

    def test_scan_bounds_file_count_and_persisted_excerpt_bytes(self):
        for index in range(300):
            self.file(f"config/cell{index:03d}.json", '{"batch_size": 8}\n')
        discovery = self.project.initialize()["discovery"]
        self.assertTrue(discovery["truncated"])
        self.assertLessEqual(len(discovery["sources"]), 48)
        self.assertLessEqual(sum(len(item["excerpt"].encode()) for item in discovery["sources"]), 24 * 1024)

    def test_proposal_remains_separate_until_named_user_accepts(self):
        self.existing_project()
        self.project.initialize()
        answer = copy.deepcopy(self.project.load()["answers"]["execution"])
        draft = {"training": "python train.py", "evaluation": "python eval.py"}
        self.project.propose("execution", draft, evidence=("README.md:2", "train.py:1"))
        stored = self.project.load()
        self.assertEqual(stored["answers"]["execution"], answer)
        self.assertEqual(stored["proposals"]["execution"]["value"], draft)
        self.assertEqual(stored["proposals"]["execution"]["status"], "pending")
        self.assertEqual(stored["proposals"]["execution"]["evidence"],
                         [{"path": "README.md", "line": 2}, {"path": "train.py", "line": 1}])
        question = self.questions()["execution"]
        self.assertEqual(question["mode"], "confirm_proposal")
        self.assertRegex(question["question"].lower(), r"confirm|approve|correct")
        self.assertTrue(question["proposal"]["evidence"])
        with self.assertRaises(NAIAError):
            self.project.execution_ready("local")
        self.project.accept_proposal("execution", "researcher")
        accepted = self.project.load()
        self.assertEqual(accepted["answers"]["execution"]["value"], draft)
        self.assertTrue(accepted["answers"]["execution"]["confirmed"])
        self.assertEqual(accepted["proposals"]["execution"]["status"], "accepted")
        self.assertEqual(accepted["onboarding"]["status"], "pending")
        self.assertEqual(self.questions()["execution"]["mode"], "confirmed")
        with self.assertRaises(NAIAError):
            self.project.execution_ready("local")

    def test_proposing_change_preserves_confirmation_until_explicit_acceptance(self):
        self.project.initialize(scan=False)
        self.confirm_project()
        self.file("train.py", "import argparse\n")
        before = self.project.load()
        draft = {"command": "python different_train.py"}
        self.project.propose("execution", draft, evidence=("train.py:1",))
        proposed = self.project.load()
        for key in ("answers", "onboarding", "backends"):
            self.assertEqual(proposed[key], before[key], key)
        self.assertEqual(self.questions()["execution"]["mode"], "confirm_proposal")
        self.project.accept_proposal("execution", "researcher")
        after = self.project.load()
        self.assertEqual(after["answers"]["execution"]["value"], draft)
        self.assertEqual(after["onboarding"]["status"], "pending")
        self.assertEqual(after["backends"], before["backends"])

    def test_invalid_evidence_is_rejected_without_mutating_context(self):
        self.project.initialize(scan=False)
        self.file("train.py", "import argparse\n")
        outside = Path(self.temp.name) / "outside.py"
        outside.write_text("print('outside')\n")
        (self.project.root / "linked.py").symlink_to(outside)
        invalid = ("../outside.py", str(outside), "missing.py", "train.py:0", "train.py:-1",
                   "train.py:not-a-line", "linked.py:1", "src", "train.py\x00:1")
        (self.project.root / "src").mkdir()
        before = self.project.context_path.read_bytes()
        for evidence in invalid:
            with self.subTest(evidence=evidence):
                with self.assertRaises((NAIAError, ValueError)):
                    self.project.propose("execution", {"command": "python train.py"}, evidence=(evidence,))
                self.assertEqual(self.project.context_path.read_bytes(), before)

    def test_invalid_proposal_or_acceptance_cannot_change_context(self):
        self.project.initialize(scan=False)
        self.file("train.py", "import argparse\n")
        before = self.project.context_path.read_bytes()
        for field, value in (("unknown", "draft"), ("execution", None), ("execution", ""),
                             ("execution", {})):
            with self.subTest(field=field, value=value):
                with self.assertRaises(NAIAError):
                    self.project.propose(field, value, evidence=("train.py:1",))
                self.assertEqual(self.project.context_path.read_bytes(), before)
        with self.assertRaises(NAIAError):
            self.project.accept_proposal("execution", "researcher")
        with self.assertRaises(NAIAError):
            self.project.propose("execution", {"command": "python train.py"})
        self.assertEqual(self.project.context_path.read_bytes(), before)
        self.project.propose("execution", {"command": "python train.py"}, evidence=("train.py:1",))
        proposed = self.project.context_path.read_bytes()
        with self.assertRaises(NAIAError):
            self.project.accept_proposal("execution", " ")
        self.assertEqual(self.project.context_path.read_bytes(), proposed)

    def test_proposal_cannot_use_evidence_from_excluded_files(self):
        self.file("scripts/private/train.py", "import argparse\n")
        self.project.initialize(excluded_paths=("scripts/private",))
        before = self.project.context_path.read_bytes()
        with self.assertRaises(NAIAError):
            self.project.propose("execution", {"command": "python scripts/private/train.py"},
                                 evidence=("scripts/private/train.py:1",))
        self.assertEqual(self.project.context_path.read_bytes(), before)

    def test_direct_confirmed_answer_supersedes_a_pending_proposal(self):
        self.project.initialize(scan=False)
        self.file("train.py", "import argparse\n")
        self.project.propose("execution", {"training": "python train.py"}, evidence=("train.py:1",))
        corrected = {"training": "python train.py --config user-approved.json"}
        self.project.answer("execution", corrected, confirmed=True)
        self.assertEqual(self.questions()["execution"]["mode"], "confirmed")
        self.assertEqual(self.project.load()["answers"]["execution"]["value"], corrected)
        with self.assertRaises(NAIAError):
            self.project.accept_proposal("execution", "researcher")
        self.assertEqual(self.project.load()["answers"]["execution"]["value"], corrected)

    def test_existing_unconfirmed_answer_is_offered_for_confirmation(self):
        self.project.initialize(scan=False)
        draft = {"backend": "local", "gpus": 1}
        self.project.answer("hardware", draft, confirmed=False)
        question = self.questions()["hardware"]
        self.assertEqual(question["mode"], "confirm_proposal")
        self.assertEqual(question["proposal"]["value"], draft)
        self.assertFalse(question["answer"]["confirmed"])
        self.project.accept_proposal("hardware", "researcher")
        self.assertTrue(self.project.load()["answers"]["hardware"]["confirmed"])
        self.assertEqual(self.project.load()["answers"]["hardware"]["value"], draft)

    def test_cli_init_scan_propose_accept_lifecycle(self):
        self.existing_project()
        self.file("scripts/private/train.py", "PRIVATE_CLI_SENTINEL = 'train'\n")
        initialized = self.cli("init", "--assistant", "claude", "--exclude", "scripts/private")
        self.assertEqual(initialized["assistants"]["selection"], "claude")
        self.assertTrue(self.project.load()["discovery"]["existing_project"])
        self.assertNotIn("PRIVATE_CLI_SENTINEL", json.dumps(self.project.load()["discovery"]))
        self.cli("context", "scan", "--exclude", "scripts/private", "--exclude", "outputs")
        value = {"training": "python train.py", "evaluation": "python eval.py"}
        self.cli("context", "propose", "execution", "--value", json.dumps(value),
                 "--evidence", "README.md:2", "--evidence", "eval.py:1")
        questions = self.cli("context", "questions")
        execution = next(item for item in questions if item["field"] == "execution")
        self.assertEqual(execution["mode"], "confirm_proposal")
        self.cli("context", "accept", "execution", "--by", "researcher")
        accepted = self.project.load()
        self.assertTrue(accepted["answers"]["execution"]["confirmed"])
        self.assertEqual(accepted["answers"]["execution"]["value"], value)
        self.assertEqual(accepted["onboarding"]["status"], "pending")
        error = self.cli("context", "accept", "hardware", "--by", "researcher", expected=2)
        self.assertIn("error", error)

    def test_no_scan_keeps_setup_pending_and_allows_later_explicit_scan(self):
        self.existing_project()
        self.cli("init", "--assistant", "codex", "--no-scan")
        data = self.project.load()
        self.assertFalse(data.get("discovery", {}).get("sources"))
        self.assertEqual(data["onboarding"]["status"], "pending")
        self.cli("context", "scan")
        self.assertTrue(self.project.load()["discovery"]["existing_project"])


if __name__ == "__main__":
    unittest.main()
