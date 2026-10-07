"""Read-only Reports contracts over disposable local bundles."""
from __future__ import annotations

import json
from html import escape
from pathlib import Path
import tempfile
import unittest
from http.server import ThreadingHTTPServer
import os
import subprocess
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen


from pathlib import Path as _Path
import sys
sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))
from naia.reports import Reports, ReportError

class ReportsContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "reports"
        self.directory.mkdir()
        self.reports = Reports(self.root, "reports")

    def bundle(self, report_id="REPORT_A", *, html="<p>Visible evidence</p>", **changes):
        folder = self.directory / report_id
        folder.mkdir(exist_ok=True)
        metadata = {"schema_version": 1, "id": report_id, "title": "Evidence report",
                    "date": "2026-10-07", "summary": "A concise summary", "tags": [],
                    "suites": [], "naia_tasks": [], "sources": []}
        metadata.update(changes)
        (folder / "meta.json").write_text(json.dumps(metadata), encoding="utf-8")
        document = "<!doctype html><html><head><title>" + escape(str(metadata["title"])) + "</title></head><body>" + html + "</body></html>"
        (folder / "index.html").write_text(document, encoding="utf-8")
        return folder

    def ids(self, query="", tags=()):
        return [row["id"] for row in self.reports.search(query, tags)["reports"]]

    def test_missing_library_is_empty_and_valid(self):
        reports = Reports(self.root, "missing")
        self.assertEqual(reports.search()["reports"], [])
        self.assertTrue(reports.check()["valid"])

    def test_valid_metadata_and_assets_are_read_without_mutation(self):
        folder = self.bundle(tags=["analysis"], suites=["SUITE_A"], naia_tasks=["REVIEW_A"],
                             sources=["results/data.json"])
        (folder / "plot.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        (folder / "data.json").write_text('{"value": 1}')
        before = {str(path): path.read_bytes() for path in folder.iterdir()}
        self.assertEqual(self.reports.get("REPORT_A")["sources"], ["results/data.json"])
        self.assertTrue(self.reports.check("REPORT_A")["valid"])
        content, mime = self.reports.asset("REPORT_A", "index.html")
        self.assertIn(b"Visible evidence", content)
        self.assertTrue(mime.startswith("text/html"))
        self.assertEqual(self.reports.asset("REPORT_A", "data.json")[0], b'{"value": 1}')
        self.assertEqual(before, {str(path): path.read_bytes() for path in folder.iterdir()})

    def test_metadata_date_and_id_must_be_real_and_match_folder(self):
        for value in ("2026-02-30", "2026-1-01", "not-a-date"):
            with self.subTest(date=value):
                self.bundle(date=value)
                with self.assertRaises(ReportError):
                    self.reports.get("REPORT_A")
        self.bundle(id="OTHER")
        with self.assertRaises(ReportError):
            self.reports.get("REPORT_A")
        self.bundle("lowercase", id="lowercase")
        with self.assertRaises(ReportError):
            self.reports.get("lowercase")

    def test_required_metadata_and_optional_lists_reject_wrong_types(self):
        for key, value in (("title", ""), ("summary", None), ("date", 12),
                           ("tags", "analysis"), ("tags", [""]),
                           ("sources", [1]), ("schema_version", True),
                           ("schema_version", 2)):
            with self.subTest(key=key, value=value):
                self.bundle(**{key: value})
                with self.assertRaises(ReportError):
                    self.reports.get("REPORT_A")
        folder = self.bundle()
        metadata = json.loads((folder / "meta.json").read_text())
        del metadata["summary"]
        (folder / "meta.json").write_text(json.dumps(metadata))
        with self.assertRaises(ReportError):
            self.reports.get("REPORT_A")

    def test_corrupt_report_is_individual_error_and_keeps_library_usable(self):
        self.bundle("GOOD", title="Valid evidence")
        broken = self.bundle("BROKEN")
        (broken / "meta.json").write_text("{")
        search = self.reports.search()
        by_id = {row["id"]: row for row in search["reports"]}
        self.assertEqual(set(by_id), {"GOOD", "BROKEN"})
        self.assertIn("error", by_id["BROKEN"])
        self.assertNotIn("error", by_id["GOOD"])
        checks = self.reports.check()
        self.assertFalse(checks["valid"])
        self.assertEqual({row["id"]: row["valid"] for row in checks["reports"]},
                         {"GOOD": True, "BROKEN": False})
        self.assertEqual(self.ids("Valid"), ["GOOD"])

    def test_missing_index_is_invalid(self):
        folder = self.bundle()
        (folder / "index.html").unlink()
        self.assertFalse(self.reports.check()["valid"])
        with self.assertRaises(ReportError):
            self.reports.asset("REPORT_A", "index.html")

    def test_search_ranks_title_tags_summary_and_body_in_order(self):
        self.bundle("TITLE", title="Needle", summary="Other", html="<p>Other</p>")
        self.bundle("TAG", title="Other", tags=["Needle"], summary="Other", html="<p>Other</p>")
        self.bundle("SUMMARY", title="Other", summary="Needle", html="<p>Other</p>")
        self.bundle("BODY", title="Other", summary="Other", html="<p>Needle</p>")
        self.assertEqual(self.ids("needle"), ["TITLE", "TAG", "SUMMARY", "BODY"])

    def test_search_terms_and_tags_are_casefolded_and_intersected(self):
        self.bundle("BOTH", title="Alpha", tags=["Blue", "ROUND"], html="<p>Beta</p>")
        self.bundle("ONE", title="Alpha", tags=["Blue"], html="<p>Other</p>")
        self.assertEqual(self.ids("ALPHA beta"), ["BOTH"])
        self.assertEqual(self.ids(tags=("blue", "round")), ["BOTH"])
        self.assertEqual(self.ids("missing"), [])
        self.assertEqual(self.reports.search()["tags"], ["Blue", "ROUND"])

    def test_ties_sort_by_newest_date_then_id(self):
        for report_id, date in (("Z", "2026-10-07"), ("A", "2026-10-07"), ("OLD", "2020-01-01")):
            self.bundle(report_id, date=date)
        self.assertEqual(self.ids(), ["A", "Z", "OLD"])

    def test_search_extracts_visible_text_and_highlight_segments(self):
        self.bundle(html="<h1>Visible &amp; distinct</h1><script>scriptsecret</script>"
                         "<style>.stylesecret{}</style><svg><text>svgsecret</text></svg>"
                         "<template>templatesecret</template><p>Body needle here.</p>")
        for hidden in ("scriptsecret", "stylesecret", "svgsecret", "templatesecret"):
            self.assertEqual(self.ids(hidden), [])
        self.assertEqual(self.ids("visible distinct"), ["REPORT_A"])
        snippet = self.reports.search("needle")["reports"][0]["snippet"]
        self.assertTrue(any(segment["hit"] and "needle" in segment["text"].casefold()
                            for segment in snippet))
        self.assertTrue(all(isinstance(segment["hit"], bool) for segment in snippet))

    def test_cache_observes_html_and_metadata_edits(self):
        folder = self.bundle(html="<p>Oldword evidence</p>")
        self.assertEqual(self.ids("oldword"), ["REPORT_A"])
        (folder / "index.html").write_text("<!doctype html><html><head><title>Evidence report</title></head><body><p>Newword evidence has different bytes</p></body></html>")
        self.assertEqual(self.ids("oldword"), [])
        self.assertEqual(self.ids("newword"), ["REPORT_A"])
        self.bundle(title="Updated report", html="<p>Newword evidence</p>")
        self.assertEqual(self.reports.get("REPORT_A")["title"], "Updated report")

    def test_added_and_removed_reports_refresh_search(self):
        self.bundle("A")
        self.assertEqual(self.ids(), ["A"])
        folder = self.bundle("B")
        self.assertEqual(self.ids(), ["A", "B"])
        (folder / "meta.json").unlink()
        (folder / "index.html").unlink()
        folder.rmdir()
        self.assertEqual(self.ids(), ["A"])

    def test_assets_reject_traversal_encodings_absolute_and_separator_paths(self):
        folder = self.bundle()
        (self.root / "outside.txt").write_text("private outside bytes")
        (folder / "ok.css").write_text("body{}")
        for path in ("../outside.txt", "/etc/passwd", "./index.html", "nested/../index.html",
                     "nested\\index.html", "%2e%2e/outside.txt", "%252e%252e/outside.txt",
                     "%69ndex.html", "index.html%00", ""):
            with self.subTest(path=path):
                with self.assertRaises(ReportError):
                    self.reports.asset("REPORT_A", path)

    def test_symlink_assets_and_report_directories_are_rejected(self):
        folder = self.bundle()
        (self.root / "outside.js").write_text("private outside bytes")
        (folder / "link.js").symlink_to(self.root / "outside.js")
        (folder / "inside.js").write_text("console.log('allowed')")
        (folder / "alias.js").symlink_to(folder / "inside.js")
        for name in ("link.js", "alias.js"):
            with self.assertRaises(ReportError):
                self.reports.asset("REPORT_A", name)
        outside = self.root / "OUTSIDE"
        outside.mkdir()
        (outside / "meta.json").write_text(json.dumps({"id": "LINKED", "title": "Secret",
             "date": "2026-10-07", "summary": "Secret"}))
        (outside / "index.html").write_text("<p>Private text</p>")
        (self.directory / "LINKED").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ReportError):
            self.reports.get("LINKED")

    def test_sensitive_hidden_and_unsupported_assets_are_rejected(self):
        folder = self.bundle()
        for name in (".env", "secret.pem", "password.key", "script.py", "weights.pt",
                     "api_keys.json", "credentials.json", "passwd.json", "auth.js",
                     "oauth.js", "kubeconfig.json", "service_account.json"):
            (folder / name).write_text("sensitive content")
            with self.subTest(name=name):
                with self.assertRaises(ReportError):
                    self.reports.asset("REPORT_A", name)

    def test_excluded_reports_and_files_never_enter_index_or_asset(self):
        self.bundle("PUBLIC")
        private = self.bundle("PRIVATE", title="Hidden secret", html="<p>Uniquesecret</p>")
        (self.directory / "PUBLIC" / "blocked.js").write_text("private content")
        excluded = lambda path: path.startswith("reports/PRIVATE") or path.endswith("/blocked.js")
        reports = Reports(self.root, "reports", excluded=excluded)
        self.assertEqual([row["id"] for row in reports.search()["reports"]], ["PUBLIC"])
        self.assertEqual(reports.search("Uniquesecret")["reports"], [])
        with self.assertRaises(ReportError):
            reports.asset("PUBLIC", "blocked.js")
        with self.assertRaises(ReportError):
            reports.get("PRIVATE")

    def test_limits_reject_oversized_metadata_html_and_assets(self):
        folder = self.bundle()
        (folder / "large.js").write_text("x" * 200)
        for limits in ({"meta_bytes": 10}, {"html_bytes": 10}, {"report_bytes": 10}, {"files": 1}):
            with self.subTest(limits=limits):
                self.assertFalse(Reports(self.root, "reports", limits=limits).check()["valid"])
        reports = Reports(self.root, "reports", limits={"asset_bytes": 100})
        with self.assertRaises(ReportError):
            reports.asset("REPORT_A", "large.js")

    def test_bounded_cache_and_report_limit_keep_search_usable(self):
        for report_id in ("A", "B", "C"):
            self.bundle(report_id)
        reports = Reports(self.root, "reports", limits={"cache_entries": 1, "cache_bytes": 64,
                                                        "reports": 2})
        result = reports.search()
        self.assertLessEqual(len(result["reports"]), 2)
        self.assertTrue(result["warnings"])
        self.assertTrue(reports.search("Visible")["reports"])

    def test_match_path_guards_raw_routes_lexically(self):
        self.bundle()
        self.assertEqual(self.reports.match_path("reports/REPORT_A/index.html"),
                         ("REPORT_A", "index.html"))
        self.assertIsNotNone(self.reports.match_path("reports/REPORT_A/../index.html"))
        self.assertIsNone(self.reports.match_path("different/index.html"))

    def test_unknown_report_and_outside_library_are_rejected(self):
        with self.assertRaises(ReportError):
            self.reports.get("UNKNOWN")
        with self.assertRaises(ReportError):
            self.reports.asset("UNKNOWN", "index.html")
        with self.assertRaises(ReportError):
            Reports(self.root, self.root.parent / "other")


    def test_declared_title_body_and_duplicate_metadata_are_validated(self):
        folder = self.bundle()
        document = (folder / "index.html").read_text()
        (folder / "index.html").write_text(document.replace("<title>Evidence report</title>",
                                                           "<title>Different title</title>"))
        self.assertFalse(self.reports.check()["valid"])
        self.bundle()
        (folder / "index.html").write_text(document.replace("<body>", "").replace("</body>", ""))
        self.assertFalse(self.reports.check()["valid"])
        self.bundle()
        raw = (folder / "meta.json").read_text()
        (folder / "meta.json").write_text(raw[:-1] + ', "title": "Duplicate"}')
        with self.assertRaises(ReportError):
            self.reports.get("REPORT_A")

    def test_required_remote_missing_and_cross_report_resources_are_rejected(self):
        for html in ('<script src="https://evil.invalid/code.js"></script>',
                     '<img src="missing.png">', '<link rel="stylesheet" href="/app.css">',
                     '<script src="/reports/OTHER/helper.js"></script>',
                     '<style>body{background:url(https://evil.invalid/image.png)}</style>',
                     '<meta http-equiv="refresh" content="0;url=/">', '<base href="/">'):
            with self.subTest(html=html):
                self.bundle(html=html)
                self.assertFalse(self.reports.check()["valid"])

    def test_local_resources_and_data_images_are_valid(self):
        folder = self.bundle(html='<script src="assets/helper.js"></script>'
             '<img src="data:image/svg+xml,%3Csvg%3E%3C/svg%3E">')
        (folder / "assets").mkdir()
        (folder / "assets" / "helper.js").write_text("window.local=true")
        self.assertTrue(self.reports.check()["valid"])
        self.assertIn(b"local", self.reports.asset("REPORT_A", "assets/helper.js")[0])

    def test_configured_hidden_project_directory_is_allowed(self):
        library = self.root / ".lab" / "reports"
        library.mkdir(parents=True)
        folder = self.bundle()
        folder.rename(library / "REPORT_A")
        reports = Reports(self.root, ".lab/reports")
        self.assertTrue(reports.check()["valid"])
        self.assertEqual([row["id"] for row in reports.search()["reports"]], ["REPORT_A"])

    def test_external_module_scripts_are_rejected_under_opaque_sandbox(self):
        folder = self.bundle(html='<script type="module" src="helper.js"></script>')
        (folder / "helper.js").write_text("export const value=1")
        self.assertFalse(self.reports.check()["valid"])

    def test_source_directory_declarations_are_not_read(self):
        self.bundle(sources=["experiments/analysis/example/"])
        self.assertTrue(self.reports.check()["valid"])
        self.assertFalse((self.root / "experiments").exists())


    def test_limits_require_known_positive_integer_mapping(self):
        for limits in ([], "invalid", True, {"files": False}, {"html_bytes": 0},
                       {"asset_bytes": -1}, {"unknown_limit": 1}):
            with self.subTest(limits=limits):
                with self.assertRaises(ReportError):
                    Reports(self.root, "reports", limits=limits)

    def test_discovery_limit_counts_skipped_flat_files(self):
        for index in range(3):
            (self.directory / ("flat_" + str(index) + ".txt")).write_text("not a report")
        reports = Reports(self.root, "reports", limits={"reports": 1})
        result = reports.search()
        self.assertEqual(result["reports"], [])
        self.assertTrue(result["warnings"])
        self.assertFalse(reports.check()["valid"])


class ReportsHTTPTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "reports"
        self.folder = self.directory / "SAFE"
        self.folder.mkdir(parents=True)
        (self.folder / "meta.json").write_text(json.dumps({"id": "SAFE", "title": "Local evidence",
            "date": "2026-10-07", "summary": "A safe synthetic report", "tags": ["browser"]}))
        (self.folder / "index.html").write_text("<!doctype html><html><head><title>Local evidence</title></head><body><h1>Report</h1>"
            "<script>window.reportScriptRan=true</script></body></html>")
        (self.folder / "plot.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        (self.folder / "helpers.js").write_text("window.assetLoaded=true")
        self.token = "reports-test-token"
        self.configure()
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.Handler)
        self.server = server
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{server.server_port}"

    def request(self, path, payload=None, *, headers=None, authenticated=False, raw=None):
        headers = dict(headers or {})
        if payload is not None or raw is not None:
            headers.setdefault("Content-Type", "application/json")
            if authenticated:
                headers.setdefault("Origin", self.base)
                headers.setdefault("X-NAIA-Token", self.token)
            body = raw if raw is not None else json.dumps(payload).encode()
            request = Request(self.base + path, body, headers, method="POST")
        else:
            request = Request(self.base + path, headers=headers)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.read(), response.headers

    def api(self, path, **kwargs):
        status, content, headers = self.request(path, **kwargs)
        return status, json.loads(content), headers

    def assert_report_csp(self, headers):
        csp = headers.get("Content-Security-Policy", "")
        self.assertIn("sandbox", csp)
        self.assertNotIn("allow-same-origin", csp)
        self.assertIn("connect-src 'none'", csp)
        self.assertIn("form-action 'none'", csp)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_library_search_tags_and_trusted_viewer_are_available(self):
        status, data, _ = self.api("/api/reports?q=local&tag=browser")
        self.assertEqual(status, 200)
        self.assertEqual([row["id"] for row in data["reports"]], ["SAFE"])
        status, body, _ = self.request("/report?id=SAFE&theme=dark&dur=72k")
        self.assertEqual(status, 200)
        text = body.decode()
        self.assertIn('id="reportFrame"', text)
        self.assertIn("allow-scripts", text)
        self.assertNotIn("allow-same-origin", text)
        self.assertNotIn("reports-test-token", text)
        for path in ("/reports.js", "/reports.css", "/reports_viewer.js"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 200)

    def test_direct_report_and_raw_material_routes_preserve_sandbox(self):
        status, content, headers = self.request("/reports/SAFE/index.html")
        self.assertEqual(status, 200)
        self.assertIn(b"reportScriptRan", content)
        self.assert_report_csp(headers)
        for route in ("/asset?path=reports%2FSAFE%2Findex.html",
                      "/material?path=reports%2FSAFE%2Findex.html"):
            with self.subTest(route=route):
                status, content, headers = self.request(route)
                if status == 200:
                    if b'id="reportFrame"' in content:
                        self.assertIn(b"allow-scripts", content)
                        self.assertNotIn(b"allow-same-origin", content)
                        self.assertNotIn(b"reportScriptRan", content)
                    else:
                        self.assert_report_csp(headers)
                else:
                    self.assertIn(status, (400, 403, 404))

    def test_report_relative_js_and_svg_assets_are_available(self):
        for path, mime in (("helpers.js", "javascript"), ("plot.svg", "image/svg+xml")):
            with self.subTest(path=path):
                status, body, headers = self.request("/reports/SAFE/" + path)
                self.assertEqual(status, 200)
                self.assertIn(mime, headers.get("Content-Type"))
                self.assertTrue(body)
                self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_only_font_responses_allow_opaque_origin_reads(self):
        (self.folder / "font.woff2").write_bytes(b"synthetic font fixture")
        status, _, headers = self.request("/reports/SAFE/font.woff2")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "font/woff2")
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "null")
        for route in ("/reports/SAFE/index.html", "/reports/SAFE/helpers.js",
                      "/api/reports", "/api/state"):
            with self.subTest(route=route):
                self.assertIsNone(self.request(route)[2].get("Access-Control-Allow-Origin"))


    def test_encoded_traversal_hidden_and_sensitive_report_files_are_blocked(self):
        (self.root / "outside.js").write_text("private outside")
        (self.folder / ".env").write_text("private token")
        for path in ("/reports/SAFE/%2e%2e/outside.js",
                     "/reports/SAFE/%252e%252e/outside.js",
                     "/reports/SAFE/%2eenv", "/reports/SAFE/.env",
                     "/reports/SAFE/%5cindex.html", "/reports/SAFE/meta.json"):
            with self.subTest(path=path):
                status, content, _ = self.request(path)
                self.assertIn(status, (400, 403, 404))
                self.assertNotIn(b"private", content)

    def test_bad_origin_host_token_and_json_cannot_mutate_toy_queue(self):
        before = self.queue.read_bytes()
        payload = {"action": "add", "id": "ATTACK", "title": "Attack",
                   "goal": "Mutation attempt", "decision": "Must fail"}
        for headers in ({}, {"Origin": "null", "X-NAIA-Token": self.token},
                        {"Origin": "https://evil.invalid", "X-NAIA-Token": self.token},
                        {"Origin": self.base, "X-NAIA-Token": "wrong"},
                        {"Origin": self.base, "X-NAIA-Token": self.token, "Host": "evil.invalid"},
                        {"Origin": self.base, "X-NAIA-Token": self.token, "Content-Type": "text/plain"}):
            with self.subTest(headers=headers):
                self.assertIn(self.request("/api/action", payload, headers=headers)[0], (400, 403, 415))
                self.assertEqual(self.queue.read_bytes(), before)
        self.assertEqual(self.request("/api/action", headers={"Origin": self.base,
            "X-NAIA-Token": self.token}, raw=b"{")[0], 400)
        self.assertEqual(self.queue.read_bytes(), before)

    def test_authenticated_action_remains_usable_and_only_changes_toy_queue(self):
        status, content, _ = self.request("/api/action", {"action": "add", "id": "GOOD",
            "title": "Review evidence", "goal": "Inspect evidence", "decision": "Approve"},
            authenticated=True)
        self.assertEqual(status, 200, content)
        self.assertIn(b"GOOD", self.queue.read_bytes())

    def test_hostile_api_reads_and_duplicate_viewer_id_are_rejected(self):
        self.assertEqual(self.request("/api/reports", headers={"Host": "evil.invalid"})[0], 403)
        self.assertIsNone(self.request("/api/reports")[2].get("Access-Control-Allow-Origin"))
        for path in ("/api/state", "/api/reports"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path, headers={"Origin": "null"})[0], 403)
        self.assertIn(self.request("/report?id=SAFE&id=OTHER")[0], (400, 404))

    def test_generic_routes_cannot_bypass_hidden_context_symlinks_or_raw_scripts(self):
        hidden = self.root / ".lab"
        hidden.mkdir(exist_ok=True)
        secret = hidden / "project.json"
        if not secret.exists():
            secret.write_text('{"value":"sensitive-private-content"}')
        script = self.root / "raw.js"
        script.write_text("window.unsafe=true")
        (self.root / "alias.html").symlink_to(self.folder / "index.html")
        for route in ("/material?path=.lab%2Fproject.json",
                      "/material?path=.lab%2F%2Fproject.json",
                      "/asset?path=.lab%2Fproject.json",
                      "/material?path=alias.html", "/asset?path=alias.html",
                      "/asset?path=raw.js",
                      "/asset?path=reports%2F%2FSAFE%2Findex.html",
                      "/material?path=reports%2FSAFE%2Findex.html&path=raw.js"):
            with self.subTest(route=route):
                status, content, _ = self.request(route)
                self.assertIn(status, (400, 403, 404))
                self.assertNotIn(b"sensitive-private-content", content)
                self.assertNotIn(b"window.unsafe", content)


    def test_check_cli_exit_status_reflects_invalid_reports(self):
        result = self.cli("report", "check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])
        (self.folder / "meta.json").write_text("{")
        result = self.cli("report", "check")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)["valid"])
        result = self.cli("report", "list", "--query", "local")
        self.assertEqual(result.returncode, 0, result.stderr)

    def configure(self):
        from naia.context import Project
        from naia.ui import handler
        self.project = Project(self.root)
        self.project.initialize(scan=False)
        self.queue = self.project.directory / "tasks.json"
        class Quiet(handler(self.project, self.token, reports_root="reports")):
            def log_message(self, *args):
                pass
        self.Handler = Quiet

    def cli(self, *args):
        environment = dict(os.environ, PYTHONPATH=str(_Path(__file__).resolve().parents[1] / "src"))
        return subprocess.run([sys.executable, "-m", "naia.cli", "--project", str(self.root),
            "--reports-root", "reports", *args], capture_output=True, text=True, env=environment)


if __name__ == "__main__":
    unittest.main()
