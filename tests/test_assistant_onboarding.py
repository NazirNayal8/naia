"""CPU-only assistant onboarding contracts; no jobs or external services."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naia.cli import main, parser
from naia.context import Project, QUESTIONS
from naia.demo import install as install_demo
from naia.storage import NAIAError, write_json


BEGIN = "<!-- naia:instructions -->"
END = "<!-- /naia:instructions -->"
LEGACY_BEGIN = "<!-- research-workbench:instructions -->"
LEGACY_END = "<!-- /research-workbench:instructions -->"
FILES = {"codex": {"AGENTS.md"}, "claude": {"CLAUDE.md"},
         "both": {"AGENTS.md", "CLAUDE.md"}}


class AssistantOnboardingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(self.temp.name)

    def snapshot(self, project=None):
        project = project or self.project
        return {
            str(path.relative_to(project.root)): path.read_bytes()
            for path in project.root.rglob("*")
            if path.is_file() and "locks" not in path.relative_to(project.root).parts
        }

    def cli(self, *arguments, project=None):
        project = project or self.project
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--project", str(project.root), *arguments])
        self.assertEqual(code, 0, stderr.getvalue())
        return json.loads(stdout.getvalue())

    def assert_selection(self, project, choice):
        assistants = project.load()["assistants"]
        self.assertEqual(assistants["selection"], choice)
        self.assertEqual(set(assistants["instruction_files"]), FILES[choice])

    def assert_contract(self, text):
        self.assertEqual(text.count(BEGIN), 1)
        self.assertEqual(text.count(END), 1)
        block = text.split(BEGIN, 1)[1].split(END, 1)[0].lower()
        topics = {
            "project context": r"\.lab/project\.json",
            "context questionnaire": r"naia context|during onboarding",
            "workflow policy": r"naia policy",
            "actionable task queue": r"naia task|task queue",
            "automatic queue maintenance": r"automatic|after every|after each|always",
            "task creation": r"\badd\b|\bcreate\b",
            "task updates": r"\bupdate\b|\bupdat\w*\b",
            "review tasks": r"review",
            "discussion follow-up": r"discussion",
            "evaluation follow-up": r"evaluat",
            "analysis follow-up": r"analys",
            "concise writing": r"concise|short",
            "unsolicited document limit": r"unsolicited",
            "validation before launch": r"validat",
            "dry run before launch": r"dry[- ]run",
            "automatic evaluation": r"automatic.*evaluat|auto.?eval",
            "duplicate prevention": r"duplicat",
            "approval boundaries": r"approv",
            "validated results": r"provenance|identity|validated results",
            "shared execution": r"shared",
            "user decisions": r"user",
        }
        for topic, expression in topics.items():
            with self.subTest(topic=topic):
                self.assertRegex(block, expression)

    def test_bare_init_remains_opt_in_and_idempotent(self):
        self.project.initialize()
        before = self.snapshot()
        self.project.initialize()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(list(self.project.root.glob("*.md")), [])
        assistants = self.project.load()["assistants"]
        self.assertIsNone(assistants["selection"])
        self.assertEqual(assistants["instruction_files"], [])

    def test_initialize_installs_only_selected_assistant_files(self):
        for choice, expected in FILES.items():
            with self.subTest(choice=choice):
                project = Project(self.project.root / choice)
                project.initialize(assistant=choice)
                self.assert_selection(project, choice)
                self.assertEqual({path.name for path in project.root.glob("*.md")}, expected)
                for filename in expected:
                    self.assert_contract((project.root / filename).read_text())

    def test_repeated_selection_and_bare_init_preserve_choice_and_instructions(self):
        self.project.initialize(assistant="both")
        before = self.snapshot()
        self.project.initialize(assistant="both")
        self.project.initialize()
        self.assertEqual(self.snapshot(), before)
        self.assert_selection(self.project, "both")

    def test_configure_assistant_preserves_user_answers_and_policies(self):
        self.project.initialize()
        self.project.answer("project", {"goal": "Keep existing research context"}, confirmed=True)
        self.project.answer("evaluation", {"metrics": ["score"], "episodes": 17}, confirmed=False)
        before = self.project.load()
        target = self.project.root / "CLAUDE.md"
        user_text = "Custom user rules.\nRespect local exclusions.\n"
        target.write_text(user_text)
        self.project.configure_assistant("claude")
        after = self.project.load()
        self.assertEqual(after["answers"], before["answers"])
        self.assertEqual(after["policies"], before["policies"])
        self.assertEqual(after["backends"], before["backends"])
        self.assertTrue(target.read_text().startswith(user_text))
        self.assert_selection(self.project, "claude")
        self.assert_contract(target.read_text())

    def test_fresh_defaults_do_not_confirm_research_assumptions(self):
        self.project.initialize()
        answers = self.project.load()["answers"]
        for field in ("reporting", "governance"):
            with self.subTest(field=field):
                self.assertTrue(answers[field]["confirmed"])
                self.assertNotIn(answers[field]["value"], (None, "", {}))
        for field in ("project", "hardware", "execution", "evaluation", "configuration"):
            with self.subTest(field=field):
                self.assertFalse(answers[field]["confirmed"])
        self.assertEqual(self.project.load()["onboarding"]["status"], "pending")

    def test_legacy_context_answers_and_existing_policy_exceptions_are_preserved(self):
        self.project.initialize()
        legacy = self.project.load()
        del legacy["assistants"]
        legacy["policies"].pop("auto_review_tasks", None)
        legacy["policies"]["auto_evaluate"] = False
        legacy["answers"]["reporting"] = {"value": "Existing report format", "confirmed": False}
        legacy["answers"]["governance"] = {"value": "Existing user rules", "confirmed": True}
        write_json(self.project.context_path, legacy)
        before = self.snapshot()
        self.project.initialize()
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(self.project.questions()[0]["answer"]["value"])
        self.project.configure_assistant("codex")
        updated = self.project.load()
        self.assertEqual(updated["answers"], legacy["answers"])
        self.assertEqual(updated["onboarding"], legacy["onboarding"])
        self.assertFalse(updated["policies"]["auto_evaluate"])
        self.assertTrue(updated["policies"]["auto_review_tasks"])
        self.assert_selection(self.project, "codex")

    def test_questions_begin_with_assistant_choice_and_keep_context_topics(self):
        self.project.initialize()
        questions = self.project.questions()
        self.assertEqual(len(questions), len(QUESTIONS) + 1)
        assistant = questions[0]
        self.assertEqual(assistant["field"], "assistant")
        self.assertTrue(assistant["question"])
        options = {
            option if isinstance(option, str) else option.get("value", option.get("id"))
            for option in assistant["options"]
        }
        self.assertEqual(options, set(FILES))
        self.assertEqual([question["field"] for question in questions[1:]],
                         [question["field"] for question in QUESTIONS])
        for question in questions[1:]:
            with self.subTest(field=question["field"]):
                self.assertTrue(question["question"])
                self.assertIn("answer", question)
        self.project.configure_assistant("codex")
        self.assertEqual(self.project.questions()[0]["answer"]["value"], "codex")

    def test_invalid_assistant_choice_changes_no_files(self):
        before = self.snapshot()
        with self.assertRaises(NAIAError):
            self.project.initialize(assistant="unknown")
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(NAIAError):
            self.project.configure_assistant("unknown")
        self.assertEqual(self.snapshot(), before)
        self.project.initialize(assistant="codex")
        before = self.snapshot()
        with self.assertRaises(NAIAError):
            self.project.configure_assistant("unknown")
        self.assertEqual(self.snapshot(), before)

    def test_existing_naia_and_legacy_blocks_upgrade_without_changing_surroundings(self):
        self.project.initialize()
        prefix = "User rules: café.\r\nKeep exactly two spaces here.  \r\n\r\n"
        suffix = "\r\n\r\nFinal user rule: λ.\r\n"
        for filename, begin, end in (("AGENTS.md", BEGIN, END),
                                     ("CLAUDE.md", LEGACY_BEGIN, LEGACY_END)):
            path = self.project.root / filename
            text = prefix + begin + "\nOld minimal integration.\n" + end + suffix
            path.write_bytes(text.encode("utf-8"))
        self.project.install_instructions(["AGENTS.md", "CLAUDE.md"])
        before = self.snapshot()
        for filename in ("AGENTS.md", "CLAUDE.md"):
            with self.subTest(filename=filename):
                text = (self.project.root / filename).read_bytes().decode("utf-8")
                self.assertEqual(text[:text.index(BEGIN)], prefix)
                self.assertEqual(text[text.index(END) + len(END):], suffix)
                self.assertNotIn("Old minimal integration.", text)
                self.assertNotIn(LEGACY_BEGIN, text)
                self.assertNotIn(LEGACY_END, text)
                self.assert_contract(text)
        self.project.install_instructions(["AGENTS.md", "CLAUDE.md"])
        self.assertEqual(self.snapshot(), before)

    def test_marker_errors_cannot_partially_install_files_or_selection(self):
        valid_block = BEGIN + "\nOld minimal integration.\n" + END
        invalid_blocks = {
            "missing closing marker": BEGIN + "\nUser text.\n",
            "missing opening marker": "User text.\n" + END,
            "reversed markers": END + "\nUser text.\n" + BEGIN,
            "duplicate blocks": valid_block + "\n" + valid_block,
            "mixed marker families": valid_block + "\n" + LEGACY_BEGIN + "\nLegacy.\n" + LEGACY_END,
            "mismatched marker families": BEGIN + "\nMixed.\n" + LEGACY_END,
            "incomplete legacy marker": LEGACY_BEGIN + "\nLegacy.\n",
            "orphan legacy closing marker": "User text.\n" + LEGACY_END,
            "nested opening markers": BEGIN + "\n" + BEGIN + "\nNested.\n" + END,
        }
        for label, invalid in invalid_blocks.items():
            with self.subTest(markers=label):
                project = Project(self.project.root / label.replace(" ", "_"))
                project.initialize()
                (project.root / "AGENTS.md").write_text("Keep this prefix.\n" + valid_block)
                (project.root / "CLAUDE.md").write_text(invalid)
                before = self.snapshot(project)
                with self.assertRaises(NAIAError):
                    project.configure_assistant("both")
                self.assertEqual(self.snapshot(project), before)
                with self.assertRaises(NAIAError):
                    project.install_instructions(["AGENTS.md", "CLAUDE.md"])
                self.assertEqual(self.snapshot(project), before)

    def test_invalid_filename_is_rejected_before_installing_valid_first_file(self):
        self.project.initialize()
        before = self.snapshot()
        with self.assertRaises(NAIAError):
            self.project.install_instructions(["AGENTS.md", "other.md"])
        self.assertEqual(self.snapshot(), before)

    def test_assistant_selection_is_not_required_for_legacy_confirmation(self):
        self.project.initialize()
        for question in QUESTIONS:
            self.project.answer(question["field"], "User-approved answer", confirmed=True)
        self.project.configure_backend("local", {"kind": "local"}, confirmed=True)
        self.project.confirm("test-user")
        self.assertEqual(self.project.execution_ready("local")["kind"], "local")
        self.assertIsNone(self.project.load()["assistants"]["selection"])
        self.assertEqual(list(self.project.root.glob("*.md")), [])

    def test_demo_remains_usable_without_assistant_selection(self):
        install_demo(self.project)
        self.assertEqual(self.project.load()["onboarding"]["status"], "confirmed")
        self.assertIsNone(self.project.load()["assistants"]["selection"])
        self.assertFalse((self.project.root / "AGENTS.md").exists())
        self.assertFalse((self.project.root / "CLAUDE.md").exists())

    def test_cli_init_exposes_choices_selection_and_preserves_bare_repeat(self):
        for choice, expected in FILES.items():
            with self.subTest(choice=choice):
                project = Project(self.project.root / choice)
                result = self.cli("init", "--assistant", choice, project=project)
                self.assertEqual(result["assistants"]["selection"], choice)
                self.assertEqual(set(result["assistants"]["instruction_files"]), expected)
                self.assertEqual(result["questions"][0]["field"], "assistant")
                self.assertEqual(result["questions"][0]["answer"]["value"], choice)
                before = {filename: (project.root / filename).read_bytes() for filename in expected}
                self.cli("init", "--assistant", choice, project=project)
                repeated = self.cli("init", project=project)
                self.assertEqual(repeated["assistants"]["selection"], choice)
                self.assertEqual({filename: (project.root / filename).read_bytes()
                                  for filename in expected}, before)

    def test_cli_instruction_selection_and_legacy_filename_parser(self):
        self.cli("init")
        args = parser().parse_args(["instructions", "install", "--assistant", "both"])
        self.assertEqual(args.assistant, "both")
        args = parser().parse_args(["instructions", "install", "AGENTS.md", "CLAUDE.md"])
        self.assertEqual(args.files, ["AGENTS.md", "CLAUDE.md"])
        self.cli("instructions", "install", "--assistant", "both")
        self.assert_selection(self.project, "both")
        before = self.snapshot()
        self.cli("instructions", "install", "AGENTS.md", "CLAUDE.md")
        self.assertEqual(self.snapshot(), before)

    def test_cli_invalid_assistant_choice_has_no_side_effects(self):
        before = self.snapshot()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                main(["--project", str(self.project.root), "init", "--assistant", "unknown"])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.snapshot(), before)

    def test_codex_override_warns_without_modifying_user_override(self):
        override = self.project.root / "AGENTS.override.md"
        content = "User override, preserve exactly.\r\n"
        override.write_bytes(content.encode("utf-8"))
        result = self.cli("init", "--assistant", "codex")
        self.assertTrue(result["warnings"])
        self.assertIn("AGENTS.override.md", result["warnings"][0])
        self.assertEqual(override.read_bytes(), content.encode("utf-8"))
        result = self.cli("instructions", "install", "--assistant", "claude")
        self.assertFalse(result["warnings"])
        self.assertTrue((self.project.root / "AGENTS.md").exists())
        self.assertEqual(override.read_bytes(), content.encode("utf-8"))

    def test_invalid_assistant_types_have_no_side_effects(self):
        for invalid in ([], {}, 1, False):
            with self.subTest(value=invalid):
                before = self.snapshot()
                with self.assertRaises(NAIAError):
                    self.project.initialize(assistant=invalid)
                with self.assertRaises(NAIAError):
                    self.project.configure_assistant(invalid)
                self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
