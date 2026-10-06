"""Unified workflow/Lens contracts without PyTorch or real compute jobs."""
from http.server import ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naia.architectures import Architectures
from naia.context import Project
from naia.demo import install
from naia.storage import NAIAError, read_json, write_json
from naia.suites import Suites, definition_digest
from naia.tasks import Tasks
from naia.ui import handler
from naia_arch.cli import make_handler


GRAPH = {"schema_version": 1, "capture_mode": "declared",
         "nodes": [{"id": "model", "parent": None, "label": "Example model"},
                   {"id": "block", "parent": "model", "label": "Projection"}],
         "edges": [], "events": [{"node": "block", "outputs": {"shape": [1, 4]}}]}


class ArchitectureFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(self.temp.name)
        self.project.initialize()
        self.registry = Architectures(self.project)
        self.graph_path = self.project.root / "evidence/model.json"
        write_json(self.graph_path, GRAPH)

    def register(self, **links):
        return self.registry.add("MODEL", "evidence/model.json", "Example model", **links)

    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "naia.cli", *args],
                              cwd=self.project.root, text=True, capture_output=True,
                              env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=20)


class ArchitectureWorkflowTest(ArchitectureFixture, unittest.TestCase):
    def test_existing_workspace_without_registry_is_read_only_and_empty(self):
        self.assertEqual(self.registry.load(), {"schema_version": 1, "items": {}})
        self.assertEqual(self.registry.list(), [])
        self.assertFalse(self.registry.path.exists())

    def test_register_preserves_graph_and_does_not_require_launch_confirmation(self):
        before = self.graph_path.read_bytes()
        entry = self.register()
        self.assertEqual(entry["graph"], "evidence/model.json")
        self.assertEqual(entry["graph_sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(self.graph_path.read_bytes(), before)
        self.assertEqual(self.registry.graph("MODEL"), GRAPH)
        self.assertTrue(self.registry.list()[0]["available"])
        self.assertEqual(self.project.load()["onboarding"]["status"], "pending")
        self.assertFalse(list(self.project.directory.glob("**/*.md")))

    def test_absolute_inside_path_is_saved_as_portable_reference(self):
        entry = self.registry.add("MODEL", str(self.graph_path), "Model")
        self.assertEqual(entry["graph"], "evidence/model.json")

    def test_duplicate_ids_never_overwrite(self):
        self.register()
        before = self.registry.path.read_bytes()
        with self.assertRaises(NAIAError):
            self.register()
        self.assertEqual(self.registry.path.read_bytes(), before)

    def test_graph_mutation_or_deletion_marks_record_unavailable(self):
        self.register()
        write_json(self.graph_path, {**GRAPH, "capture_mode": "changed"})
        with self.assertRaisesRegex(NAIAError, "changed"):
            self.registry.graph("MODEL")
        self.assertFalse(self.registry.list()[0]["available"])
        self.graph_path.unlink()
        self.assertFalse(self.registry.list()[0]["available"])

    def test_invalid_graphs_do_not_create_registry(self):
        bad_graphs = [[], {"schema_version": 1, "nodes": [None]},
                      {"schema_version": 1, "nodes": [{"id": "x", "parent": []}]},
                      {**GRAPH, "edges": {}}, {**GRAPH, "events": [None]},
                      {**GRAPH, "warnings": "not a list"}]
        for graph in bad_graphs:
            with self.subTest(graph=graph):
                write_json(self.graph_path, graph)
                with self.assertRaises(NAIAError):
                    self.register()
                self.assertFalse(self.registry.path.exists())

    def test_nonfinite_and_oversized_graphs_rejected(self):
        self.graph_path.write_text('{"schema_version":1,"nodes":[{"id":"x"}],"value":NaN}')
        with self.assertRaises(NAIAError):
            self.register()
        self.graph_path.write_text(json.dumps(GRAPH))
        from unittest.mock import patch
        with patch("naia.architectures.MAX_GRAPH_BYTES", 4):
            with self.assertRaisesRegex(NAIAError, "limit"):
                self.register()
        self.assertFalse(self.registry.path.exists())

    def test_external_and_symlink_escaped_graphs_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "outside.json"
            write_json(external, GRAPH)
            with self.assertRaisesRegex(NAIAError, "escapes"):
                self.registry.add("MODEL", str(external), "Outside")
            link = self.project.root / "external.json"
            try:
                link.symlink_to(external)
            except OSError:
                self.skipTest("Symlinks unavailable")
            with self.assertRaisesRegex(NAIAError, "escapes"):
                self.registry.add("MODEL", "external.json", "Outside")
        self.assertFalse(self.registry.path.exists())

    def test_tampered_registry_path_cannot_expose_external_graph(self):
        self.register()
        data = self.registry.load()
        data["items"]["MODEL"]["graph"] = "../outside.json"
        write_json(self.registry.path, data)
        self.assertFalse(self.registry.list()[0]["available"])
        with self.assertRaisesRegex(NAIAError, "escapes"):
            self.registry.graph("MODEL")

    def test_task_and_suite_links_preserve_approved_experiment_identity(self):
        with tempfile.TemporaryDirectory() as root:
            project = Project(root)
            install(project)
            write_json(project.root / "model.json", GRAPH)
            tasks = Tasks(project)
            tasks.add("INSPECT", "Inspect model", "Understand architecture", "Review design")
            before = definition_digest(Suites(project).load("DEMO"))
            entry = Architectures(project).add("MODEL", "model.json", "Demo model", suite="DEMO", task="INSPECT")
            self.assertEqual(entry["suite"], "DEMO")
            self.assertEqual(entry["task"], "INSPECT")
            self.assertEqual(before, definition_digest(Suites(project).load("DEMO")))

    def test_unknown_links_and_unsafe_ids_rejected_before_writes(self):
        for links in ({"suite": "MISSING"}, {"task": "MISSING"}):
            with self.subTest(links=links), self.assertRaises(NAIAError):
                self.register(**links)
        with self.assertRaises(NAIAError):
            self.registry.add("../escape", "evidence/model.json", "Model")
        self.assertFalse(self.registry.path.exists())

    def test_graph_can_be_minimal_declared_hierarchy(self):
        write_json(self.graph_path, {"schema_version": 1, "nodes": [{"id": "model"}]})
        self.register()
        self.assertTrue(self.registry.list()[0]["available"])

    def test_cli_add_and_list_and_lens_alias(self):
        result = self.cli("arch", "add", "MODEL", "--graph", "evidence/model.json", "--title", "Example")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli("lens", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)[0]["available"])

    def test_standalone_cli_does_not_initialize_project_or_import_torch(self):
        with tempfile.TemporaryDirectory() as root:
            graph = Path(root) / "model.json"
            write_json(graph, GRAPH)
            code = "import sys; from naia.cli import main; result = main(['arch','validate',sys.argv[1]]); assert 'torch' not in sys.modules; raise SystemExit(result)"
            result = subprocess.run([sys.executable, "-c", code, str(graph)], cwd=root, text=True,
                                    capture_output=True, env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["valid"])
            self.assertFalse((Path(root) / ".lab").exists())

    def test_registered_links_survive_project_relocation(self):
        import shutil
        self.register()
        with tempfile.TemporaryDirectory() as root:
            relocated = Path(root) / "relocated"
            shutil.copytree(self.project.root, relocated)
            self.assertEqual(Architectures(Project(relocated)).graph("MODEL"), GRAPH)


class ArchitectureDashboardTest(ArchitectureFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.register()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.project, "test-token"))
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def test_dashboard_embeds_lens_and_serves_only_registered_graphs(self):
        with urlopen(self.base + "/api/state", timeout=5) as response:
            state = json.load(response)
        self.assertEqual(state["architectures"][0]["id"], "MODEL")
        with urlopen(self.base + "/api/architecture?id=MODEL", timeout=5) as response:
            self.assertEqual(json.load(response), GRAPH)
        with urlopen(self.base + "/architecture?id=MODEL", timeout=5) as response:
            page = response.read()
            self.assertIn(b'/architecture/blocks.js', page)
            self.assertIn(b'/architecture/viewer.js', page)
            self.assertIn(b'/architecture/style.css', page)
            self.assertLess(page.index(b'/architecture/blocks.js'), page.index(b'/architecture/viewer.js'))
            self.assertIn("frame-ancestors 'self'", response.headers["Content-Security-Policy"])
        with urlopen(self.base + "/", timeout=5) as response:
            self.assertIn(b'data-tab="architectures"', response.read())
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        for path in ("/architecture/blocks.js", "/architecture/viewer.js", "/architecture/style.css", "/app.js"):
            with urlopen(self.base + path, timeout=5) as response:
                self.assertEqual(response.status, 200)
                if path.endswith("blocks.js"):
                    self.assertIn("text/javascript", response.headers["Content-Type"])
                    self.assertEqual(response.read(), (ROOT / "src/naia_arch/assets/blocks.js").read_bytes())

    def test_invalid_queries_and_external_paths_are_rejected(self):
        for query in ("", "?id=", "?id=MISSING", "?id=MODEL&id=MODEL", "?id=MODEL&path=outside", "?" + urlencode({"id": "../outside"})):
            with self.subTest(query=query), self.assertRaises(HTTPError) as error:
                urlopen(self.base + "/api/architecture" + query, timeout=5)
            self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + "/evidence/model.json", timeout=5)
        self.assertEqual(error.exception.code, 404)

    def test_changed_graph_is_not_served(self):
        write_json(self.graph_path, {**GRAPH, "capture_mode": "changed"})
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + "/api/architecture?id=MODEL", timeout=5)
        self.assertEqual(error.exception.code, 400)

    def test_browser_cannot_execute_or_register_models(self):
        request = Request(self.base + "/api/architecture", data=b'{"factory":"malicious:run"}', method="POST",
                          headers={"Content-Type": "application/json", "Origin": self.base, "X-NAIA-Token": "test-token"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=5)
        self.assertEqual(error.exception.code, 404)
        bad_host = Request(self.base + "/api/architecture?id=MODEL", headers={"Host": "attacker.example"})
        with self.assertRaises(HTTPError) as error:
            urlopen(bad_host, timeout=5)
        self.assertEqual(error.exception.code, 403)


class StandaloneArchitectureAssetTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(GRAPH))
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def test_standalone_page_loads_the_packaged_block_glossary(self):
        with urlopen(self.base + "/", timeout=5) as response:
            page = response.read()
            self.assertIn(b'src="/blocks.js"', page)
            self.assertLess(page.index(b'src="/blocks.js"'), page.index(b'src="/viewer.js"'))
        with urlopen(self.base + "/blocks.js", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/javascript", response.headers["Content-Type"])
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.read(), (ROOT / "src/naia_arch/assets/blocks.js").read_bytes())

    def test_standalone_asset_keeps_host_guard_and_path_allowlist(self):
        request = Request(self.base + "/blocks.js", headers={"Host": "attacker.example"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=5)
        self.assertEqual(error.exception.code, 403)
        for path in ("/assets/blocks.js", "/../blocks.js", "/blocks.js?path=outside"):
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                urlopen(self.base + path, timeout=5)
            self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
