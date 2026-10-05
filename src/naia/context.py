"""Confirmed project context, assistant integrations, and built-in workflow rules."""
from __future__ import annotations

import copy
from pathlib import Path
import shutil

from .storage import NAIAError, atomic_text, inside, locked, now, read_json, write_json


POLICY = {
    "unsolicited_documents": False,
    "concise_cards": True,
    "approve_design_and_interpretations": True,
    "approve_destructive_changes": True,
    "assignments_in_naia": True,
    "evaluation_only_suites": False,
    "shared_launchers": True,
    "predeclare_results": True,
    "auto_evaluate": True,
    "skip_duplicate_work": True,
    "auto_review_tasks": True,
    "validate_before_launch": True,
    "show_launch_plan": True,
}
ASSISTANTS = {
    "codex": ("AGENTS.md",),
    "claude": ("CLAUDE.md",),
    "both": ("AGENTS.md", "CLAUDE.md"),
}
ASSISTANT_QUESTION = {
    "field": "assistant",
    "question": "Which project assistants should NAIA configure: Codex, Claude, or both?",
    "options": list(ASSISTANTS),
}
DEFAULT_ANSWERS = {
    "reporting": {
        "format": "Concise suite cards; additional reports only when explicitly requested",
        "destination": ".lab/suites",
    },
    "governance": {"rules": "naia policy", "exceptions": [], "excluded_paths": []},
}
QUESTIONS = [
    {"field": "project", "question": "What is the overall goal, scope, success criterion, and what is excluded?"},
    {"field": "hardware", "question": "Where does work run: local GPUs, Slurm, or another system? Provide GPU/memory limits, concurrency, environments, shared paths, and optionally a submission script."},
    {"field": "execution", "question": "How are training and evaluation invoked? What artifacts prove completion, and how does resume work?"},
    {"field": "evaluation", "question": "Which metrics, splits, seeds, budgets, controls, and evaluation constraints matter?"},
    {"field": "reporting", "question": "Default: concise suite cards, with other reports only on request. Any different formats or destinations?"},
    {"field": "configuration", "question": "Which configuration system exists? Preserve it, or discuss composable Hydra for a new project or an explicitly approved migration?"},
    {"field": "governance", "question": "NAIA's standard rules already apply. Any project-specific exceptions, retention constraints, or excluded inspection paths?"},
]
ASSISTANT_RULES = """- Read `.lab/project.json` and the task queue before project work. Follow `naia policy`; respect existing project instructions and inspection exclusions. Codex and Claude share the same NAIA records.
- Users state intent; handle routine workflow steps without asking them to repeat these rules. During onboarding, inspect the permitted repo, propose detected settings, and ask only about unresolved project choices. Record confirmed answers, not guesses. Preserve the config system; suggest Hydra for a new ML project, never migrate silently.
- After substantive discussions, add or update tasks for decisions the user must make, outstanding results they must review, and blockers needing their input. Link evidence and prioritize the next decision. Reuse existing tasks; do not create duplicates or tasks for purely informational exchanges. Maintain review follow-ups for evaluations and analyses without being reminded.
- Before any authorized launch, register the approved suite, reserve its results, validate its definition, run a dry-run preflight, and show a brief plan. Use shared `naia suite launch` / `evaluate` commands and confirmed backends. These checks do not require separate reminders or approval for each routine step; new designs, meaningful scope changes, and actual launches still need user authorization.
- Automatic declared evaluation is on by default. Reuse verified completed work and live jobs; inspect uncertain states before retrying. Sync validated results and ensure a review task exists when evidence is ready. Never present generated metrics as automatic scientific conclusions.
- For architecture inspection, use bundled `naia arch` commands. Capture trusted model factories in the model's existing PyTorch environment, never through a browser endpoint. Register saved graphs with suite/task links when relevant; reuse unchanged evidence and keep capture optional. Viewing graphs must not require installing PyTorch or changing project dependencies.
- Keep cards and responses short: compact tables and bullets, no long narrative history. Create Markdown only for suite cards or a specifically requested document; no unsolicited reports, notes, runbooks, or task files. Keep operational assignments in NAIA, not suite cards. Evaluation-only work belongs to its training suite.
- Record design decisions and interpretations only after discussion and user approval. Ask about meaningful missing assumptions, not already established defaults. Only seal suites when the user approves. Prefer existing helpers; do not create per-suite launchers/evaluators.
- Propose cleanup before deleting, moving, overwriting, publishing, or restructuring existing work; obtain approval and preserve unrelated changes. Never store credentials in project context. Confirmed project-specific exceptions may refine these defaults; do not silently weaken approval or safety boundaries.
"""
POLICY_TEXT = "NAIA assistant contract\n\n" + ASSISTANT_RULES
INSTRUCTIONS_BEGIN = "<!-- naia:instructions -->"
INSTRUCTIONS_END = "<!-- /naia:instructions -->"
INSTRUCTIONS_BLOCK = INSTRUCTIONS_BEGIN + "\n## NAIA workflow\n\n" + ASSISTANT_RULES + INSTRUCTIONS_END + "\n"


class Project:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / ".lab"
        self.context_path = self.directory / "project.json"

    @classmethod
    def discover(cls, explicit=None):
        if explicit:
            return cls(explicit)
        for path in (Path.cwd(), *Path.cwd().parents):
            if (path / ".lab/project.json").is_file():
                return cls(path)
        return cls(Path.cwd())

    def path(self, relative):
        return inside(self.root, relative)

    def load(self):
        data = read_json(self.context_path)
        if data.get("schema_version") != 1:
            raise NAIAError("Unsupported project context version")
        return data

    def initialize(self, assistant=None):
        if assistant is not None and (not isinstance(assistant, str) or assistant not in ASSISTANTS):
            raise NAIAError("Choose assistant codex, claude, or both")
        self.root.mkdir(parents=True, exist_ok=True)
        with locked(self.directory / "state/locks/context.lock"):
            if self.context_path.exists():
                data = self.load()
            else:
                if (self.directory / "tasks.json").exists() or (self.directory / "state/registry.json").exists():
                    raise NAIAError("Existing workspace records have no project context; inspect them before initialization")
                data = {
                    "schema_version": 1, "created_at": now(), "revision": 1,
                    "onboarding": {"status": "pending", "confirmed_by": None},
                    "answers": {item["field"]: {
                        "confirmed": item["field"] in DEFAULT_ANSWERS,
                        "value": copy.deepcopy(DEFAULT_ANSWERS.get(item["field"])),
                    } for item in QUESTIONS},
                    "assistants": {"selection": None, "instruction_files": []},
                    "policies": copy.deepcopy(POLICY),
                    "backends": {"local": {"kind": "local", "confirmed": False}},
                }
                write_json(self.context_path, data)
                write_json(self.directory / "tasks.json", {"schema_version": 1, "order": [], "items": {}})
                write_json(self.directory / "state/registry.json", {"schema_version": 1, "suites": []})
        if assistant is not None:
            self.configure_assistant(assistant)
            return self.load()
        return data

    def questions(self):
        data = self.load()
        choice = data.get("assistants", {}).get("selection")
        return [{**ASSISTANT_QUESTION, "answer": {"confirmed": bool(choice), "value": choice}},
                *[{**q, "answer": data["answers"][q["field"]]} for q in QUESTIONS]]

    def configure_assistant(self, choice):
        if not isinstance(choice, str) or choice not in ASSISTANTS:
            raise NAIAError("Choose assistant codex, claude, or both")
        # Selecting the integration authorizes only the selected managed blocks.
        self.load()
        files = list(ASSISTANTS[choice])
        results = self.install_instructions(files)
        with locked(self.directory / "state/locks/context.lock"):
            data = self.load()
            current = data.get("assistants", {})
            changed = current.get("selection") != choice or current.get("instruction_files") != files
            missing = set(POLICY) - set(data.get("policies", {}))
            if changed or missing:
                if changed:
                    data["assistants"] = {"selection": choice, "instruction_files": files, "configured_at": now()}
                for key in missing:
                    data.setdefault("policies", {})[key] = copy.deepcopy(POLICY[key])
                data["revision"] += 1
                write_json(self.context_path, data)
        return {"selection": choice, "instruction_files": files, "files": results,
                "warnings": self.assistant_warnings(),
                "assistant_action": "Read the installed instruction files now. Start a new assistant session if needed for automatic instruction discovery."}

    def assistant_warnings(self):
        files = self.load().get("assistants", {}).get("instruction_files", [])
        warnings = []
        override = self.root / "AGENTS.override.md"
        if "AGENTS.md" in files and override.is_file() and override.stat().st_size:
            warnings.append("AGENTS.override.md takes precedence over AGENTS.md in Codex. Review it before relying on NAIA defaults; NAIA did not modify it.")
        return warnings

    def answer(self, field, value, *, confirmed):
        if field not in {q["field"] for q in QUESTIONS}:
            raise NAIAError(f"Unknown onboarding field: {field}")
        with locked(self.directory / "state/locks/context.lock"):
            data = self.load()
            data["answers"][field] = {"value": value, "confirmed": confirmed, "updated_at": now()}
            data["revision"] += 1
            data["onboarding"] = {"status": "pending", "confirmed_by": None}
            write_json(self.context_path, data)
        return data

    def configure_backend(self, backend_id, profile, *, confirmed):
        from .storage import name
        name(backend_id)
        if profile.get("kind") not in ("local", "slurm"):
            raise NAIAError("Initial backends support local and Slurm; custom adapters are not yet implemented")
        for key in ("management_python", "command_python", "evaluation_python"):
            if key in profile and (not isinstance(profile[key], str) or not profile[key] or "\0" in profile[key]):
                raise NAIAError(f"Invalid backend {key}")
        for key in ("command_prefix", "evaluation_command_prefix"):
            if key in profile and (not isinstance(profile[key], list) or any(not isinstance(v, str) or "\0" in v for v in profile[key])):
                raise NAIAError(f"Invalid backend {key}")
        if profile["kind"] == "slurm":
            if not isinstance(profile.get("management_python"), str) or not profile["management_python"]:
                raise NAIAError("Slurm requires management_python on shared storage")
            allowed = {"partition", "account", "qos", "time", "mem", "cpus-per-task", "gres", "constraint", "exclude"}
            for options in (profile.get("resources", {}), profile.get("evaluation_resources", {})):
                if not isinstance(options, dict) or any(k not in allowed for k in options):
                    raise NAIAError("Unsupported Slurm resource option")
                if any(not isinstance(v, (str, int)) or "\n" in str(v) for v in options.values()):
                    raise NAIAError("Invalid Slurm resource value")
        with locked(self.directory / "state/locks/context.lock"):
            data = self.load()
            data["backends"][backend_id] = {**profile, "confirmed": confirmed}
            data["revision"] += 1
            data["onboarding"] = {"status": "pending", "confirmed_by": None}
            write_json(self.context_path, data)
        return data

    def confirm(self, actor):
        if not actor.strip():
            raise NAIAError("Confirmation requires a named user")
        with locked(self.directory / "state/locks/context.lock"):
            data = self.load()
            missing = [k for k, v in data["answers"].items() if not v["confirmed"] or v["value"] in (None, "", {})]
            if missing:
                raise NAIAError(f"Unconfirmed onboarding fields: {', '.join(missing)}")
            if not any(p.get("confirmed") for p in data["backends"].values()):
                raise NAIAError("Confirm at least one execution backend")
            data["onboarding"] = {"status": "confirmed", "confirmed_by": actor, "confirmed_at": now()}
            write_json(self.context_path, data)
        return data

    def execution_ready(self, backend):
        data = self.load()
        if data["onboarding"]["status"] != "confirmed":
            raise NAIAError("Complete user-approved onboarding before execution")
        profile = data["backends"].get(backend)
        if not profile or not profile.get("confirmed"):
            raise NAIAError(f"Backend {backend!r} is not confirmed")
        return profile

    def doctor(self):
        data = self.load()
        checks = [{"name": "onboarding", "ok": data["onboarding"]["status"] == "confirmed"}]
        for key, profile in data["backends"].items():
            checks.append({"name": f"backend:{key}:confirmed", "ok": bool(profile.get("confirmed"))})
            if profile["kind"] == "slurm":
                for executable in ("sbatch", "squeue", "sacct"):
                    checks.append({"name": f"backend:{key}:{executable}", "ok": shutil.which(executable) is not None})
                checks.append({"name": f"backend:{key}:management_python", "ok": Path(profile["management_python"]).is_file()})
        return {"project": str(self.root), "ok": all(c["ok"] for c in checks), "checks": checks}

    def install_instructions(self, filenames):
        if not filenames or len(set(filenames)) != len(filenames) or any(
                filename not in ("AGENTS.md", "CLAUDE.md") for filename in filenames):
            raise NAIAError("Choose distinct AGENTS.md and/or CLAUDE.md instruction files")
        pairs = [(INSTRUCTIONS_BEGIN, INSTRUCTIONS_END),
                 ("<!-- research-workbench:instructions -->", "<!-- /research-workbench:instructions -->")]
        with locked(self.directory / "state/locks/instructions.lock"):
            plans = []
            # Preflight all files before writing either integration.
            for filename in filenames:
                path = self.path(filename)
                original = path.read_bytes().decode("utf-8") if path.exists() else ""
                present = [(begin, end) for begin, end in pairs if begin in original or end in original]
                if len(present) > 1:
                    raise NAIAError(f"Inspect mixed instruction markers in {filename} before updating")
                if present:
                    begin, end = present[0]
                    if original.count(begin) != 1 or original.count(end) != 1 or original.index(begin) > original.index(end):
                        raise NAIAError(f"Inspect malformed instruction markers in {filename} before updating")
                    start = original.index(begin)
                    stop = original.index(end) + len(end)
                    updated = original[:start] + INSTRUCTIONS_BLOCK.rstrip("\n") + original[stop:]
                else:
                    updated = original + ("\n" if original and not original.endswith("\n\n") else "") + INSTRUCTIONS_BLOCK
                plans.append((filename, path, original, updated))
            results = []
            for filename, path, original, updated in plans:
                changed = original != updated
                if changed:
                    atomic_text(path, updated)
                results.append({"file": filename, "changed": changed})
        return results
