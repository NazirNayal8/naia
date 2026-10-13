"""Markdown links do not open or validate optional report directories."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from naia.context import Project
from naia.materials import MaterialRenderer
from naia.reports import ReportError
from naia.storage import NAIAError, write_json


class SuiteCardMaterialsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = Project(self.root)
        self.project.initialize(scan=False, excluded_paths=["reports"])
        data = self.project.load()
        data["answers"]["reporting"]["value"]["reports_directory"] = "reports"
        write_json(self.project.context_path, data)
        self.card = self.root / "card.md"
        self.card.write_text("# Suite\n[Metrics](metrics.json)\n![Energy](energy.png)\n"
                             "[Report](reports/SAFE/index.html)\n[Shortcut](report:SAFE)\n")
        self.renderer = MaterialRenderer(self.project)

    def assert_links_render(self):
        before = self.card.read_bytes()
        body = self.renderer.render_material_page(self.card)
        self.assertIn(b'href="/material?path=metrics.json"', body)
        self.assertIn(b'src="/asset?path=energy.png"', body)
        self.assertIn(b'href="/report?id=SAFE"', body)
        self.assertEqual(self.card.read_bytes(), before)
        return body

    def test_excluded_missing_reports_do_not_block_card_links(self):
        with self.assertRaises(ReportError):
            self.project.reports()
        self.assert_links_render()
        self.assertFalse((self.root / "reports").exists())

    def test_excluded_report_files_remain_unreadable_and_unchanged(self):
        report = self.root / "reports" / "SAFE" / "index.html"
        report.parent.mkdir(parents=True)
        report.write_text("Private report evidence")
        before = report.read_bytes()
        self.assert_links_render()
        with self.assertRaises(ReportError):
            self.project.reports(validate_on_init=False).asset("SAFE", "index.html")
        with self.assertRaises(NAIAError):
            self.renderer.read_text("reports/SAFE/index.html")
        self.assertEqual(report.read_bytes(), before)

    def test_report_root_file_does_not_block_card_links(self):
        self.project.scan(excluded_paths=[])
        report_root = self.root / "reports"
        report_root.write_bytes(b"not a directory")
        self.assert_links_render()
        self.assertEqual(report_root.read_bytes(), b"not a directory")

    def test_report_root_symlink_does_not_block_card_links_or_allow_reads(self):
        self.project.scan(excluded_paths=[])
        target = self.root / "real-reports"
        target.mkdir()
        try:
            (self.root / "reports").symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlinks unavailable: {exc}")
        self.assert_links_render()
        with self.assertRaises(ReportError):
            self.project.reports(validate_on_init=False).asset("SAFE", "index.html")
        self.assertEqual(list(target.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
