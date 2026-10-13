"""Optional report libraries must not block unrelated dashboard workflows."""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from naia.architectures import Architectures
from naia.context import Project
from naia.report_editing import EditError, ReportEditor
from naia.reports import ReportError, Reports
from naia.storage import write_json
from naia.ui import handler


def bundle(directory):
    folder = directory / "SAFE"
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({"id": "SAFE", "title": "Synthetic report",
        "date": "2026-10-13", "summary": "Disposable evidence", "tags": []}))
    (folder / "index.html").write_text('<!doctype html><html><head><title>Synthetic report</title>'
        '</head><body><p data-naia-edit="finding">Report-only evidence</p></body></html>')
    return folder


class OptionalReportLibraryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def assert_unavailable(self, library, message):
        result = library.search()
        self.assertFalse(result["available"])
        self.assertEqual(result["reports"], [])
        self.assertEqual(result["tags"], [])
        self.assertIn(message, result["message"])
        self.assertTrue(result["warnings"])
        for operation in (lambda: library.get("SAFE"),
                          lambda: library.asset("SAFE", "index.html"),
                          lambda: ReportEditor(library).snapshot("SAFE"),
                          lambda: ReportEditor(library).save("SAFE", "0" * 64, {"finding": "Changed"})):
            with self.assertRaises((ReportError, EditError)):
                operation()

    def test_deferred_excluded_root_is_unavailable_not_empty_or_readable(self):
        folder = bundle(self.root / "blocked-reports")
        before = {path: path.read_bytes() for path in folder.iterdir()}
        excluded = lambda path: path == "blocked-reports" or path.startswith("blocked-reports/")
        with self.assertRaises(ReportError):
            Reports(self.root, "blocked-reports", excluded=excluded)
        library = Reports(self.root, "blocked-reports", excluded=excluded, validate_on_init=False)
        self.assert_unavailable(library, "excluded")
        self.assertEqual(before, {path: path.read_bytes() for path in folder.iterdir()})

    def test_missing_root_is_available_empty_without_creating_directories(self):
        library = Reports(self.root, "new/reports", validate_on_init=False)
        before = list(self.root.iterdir())
        result = library.search()
        self.assertTrue(result["available"])
        self.assertEqual(result["reports"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(before, list(self.root.iterdir()))
        self.assertFalse(library.directory.exists())
        bundle(library.directory)
        self.assertEqual([item["id"] for item in library.search()["reports"]], ["SAFE"])

    def test_symlink_root_is_unavailable_and_target_is_untouched(self):
        folder = bundle(self.root / "real-reports")
        before = {path: path.read_bytes() for path in folder.iterdir()}
        alias = self.root / "report-alias"
        try:
            alias.symlink_to(self.root / "real-reports", target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlinks are unavailable: {exc}")
        with self.assertRaises(ReportError):
            Reports(self.root, "report-alias")
        self.assert_unavailable(Reports(self.root, "report-alias", validate_on_init=False), "Symlinks")
        self.assertEqual(before, {path: path.read_bytes() for path in folder.iterdir()})

    def test_root_file_is_unavailable_and_never_replaced(self):
        path = self.root / "reports"
        path.write_bytes(b"not a directory")
        self.assert_unavailable(Reports(self.root, "reports", validate_on_init=False), "not a directory")
        self.assertEqual(path.read_bytes(), b"not a directory")

    def test_deferred_initialization_does_not_allow_outside_project(self):
        for directory in (self.root, self.root.parent / "outside-reports"):
            with self.subTest(directory=directory), self.assertRaises(ReportError):
                Reports(self.root, directory, validate_on_init=False)

    def test_project_and_cli_remain_strict_for_excluded_report_roots(self):
        project = Project(self.root)
        project.initialize(scan=False, excluded_paths=["blocked-reports"])
        data = project.load()
        data["answers"]["reporting"]["value"]["reports_directory"] = "blocked-reports"
        write_json(project.context_path, data)
        with self.assertRaises(ReportError):
            project.reports()
        self.assertFalse(project.reports(validate_on_init=False).search()["available"])
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        result = subprocess.run([sys.executable, "-m", "naia.cli", "--project", str(self.root),
                                 "report", "list"], capture_output=True, text=True, env=environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("excluded", result.stdout + result.stderr)
        self.assertFalse((self.root / "blocked-reports").exists())


class OptionalReportsHTTPTest(unittest.TestCase):
    def start(self, *, excluded=False, root_file=False, symlink=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = Project(self.root)
        self.project.initialize(scan=False, excluded_paths=["reports"] if excluded else [])
        self.directory = self.root / "reports"
        if excluded:
            bundle(self.directory)
        elif root_file:
            self.directory.write_bytes(b"not a directory")
        elif symlink:
            bundle(self.root / "real-reports")
            try:
                self.directory.symlink_to(self.root / "real-reports", target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Symlinks are unavailable: {exc}")
        data = self.project.load()
        data["answers"]["reporting"]["value"]["reports_directory"] = "reports"
        write_json(self.project.context_path, data)
        (self.root / "evidence.txt").write_text("Normal project evidence")
        self.graph = {"schema_version": 1, "nodes": [{"id": "model", "parent": None}], "edges": []}
        write_json(self.root / "model.json", self.graph)
        Architectures(self.project).add("MODEL", "model.json", "Synthetic model")
        self.token = "optional-reports-test"
        class Quiet(handler(self.project, self.token)):
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, path, payload=None):
        headers = {}
        body = None
        if payload is not None:
            headers = {"Origin": self.base, "X-NAIA-Token": self.token, "Content-Type": "application/json"}
            body = json.dumps(payload).encode()
        request = Request(self.base + path, body, headers)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, response.read()

    def assert_other_workflows_usable(self):
        for path in ("/", "/archive", "/api/state", "/api/archive", "/architecture",
                     "/api/architecture?id=MODEL", "/material?path=evidence.txt"):
            with self.subTest(path=path):
                status, body = self.request(path)
                self.assertEqual(status, 200, body)
        before_context = self.project.context_path.read_bytes()
        status, body = self.request("/api/action", {"action": "add", "id": "REVIEW", "title": "Review",
            "goal": "Inspect evidence", "decision": "Approve"})
        self.assertEqual(status, 200, body)
        self.assertIn("REVIEW", json.loads((self.project.directory / "tasks.json").read_text())["items"])
        self.assertEqual(self.project.context_path.read_bytes(), before_context)

    def assert_report_routes_blocked(self):
        for path in ("/report?id=SAFE", "/reports/SAFE/index.html",
                     "/material?path=reports/SAFE/index.html", "/asset?path=reports/SAFE/index.html"):
            with self.subTest(path=path):
                status, body = self.request(path)
                self.assertIn(status, (400, 403, 404), body)
                self.assertNotIn(b"Report-only evidence", body)
        for path, payload in (("/api/report-edit", {"id": "SAFE"}),
                              ("/api/report-save", {"id": "SAFE", "revision": "0" * 64,
                                                    "changes": {"finding": "Changed"}})):
            status, body = self.request(path, payload)
            self.assertIn(status, (400, 403, 404), body)

    def test_excluded_reports_do_not_block_dashboard_or_other_workflows(self):
        self.start(excluded=True)
        before = {path: path.read_bytes() for path in (self.directory / "SAFE").iterdir()}
        self.assert_other_workflows_usable()
        status, body = self.request("/api/reports")
        self.assertEqual(status, 200, body)
        result = json.loads(body)
        self.assertFalse(result["available"])
        self.assertIn("excluded", result["message"])
        self.assert_report_routes_blocked()
        self.assertEqual(before, {path: path.read_bytes() for path in (self.directory / "SAFE").iterdir()})

    def test_missing_reports_are_empty_and_refresh_after_explicit_creation(self):
        self.start()
        self.assert_other_workflows_usable()
        status, body = self.request("/api/reports")
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertTrue(result["available"])
        self.assertEqual(result["reports"], [])
        self.assertFalse(self.directory.exists())
        bundle(self.directory)
        self.assertEqual([row["id"] for row in json.loads(self.request("/api/reports")[1])["reports"]], ["SAFE"])
        self.assertEqual(self.request("/report?id=SAFE")[0], 200)

    def test_root_file_only_disables_reports(self):
        self.start(root_file=True)
        self.assert_other_workflows_usable()
        status, body = self.request("/api/reports")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["available"])
        self.assert_report_routes_blocked()
        self.assertEqual(self.directory.read_bytes(), b"not a directory")

    def test_symlink_root_only_disables_reports(self):
        self.start(symlink=True)
        self.assert_other_workflows_usable()
        status, body = self.request("/api/reports")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["available"])
        self.assert_report_routes_blocked()


if __name__ == "__main__":
    unittest.main()
