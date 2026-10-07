"""Inline report edits against disposable libraries, never project reports."""
from __future__ import annotations

from html import escape
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from naia.report_authoring import new_report
from naia.report_editing import EDITOR_JS_ROUTE, EditConflict, EditError, ReportEditor
from naia.reports import Reports, ReportError


class ReportEditingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = Reports(self.root, "reports")
        self.editor = ReportEditor(self.library)

    def bundle(self, report_id="REPORT_A", *, body=None, bridge=True, head=""):
        folder = self.root / "reports" / report_id
        folder.mkdir(parents=True, exist_ok=True)
        meta = {"schema_version": 1, "id": report_id, "title": "Evidence report",
                "date": "2026-10-07", "summary": "Synthetic source", "tags": [],
                "suites": ["SUITE_A"], "naia_tasks": ["REVIEW_A"], "sources": ["results/data.json"]}
        if body is None:
            body = '<h1 data-naia-edit="title">Evidence report</h1>\r\n' \
                   '<p class="summary" data-naia-edit="summary">Old &amp; approved café.</p>' \
                   '<table><tr><td>3.5</td></tr></table>' \
                   '<script id="science-data" type="application/json">{"score":null,"negative":-4}</script>' \
                   '<script>window.original = {value: 12};</script>'
        tail = '<script src="' + EDITOR_JS_ROUTE + '"></script>' if bridge else ""
        content = '<!doctype html>\r\n<html><head><title>Evidence report</title>' + head \
                  + '<style>body{font-family:system-ui}</style></head><body><main>' + body \
                  + '</main>' + tail + '</body></html>\r\n'
        (folder / "meta.json").write_bytes((json.dumps(meta) + "\n").encode())
        (folder / "index.html").write_bytes(content.encode())
        return folder

    def save(self, changes, report_id="REPORT_A"):
        return self.editor.save(report_id, self.editor.snapshot(report_id)["revision"], changes)

    def layout_bundle(self):
        return self.bundle(body='<header>Fixed report introduction</header>\n'
            '<div data-naia-layout="report">\n<!-- root gap -->\n'
            '<section title="hidden bait" data-naia-section="alpha" data-naia-layout="alpha">\n'
            '<h2 data-naia-item="alpha-title" data-naia-edit="alpha-title">Alpha heading</h2>\n<!-- alpha gap -->\n'
            '<p data-naia-item="alpha-text" data-naia-edit="alpha-text">Approved alpha prose.</p>\n'
            '<figure data-naia-item="alpha-chart" data-naia-kind="visual" data-naia-label="Planning success">'
            '<svg id="plot-one"><path d="M 1 3 L 4 6"/></svg><figcaption>Immutable caption</figcaption></figure>\n'
            '</section>\n<!-- between sections -->\n'
            '<section data-naia-section="beta" data-naia-layout="beta">\n'
            '<h2 data-naia-item="beta-title" data-naia-edit="beta-title">Beta heading</h2>\n'
            '<p data-naia-item="beta-text" data-naia-edit="beta-text">Approved beta prose.</p>\n'
            '<div data-naia-item="beta-table" data-naia-kind="visual"><table id="table-two"><tr><td>12.5</td></tr></table></div>\n'
            '</section>\n</div>\n<footer>Fixed evidence sources</footer>'
            '<script id="science-data" type="application/json">{"score":12.5,"series":[3,1,null]}</script>'
            '<script>window.original={target:"plot-one",table:"table-two"};</script>')

    def layout_save(self, layout, changes=None):
        return self.editor.save("REPORT_A", self.editor.snapshot("REPORT_A")["revision"], changes or {}, layout=layout)

    def test_layout_snapshot_has_exact_orders_and_source_marked_visuals(self):
        self.layout_bundle()
        layout = self.editor.snapshot("REPORT_A")["layout"]
        self.assertEqual(layout["root"], "report")
        self.assertEqual(layout["containers"], [
            {"id": "report", "kind": "sections", "order": ["alpha", "beta"]},
            {"id": "alpha", "kind": "items", "order": ["alpha-title", "alpha-text", "alpha-chart"]},
            {"id": "beta", "kind": "items", "order": ["beta-title", "beta-text", "beta-table"]}])
        self.assertEqual(layout["sections"][0], {"id": "alpha", "container": "report", "label": "Alpha heading", "hidden": False})
        chart = next(item for item in layout["items"] if item["id"] == "alpha-chart")
        self.assertEqual(chart, {"id": "alpha-chart", "container": "alpha", "label": "Planning success", "kind": "visual"})

    def test_section_reordering_preserves_inner_source_scripts_data_and_all_comments(self):
        folder = self.layout_bundle()
        before = (folder / "index.html").read_bytes()
        meta = (folder / "meta.json").read_bytes()
        result = self.layout_save({"orders": {"report": ["beta", "alpha"]}})
        after = (folder / "index.html").read_bytes()
        self.assertLess(after.index(b'data-naia-section="beta"'), after.index(b'data-naia-section="alpha"'))
        self.assertEqual((folder / "meta.json").read_bytes(), meta)
        self.assertEqual((self.root / result["backup"]).read_bytes(), before)
        for value in (b'<path d="M 1 3 L 4 6"/>', b'12.5</td>', b'{"score":12.5,"series":[3,1,null]}',
                      b'window.original={target:"plot-one",table:"table-two"};', b'<!-- root gap -->',
                      b'<!-- alpha gap -->', b'<!-- between sections -->', b'Fixed report introduction', b'Fixed evidence sources'):
            self.assertEqual(after.count(value), before.count(value), value)
        self.assertTrue(self.library.check()["valid"])

    def test_visual_item_can_move_between_sections_without_serializing_its_dom(self):
        folder = self.layout_bundle()
        before = (folder / "index.html").read_bytes()
        chart = before[before.index(b'<figure data-naia-item="alpha-chart"'):before.index(b'</figure>') + len(b'</figure>')]
        result = self.layout_save({"orders": {"alpha": ["alpha-title", "alpha-text"],
            "beta": ["beta-title", "alpha-chart", "beta-text", "beta-table"]}})
        after = (folder / "index.html").read_bytes()
        self.assertEqual(after.count(chart), 1)
        self.assertGreater(after.index(chart), after.index(b'data-naia-section="beta"'))
        self.assertEqual(next(item for item in result["layout"]["items"] if item["id"] == "alpha-chart")["container"], "beta")

    def test_section_removal_is_reversible_hidden_attribute_and_retains_chart_targets(self):
        folder = self.layout_bundle()
        before = (folder / "index.html").read_bytes()
        result = self.layout_save({"hidden": ["alpha"]})
        hidden = (folder / "index.html").read_bytes()
        self.assertTrue(result["layout"]["sections"][0]["hidden"])
        self.assertIn(b'id="plot-one"', hidden)
        self.assertIn(b'title="hidden bait"', hidden)
        self.assertEqual(len(hidden) - len(before), len(b" hidden"))
        result = self.layout_save({"hidden": []})
        self.assertFalse(result["layout"]["sections"][0]["hidden"])
        self.assertEqual((folder / "index.html").read_bytes(), before)

    def test_plain_text_new_section_can_be_inserted_edited_and_receive_existing_visual(self):
        folder = self.layout_bundle()
        result = self.layout_save({"add": [{"id": "notes", "container": "report", "title": '<img src=x> & title', "text": "Draft text"}],
            "orders": {"report": ["notes", "beta", "alpha"], "notes": ["notes-title", "alpha-chart", "notes-text"],
                       "alpha": ["alpha-title", "alpha-text"]}}, changes={"notes-text": 'Approved <script>literal</script>\nSecond line', "alpha-text": "Updated alpha prose"})
        source = (folder / "index.html").read_bytes()
        self.assertIn(b'&lt;img src=x&gt; &amp; title', source)
        self.assertIn(b'Approved &lt;script&gt;literal&lt;/script&gt;\nSecond line', source)
        self.assertNotIn(b'<img src=x>', source)
        self.assertEqual(result["layout"]["containers"][0]["order"], ["notes", "beta", "alpha"])
        self.assertEqual(next(item for item in result["layout"]["items"] if item["id"] == "alpha-chart")["container"], "notes")
        self.assertEqual(next(block for block in result["blocks"] if block["id"] == "notes-text")["text"], 'Approved <script>literal</script>\nSecond line')

    def test_empty_managed_root_supports_new_sections_without_existing_editable_text(self):
        self.bundle(body='<div data-naia-layout="empty-layout">\n<!-- retained gap -->\n</div>')
        snapshot = self.editor.snapshot("REPORT_A")
        self.assertTrue(snapshot["editable"])
        self.assertEqual(snapshot["blocks"], [])
        result = self.layout_save({"add": [{"id": "new-section", "container": "empty-layout", "title": "Approved heading", "text": ""}]})
        self.assertEqual(result["layout"]["containers"][0]["order"], ["new-section"])

    def test_layout_requests_reject_omission_duplicates_unknowns_collisions_raw_html_and_noops(self):
        folder = self.layout_bundle()
        before = (folder / "index.html").read_bytes()
        invalid = [{}, {"orders": {"report": ["alpha"]}}, {"orders": {"report": ["alpha", "alpha"]}},
            {"orders": {"unknown": []}}, {"orders": {"alpha": ["alpha-title", "alpha-text"]}},
            {"orders": {"alpha": ["alpha-title", "alpha-text", "alpha-chart", "beta-table"]}},
            {"orders": {"alpha": ["alpha-title", "alpha-text", "alpha-chart", "alpha-chart"]}},
            {"hidden": ["unknown"]}, {"hidden": ["alpha", "alpha"]}, {"remove": ["alpha"]},
            {"add": [{"id": "alpha", "container": "report", "title": "Collision", "text": "Text"}]},
            {"add": [{"id": "notes", "container": "alpha", "title": "Wrong root", "text": "Text"}]},
            {"add": [{"id": "notes", "container": "report", "title": "Raw", "text": "Text", "html": "<p>unsafe</p>"}]},
            {"add": [{"id": "View", "container": "report", "title": "Reserved", "text": "Text"}]},
            {"add": [{"id": "notes", "container": "report", "title": "", "text": "Text"}]}]
        for layout in invalid:
            with self.subTest(layout=layout):
                with self.assertRaises(EditError):
                    self.layout_save(layout)
                self.assertEqual((folder / "index.html").read_bytes(), before)
        self.bundle(body='<div data-naia-layout="report"><section data-naia-section="alpha" data-naia-layout="alpha">'
                         '<p data-naia-item="notes-title">Existing identifier</p></section></div>')
        with self.assertRaises(EditError):
            self.layout_save({"add": [{"id": "notes", "container": "report", "title": "Collision", "text": "Text"}]})

    def test_layout_source_rejects_unmarked_gaps_nested_markers_scripts_and_prose_id_collisions(self):
        invalid = [
            '<div data-naia-layout="report">Unmarked prose<section data-naia-section="alpha" data-naia-layout="alpha"></section></div>',
            '<div data-naia-layout="report"><section data-naia-section="alpha" data-naia-layout="alpha"><p>Unmarked child</p></section></div>',
            '<div data-naia-layout="report"><section data-naia-section="alpha" data-naia-layout="alpha"><div data-naia-item="chart"><script>{"score":12}</script></div></section></div>',
            '<div data-naia-layout="report"><section data-naia-section="alpha" data-naia-layout="alpha"><p data-naia-item="text"><span data-naia-edit="alpha">Collision</span></p></section></div>',
            '<div data-naia-layout="report"><section data-naia-section="alpha" data-naia-layout="alpha"><div data-naia-item="visual"><span data-naia-item="nested">Nested</span></div></section></div>',
            '<div data-naia-layout="report"><section data-naia-section="alpha" data-naia-layout="alpha"><p data-naia-item="alpha-title" data-naia-kind="script">Invalid kind</p></section></div>',
            '<div data-naia-layout="report" data-naia-readonly></div>',
            '<div data-naia-layout="one"></div><div data-naia-layout="two"></div>',
        ]
        for body in invalid:
            with self.subTest(body=body):
                self.bundle(body=body)
                with self.assertRaises(EditError):
                    self.editor.snapshot("REPORT_A")

    def test_layout_revision_conflict_retains_latest_source_and_backup(self):
        folder = self.layout_bundle()
        stale = self.editor.snapshot("REPORT_A")["revision"]
        result = self.layout_save({"hidden": ["beta"]})
        current = (folder / "index.html").read_bytes()
        backup = (self.root / result["backup"]).read_bytes()
        with self.assertRaises(EditConflict):
            self.editor.save("REPORT_A", stale, {}, layout={"orders": {"report": ["beta", "alpha"]}})
        self.assertEqual((folder / "index.html").read_bytes(), current)
        self.assertEqual((self.root / result["backup"]).read_bytes(), backup)

    def test_layout_source_and_addition_counts_are_bounded(self):
        for body in (
            '<div data-naia-layout="report">' + ''.join('<section data-naia-section="s' + str(index) + '" data-naia-layout="s' + str(index) + '"></section>' for index in range(65)) + '</div>',
            '<div data-naia-layout="report"><section data-naia-section="alpha" data-naia-layout="alpha">'
            + ''.join('<div data-naia-item="i' + str(index) + '">Immutable</div>' for index in range(257)) + '</section></div>'):
            self.bundle(body=body)
            with self.assertRaises(EditError):
                self.editor.snapshot("REPORT_A")
        self.layout_bundle()
        with self.assertRaises(EditError):
            self.layout_save({"add": [{"id": "n" + str(index), "container": "report", "title": "Added heading", "text": ""} for index in range(33)]})
        result = self.layout_save({"add": [{"id": "n" + str(index), "container": "report", "title": "Added heading", "text": ""} for index in range(32)]})
        self.assertEqual(len(result["layout"]["sections"]), 34)

    def test_moving_items_and_back_does_not_grow_whitespace_or_alter_chart_bytes(self):
        folder = self.layout_bundle()
        before = (folder / "index.html").read_bytes()
        self.layout_save({"orders": {"alpha": ["alpha-title", "alpha-text"],
            "beta": ["beta-title", "beta-text", "beta-table", "alpha-chart"]}})
        self.layout_save({"orders": {"alpha": ["alpha-title", "alpha-text", "alpha-chart"],
            "beta": ["beta-title", "beta-text", "beta-table"]}})
        after = (folder / "index.html").read_bytes()
        self.assertEqual(len(after), len(before))
        self.assertEqual(after.count(b'<path d="M 1 3 L 4 6"/>'), 1)
        self.assertEqual(after.count(b'<!-- alpha gap -->'), 1)

    def test_snapshot_is_read_only_and_returns_exact_source_revision(self):
        folder = self.bundle()
        before = {path.name: path.read_bytes() for path in folder.iterdir()}
        snapshot = self.editor.snapshot("REPORT_A")
        import hashlib
        self.assertEqual(snapshot["revision"], hashlib.sha256(before["index.html"]).hexdigest())
        self.assertTrue(snapshot["editable"])
        self.assertEqual(snapshot["blocks"], [{"id": "title", "text": "Evidence report"},
            {"id": "summary", "text": "Old & approved café."}])
        self.assertEqual(before, {path.name: path.read_bytes() for path in folder.iterdir()})
        self.assertFalse((self.root / "reports/.naia-edit").exists())

    def test_literal_edit_replaces_only_marked_contents_and_preserves_data_metadata_and_newlines(self):
        folder = self.bundle()
        before = (folder / "index.html").read_bytes()
        meta = (folder / "meta.json").read_bytes()
        submitted = 'New <script>alert("literal")</script> & café\nSecond line.'
        result = self.save({"summary": submitted})
        expected = before.replace(b"Old &amp; approved caf\xc3\xa9.", escape(submitted).encode())
        self.assertEqual((folder / "index.html").read_bytes(), expected)
        self.assertEqual((folder / "meta.json").read_bytes(), meta)
        self.assertEqual(result["blocks"][1]["text"], submitted)
        self.assertEqual(result["backup"], "reports/.naia-edit/REPORT_A/index.previous.html")
        self.assertEqual((self.root / result["backup"]).read_bytes(), before)
        self.assertEqual(result["revision"], self.editor.snapshot("REPORT_A")["revision"])
        self.assertTrue(self.library.check("REPORT_A")["valid"])
        self.assertTrue(self.library.check()["valid"])
        self.assertEqual([row["id"] for row in self.library.search()["reports"]], ["REPORT_A"])
        self.assertEqual([row["id"] for row in self.library.search("Second line")["reports"]], ["REPORT_A"])

    def test_multiple_edits_retain_only_one_previous_source(self):
        folder = self.bundle()
        self.save({"summary": "First approved edit"})
        intermediate = (folder / "index.html").read_bytes()
        result = self.save({"summary": "Second approved edit", "title": "Body heading"})
        private = self.root / "reports/.naia-edit/REPORT_A"
        self.assertEqual({path.name for path in private.iterdir()}, {"editor.lock", "index.previous.html"})
        self.assertEqual((self.root / result["backup"]).read_bytes(), intermediate)
        self.assertEqual({path.name for path in folder.iterdir()}, {"index.html", "meta.json"})
        self.assertTrue(self.library.check()["valid"])
        for path in (".naia-edit/REPORT_A/index.previous.html", "../.naia-edit/REPORT_A/index.previous.html"):
            with self.assertRaises(ReportError):
                self.library.asset("REPORT_A", path)
        with self.assertRaises(ReportError):
            self.library.asset(".naia-edit", "REPORT_A/index.previous.html")

    def test_old_revision_is_a_conflict_and_leaves_latest_source_and_backup_unchanged(self):
        folder = self.bundle()
        first = self.editor.snapshot("REPORT_A")
        saved = self.save({"summary": "First edit"})
        current = (folder / "index.html").read_bytes()
        backup = (self.root / saved["backup"]).read_bytes()
        with self.assertRaises(EditConflict):
            self.editor.save("REPORT_A", first["revision"], {"summary": "Stale edit"})
        self.assertEqual((folder / "index.html").read_bytes(), current)
        self.assertEqual((self.root / saved["backup"]).read_bytes(), backup)

    def test_new_draft_is_editable_and_legacy_reports_require_explicit_markers_and_bridge(self):
        result = new_report(self.library, "DRAFT", "Draft", date="2026-10-07")
        snapshot = self.editor.snapshot("DRAFT")
        self.assertTrue(snapshot["editable"])
        folder = Path(result["path"])
        self.save({"heading": "Approved body heading"}, "DRAFT")
        self.assertEqual(self.library.get("DRAFT")["title"], "Draft")
        self.bundle("NO_BRIDGE", bridge=False)
        missing = self.editor.snapshot("NO_BRIDGE")
        self.assertFalse(missing["editable"])
        self.assertIn("bridge", missing["reason"])
        with self.assertRaises(EditError):
            self.editor.save("NO_BRIDGE", missing["revision"], {"summary": "Unavailable"})
        self.bundle("LEGACY", body="<p>Approved evidence.</p>")
        self.assertFalse(self.editor.snapshot("LEGACY")["editable"])

    def test_allowed_leaf_types_and_entities(self):
        tags = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "dt", "dd", "blockquote",
                "figcaption", "span", "strong", "em", "b", "i", "small", "cite", "q"]
        body = "".join('<' + tag + ' data-naia-edit="block_' + str(index) + '">A &amp; &#60; B</' + tag + '>'
                       for index, tag in enumerate(tags))
        self.bundle(body=body)
        snapshot = self.editor.snapshot("REPORT_A")
        self.assertEqual(len(snapshot["blocks"]), len(tags))
        self.assertTrue(all(block["text"] == "A & < B" for block in snapshot["blocks"]))

    def test_invalid_markers_nested_markup_and_nonprose_contexts_are_rejected(self):
        invalid = [
            '<p data-naia-edit="same">A</p><p data-naia-edit="same">B</p>',
            '<p data-naia-edit="a" data-naia-edit="b">A</p>',
            '<p data-naia-edit="bad id">A</p>', '<p data-naia-edit="9bad">A</p>',
            '<p data-naia-edit="constructor">A</p>', '<p data-naia-edit="prototype">A</p>',
            '<p data-naia-edit="id">A</p>', '<p data-naia-edit="view">A</p>',
            '<p data-naia-edit="View">A</p>', '<p data-naia-edit="Constructor">A</p>',
            '<p data-naia-edit="PROTOTYPE">A</p>', '<p data-naia-edit="ID">A</p>',
            '<p data-naia-edit="__proto__">A</p>', '<p data-naia-edit="a"/>',
            '<p data-naia-edit="a">A <strong>B</strong></p>',
            '<p data-naia-edit="a">A<!-- retained comment --></p>',
            '<p data-naia-edit="a">A<br>B</p>', '<p data-naia-edit="a">A</div>',
            '<div data-naia-edit="a">A</div>', '<p><div><span data-naia-edit="a">A</span></div></p>',
            '<script data-naia-edit="a">var score=3;</script>',
            '<style data-naia-edit="a">p{color:red}</style>',
            '<xmp data-naia-edit="a">Raw text</xmp>', '<plaintext data-naia-edit="a">Raw text</plaintext>',
            '<section data-naia-readonly><p data-naia-edit="a">A</p></section>',
            '<p data-naia-readonly data-naia-edit="a">A</p>',
        ]
        for ancestor in ("table", "svg", "math", "form", "template", "pre", "code", "a", "button",
                         "listing"):
            invalid.append('<' + ancestor + '><span data-naia-edit="a">A</span></' + ancestor + '>')
        for body in invalid:
            with self.subTest(body=body):
                folder = self.bundle(body=body)
                before = (folder / "index.html").read_bytes()
                with self.assertRaises(EditError):
                    self.editor.snapshot("REPORT_A")
                self.assertEqual((folder / "index.html").read_bytes(), before)
        self.bundle(head='<span data-naia-edit="head_text">Bad</span>')
        with self.assertRaises(EditError):
            self.editor.snapshot("REPORT_A")

    def test_apparent_markers_inside_raw_text_are_not_editable_blocks(self):
        for tag in ("script", "style", "xmp", "plaintext", "iframe", "noembed", "noframes"):
            with self.subTest(tag=tag):
                folder = self.bundle(body='<' + tag + '><p data-naia-edit="raw_text">Literal source</p></' + tag + '>')
                before = (folder / "index.html").read_bytes()
                snapshot = self.editor.snapshot("REPORT_A")
                self.assertFalse(snapshot["editable"])
                self.assertEqual(snapshot["blocks"], [])
                with self.assertRaises(EditError):
                    self.editor.save("REPORT_A", snapshot["revision"], {"raw_text": "Unauthorized source change"})
                self.assertEqual((folder / "index.html").read_bytes(), before)

    def test_snapshot_normalizes_literal_crlf_and_cr_but_retains_original_source_bytes(self):
        folder = self.bundle(body='<p data-naia-edit="a">First\r\nSecond\rThird&#13;Fourth</p>')
        before = (folder / "index.html").read_bytes()
        snapshot = self.editor.snapshot("REPORT_A")
        self.assertEqual(snapshot["blocks"], [{"id": "a", "text": "First\nSecond\nThird\rFourth"}])
        self.assertEqual((folder / "index.html").read_bytes(), before)

    def test_bad_change_shapes_unknown_ids_unicode_and_limits_preserve_source(self):
        folder = self.bundle()
        revision = self.editor.snapshot("REPORT_A")["revision"]
        before = (folder / "index.html").read_bytes()
        changes = [{}, [], {"unknown": "New"}, {"summary": None}, {"summary": "x" * 8193},
                   {"summary": "nul\x00"}, {"summary": "surrogate\ud800"},
                   {"summary": "😀" * 8192, "title": "x"}]
        for change in changes:
            with self.subTest(change_type=type(change).__name__):
                with self.assertRaises(EditError):
                    self.editor.save("REPORT_A", revision, change)
                self.assertEqual((folder / "index.html").read_bytes(), before)
        with self.assertRaises(EditError):
            self.editor.save("REPORT_A", "bad revision", {"summary": "New"})
        for body in ('<p data-naia-edit="large">' + "x" * 8193 + '</p>',
                     "".join('<p data-naia-edit="b' + str(index) + '">A</p>' for index in range(129)),
                     "".join('<p data-naia-edit="b' + str(index) + '">' + "x" * 8192 + '</p>' for index in range(5))):
            self.bundle(body=body)
            with self.assertRaises(EditError):
                self.editor.snapshot("REPORT_A")

    def test_candidate_library_limits_are_checked_before_publishing(self):
        folder = self.bundle()
        original = (folder / "index.html").read_bytes()
        library = Reports(self.root, "reports", limits={"html_bytes": len(original) + 8})
        editor = ReportEditor(library)
        revision = editor.snapshot("REPORT_A")["revision"]
        with self.assertRaises(EditError):
            editor.save("REPORT_A", revision, {"summary": "<" * 500})
        self.assertEqual((folder / "index.html").read_bytes(), original)
        self.assertFalse((self.root / "reports/.naia-edit/REPORT_A/index.previous.html").exists())
        total = sum(path.stat().st_size for path in folder.iterdir())
        editor = ReportEditor(Reports(self.root, "reports", limits={"report_bytes": total + 4}))
        with self.assertRaises(EditError):
            editor.save("REPORT_A", editor.snapshot("REPORT_A")["revision"], {"summary": "x" * 100})
        self.assertEqual((folder / "index.html").read_bytes(), original)

    def test_exclusions_and_symlinks_reject_edit_targets_and_private_recovery_paths(self):
        folder = self.bundle()
        before = (folder / "index.html").read_bytes()
        for excluded in (lambda path: path.startswith("reports/REPORT_A"),
                         lambda path: "/.naia-edit" in path,
                         lambda path: path.endswith("index.previous.html")):
            editor = ReportEditor(Reports(self.root, "reports", excluded=excluded))
            with self.assertRaises(EditError):
                editor.save("REPORT_A", self.editor.snapshot("REPORT_A")["revision"], {"summary": "Blocked"})
        self.assertEqual((folder / "index.html").read_bytes(), before)
        outside = self.root / "outside"
        outside.mkdir()
        private = self.root / "reports/.naia-edit/REPORT_A"
        private.mkdir(parents=True, exist_ok=True)
        recovery = private / "index.previous.html"
        external = outside / "evidence.html"
        external.write_bytes(b"External approved evidence")
        recovery.symlink_to(external)
        with self.assertRaises(EditError):
            self.save({"summary": "Blocked symlink"})
        self.assertEqual(external.read_bytes(), b"External approved evidence")
        recovery.unlink()
        lock = private / "editor.lock"
        lock.unlink(missing_ok=True)
        lock.symlink_to(external)
        with self.assertRaises(EditError):
            self.save({"summary": "Blocked lock"})
        self.assertEqual((folder / "index.html").read_bytes(), before)
        lock.unlink()
        private.rmdir()
        (self.root / "reports/.naia-edit").rmdir()
        (self.root / "reports/.naia-edit").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(EditError):
            self.save({"summary": "Blocked private directory"})
        (folder / "index.html").unlink()
        (folder / "index.html").symlink_to(external)
        with self.assertRaises(EditError):
            self.editor.snapshot("REPORT_A")

    def test_configured_hidden_library_ancestor_is_supported(self):
        library = Reports(self.root, ".lab/reports")
        self.library = library
        self.editor = ReportEditor(library)
        folder = self.root / ".lab/reports/REPORT_A"
        original = self.bundle()
        folder.parent.mkdir(parents=True)
        original.rename(folder)
        result = self.save({"summary": "Updated hidden library draft"})
        self.assertEqual(result["backup"], ".lab/reports/.naia-edit/REPORT_A/index.previous.html")
        self.assertTrue(library.check()["valid"])

    def test_replacement_failure_retains_previous_source_and_cleans_temporary_files(self):
        folder = self.bundle()
        source = (folder / "index.html").read_bytes()
        replace = os.replace

        def fail_publish(src, dst, **kwargs):
            if dst == "index.html":
                raise OSError("Injected replacement failure")
            return replace(src, dst, **kwargs)

        with patch("naia.report_editing.os.replace", side_effect=fail_publish):
            with self.assertRaises(EditError):
                self.save({"summary": "Failed edit"})
        self.assertEqual((folder / "index.html").read_bytes(), source)
        private = self.root / "reports/.naia-edit/REPORT_A"
        self.assertEqual((private / "index.previous.html").read_bytes(), source)
        self.assertEqual({path.name for path in private.iterdir()}, {"editor.lock", "index.previous.html"})
        self.assertEqual({path.name for path in folder.iterdir()}, {"meta.json", "index.html"})

    def test_external_change_during_candidate_validation_is_detected(self):
        folder = self.bundle()
        revision = self.editor.snapshot("REPORT_A")["revision"]
        candidate = self.editor._candidate
        external = (folder / "index.html").read_bytes().replace(b"Old &amp; approved", b"External approved")

        def mutate(report_id, content):
            parsed = candidate(report_id, content)
            (folder / "index.html").write_bytes(external)
            return parsed

        with patch.object(self.editor, "_candidate", side_effect=mutate):
            with self.assertRaises(EditConflict):
                self.editor.save("REPORT_A", revision, {"summary": "Concurrent update"})
        self.assertEqual((folder / "index.html").read_bytes(), external)

    def test_temporary_symlink_swap_is_rejected_without_touching_external_file(self):
        folder = self.bundle()
        before = (folder / "index.html").read_bytes()
        external = self.root / "outside.html"
        external.write_bytes(b"External source")
        create = self.editor._temporary
        swapped = []

        def swap(descriptor, directory, content, mode):
            temporary = create(descriptor, directory, content, mode)
            if content != before:
                path = directory / temporary[0]
                path.unlink()
                path.symlink_to(external)
                swapped.append(path)
            return temporary

        with patch.object(self.editor, "_temporary", side_effect=swap):
            with self.assertRaises(EditConflict):
                self.save({"summary": "Unsafe temporary swap"})
        self.assertEqual((folder / "index.html").read_bytes(), before)
        self.assertEqual(external.read_bytes(), b"External source")
        self.assertEqual(len(swapped), 1)
        self.assertTrue(swapped[0].is_symlink())

    def test_failed_candidate_temp_creation_cleans_backup_temp_and_preserves_source(self):
        folder = self.bundle()
        before = (folder / "index.html").read_bytes()
        create = self.editor._temporary

        def fail_candidate(descriptor, directory, content, mode):
            if content != before:
                raise OSError("Injected temporary creation failure")
            return create(descriptor, directory, content, mode)

        with patch.object(self.editor, "_temporary", side_effect=fail_candidate):
            with self.assertRaises(EditError):
                self.save({"summary": "Failed temporary creation"})
        self.assertEqual((folder / "index.html").read_bytes(), before)
        private = self.root / "reports/.naia-edit/REPORT_A"
        self.assertEqual({path.name for path in private.iterdir()}, {"editor.lock"})

    def test_ancestor_symlink_swap_cannot_redirect_publication(self):
        folder = self.bundle()
        revision = self.editor.snapshot("REPORT_A")["revision"]
        source = (folder / "index.html").read_bytes()
        moved = self.root / "moved-report"
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "index.html").write_bytes(b"Outside source")
        candidate = self.editor._candidate

        def swap(report_id, content):
            parsed = candidate(report_id, content)
            folder.rename(moved)
            folder.symlink_to(outside, target_is_directory=True)
            return parsed

        with patch.object(self.editor, "_candidate", side_effect=swap):
            with self.assertRaises(EditError):
                self.editor.save("REPORT_A", revision, {"summary": "Unsafe target"})
        self.assertEqual((outside / "index.html").read_bytes(), b"Outside source")
        self.assertEqual((moved / "index.html").read_bytes(), source)

    @unittest.skipUnless(os.name == "posix", "flock requires a POSIX system")
    def test_cooperative_process_lock_serializes_writers(self):
        self.bundle()
        revision = self.editor.snapshot("REPORT_A")["revision"]
        private = self.root / "reports/.naia-edit/REPORT_A"
        private.mkdir(parents=True)
        process = subprocess.Popen([sys.executable, "-u", "-c",
            "import fcntl,sys; f=open(sys.argv[1],'a+b'); fcntl.flock(f,fcntl.LOCK_EX); "
            "print('locked',flush=True); sys.stdin.readline()", str(private / "editor.lock")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        self.assertEqual(process.stdout.readline().strip(), "locked")
        started = threading.Event()
        done = threading.Event()
        outcome = []

        def save():
            started.set()
            try:
                outcome.append(self.editor.save("REPORT_A", revision, {"summary": "Locked edit"}))
            except BaseException as exc:
                outcome.append(exc)
            done.set()

        thread = threading.Thread(target=save)
        thread.start()
        self.assertTrue(started.wait(2))
        self.assertFalse(done.wait(0.15))
        process.stdin.write("release\n")
        process.stdin.flush()
        process.communicate(timeout=5)
        self.assertTrue(done.wait(5))
        thread.join(timeout=1)
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], dict, outcome)


if __name__ == "__main__":
    unittest.main()
