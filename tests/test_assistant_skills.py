"""Opt-in setup skill installation; all user directories are disposable fixtures."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from importlib.resources import files
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naia import assistant_skills
from naia.cli import main
from naia.storage import NAIAError


class AssistantSkillsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="naia-assistant-skill-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "user"
        self.project = self.root / "project"
        self.home.mkdir()
        self.project.mkdir()
        home = patch.object(Path, "home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)
        # Never override HOME/CODEX_HOME or inherit an actual Claude config path.
        claude = patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": ""})
        claude.start()
        self.addCleanup(claude.stop)

    def directory(self, assistant):
        base = ".agents" if assistant == "codex" else ".claude"
        return self.home / base / "skills" / "naia-setup"

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file() and not path.is_symlink()}

    def cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--project", str(self.project), *arguments])
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_installed(self, assistant):
        directory = self.directory(assistant)
        content = (directory / "SKILL.md").read_text(encoding="utf-8")
        record = json.loads((directory / "installation.json").read_text())
        self.assertTrue(content.startswith("---\nname: naia-setup\n"))
        self.assertIn("description:", content.split("---", 2)[1])
        self.assertIn("installation.json", content)
        self.assertIn("-m naia.cli", content)
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["package"], "naia")
        self.assertEqual(record["skill"], "naia-setup")
        self.assertEqual(record["sha256"], hashlib.sha256(content.encode("utf-8")).hexdigest())
        self.assertEqual(record["python"], str(Path(sys.executable).absolute()))
        return content, record

    def test_bundled_skill_is_readable_without_optional_ui_metadata(self):
        skill = files("naia").joinpath("skills", "naia-setup", "SKILL.md")
        self.assertTrue(skill.is_file())
        self.assertIn("Set up NAIA", skill.read_text(encoding="utf-8"))
        result = assistant_skills.install_setup_skill("both")
        self.assertEqual(result["skill"], "naia-setup")
        self.assertEqual({item["assistant"] for item in result["files"]}, {"codex", "claude"})
        self.assertTrue(all(item["changed"] for item in result["files"]))
        self.assertIn("$naia-setup", result["assistant_action"])
        self.assertIn("/naia-setup", result["assistant_action"])
        self.assertEqual(self.assert_installed("codex"), self.assert_installed("claude"))
        self.assertFalse((self.project / ".lab").exists())

    def test_selectors_install_only_requested_integration(self):
        for selected in ("codex", "claude"):
            with self.subTest(selected=selected):
                subhome = self.home / selected
                subhome.mkdir()
                with patch.object(Path, "home", return_value=subhome):
                    result = assistant_skills.install_setup_skill(selected)
                self.assertEqual([item["assistant"] for item in result["files"]], [selected])
                requested = ".agents" if selected == "codex" else ".claude"
                other = ".claude" if selected == "codex" else ".agents"
                self.assertTrue((subhome / requested / "skills" / "naia-setup" / "SKILL.md").is_file())
                self.assertFalse((subhome / other).exists())

    def test_claude_config_override_does_not_change_codex_location(self):
        configured = self.root / "configured claude"
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(configured)}):
            result = assistant_skills.install_setup_skill("both")
        self.assertEqual({item["path"] for item in result["files"]}, {
            str(self.directory("codex") / "SKILL.md"),
            str(configured / "skills" / "naia-setup" / "SKILL.md"),
        })
        self.assertFalse((self.home / ".claude").exists())
        self.assertTrue((configured / "skills" / "naia-setup" / "SKILL.md").is_file())

    def test_invalid_selector_does_not_write(self):
        before = self.snapshot()
        with self.assertRaises(NAIAError):
            assistant_skills.install_setup_skill("other")
        self.assertEqual(self.snapshot(), before)

    def test_repeat_install_is_idempotent(self):
        assistant_skills.install_setup_skill("both")
        before = self.snapshot()
        stamps = {path: path.stat().st_mtime_ns for path in self.home.rglob("*") if path.is_file()}
        with patch.object(assistant_skills, "atomic_text", side_effect=AssertionError("Idempotent installation wrote files")):
            result = assistant_skills.install_setup_skill("both")
        self.assertFalse(any(item["changed"] for item in result["files"]))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual({path: path.stat().st_mtime_ns for path in stamps}, stamps)

    def test_cli_install_precedes_project_discovery_and_preserves_instructions(self):
        for directory in (self.home, self.project):
            for filename in ("AGENTS.md", "CLAUDE.md"):
                (directory / filename).write_text("Existing instructions remain unchanged.\n")
        existing = self.snapshot()
        with patch("naia.cli.Project.discover", side_effect=AssertionError("Installation inspected the project")):
            code, stdout, stderr = self.cli("assistant", "install", "--assistant", "both")
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["skill"], "naia-setup")
        self.assertFalse((self.project / ".lab").exists())
        after = self.snapshot()
        for name, content in existing.items():
            self.assertEqual(after[name], content)
        self.assertEqual(set(self.project.iterdir()), {self.project / "AGENTS.md", self.project / "CLAUDE.md"})

    def test_cli_help_does_not_initialize_or_install(self):
        before = self.snapshot()
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as caught:
            main(["assistant", "install", "--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("--assistant", stdout.getvalue())
        self.assertIn("codex", stdout.getvalue())
        self.assertIn("claude", stdout.getvalue())
        self.assertEqual(self.snapshot(), before)

    def test_custom_second_target_is_preflighted_before_first_is_written(self):
        claude = self.directory("claude")
        claude.mkdir(parents=True)
        (claude / "SKILL.md").write_text("User-owned setup instructions.\n")
        before = self.snapshot()
        with self.assertRaisesRegex(NAIAError, "custom|managed|modified"):
            assistant_skills.install_setup_skill("both")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.directory("codex").exists())

    def test_custom_existing_directory_is_not_adopted(self):
        target = self.directory("codex")
        target.mkdir(parents=True)
        (target / "README.txt").write_text("User files.\n")
        before = self.snapshot()
        with self.assertRaisesRegex(NAIAError, "managed|custom"):
            assistant_skills.install_setup_skill("codex")
        self.assertEqual(self.snapshot(), before)

    def test_modified_managed_skill_is_preserved(self):
        assistant_skills.install_setup_skill("both")
        skill = self.directory("claude") / "SKILL.md"
        skill.write_text(skill.read_text() + "\nUser customization.\n")
        before = self.snapshot()
        with self.assertRaisesRegex(NAIAError, "custom|modified"):
            assistant_skills.install_setup_skill("both")
        self.assertEqual(self.snapshot(), before)

    def test_corrupt_ownership_record_is_preserved(self):
        assistant_skills.install_setup_skill("codex")
        record = self.directory("codex") / "installation.json"
        record.write_text("not valid JSON\n")
        before = self.snapshot()
        with self.assertRaisesRegex(NAIAError, "custom|modified"):
            assistant_skills.install_setup_skill("codex")
        self.assertEqual(self.snapshot(), before)

    def test_non_utf8_existing_skill_is_preserved(self):
        target = self.directory("codex")
        target.mkdir(parents=True)
        (target / "SKILL.md").write_bytes(b"\xff\xfe\x80")
        before = self.snapshot()
        with self.assertRaisesRegex(NAIAError, "Inspect|text|UTF"):
            assistant_skills.install_setup_skill("codex")
        self.assertEqual(self.snapshot(), before)

    def test_managed_update_refreshes_content_and_ownership(self):
        assistant_skills.install_setup_skill("both")
        source = self.root / "replacement-skill"
        source.mkdir()
        replacement = source / "SKILL.md"
        old = (self.directory("codex") / "SKILL.md").read_text()
        new = old + "\nUpdated bundled instructions.\n"
        replacement.write_text(new)
        with patch.object(assistant_skills, "files") as resources:
            resources.return_value.joinpath.return_value = replacement
            result = assistant_skills.install_setup_skill("both")
        self.assertTrue(all(item["changed"] for item in result["files"]))
        self.assertEqual(self.assert_installed("codex")[0], new)
        self.assertEqual(self.assert_installed("claude")[0], new)

    def test_new_install_write_failure_rolls_back_first_target(self):
        before = self.snapshot()
        actual = assistant_skills.atomic_text
        calls = []

        def fail_second_target(path, content):
            calls.append(path)
            if path == self.directory("claude") / "SKILL.md":
                raise OSError("Injected write failure")
            return actual(path, content)

        with patch.object(assistant_skills, "atomic_text", side_effect=fail_second_target):
            with self.assertRaisesRegex(OSError, "Injected"):
                assistant_skills.install_setup_skill("both")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(calls[:2], [self.directory("codex") / "SKILL.md", self.directory("codex") / "installation.json"])

    def test_managed_update_write_failure_restores_original_files(self):
        assistant_skills.install_setup_skill("both")
        source = self.root / "replacement-skill"
        source.mkdir()
        replacement = source / "SKILL.md"
        replacement.write_text((self.directory("codex") / "SKILL.md").read_text() + "\nUpdated version.\n")
        before = self.snapshot()
        actual = assistant_skills.atomic_text

        def fail_update(path, content):
            if path == self.directory("claude") / "SKILL.md":
                raise OSError("Injected update failure")
            return actual(path, content)

        with patch.object(assistant_skills, "files") as resources, patch.object(
                assistant_skills, "atomic_text", side_effect=fail_update):
            resources.return_value.joinpath.return_value = replacement
            with self.assertRaisesRegex(OSError, "Injected"):
                assistant_skills.install_setup_skill("both")
        self.assertEqual(self.snapshot(), before)

    @unittest.skipIf(os.name == "nt", "Symlink creation may require extra Windows privileges")
    def test_symlinked_skill_directory_or_file_is_not_followed(self):
        for kind in ("directory", "file"):
            with self.subTest(kind=kind):
                separate = self.home / kind
                separate.mkdir()
                target = separate / ".agents" / "skills" / "naia-setup"
                unrelated = self.root / (kind + "-unrelated")
                unrelated.mkdir()
                existing = unrelated / "SKILL.md"
                existing.write_text("Unrelated instructions.\n")
                if kind == "directory":
                    target.parent.mkdir(parents=True)
                    target.symlink_to(unrelated, target_is_directory=True)
                else:
                    target.mkdir(parents=True)
                    (target / "SKILL.md").symlink_to(existing)
                before = self.snapshot()
                with patch.object(Path, "home", return_value=separate):
                    with self.assertRaisesRegex(NAIAError, "Inspect|symlink"):
                        assistant_skills.install_setup_skill("codex")
                self.assertEqual(self.snapshot(), before)

    @unittest.skipIf(os.name == "nt", "Symlink creation may require extra Windows privileges")
    def test_symlinked_installation_record_is_not_followed(self):
        assistant_skills.install_setup_skill("codex")
        record = self.directory("codex") / "installation.json"
        shared = self.root / "unrelated-record.json"
        shared.write_bytes(record.read_bytes())
        record.unlink()
        record.symlink_to(shared)
        before = self.snapshot()
        with self.assertRaisesRegex(NAIAError, "Inspect|symlink"):
            assistant_skills.install_setup_skill("codex")
        self.assertTrue(record.is_symlink())
        self.assertEqual(self.snapshot(), before)

    @unittest.skipIf(os.name == "nt", "Symlink creation may require extra Windows privileges")
    def test_shared_symlinked_skills_root_preserves_custom_skill(self):
        shared = self.root / "shared-skills"
        shared.mkdir()
        agents = self.home / ".agents"
        agents.mkdir()
        (agents / "skills").symlink_to(shared, target_is_directory=True)
        custom = shared / "naia-setup"
        custom.mkdir()
        (custom / "SKILL.md").write_text("Existing shared skill.\n")
        before = self.snapshot()
        with self.assertRaisesRegex(NAIAError, "custom|modified"):
            assistant_skills.install_setup_skill("codex")
        self.assertEqual(self.snapshot(), before)

    @unittest.skipIf(os.name == "nt", "Symlink creation may require extra Windows privileges")
    def test_install_to_explicit_shared_symlinked_skills_root(self):
        shared = self.root / "shared-skills"
        shared.mkdir()
        agents = self.home / ".agents"
        agents.mkdir()
        (agents / "skills").symlink_to(shared, target_is_directory=True)
        assistant_skills.install_setup_skill("codex")
        self.assert_installed("codex")
        self.assertTrue((shared / "naia-setup" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
