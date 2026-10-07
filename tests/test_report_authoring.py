"""Authoring/export safety contracts using disposable report libraries only."""
from __future__ import annotations

from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import unittest


import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from naia.reports import Reports
from naia.report_authoring import AuthoringError as ReportError, new_report, export_report

KIT_URL = "/reports/_kit/naia_report_kit.js"
KIT_ASSETS = {KIT_URL: b"window.NAIAReport={init:function(){return{};}};",
              "/reports/_kit/naia_report_kit.css": b"body{font-family:system-ui}"}


class TextResources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.resources = []
        self.scripts = []
        self.styles = []
        self.tag = None
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        for key in ("src", "href"):
            if values.get(key):
                self.resources.append((tag, key, values[key]))
        self.tag = tag if tag in ("script", "style") else None
    def handle_endtag(self, tag):
        if tag == self.tag:
            self.tag = None
    def handle_data(self, data):
        if self.tag == "script":
            self.scripts.append(data)
        elif self.tag == "style":
            self.styles.append(data)


class ReportAuthoringTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = Reports(self.root, "reports")
        (self.root / "exports").mkdir()

    def bundle(self, report_id="REPORT_A", *, body="<p>Original prose &amp; evidence</p>", head=""):
        folder = self.root / "reports" / report_id
        folder.mkdir(parents=True)
        title = "Evidence report"
        (folder / "meta.json").write_text(json.dumps({"id": report_id, "title": title,
             "date": "2026-10-07", "summary": "Synthetic evidence", "tags": []}))
        (folder / "index.html").write_text("<!doctype html><html><head><title>" + title +
            "</title>" + head + "</head><body>" + body + "</body></html>")
        return folder

    def exported(self, report_id="REPORT_A", name="exports/report.html", **kwargs):
        result = export_report(self.library, report_id, name, **kwargs)
        return result, Path(result["path"]).read_text()

    def test_new_report_creates_valid_empty_draft_and_escaped_title(self):
        title = 'Evidence <script>alert("x")</script> & "quotes"'
        result = new_report(self.library, "NEW_REPORT", title, summary="Approved draft summary",
                            date="2026-10-07")
        folder = Path(result["path"])
        self.assertEqual(folder, self.root / "reports" / "NEW_REPORT")
        self.assertEqual(result["meta"]["title"], title)
        self.assertEqual(result["meta"]["date"], "2026-10-07")
        self.assertTrue(self.library.check("NEW_REPORT")["valid"])
        document = (folder / "index.html").read_text()
        self.assertIn("<title>" + escape(title) + "</title>", document)
        self.assertNotIn(title, document)
        self.assertIn(KIT_URL, document)
        self.assertNotIn("<svg", document.lower())
        self.assertEqual(result["meta"]["tags"], [])
        self.assertEqual(result["meta"]["sources"], [])

    def test_new_report_uses_real_default_date_and_date_alias(self):
        result = new_report(self.library, "DEFAULT_DATE", "Draft")
        from datetime import date
        date.fromisoformat(result["meta"]["date"])
        alias = new_report(self.library, "ALIAS_DATE", "Draft", report_date="2026-10-06")
        self.assertEqual(alias["meta"]["date"], "2026-10-06")
        with self.assertRaises(ReportError):
            new_report(self.library, "TWO_DATES", "Draft", date="2026-10-07", report_date="2026-10-06")

    def test_new_report_refuses_bad_identity_date_title_and_overwrite(self):
        for report_id, title, date in (("lowercase", "Draft", "2026-10-07"),
                                     ("../ESCAPE", "Draft", "2026-10-07"),
                                     ("GOOD", "", "2026-10-07"),
                                     ("GOOD", "Draft", "2026-02-30")):
            with self.subTest(report_id=report_id, title=title, date=date):
                with self.assertRaises(ReportError):
                    new_report(self.library, report_id, title, date=date)
        result = new_report(self.library, "EXISTING", "Original")
        before = {path.name: path.read_bytes() for path in Path(result["path"]).iterdir()}
        with self.assertRaises(ReportError):
            new_report(self.library, "EXISTING", "Replacement")
        self.assertEqual(before, {path.name: path.read_bytes() for path in Path(result["path"]).iterdir()})

    def test_creation_preserves_existing_invalid_folder(self):
        folder = self.root / "reports" / "EXISTING"
        folder.mkdir(parents=True)
        (folder / "keep.txt").write_text("user's existing bytes")
        with self.assertRaises(ReportError):
            new_report(self.library, "EXISTING", "Draft")
        self.assertEqual((folder / "keep.txt").read_text(), "user's existing bytes")

    def test_creation_checks_excluded_folder_and_symlink_ancestors(self):
        library = Reports(self.root, "reports", excluded=lambda path: path.startswith("reports/BLOCKED"))
        with self.assertRaises(ReportError):
            new_report(library, "BLOCKED", "Draft")
        self.assertFalse((self.root / "reports" / "BLOCKED").exists())
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / "reports").mkdir(exist_ok=True)
        (self.root / "reports" / "LINKED").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ReportError):
            new_report(self.library, "LINKED", "Draft")
        self.assertEqual(list(outside.iterdir()), [])

    def test_new_report_allows_explicit_lab_library_prefix(self):
        library = Reports(self.root, ".lab/reports")
        new_report(library, "LAB_DRAFT", "Draft")
        self.assertTrue(library.check("LAB_DRAFT")["valid"])

    def test_export_embeds_local_scripts_css_images_fonts_and_json_without_mutation(self):
        folder = self.bundle(body='<p>Original prose &amp; evidence</p><img src="image.svg">'
            '<script src="helper.js"></script><script id="science-data" type="application/json">'
            '{"score":null,"negative":-4,"label":"original"}</script>',
            head='<link rel="stylesheet" href="style.css">')
        (folder / "image.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="2" height="2"/></svg>')
        (folder / "font.woff2").write_bytes(b"synthetic font")
        (folder / "style.css").write_text('@font-face{font-family:Local;src:url(font.woff2)}'
                                          'body{font-family:Local,system-ui;background-image:url(image.svg)}')
        (folder / "helper.js").write_text("window.exportFixtureRan=true;")
        before = {path.name: path.read_bytes() for path in folder.iterdir()}
        result, document = self.exported()
        parser = TextResources()
        parser.feed(document)
        self.assertTrue(all(value.startswith(("data:", "#")) for _, _, value in parser.resources),
                        parser.resources)
        self.assertIn("window.exportFixtureRan=true", document)
        self.assertIn("data:font/woff2", document)
        self.assertIn("data:image/svg+xml", document)
        self.assertIn('{"score":null,"negative":-4,"label":"original"}', document)
        self.assertIn("Original prose &amp; evidence", document)
        self.assertEqual(result["bytes"], Path(result["path"]).stat().st_size)
        self.assertEqual(before, {path.name: path.read_bytes() for path in folder.iterdir()})

    def test_export_resolves_recursive_css_and_relative_nested_resources(self):
        folder = self.bundle(head='<link rel="stylesheet" href="styles/main.css">')
        (folder / "styles").mkdir()
        (folder / "images").mkdir()
        (folder / "styles" / "main.css").write_text('@import "sub.css";body{color:blue}')
        (folder / "styles" / "sub.css").write_text('.detail{background:url(../images/pixel.svg)}')
        (folder / "images" / "pixel.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        _, document = self.exported()
        self.assertIn("color:blue", document)
        self.assertIn("data:image/svg+xml", document)
        self.assertNotIn('@import "sub.css"', document)
        self.assertNotIn("../images/pixel.svg", document)

    def test_export_refuses_css_cycles_missing_resources_and_remote_dependencies(self):
        for head in ('<link rel="stylesheet" href="missing.css">',
                     '<script src="https://evil.invalid/helper.js"></script>'):
            with self.subTest(head=head):
                folder = self.bundle("BROKEN", head=head)
                with self.assertRaises(ReportError):
                    self.exported("BROKEN")
                self.assertFalse((self.root / "exports/report.html").exists())
                for path in folder.iterdir():
                    path.unlink()
                folder.rmdir()
        folder = self.bundle(head='<link rel="stylesheet" href="a.css">')
        (folder / "a.css").write_text('@import "b.css";')
        (folder / "b.css").write_text('@import "a.css";')
        with self.assertRaises(ReportError):
            self.exported()
        self.assertFalse((self.root / "exports/report.html").exists())

    def test_export_drops_optional_google_fonts_and_keeps_system_fallback(self):
        self.bundle(head='<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter">'
            '<style>body{font-family:Inter,system-ui}</style>')
        _, document = self.exported()
        self.assertNotIn("fonts.googleapis.com", document)
        self.assertIn("system-ui", document)

    def test_shared_kit_requires_supplied_asset_and_is_inlined(self):
        new_report(self.library, "NEW_REPORT", "Draft")
        with self.assertRaises(ReportError):
            self.exported("NEW_REPORT")
        self.assertFalse((self.root / "exports/report.html").exists())
        _, document = self.exported("NEW_REPORT", kit_assets=KIT_ASSETS)
        self.assertIn("window.NAIAReport={init:", document)
        parser = TextResources()
        parser.feed(document)
        self.assertFalse(any(value == KIT_URL for _, _, value in parser.resources))

    def test_export_refuses_existing_output_and_report_tree_output(self):
        self.bundle()
        output = self.root / "exports" / "report.html"
        output.write_text("user's existing export")
        with self.assertRaises(ReportError):
            self.exported()
        self.assertEqual(output.read_text(), "user's existing export")
        with self.assertRaises(ReportError):
            self.exported(name="reports/REPORT_A/extra.html")
        self.assertFalse((self.root / "reports" / "REPORT_A" / "extra.html").exists())

    def test_export_refuses_outside_hidden_excluded_symlink_and_wrong_suffix_paths(self):
        self.bundle()
        library = Reports(self.root, "reports", excluded=lambda path: path.startswith("blocked/"))
        for output in (self.root.parent / "outside.html", ".hidden/out.html", "exports/out.js", "blocked/out.html"):
            with self.subTest(output=output):
                with self.assertRaises(ReportError):
                    export_report(library, "REPORT_A", output)
        target = self.root / "linked-target"
        target.mkdir()
        (self.root / "linked").symlink_to(target, target_is_directory=True)
        with self.assertRaises(ReportError):
            self.exported(name="linked/out.html")
        self.assertFalse((target / "out.html").exists())
        (self.root / "exports" / "alias.html").symlink_to(self.root / "not-created.html")
        with self.assertRaises(ReportError):
            self.exported(name="exports/alias.html")


    def test_export_refuses_async_script_without_partial_output(self):
        folder = self.bundle(body='<script async src="helper.js"></script>')
        (folder / "helper.js").write_text("window.asyncFixture=true;")
        before = (folder / "index.html").read_bytes()
        with self.assertRaises(ReportError):
            self.exported()
        self.assertFalse((self.root / "exports/report.html").exists())
        self.assertEqual((folder / "index.html").read_bytes(), before)

    def test_export_refuses_unsupported_css_image_set_without_false_offline_claim(self):
        folder = self.bundle(head='<link rel="stylesheet" href="style.css">')
        (folder / "style.css").write_text('body{background-image:image-set("image.svg" 1x)}')
        (folder / "image.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        with self.assertRaises(ReportError):
            self.exported()
        self.assertFalse((self.root / "exports/report.html").exists())


    def test_export_escapes_inlined_script_closing_tags(self):
        folder = self.bundle(body='<script src="helper.js"></script>')
        (folder / "helper.js").write_text('window.literal="</script><div>literal</div>";')
        _, document = self.exported()
        self.assertNotIn('window.literal="</script>', document)
        self.assertIn("<\\/script>", document)


if __name__ == "__main__":
    unittest.main()
