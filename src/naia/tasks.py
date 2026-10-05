"""Human attention queue; execution jobs are not tasks."""
from .storage import NAIAError, digest, locked, name, now, read_json, write_json


class Tasks:
    def __init__(self, project):
        self.project = project
        self.path = project.directory / "tasks.json"

    def load(self):
        return read_json(self.path)

    def add(self, task_id, title, goal, decision, *, owner="unassigned", dependencies=(), materials=(), top=False):
        name(task_id)
        if not all(isinstance(v, str) and v.strip() for v in (title, goal, decision)):
            raise NAIAError("Tasks require title, goal, and decision")
        with locked(self.project.directory / "state/locks/tasks.lock"):
            data = self.load()
            if task_id in data["items"]:
                raise NAIAError(f"Task exists: {task_id}")
            if any(dep not in data["items"] for dep in dependencies):
                raise NAIAError("Task dependency does not exist")
            item = {"id": task_id, "title": title, "goal": goal, "decision": decision,
                    "owner": owner, "depends_on": list(dependencies), "materials": list(materials),
                    "status": "ready", "created_at": now(), "notes": []}
            data["items"][task_id] = item
            data["order"].insert(0 if top else len(data["order"]), task_id)
            write_json(self.path, data)
        return item

    def next(self):
        data = self.load()
        for status in ("active", "ready"):
            for task_id in data["order"]:
                if data["items"][task_id]["status"] == status:
                    return data["items"][task_id]
        return None

    def action(self, task_id, action, *, note="", owner=None):
        with locked(self.project.directory / "state/locks/tasks.lock"):
            data = self.load()
            if task_id not in data["items"]:
                raise NAIAError(f"Unknown task: {task_id}")
            item = data["items"][task_id]
            if action == "assign":
                if not owner:
                    raise NAIAError("Assignment requires an owner")
                item["owner"] = owner
            elif action == "move-top":
                data["order"].remove(task_id)
                data["order"].insert(0, task_id)
            else:
                transitions = {"start": ({"ready", "paused"}, "active"),
                               "pause": ({"active", "ready"}, "paused"),
                               "resume": ({"paused"}, "ready"),
                               "done": ({"active", "ready", "paused"}, "done"),
                               "cancel": ({"active", "ready", "paused"}, "cancelled")}
                if action not in transitions:
                    raise NAIAError(f"Unknown task action: {action}")
                allowed, status = transitions[action]
                if item["status"] not in allowed:
                    raise NAIAError(f"Cannot {action} a {item['status']} task")
                if status == "active" and any(v["status"] == "active" for v in data["items"].values()):
                    raise NAIAError("Pause or finish the active task first")
                item["status"] = status
            if note:
                item["notes"].append({"at": now(), "text": note})
            item["updated_at"] = now()
            write_json(self.path, data)
        return item

    def review(self, suite_id, card):
        task_id = f"REVIEW-{suite_id}"
        if len(task_id) > 100:
            task_id = f"REVIEW-{suite_id[:70]}-{digest(suite_id)[:8]}"
        if task_id in self.load()["items"]:
            return
        try:
            self.add(task_id, f"Review {suite_id}", "Review validated experiment results.",
                     "Record the conclusion and decide the next step.", materials=[card])
        except NAIAError:
            if task_id not in self.load()["items"]:
                raise
