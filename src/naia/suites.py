"""Generic suite definitions and generated cards; no dataset-specific coordinates."""
from __future__ import annotations

import math
import re

from .storage import NAIAError, atomic_text, digest, inside, locked, name, now, read_json, write_json
from .tasks import Tasks


BEGIN = "<!-- lab:results -->"
END = "<!-- /lab:results -->"
UI_STATUSES = ("proposed", "approved", "ready", "queued", "training", "evaluating", "active", "running", "reopened", "sealed", "shelved")


def definition_digest(data):
    """Sealing changes lifecycle metadata, not the experiment that produced results."""
    return digest({k: v for k, v in data.items() if k not in {"status", "sealed", "ui_status", "ui_status_changed"}})


def command_valid(command):
    if not isinstance(command, dict) or not isinstance(command.get("argv"), list) or not command["argv"]:
        raise NAIAError("Commands require a nonempty argv list, never a shell expression")
    if any(not isinstance(arg, str) or "\0" in arg for arg in command["argv"]):
        raise NAIAError("Command arguments must be strings without NUL")
    environment = command.get("environment", {})
    if not isinstance(environment, dict) or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) or not isinstance(v, str) for k, v in environment.items()):
        raise NAIAError("Invalid command environment")
    if any(k in environment for k in ("HOME", "CODEX_HOME")):
        raise NAIAError("Do not override HOME or CODEX_HOME")
    timeout = command.get("timeout_seconds")
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0):
        raise NAIAError("timeout_seconds must be positive and finite")
    if "resume_argv" in command:
        command_valid({"argv": command["resume_argv"]})


def validate_definition(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise NAIAError("Expected suite schema_version=1")
    name(data.get("id"))
    for field in ("title", "question"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise NAIAError(f"Suite requires {field}")
    if not isinstance(data.get("cells"), list) or not data["cells"]:
        raise NAIAError("Suite needs nonempty cells")
    if not isinstance(data.get("evaluation"), list) or not data["evaluation"]:
        raise NAIAError("Predeclare at least one evaluation profile")
    command_valid(data.get("training"))
    seen = set()
    reserved = {"project", "python", "run_dir", "artifact", "metrics", "cell", "suite", "resume_from"}
    for cell in data["cells"]:
        key = name(cell.get("id"))
        if key in seen:
            raise NAIAError(f"Duplicate cell: {key}")
        seen.add(key)
        parameters = cell.get("parameters", {})
        if not isinstance(parameters, dict):
            raise NAIAError("Cell parameters must be a mapping")
        for param, value in parameters.items():
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", param) or param in reserved:
                raise NAIAError(f"Unsafe or reserved parameter: {param}")
            if not isinstance(value, (str, int, float, bool)) or isinstance(value, float) and not math.isfinite(value):
                raise NAIAError("Initial command parameters support finite scalar values")
    profiles = set()
    for profile in data["evaluation"]:
        key = name(profile.get("id"))
        if key in profiles:
            raise NAIAError(f"Duplicate evaluation profile: {key}")
        profiles.add(key)
        command_valid(profile.get("command"))
        metrics = profile.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            raise NAIAError("Each profile must reserve metric columns")
        for metric, spec in metrics.items():
            name(metric)
            if not isinstance(spec, dict) or not isinstance(spec.get("path"), str) or not spec["path"]:
                raise NAIAError("Metric specs require a JSON field path")
            if spec.get("direction") not in (None, "min", "max"):
                raise NAIAError("Metric direction must be min, max, or unspecified")
    for key in ("artifact", "resume_artifact"):
        if key in data:
            path = data[key]
            if not isinstance(path, str) or not path or path.startswith(("/", "\\")) or ".." in path.replace("\\", "/").split("/"):
                raise NAIAError(f"{key} must be relative to each attempt directory")
    if not data.get("artifact"):
        raise NAIAError("Declare the training completion artifact")
    predecessors = data.get("predecessors", [])
    if not isinstance(predecessors, list):
        raise NAIAError("predecessors must be a list")
    for predecessor in predecessors:
        name(predecessor)
        if predecessor == data["id"]:
            raise NAIAError("A suite cannot precede itself")
    # Unknown placeholders must fail preflight, not the first real submission.
    for cell in data["cells"]:
        allowed = set(cell.get("parameters", {})) | reserved
        commands = [data["training"], *(p["command"] for p in data["evaluation"])]
        for command in commands:
            strings = command["argv"] + command.get("resume_argv", []) + list(command.get("environment", {}).values())
            referenced = {match for value in strings for match in re.findall(r"\{([A-Za-z][A-Za-z0-9_]*)\}", value)}
            if referenced - allowed:
                raise NAIAError(f"Unknown placeholders for {cell['id']}: {sorted(referenced - allowed)}")
    return data


class Suites:
    def __init__(self, project):
        self.project = project

    def location(self, suite_id):
        return self.project.path(f".lab/suites/{name(suite_id)}")

    def load(self, suite_id, *, approved=False):
        directory = self.location(suite_id)
        data = validate_definition(read_json(directory / "suite.json"))
        if data["id"] != suite_id:
            raise NAIAError("Suite directory and definition identity differ")
        if approved and (data.get("status") != "approved" or not data.get("approval", {}).get("by")):
            raise NAIAError("Suite must be approved and unsealed before execution")
        card = directory / "card.md"
        if not card.is_file():
            raise NAIAError("Suite card missing")
        text = card.read_text()
        if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(BEGIN) > text.index(END):
            raise NAIAError("Suite card requires one valid generated result block")
        return data

    def add(self, definition, actor):
        data = dict(validate_definition(definition))
        if not actor.strip():
            raise NAIAError("Explicit approval requires a named user")
        data.update(status="approved", approval={"by": actor, "at": now()})
        directory = self.location(data["id"])
        with locked(self.project.directory / "state/locks/suites.lock"):
            if directory.exists():
                raise NAIAError("Suite already exists; do not overwrite approved definitions")
            existing = {p.name for p in (self.project.directory / "suites").glob("*") if p.is_dir()}
            if any(p not in existing for p in data.get("predecessors", [])):
                raise NAIAError("Scientific predecessor must exist")
            directory.mkdir(parents=True)
            write_json(directory / "suite.json", data)
            card = (f"# {data['id']}: {data['title']}\n\n{data['question']}\n\n"
                    f"Approved by: {actor}\n\n{BEGIN}\nPending.\n{END}\n\n"
                    f"```bash\nnaia suite launch {data['id']}\nnaia suite evaluate {data['id']}\nnaia sync\n```\n")
            atomic_text(directory / "card.md", card)
        self.sync()
        return data

    def definitions(self):
        return [self.load(path.parent.name) for path in sorted((self.project.directory / "suites").glob("*/suite.json"))]

    def seal(self, suite_id, actor):
        if not actor.strip():
            raise NAIAError("Sealing requires a named user")
        with locked(self.project.directory / "state/locks/suites.lock"):
            data = self.load(suite_id)
            data.update(status="sealed", ui_status="sealed", sealed={"by": actor, "at": now()})
            write_json(self.location(suite_id) / "suite.json", data)
        self.sync()
        return data

    def set_status(self, suite_id, status, actor):
        """User-edited display lifecycle is not execution approval or observed job state."""
        if not isinstance(status, str) or status not in UI_STATUSES:
            raise NAIAError("Unknown suite status")
        if not isinstance(actor, str) or not actor.strip():
            raise NAIAError("Status changes require a named user")
        with locked(self.project.directory / "state/locks/suites.lock"):
            data = self.load(suite_id)
            data.update(ui_status=status, ui_status_changed={"by": actor, "at": now()})
            if status in ("sealed", "shelved"):
                data.update(status="sealed", sealed={"by": actor, "at": now()})
            elif data.get("status") == "sealed":
                if not data.get("approval", {}).get("by"):
                    raise NAIAError("Status labels cannot approve an experiment")
                data["status"] = "approved"
            elif status == "approved" and data.get("status") != "approved":
                raise NAIAError("Status labels cannot approve an experiment")
            write_json(self.location(suite_id) / "suite.json", data)
        self.sync()
        return data

    def pointer(self, suite_id, cell_id):
        path = self.project.path(f".lab/state/runs/{name(suite_id)}/{name(cell_id)}/current.json")
        if not path.exists():
            return None
        pointer = read_json(path)
        record = read_json(self.project.path(pointer["record"]))
        if record.get("suite") != suite_id or record.get("cell") != cell_id:
            raise NAIAError("Run pointer identity mismatch")
        return record

    def checked_result(self, record, profile):
        entry = record["evaluation"][profile["id"]]
        if entry["status"] != "complete":
            return None
        artifact = self.project.path(record["artifact"])
        from .storage import file_digest
        result_path = self.project.path(entry["result"])
        result = read_json(result_path)
        identity = {"suite": record["suite"], "cell": record["cell"], "attempt": record["attempt"],
                    "definition_hash": record["definition_hash"], "profile": profile["id"],
                    "evaluation_attempt": entry["attempt"],
                    "artifact_sha256": record["artifact_sha256"]}
        if result.get("identity") != identity or not artifact.is_file() or file_digest(artifact) != identity["artifact_sha256"]:
            raise NAIAError("Result provenance or artifact digest mismatch")
        values = result.get("metrics", {})
        if set(values) != set(profile["metrics"]) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values.values()):
            raise NAIAError("Result metrics differ from expected finite numeric columns")
        return values

    def render(self, data):
        lines = ["| Cell | Profile | Status | " + " | ".join(sorted({k for p in data["evaluation"] for k in p["metrics"]})) + " |"]
        metrics = sorted({k for p in data["evaluation"] for k in p["metrics"]})
        lines.append("|" + " --- |" * (3 + len(metrics)))
        complete = True
        for cell in data["cells"]:
            record = self.pointer(data["id"], cell["id"])
            for profile in data["evaluation"]:
                values = {}
                status = "pending"
                if record:
                    if record["definition_hash"] != definition_digest(data):
                        status = "definition_changed"
                    else:
                        status = record["evaluation"][profile["id"]]["status"]
                        if status == "pending" and record["training"]["status"] != "complete":
                            status = "training:" + record["training"]["status"]
                        if status == "complete":
                            try:
                                values = self.checked_result(record, profile)
                            except NAIAError:
                                status = "invalid_provenance"
                complete &= status == "complete"
                lines.append("| " + " | ".join([cell["id"], profile["id"], status] + [f"{values[k]:.6g}" if k in values else "—" for k in metrics]) + " |")
        return "\n".join(lines), complete

    def sync(self):
        with locked(self.project.directory / "state/locks/sync.lock"):
            definitions = self.definitions()
            by_id = {s["id"]: s for s in definitions}
            visited, visiting = set(), set()
            def visit(sid):
                if sid in visiting:
                    raise NAIAError("Scientific lineage has a cycle")
                if sid in visited:
                    return
                visiting.add(sid)
                for predecessor in by_id[sid].get("predecessors", []):
                    if predecessor not in by_id:
                        raise NAIAError(f"Missing predecessor: {predecessor}")
                    visit(predecessor)
                visiting.remove(sid)
                visited.add(sid)
            for sid in by_id:
                visit(sid)
            registry = []
            for data in definitions:
                table, complete = self.render(data)
                card = self.location(data["id"]) / "card.md"
                text = card.read_text()
                before, rest = text.split(BEGIN, 1)
                _, after = rest.split(END, 1)
                updated = before + BEGIN + "\n" + table + "\n" + END + after
                if updated != text:
                    atomic_text(card, updated)
                relative = str(card.relative_to(self.project.root))
                registry.append({"id": data["id"], "title": data["title"], "status": data.get("ui_status", data["status"]),
                                 "execution_status": data["status"], "summary": data["question"],
                                 "results_ready": complete, "predecessors": data.get("predecessors", []), "card": relative})
                if complete:
                    Tasks(self.project).review(data["id"], relative)
            result = {"schema_version": 1, "suites": registry}
            write_json(self.project.directory / "state/registry.json", result)
        return result


def import_analysis(project, data, actor):
    name(data.get("id"))
    for key in ("question", "instructions", "inputs", "outputs"):
        if not data.get(key):
            raise NAIAError(f"Analysis requires {key}")
    if any(not isinstance(data[key], str) for key in ("question", "instructions")):
        raise NAIAError("Analysis question and instructions must be text")
    for key in ("inputs", "outputs"):
        if not isinstance(data[key], list) or any(not isinstance(path, str) for path in data[key]):
            raise NAIAError("Analysis inputs and outputs must be path lists")
    for path in data["inputs"]:
        if not project.path(path).exists():
            raise NAIAError(f"Missing analysis input: {path}")
    for path in data["outputs"]:
        project.path(path)
    if not actor.strip():
        raise NAIAError("Analysis assignment requires approval")
    path = project.path(f".lab/analyses/{data['id']}.json")
    with locked(project.directory / "state/locks/analyses.lock"):
        if path.exists():
            raise NAIAError("Analysis already exists")
        record = {**data, "approved_by": actor, "created_at": now()}
        write_json(path, record)
    task_id = "ANALYSIS-" + data["id"]
    Tasks(project).add(task_id, data.get("title", data["question"]), data["question"],
                       "Review analysis evidence before recording conclusions.", owner=data.get("owner", "unassigned"),
                       materials=[str(path.relative_to(project.root))])
    return record
