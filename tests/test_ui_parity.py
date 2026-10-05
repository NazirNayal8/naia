"""Local UI parity through guarded HTTP APIs; never launch compute jobs."""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naia.context import Project
from naia.demo import install
from naia.storage import write_json
from naia.suites import Suites, definition_digest
from naia.ui import handler


class UIParityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(self.temp.name)
        install(self.project)
        self.token = "ui-parity-test-token"

        class QuietHandler(handler(self.project, self.token)):
            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, path, payload=None, *, authenticated=True, headers=None, raw=None):
        request_headers = dict(headers or {})
        if payload is not None or raw is not None:
            request_headers.setdefault("Content-Type", "application/json")
            if authenticated:
                request_headers.setdefault("Origin", self.base)
                request_headers.setdefault("X-NAIA-Token", self.token)
            body = raw if raw is not None else json.dumps(payload).encode()
            request = Request(self.base + path, body, request_headers, method="POST")
        else:
            request = Request(self.base + path, headers=request_headers)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.read(), response.headers

    def api(self, path, payload=None, **kwargs):
        status, body, _ = self.request(path, payload, **kwargs)
        return status, json.loads(body)

    def state(self):
        status, state = self.api("/api/state")
        self.assertEqual(status, 200)
        return state

    def add_task(self, task_id="A", **overrides):
        task = {"action": "add", "id": task_id, "title": f"Review {task_id}",
                "goal": "Inspect evidence", "decision": "Choose next work",
                "owner": "researcher", "type": "review", "materials": ["demo_worker.py"],
                "depends_on": [], **overrides}
        status, response = self.api("/api/action", task)
        self.assertEqual(status, 200, response)
        return self.state()["tasks"]["items"][task_id]

    def queue_snapshot(self):
        return self.project.path(".lab/tasks.json").read_bytes()

    def test_add_edit_and_archive_preserve_identity_history_and_links(self):
        original = self.add_task()
        self.add_task("B", depends_on=["A"])
        status, response = self.api("/api/action", {"action": "edit", "id": "A",
            "title": "Revised review", "goal": "Check revised evidence",
            "decision": "Approve result", "owner": "Alex", "type": "analysis",
            "materials": [".lab/suites/DEMO/card.md"], "depends_on": [], "placement": "keep"})
        self.assertEqual(status, 200, response)
        edited = self.state()["tasks"]["items"]["A"]
        self.assertEqual(edited["id"], original["id"])
        self.assertEqual(edited["created_at"], original["created_at"])
        self.assertEqual(edited["status"], "ready")
        self.assertEqual(edited["materials"], [".lab/suites/DEMO/card.md"])
        self.assertEqual(edited["title"], "Revised review")
        self.assertEqual(edited["owner"], "Alex")

        status, response = self.api("/api/action", {"action": "remove", "id": "A", "note": "Replaced by the revised review."})
        self.assertEqual(status, 200, response)
        state = self.state()
        self.assertNotIn("A", state["tasks"]["order"])
        self.assertEqual(state["tasks"]["items"]["B"]["depends_on"], ["A"])
        self.assertIn("archived_at", state["tasks"]["items"]["A"])
        status, archive = self.api("/api/archive")
        self.assertEqual(status, 200)
        self.assertEqual(len(archive["items"]), 1)
        self.assertEqual(archive["items"][0]["title"], "Revised review")
        self.assertEqual(archive["items"][0]["notes"][-1]["text"], "Replaced by the revised review.")
        status, _ = self.api("/api/action", {"action": "remove", "id": "A"})
        self.assertEqual(status, 400)
        self.assertEqual(len(self.api("/api/archive")[1]["items"]), 1)
        status, _ = self.api("/api/action", {"action": "add", "id": "A",
            "title": "Duplicate", "goal": "Inspect", "decision": "Review"})
        self.assertEqual(status, 400)

    def test_reorder_requires_each_open_task_once_and_preserves_closed_records(self):
        for task_id in ("A", "B", "C"):
            self.add_task(task_id)
        self.assertEqual(self.api("/api/action", {"action": "done", "id": "C"})[0], 200)
        for ordered_ids in (["B"], ["B", "A", "A"], ["B", "A", "C"], ["B", "MISSING"]):
            with self.subTest(ordered_ids=ordered_ids):
                before = self.queue_snapshot()
                status, _ = self.api("/api/action", {"action": "reorder", "ordered_ids": ordered_ids})
                self.assertEqual(status, 400)
                self.assertEqual(self.queue_snapshot(), before)
        status, response = self.api("/api/action", {"action": "reorder", "ordered_ids": ["B", "A"]})
        self.assertEqual(status, 200, response)
        state = self.state()
        open_ids = [task_id for task_id in state["tasks"]["order"]
                    if state["tasks"]["items"][task_id]["status"] not in ("done", "cancelled")]
        self.assertEqual(open_ids, ["B", "A"])
        self.assertEqual(state["focus_id"], "B")
        self.assertEqual(state["tasks"]["items"]["C"]["status"], "done")

    def test_pause_resume_and_legacy_actions_keep_one_active_task(self):
        self.add_task("A")
        self.add_task("B")
        self.assertEqual(self.api("/api/task", {"action": "start", "id": "A"})[0], 200)
        self.assertEqual(self.api("/api/action", {"action": "start", "id": "B"})[0], 400)
        self.assertEqual(self.api("/api/action", {"action": "pause", "id": "A", "note": "Waiting"})[0], 200)
        self.assertEqual(self.api("/api/action", {"action": "resume", "id": "A"})[0], 200)
        state = self.state()
        self.assertEqual(state["tasks"]["items"]["A"]["status"], "active")
        self.assertEqual(state["focus_id"], "A")
        self.assertEqual(state["tasks"]["items"]["A"]["notes"][-1]["text"], "Waiting")
        self.assertEqual(self.api("/api/action", {"action": "resolve", "note": "Reviewed"})[0], 200)
        self.assertEqual(self.state()["tasks"]["items"]["A"]["status"], "done")

    def test_invalid_task_payloads_do_not_mutate_queue(self):
        self.add_task()
        edit = {"action": "edit", "id": "A", "title": "Review A", "goal": "Inspect evidence",
                "decision": "Choose next work", "owner": "researcher", "type": "review",
                "materials": [], "depends_on": [], "placement": "keep"}
        bad_payloads = [
            {**edit, "title": []},
            {**edit, "depends_on": ["A"]},
            {**edit, "depends_on": ["MISSING"]},
            {**edit, "materials": "not-a-list"},
            {"action": "add", "id": "../outside", "title": "X", "goal": "X", "decision": "X"},
            {"action": "execute", "id": "A", "argv": ["echo", "unexpected"]},
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                before = self.queue_snapshot()
                self.assertEqual(self.api("/api/action", payload)[0], 400)
                self.assertEqual(self.queue_snapshot(), before)

    def test_completion_targets_captured_id_after_another_task_moves_to_top(self):
        self.add_task("A")
        self.add_task("B")
        captured_id = self.state()["focus_id"]
        self.assertEqual(captured_id, "A")
        self.add_task("C", placement="top")
        self.assertEqual(self.state()["focus_id"], "C")
        status, response = self.api("/api/action", {"action": "resolve", "id": captured_id, "note": "Reviewed the original dialog target"})
        self.assertEqual(status, 200, response)
        state = self.state()
        self.assertEqual(state["tasks"]["items"]["A"]["status"], "done")
        self.assertEqual(state["tasks"]["items"]["C"]["status"], "ready")
        self.assertEqual(state["focus_id"], "C")
        before = self.queue_snapshot()
        self.assertEqual(self.api("/api/action", {"action": "resolve", "id": "MISSING"})[0], 400)
        self.assertEqual(self.queue_snapshot(), before)

    def test_new_mutations_retain_origin_host_and_token_guards(self):
        self.add_task()
        endpoints = [("/api/action", {"action": "remove", "id": "A"}),
                     ("/api/suite-status", {"id": "DEMO", "status": "sealed"}),
                     ("/api/sync", {})]
        for path, payload in endpoints:
            for headers in ({}, {"Origin": "http://external.invalid", "X-NAIA-Token": self.token},
                            {"Origin": self.base, "X-NAIA-Token": "wrong"},
                            {"Origin": self.base, "X-NAIA-Token": self.token, "Host": "external.invalid"}):
                with self.subTest(path=path, headers=headers):
                    self.assertEqual(self.api(path, payload, authenticated=False, headers=headers)[0], 403)
        self.assertNotIn("archived_at", self.state()["tasks"]["items"]["A"])
        self.assertEqual(Suites(self.project).load("DEMO")["status"], "approved")

    def test_malformed_json_and_oversized_request_are_rejected(self):
        for raw in (b"[]", b"null", b"{broken", b" " * 65537):
            with self.subTest(raw_size=len(raw)):
                before = self.queue_snapshot()
                self.assertEqual(self.request("/api/action", raw=raw)[0], 400)
                self.assertEqual(self.queue_snapshot(), before)

    def test_suite_status_labels_preserve_definition_and_never_execute(self):
        suites = Suites(self.project)
        original = suites.load("DEMO")
        digest = definition_digest(original)
        context_before = self.project.context_path.read_bytes()
        for label in ("queued", "training", "evaluating"):
            status, response = self.api("/api/suite-status", {"id": "DEMO", "status": label})
            self.assertEqual(status, 200, response)
            current = suites.load("DEMO")
            self.assertEqual(current["status"], "approved")
            self.assertEqual(current["ui_status"], label)
            self.assertEqual(definition_digest(current), digest)
            self.assertEqual(current["approval"], original["approval"])
        self.assertEqual(self.project.context_path.read_bytes(), context_before)
        self.assertFalse(self.project.path(".lab/state/runs").exists())

    def test_sealing_and_reopening_need_approval_and_preserve_provenance(self):
        suites = Suites(self.project)
        digest = definition_digest(suites.load("DEMO"))
        self.assertEqual(self.api("/api/suite-status", {"id": "DEMO", "status": "sealed"})[0], 200)
        self.assertEqual(suites.load("DEMO")["status"], "sealed")
        self.assertEqual(self.api("/api/suite-status", {"id": "DEMO", "status": "reopened"})[0], 200)
        self.assertEqual(suites.load("DEMO")["status"], "approved")
        self.assertEqual(definition_digest(suites.load("DEMO")), digest)
        data = self.project.load()
        data["onboarding"]["confirmed_by"] = None
        write_json(self.project.context_path, data)
        before = suites.location("DEMO").joinpath("suite.json").read_bytes()
        self.assertEqual(self.api("/api/suite-status", {"id": "DEMO", "status": "sealed"})[0], 400)
        self.assertEqual(suites.location("DEMO").joinpath("suite.json").read_bytes(), before)

    def test_rendered_material_and_suite_cards_are_read_only_and_escape_html(self):
        material = self.project.root / "evidence.txt"
        material.write_text('<script>alert("unsafe")</script>\nResearch evidence', encoding="utf-8")
        status, body, headers = self.request("/material?" + urlencode({"path": "evidence.txt"}))
        self.assertEqual(status, 200)
        self.assertIn(b"Research evidence", body)
        self.assertNotIn(b'<script>alert("unsafe")</script>', body)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("object-src 'none'", headers["Content-Security-Policy"])
        card = Suites(self.project).location("DEMO") / "card.md"
        card.write_text(card.read_text() + '\n<script>alert("unsafe")</script>\n[unsafe](javascript:alert(1))\n')
        before = card.read_bytes()
        status, body, _ = self.request("/suite-card?" + urlencode({"id": "DEMO"}))
        self.assertEqual(status, 200)
        self.assertIn(b"CPU workflow demonstration", body)
        self.assertNotIn(b'<script>alert("unsafe")</script>', body)
        self.assertNotIn(b'href="javascript:', body)
        self.assertEqual(card.read_bytes(), before)
        self.assertEqual(material.read_text(), '<script>alert("unsafe")</script>\nResearch evidence')

    def test_material_reads_reject_sensitive_excluded_large_and_escaped_paths(self):
        self.project.root.joinpath(".env").write_text("harmless test secret", encoding="utf-8")
        private = self.project.root / "private"
        private.mkdir()
        private.joinpath("notes.txt").write_text("Excluded test text", encoding="utf-8")
        self.project.scan(excluded_paths=["private"])
        self.project.root.joinpath("large.txt").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
        self.project.root.joinpath("active.html").write_text("<script>alert(1)</script>", encoding="utf-8")
        self.project.root.joinpath("active.svg").write_text('<svg onload="alert(1)"></svg>', encoding="utf-8")
        credentials = self.project.root / "config"
        credentials.mkdir()
        for filename in ("tokens.json", "key.json", "service-account.json"):
            credentials.joinpath(filename).write_text('{"fixture": "not-a-real-secret"}', encoding="utf-8")
        with tempfile.TemporaryDirectory() as external:
            outside = Path(external) / "outside.txt"
            outside.write_text("Outside test text", encoding="utf-8")
            link = self.project.root / "link.txt"
            try:
                link.symlink_to(outside)
            except OSError:
                pass
            self.project.root.joinpath("public.txt").write_text("Public test text", encoding="utf-8")
            try:
                self.project.root.joinpath("inside-link.txt").symlink_to(self.project.root / "public.txt")
            except OSError:
                pass
            paths = ["../outside.txt", str(outside), ".env", "private/notes.txt", "large.txt",
                     "link.txt", "inside-link.txt", "sub/../public.txt", ".lab/project.json",
                     "config/tokens.json", "config/key.json", "config/service-account.json"]
            for path in paths:
                with self.subTest(path=path):
                    status, _, _ = self.request("/material?" + urlencode({"path": path}))
                    self.assertIn(status, (400, 403, 404))

        for path, unsafe in (("active.html", b"<script>alert(1)</script>"),
                             ("active.svg", b'<svg onload="alert(1)">')):
            with self.subTest(source_inspection=path):
                status, body, headers = self.request("/material?" + urlencode({"path": path}))
                self.assertEqual(status, 200)
                self.assertNotIn(unsafe, body)
                self.assertIn(b"&lt;", body)
                self.assertIn("object-src 'none'", headers["Content-Security-Policy"])
                self.assertIn(self.request("/asset?" + urlencode({"path": path}))[0], (400, 403, 404))

    def test_archive_retry_after_interrupted_queue_write_is_idempotent(self):
        self.add_task()
        task_path = self.project.path(".lab/tasks.json")

        def interrupt_queue_write(path, data):
            if Path(path) == task_path:
                raise OSError("Simulated interrupted queue write")
            return write_json(path, data)

        with patch("naia.tasks.write_json", side_effect=interrupt_queue_write):
            status, _ = self.api("/api/action", {"action": "remove", "id": "A"})
        self.assertEqual(status, 400)
        self.assertEqual(len(self.api("/api/archive")[1]["items"]), 1)
        self.assertIn("A", self.state()["tasks"]["order"])
        status, response = self.api("/api/action", {"action": "remove", "id": "A"})
        self.assertEqual(status, 200, response)
        self.assertEqual(len(self.api("/api/archive")[1]["items"]), 1)
        self.assertNotIn("A", self.state()["tasks"]["order"])

    def test_missing_or_excluded_card_does_not_disable_task_workspace(self):
        self.add_task()
        card = self.project.path(".lab/suites/DEMO/card.md")
        original = card.read_bytes()
        card.unlink()
        state = self.state()
        self.assertEqual(state["tasks"]["items"]["A"]["title"], "Review A")
        demo = next(item for item in state["suites"] if item["id"] == "DEMO")
        self.assertFalse(demo["card_available"])
        self.assertTrue(demo["card_error"])
        self.assertNotIn("DEMO", state["cards"])
        self.assertEqual(self.api("/api/action", {"action": "start", "id": "A"})[0], 200)
        card.write_bytes(original)
        self.project.scan(excluded_paths=[".lab/suites/DEMO/card.md"])
        state = self.state()
        self.assertFalse(next(item for item in state["suites"] if item["id"] == "DEMO")["card_available"])
        self.assertEqual(state["tasks"]["items"]["A"]["status"], "active")

    def test_refresh_does_not_launch_or_reconcile_jobs_and_context_is_retained(self):
        before = self.project.context_path.read_bytes()
        with patch("naia.execution.launch", side_effect=AssertionError("Unexpected launch")), \
                patch("naia.execution.reconcile", side_effect=AssertionError("Unexpected scheduler call")):
            status, response = self.api("/api/sync", {})
        self.assertEqual(status, 200, response)
        self.assertEqual(self.project.context_path.read_bytes(), before)
        self.assertEqual(self.state()["context"]["onboarding"]["status"], "confirmed")
        self.assertFalse(self.project.path(".lab/state/runs").exists())


if __name__ == "__main__":
    unittest.main()
