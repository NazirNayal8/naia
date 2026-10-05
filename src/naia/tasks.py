"""Human attention queue; execution jobs are not tasks."""
import copy

from .storage import NAIAError, digest, locked, name, now, read_json, write_json


class Tasks:
    def __init__(self, project):
        self.project = project
        self.path = project.directory / "tasks.json"
        self.archive_path = project.directory / "archive.json"

    def load(self):
        return read_json(self.path)

    def archive(self):
        return read_json(self.archive_path) if self.archive_path.exists() else {"schema_version": 1, "items": []}

    @staticmethod
    def _validate_fields(title, goal, decision, owner, dependencies, materials, task_type):
        if not all(isinstance(v, str) and v.strip() for v in (title, goal, decision, owner, task_type)):
            raise NAIAError("Tasks require text title, goal, decision, type, and owner")
        for values in (dependencies, materials):
            if not isinstance(values, (list, tuple)) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise NAIAError("Related tasks and materials must be lists of nonempty text")

    @staticmethod
    def _place(data, task_id, placement):
        if placement == "keep":
            return
        order = list(data["order"])
        if placement not in ("top", "bottom"):
            if not isinstance(placement, str) or not placement.startswith("after:"):
                raise NAIAError("Placement must be keep, top, bottom, or after:ID")
            target = placement[6:]
            if target == task_id or target not in order or data["items"][target]["status"] in ("done", "cancelled"):
                raise NAIAError("Placement target must be another open task")
        if task_id in order:
            order.remove(task_id)
        index = 0 if placement == "top" else len(order) if placement == "bottom" else order.index(placement[6:]) + 1
        order.insert(index, task_id)
        data["order"] = order

    def add(self, task_id, title, goal, decision, *, owner="unassigned", dependencies=(), materials=(), top=False,
            task_type="task", placement=None):
        name(task_id)
        self._validate_fields(title, goal, decision, owner, dependencies, materials, task_type)
        if placement == "keep":
            raise NAIAError("A new task needs a queue position")
        with locked(self.project.directory / "state/locks/tasks.lock"):
            data = self.load()
            if task_id in data["items"]:
                raise NAIAError(f"Task exists: {task_id}")
            if any(dep not in data["items"] for dep in dependencies):
                raise NAIAError("Task dependency does not exist")
            if task_id in dependencies:
                raise NAIAError("A task cannot depend on itself")
            item = {"id": task_id, "title": title, "goal": goal, "decision": decision,
                    "owner": owner, "type": task_type, "depends_on": list(dict.fromkeys(dependencies)), "materials": list(materials),
                    "status": "ready", "created_at": now(), "notes": []}
            data["items"][task_id] = item
            self._place(data, task_id, placement or ("top" if top else "bottom"))
            write_json(self.path, data)
        return item

    def edit(self, task_id, *, title, goal, decision, owner="unassigned", dependencies=(), materials=(),
             task_type="task", placement="keep"):
        self._validate_fields(title, goal, decision, owner, dependencies, materials, task_type)
        with locked(self.project.directory / "state/locks/tasks.lock"):
            data = self.load()
            if task_id not in data["order"]:
                raise NAIAError("Only queued tasks can be edited")
            if task_id in dependencies or any(dep not in data["items"] for dep in dependencies):
                raise NAIAError("Related tasks must exist and cannot include this task")
            self._place(data, task_id, placement)
            item = data["items"][task_id]
            item.update(title=title, goal=goal, decision=decision, owner=owner, type=task_type,
                        depends_on=list(dict.fromkeys(dependencies)), materials=list(materials), updated_at=now())
            write_json(self.path, data)
        return item

    def reorder(self, ordered_ids):
        with locked(self.project.directory / "state/locks/tasks.lock"):
            data = self.load()
            open_ids = [key for key in data["order"] if data["items"][key]["status"] not in ("done", "cancelled")]
            if (not isinstance(ordered_ids, list) or any(not isinstance(key, str) for key in ordered_ids)
                    or len(set(ordered_ids)) != len(ordered_ids) or set(ordered_ids) != set(open_ids)):
                raise NAIAError("Reordering requires every open task exactly once")
            data["order"] = ordered_ids + [key for key in data["order"] if key not in open_ids]
            write_json(self.path, data)
        return data

    def next(self):
        data = self.load()
        for status in ("active", "ready"):
            for task_id in data["order"]:
                if data["items"][task_id]["status"] == status:
                    return data["items"][task_id]
        return None

    def action(self, task_id, action, *, note="", owner=None, placement="bottom"):
        if not isinstance(note, str):
            raise NAIAError("Task note must be text")
        with locked(self.project.directory / "state/locks/tasks.lock"):
            data = self.load()
            if task_id not in data["order"]:
                raise NAIAError(f"Unknown task: {task_id}")
            item = data["items"][task_id]
            if action == "assign":
                if not isinstance(owner, str) or not owner.strip():
                    raise NAIAError("Assignment requires an owner")
                item["owner"] = owner
            elif action == "move-top":
                self._place(data, task_id, "top")
            elif action in ("move", "defer"):
                if item["status"] not in ("ready", "paused", "active"):
                    raise NAIAError("Only open tasks can move")
                self._place(data, task_id, placement)
                if item["status"] == "active":
                    item["status"] = "ready"
            elif action == "remove":
                if note:
                    item["notes"].append({"at": now(), "text": note})
                    note = ""
                removed = copy.deepcopy(item)
                removed.update(archived_at=now(), archive_reason="removed")
                archive = self.archive()
                prior = next((entry for entry in archive["items"] if entry["id"] == task_id), None)
                if prior is None:
                    archive["items"].append(removed)
                else:
                    # An interrupted archive/queue pair can be safely retried.
                    removed["archived_at"] = prior["archived_at"]
                    prior.update(removed)
                write_json(self.archive_path, archive)
                data["order"].remove(task_id)
                # Keep an identity tombstone so review sync never resurrects removed work.
                item.update(archived_at=removed["archived_at"], status="cancelled")
            else:
                transitions = {"start": ({"ready", "paused"}, "active"),
                               "pause": ({"active", "ready"}, "paused"),
                               "resume": ({"paused"}, "active"),
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
