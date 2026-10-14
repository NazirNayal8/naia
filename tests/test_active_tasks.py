"""Concurrent task activation is a display projection, not a priority rewrite."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naia.context import Project
from naia.storage import NAIAError
from naia.tasks import Tasks


class ActiveTasksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(self.temp.name)
        self.project.initialize()
        self.tasks = Tasks(self.project)
        for task_id in ("A", "B", "C", "D", "E"):
            self.tasks.add(task_id, task_id, "Inspect evidence", "Choose next work")

    def assert_order(self, raw, displayed):
        self.assertEqual(self.tasks.load()["order"], raw)
        self.assertEqual(self.tasks.display()["order"], displayed)

    def test_multiple_start_and_resume_use_stable_active_first_projection(self):
        raw = self.tasks.load()["order"]
        self.tasks.action("D", "start")
        self.assert_order(raw, ["D", "A", "B", "C", "E"])
        self.tasks.action("B", "start")
        self.assert_order(raw, ["B", "D", "A", "C", "E"])
        self.assertEqual(self.tasks.next()["id"], "B")
        self.tasks.action("D", "pause")
        self.assert_order(raw, ["B", "A", "C", "D", "E"])
        self.tasks.action("D", "resume")
        self.assert_order(raw, ["B", "D", "A", "C", "E"])
        self.assertEqual(self.tasks.load()["items"]["B"]["status"], "active")
        self.assertEqual(self.tasks.load()["items"]["D"]["status"], "active")

    def test_read_projection_does_not_mutate_file_or_loaded_data(self):
        self.tasks.action("E", "start")
        before = self.tasks.path.read_bytes()
        shown = self.tasks.display()
        shown["order"].clear()
        shown["items"]["A"]["title"] = "Not persisted"
        self.tasks.next()
        self.assertEqual(self.tasks.path.read_bytes(), before)
        self.assert_order(["A", "B", "C", "D", "E"], ["E", "A", "B", "C", "D"])
        self.assertEqual(self.tasks.load()["items"]["A"]["title"], "A")

    def test_pause_done_and_cancel_unpin_only_the_target_task(self):
        raw = self.tasks.load()["order"]
        for task_id in ("B", "D", "E"):
            self.tasks.action(task_id, "start")
        self.tasks.action("D", "pause")
        self.assert_order(raw, ["B", "E", "A", "C", "D"])
        self.tasks.action("B", "done", note="Reviewed")
        self.assert_order(raw, ["E", "A", "B", "C", "D"])
        self.assertEqual(self.tasks.next()["id"], "E")
        self.tasks.action("E", "cancel")
        self.assert_order(raw, raw)
        self.assertEqual(self.tasks.next()["id"], "A")

    def test_reorder_changes_group_order_but_preserves_raw_group_slots(self):
        for task_id in ("B", "D"):
            self.tasks.action(task_id, "start")
        self.tasks.reorder(["D", "B", "E", "A", "C"])
        self.assert_order(["E", "D", "A", "B", "C"], ["D", "B", "E", "A", "C"])
        self.tasks.action("D", "pause")
        self.assert_order(["E", "D", "A", "B", "C"], ["B", "E", "D", "A", "C"])
        self.tasks.action("B", "pause")
        self.assert_order(["E", "D", "A", "B", "C"], ["E", "D", "A", "B", "C"])

    def test_cross_group_drag_cannot_unpin_active_tasks(self):
        self.tasks.action("D", "start")
        self.tasks.reorder(["E", "A", "D", "B", "C"])
        self.assert_order(["E", "A", "B", "D", "C"], ["D", "E", "A", "B", "C"])

    def test_reorder_without_active_tasks_retains_legacy_behavior(self):
        self.tasks.action("B", "done")
        self.tasks.reorder(["E", "D", "C", "A"])
        self.assert_order(["E", "D", "C", "A", "B"], ["E", "D", "C", "A", "B"])
        self.assertEqual(self.tasks.load()["items"]["B"]["status"], "done")

    def test_invalid_reorders_leave_queue_unchanged(self):
        self.tasks.action("D", "start")
        before = self.tasks.path.read_bytes()
        for order in (["A"], ["A", "B", "C", "D", "D"],
                      ["A", "B", "C", "D", "MISSING"], "ABCDE"):
            with self.subTest(order=order), self.assertRaises(NAIAError):
                self.tasks.reorder(order)
            self.assertEqual(self.tasks.path.read_bytes(), before)

    def test_invalid_transitions_leave_all_other_active_tasks_unchanged(self):
        self.tasks.action("B", "start")
        self.tasks.action("D", "start")
        self.tasks.action("C", "done")
        for task_id, action in (("B", "start"), ("B", "resume"),
                                ("C", "start"), ("C", "resume"), ("MISSING", "start")):
            before = self.tasks.path.read_bytes()
            with self.subTest(task_id=task_id, action=action), self.assertRaises(NAIAError):
                self.tasks.action(task_id, action)
            self.assertEqual(self.tasks.path.read_bytes(), before)
        self.assertEqual(self.tasks.next()["id"], "B")

    def test_explicit_move_and_defer_keep_legacy_semantics(self):
        self.tasks.action("D", "start")
        self.tasks.action("B", "start")
        self.tasks.action("E", "move-top")
        self.assert_order(["E", "A", "B", "C", "D"], ["B", "D", "E", "A", "C"])
        self.tasks.action("D", "defer", placement="after:A")
        self.assert_order(["E", "A", "D", "B", "C"], ["B", "E", "A", "D", "C"])
        self.assertEqual(self.tasks.load()["items"]["D"]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
