"""Project-specific browser titles are available before dashboard API loading."""
from __future__ import annotations

from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from naia.context import Project
from naia.ui import handler


class TitleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.titles = []

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
            self.titles.append("")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.titles[-1] += data


class ProjectTitleHTTPTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def start(self, name):
        project = Project(self.root / name)
        project.root.mkdir()
        project.initialize(scan=False)
        class Quiet(handler(project, "project-title-test")):
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return project, f"http://127.0.0.1:{server.server_port}"

    def snapshot(self, project):
        return {str(path.relative_to(project.root)): path.read_bytes()
                for path in project.root.rglob("*") if path.is_file()}

    def get_html(self, base, path):
        with urlopen(base + path, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["Content-Type"])
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
            return response.read().decode("utf-8")

    def assert_title(self, html, expected):
        parser = TitleParser()
        parser.feed(html)
        self.assertEqual(parser.titles, [expected])
        self.assertIn('<h1 id="pageTitle">NAIA</h1>', html)

    def test_two_projects_have_distinct_initial_and_refreshed_titles(self):
        for name in ("robot-control", "vision-lab"):
            with self.subTest(name=name):
                project, base = self.start(name)
                before = self.snapshot(project)
                with patch.object(project, "context_view", side_effect=AssertionError("API was not requested")):
                    for path in ("/", "/archive", "/?view=suites", "/?view=reports", "/?view=arch"):
                        self.assert_title(self.get_html(base, path), f"NAIA - {name}")
                self.assertEqual(self.snapshot(project), before)

    def test_unicode_and_html_sensitive_names_are_escaped(self):
        project, base = self.start('Vision & <RGB> "Δ"')
        before = self.snapshot(project)
        html = self.get_html(base, "/")
        self.assert_title(html, 'NAIA - Vision & <RGB> "Δ"')
        self.assertIn('NAIA - Vision &amp; &lt;RGB&gt; &quot;Δ&quot;', html)
        self.assertEqual(self.snapshot(project), before)

    def test_whitespace_is_normalized_without_changing_project_name(self):
        project, base = self.start("  vision\t lab  ")
        before = self.snapshot(project)
        self.assert_title(self.get_html(base, "/archive"), "NAIA - vision lab")
        self.assertEqual(project.root.name, "  vision\t lab  ")
        self.assertEqual(self.snapshot(project), before)

    def test_empty_directory_name_has_read_only_fallback(self):
        project, base = self.start("fallback")
        before = self.snapshot(project)
        # A filesystem-root project has no basename. Only title derivation needs
        # the root path: preserve the disposable project's report accessor.
        with patch.object(project, "root", Path("/")), patch.object(project, "reports", return_value=object()):
            handler_type = handler(project, "fallback-token")
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_type)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.assert_title(self.get_html(f"http://127.0.0.1:{server.server_port}", "/"), "NAIA - Project")
        self.assertEqual(self.snapshot(project), before)


if __name__ == "__main__":
    unittest.main()
