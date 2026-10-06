"""Confirmed project context, assistant integrations, and built-in workflow rules."""
from __future__ import annotations

import copy
from pathlib import Path
import shutil

from ._assistant_roles import ROLE_PRESETS, role_question, role_record, role_section
from .discovery import inspect_project, is_excluded, normalize_exclusions
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
- Users state intent; handle routine workflow steps without asking them to repeat these rules. Before onboarding an existing project, read its instructions and inspection exclusions, then use `naia init` or `naia context scan` with those exclusions. Infer the goal, training/evaluation setup, configuration, and supported hardware from the permitted README, scripts, and configs. Cite files with `naia context propose`; show one concise summary for the user to confirm or correct instead of asking them to describe the project from scratch. Ask only for missing or uncertain details, and flag conflicting or outdated evidence. Accept proposals only after explicit user confirmation; discovery is not launch authorization. Preserve confirmed context and the existing config system; suggest Hydra for a new ML project, never migrate silently.
- If both Codex and Claude are selected, ask the optional `assistant_roles` question: peers, either assistant as lead, or custom responsibilities and boundaries. Explain proposed limits and record the user's choice with `naia instructions roles` only after confirmation. Never assign a hierarchy automatically. Follow confirmed per-assistant roles in this file and `.lab/project.json`; existing approvals and project scope remain unchanged.
- After substantive discussions, add or update tasks for decisions the user must make, outstanding results they must review, and blockers needing their input. Link evidence and prioritize the next decision. Reuse existing tasks; do not create duplicates or tasks for purely informational exchanges. Maintain review follow-ups for evaluations and analyses without being reminded.
- Before any authorized launch, register the approved suite, reserve its results, validate its definition, run a dry-run preflight, and show a brief plan. Use shared `naia suite launch` / `evaluate` commands and confirmed backends. These checks do not require separate reminders or approval for each routine step; new designs, meaningful scope changes, and actual launches still need user authorization.
- Automatic declared evaluation is on by default. Reuse verified completed work and live jobs; inspect uncertain states before retrying. Sync validated results and ensure a review task exists when evidence is ready. Never present generated metrics as automatic scientific conclusions.
- For architecture inspection, follow the model-visualization workflow below. Handle routine capture and registration for the user; do not merely hand them setup commands.
- Keep cards and responses short: compact tables and bullets, no long narrative history. Create Markdown only for suite cards or a specifically requested document; no unsolicited reports, notes, runbooks, or task files. Keep operational assignments in NAIA, not suite cards. Evaluation-only work belongs to its training suite.
- Record design decisions and interpretations only after discussion and user approval. Ask about meaningful missing assumptions, not already established defaults. Only seal suites when the user approves. Prefer existing helpers; do not create per-suite launchers/evaluators.
- Propose cleanup before deleting, moving, overwriting, publishing, or restructuring existing work; obtain approval and preserve unrelated changes. Never store credentials in project context. Confirmed project-specific exceptions may refine these defaults; do not silently weaken approval or safety boundaries.
"""
ARCHITECTURE_RULES = """1. Treat \"add this model to the visualizer\" as an end-to-end request, not a special prompt or training launch. First read permitted model, config, and forward sources. Infer the exact variant, existing PyTorch environment, sample-input shapes, dtypes, and device; ask only about uncertain details. Preserve the project's configuration system and model settings.
2. Check `naia arch list` in an initialized project. Reuse unchanged evidence; use separate graph files and IDs for changed scenarios, shapes, or budgets. Never overwrite registered graphs. Capture, validation, and standalone viewing do not require training/backend onboarding; registration needs initialized project records only.
3. Reuse an existing factory or create a minimal trusted factory returning `(model, example_args, example_kwargs)`. Use small representative inputs in the model's existing PyTorch environment. Do not train, download weights, change dependencies, or run a simulator solely to draw a model; ask if any such extra work is necessary.
4. Capture real sample dataflow, then validate the saved graph using the commands below. Tensor tracing is on by default; do not silently substitute `--no-trace` or `--structure-only`. Use compact pictograms and short computational-type captions for primitive layers, not information cards. Reuse the block glossary's shapes, pictograms, and type colours; show tensor dimensions and intermediate sizes on arrows, with full metadata, original module paths and aliases in the inspector. Expansion/contraction glyphs need verified dimensions; image glyphs need explicit image/layout metadata or recorded spatial-processing evidence. Unfamiliar custom modules must not be guessed from their class names.
5. Infer simple semantic names for major project components and inputs/outputs from permitted project terminology, configuration, and forward code: for example Visual encoder, Decoder, Denoiser, VLM, Action projector, Observation frames, Actions, and Predicted state. Do not rename every layer; Linear, attention, normalization, and arithmetic remain type-based unless they themselves are a major project component. Ask the user when a role or boundary meaning is uncertain; never guess from a class name, module path, or tensor size alone. Record each grounded name and optional role in a semantic mapping keyed by exact captured node IDs, with nonempty `evidence` citations to source files or explicit user confirmation. Use `naia arch annotate` on an existing capture (or capture's `--semantics` option) before registration; semantics are interpretive labels, not measured computation. Keep original types, paths, aliases, shapes, and dependency evidence intact. Old `--aliases` alone does not establish semantic meaning. Save a new annotated graph instead of overwriting or rerunning unchanged model evidence.
6. Verify input-to-output connectivity, branches/residuals, and representative shapes against the forward code. Keep Flow separate from Hierarchy. Keep observed, traced, and declared evidence distinct; module listings and hook order do not prove dependencies. Schema validity alone does not establish correct or complete flow. Flag unknown shapes and partial capture; if execution is unavailable, use only cited source/config evidence, not invented flow.
7. Register the graph inside the project with `naia arch add`; attach applicable existing `--suite` and `--task` links. Do not create a suite or unsolicited Markdown for visualization. Open or reuse `naia ui` and verify the model is accessible in the Architecture tab; use `naia arch view` for standalone inspection.
8. Tell the user how to open the graph, the selected variant/input dimensions, and capture limitations. Each capture describes the supplied path, not every branch or input size. Playback is illustrative, not timing. Never run factories from the browser; graph viewing must not require PyTorch or dependency changes.

```bash
naia arch capture --factory module:build --output artifacts/model-v1-raw.json
naia arch annotate artifacts/model-v1-raw.json --semantics @artifacts/model-semantics.json --output artifacts/model-v1.json
naia arch validate artifacts/model-v1.json
naia arch add MODEL-V1 --graph artifacts/model-v1.json --title \"Model\"
naia ui
```

Prepare the semantic mapping from source evidence; for example `{"module:encoder":{"name":"Visual encoder","role":"encoder","evidence":["models/world.py:42 defines the observation encoder"]},"input:0":{"name":"Observation frames","evidence":["models/world.py:56 documents the observation input"]}}`. Replace these illustrative node IDs and citations with the actual capture and project sources. Replace the module, graph path, ID, and title with project-specific values; `module:build` is the trusted factory, not a built-in module. Existing projects refresh these managed instructions with `naia instructions install`; package upgrades alone do not refresh project files.
"""
ASSISTANT_RULES += "\n## Model visualization\n\n" + ARCHITECTURE_RULES
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

    def initialize(self, assistant=None, *, excluded_paths=(), scan=True):
        if assistant is not None and (not isinstance(assistant, str) or assistant not in ASSISTANTS):
            raise NAIAError("Choose assistant codex, claude, or both")
        exclusions = normalize_exclusions(excluded_paths)
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
                    "proposals": {},
                }
                if exclusions:
                    data["inspection_excluded_paths"] = exclusions
                if scan:
                    data["discovery"] = {**inspect_project(self.root, excluded_paths=exclusions),
                                         "scanned_at": now()}
                write_json(self.context_path, data)
                write_json(self.directory / "tasks.json", {"schema_version": 1, "order": [], "items": {}})
                write_json(self.directory / "state/registry.json", {"schema_version": 1, "suites": []})
            if exclusions:
                merged = self._exclusions(data, exclusions)
                if data.get("inspection_excluded_paths") != merged:
                    data["inspection_excluded_paths"] = merged
                    if scan:
                        data["discovery"] = {**inspect_project(self.root, excluded_paths=merged),
                                             "scanned_at": now()}
                    data["revision"] += 1
                    write_json(self.context_path, data)
        if assistant is not None:
            self.configure_assistant(assistant)
        return self.context_view()

    def context_view(self):
        """Hide cached discovery and draft evidence that is no longer permitted."""
        data = copy.deepcopy(self.load())
        excluded = self._exclusions(data)
        discovery = data.get("discovery")
        if discovery:
            previous = discovery.get("sources", [])
            discovery["sources"] = [source for source in previous if not is_excluded(source["path"], excluded)]
            detected = discovery.get("detected", {})
            for key in ("training_candidates", "evaluation_candidates"):
                detected[key] = [path for path in detected.get(key, []) if not is_excluded(path, excluded)]
            if len(previous) != len(discovery["sources"]):
                detected["configuration"], detected["scheduler"] = [], []
                discovery["warnings"].append("Some cached evidence is now excluded; rescan for current signals.")
                discovery["existing_project"] = any(set(source["topics"]) - {"instructions"}
                                                     for source in discovery["sources"])
            discovery["excluded_paths"] = excluded
        blocked = []
        for field, proposal in list(data.get("proposals", {}).items()):
            if any(is_excluded(source["path"], excluded) for source in proposal.get("evidence", [])):
                del data["proposals"][field]
                blocked.append(field)
        for field, answer in data["answers"].items():
            if not answer["confirmed"] and any(is_excluded(source["path"], excluded)
                                                for source in answer.get("evidence", [])):
                answer["value"] = None
                blocked.append(field)
        if blocked:
            data["blocked_proposals"] = sorted(set(blocked))
        return data

    def questions(self):
        data = self.context_view()
        choice = data.get("assistants", {}).get("selection")
        questions = [{**ASSISTANT_QUESTION, "answer": {"confirmed": bool(choice), "value": choice},
                      "mode": "confirmed" if choice else "missing"}]
        roles_question = role_question(data.get("assistants", {}))
        if roles_question is not None:
            questions.append(roles_question)
        discovery = data.get("discovery", {})
        excluded = self._exclusions(data)
        for item in QUESTIONS:
            field = item["field"]
            answer = data["answers"][field]
            question = {**item, "answer": answer}
            proposal = data.get("proposals", {}).get(field)
            if proposal and proposal.get("status") != "pending":
                proposal = None
            if not proposal and not answer["confirmed"] and answer["value"] not in (None, "", {}, []):
                proposal = {"value": answer["value"], "evidence": answer.get("evidence", [])}
            evidence = [{"path": source["path"], "line": source["line"]}
                        for source in discovery.get("sources", [])
                        if field in source.get("topics", []) and not is_excluded(source["path"], excluded)]
            if proposal:
                question.update(mode="confirm_proposal", proposal=proposal,
                                question=f"Does this proposed {field} setup match your project? Confirm or correct it.")
            elif answer["confirmed"]:
                question["mode"] = "confirmed"
            elif evidence:
                question.update(mode="inspect_evidence", evidence=evidence,
                                assistant_action="Infer this setting from the cited files, propose it, then ask for confirmation. Ask only about missing or uncertain details.")
            else:
                question["mode"] = "missing"
            questions.append(question)
        return questions

    @staticmethod
    def _exclusions(data, extra=()):
        governance = data.get("answers", {}).get("governance", {}).get("value", {})
        governance_paths = governance.get("excluded_paths", []) if isinstance(governance, dict) else []
        groups = (data.get("inspection_excluded_paths", []),
                  data.get("discovery", {}).get("excluded_paths", []), governance_paths, extra)
        return normalize_exclusions([path for group in groups for path in normalize_exclusions(group)])

    def scan(self, *, excluded_paths=()):
        """Refresh static evidence without changing confirmed context or authorizing execution."""
        with locked(self.directory / "state/locks/context.lock"):
            data = self.load()
            exclusions = self._exclusions(data, normalize_exclusions(excluded_paths))
            discovery = {**inspect_project(self.root, excluded_paths=exclusions), "scanned_at": now()}
            data["discovery"] = discovery
            if exclusions:
                data["inspection_excluded_paths"] = exclusions
            data["revision"] += 1
            write_json(self.context_path, data)
        return discovery

    def _evidence(self, references, data):
        if isinstance(references, (str, bytes)) or not references:
            raise NAIAError("Inferred proposals require at least one relative file reference")
        evidence = []
        for reference in references:
            if not isinstance(reference, str) or not reference or "\0" in reference or "\n" in reference:
                raise NAIAError("Evidence must be a relative file or file:line reference")
            filename, separator, line = reference.rpartition(":")
            if not separator:
                filename, line = reference, "1"
            if not line.isdecimal() or int(line) < 1:
                raise NAIAError("Evidence line must be a positive integer")
            relative = Path(filename)
            normalize_exclusions([filename])
            if relative.is_absolute() or not filename or ".." in relative.parts:
                raise NAIAError("Evidence must be a relative file inside the project")
            if is_excluded(relative.as_posix(), self._exclusions(data)):
                raise NAIAError(f"Evidence is excluded from inspection: {filename}")
            for parent in [relative, *relative.parents]:
                if (self.root / parent).is_symlink():
                    raise NAIAError("Evidence cannot traverse symlinks")
            target = self.path(filename)
            if not target.is_file():
                raise NAIAError(f"Evidence file does not exist: {filename}")
            entry = {"path": relative.as_posix(), "line": int(line)}
            if entry not in evidence:
                evidence.append(entry)
        return evidence

    def propose(self, field, value, *, evidence=()):
        """Save the assistant's interpretation separately from user-approved answers."""
        if field not in {q["field"] for q in QUESTIONS}:
            raise NAIAError(f"Unknown onboarding field: {field}")
        if value in (None, "", {}, []):
            raise NAIAError("A proposal needs a nonempty value")
        with locked(self.directory / "state/locks/context.lock"):
            data = self.load()
            proposal = {"value": copy.deepcopy(value), "evidence": self._evidence(evidence, data),
                        "status": "pending", "proposed_at": now()}
            data.setdefault("proposals", {})[field] = proposal
            data["revision"] += 1
            write_json(self.context_path, data)
        return proposal

    def accept_proposal(self, field, actor):
        if field not in {q["field"] for q in QUESTIONS}:
            raise NAIAError(f"Unknown onboarding field: {field}")
        if not isinstance(actor, str) or not actor.strip():
            raise NAIAError("Confirmation requires a named user")
        with locked(self.directory / "state/locks/context.lock"):
            data = self.load()
            proposal = data.get("proposals", {}).get(field)
            if not proposal or proposal.get("status") != "pending":
                answer = data["answers"][field]
                if answer["confirmed"] or answer["value"] in (None, "", {}, []):
                    raise NAIAError(f"No pending proposal for {field}")
                proposal = {"value": answer["value"], "evidence": answer.get("evidence", []),
                            "status": "pending"}
            for source in proposal.get("evidence", []):
                self._evidence([f"{source['path']}:{source['line']}"], data)
            accepted_at = now()
            data["answers"][field] = {"value": copy.deepcopy(proposal["value"]), "confirmed": True,
                                      "evidence": proposal.get("evidence", []), "confirmed_by": actor,
                                      "updated_at": accepted_at}
            data.setdefault("proposals", {})[field] = {**proposal, "status": "accepted",
                                                       "accepted_by": actor, "accepted_at": accepted_at}
            data["revision"] += 1
            data["onboarding"] = {"status": "pending", "confirmed_by": None}
            write_json(self.context_path, data)
        return data

    def configure_assistant(self, choice):
        if not isinstance(choice, str) or choice not in ASSISTANTS:
            raise NAIAError("Choose assistant codex, claude, or both")
        files = list(ASSISTANTS[choice])
        with locked(self.directory / "state/locks/context.lock"):
            data = self.load()
            current = data.get("assistants", {})
            changed = current.get("selection") != choice or current.get("instruction_files") != files
            missing = set(POLICY) - set(data.get("policies", {}))
            prospective = {**current, "selection": choice, "instruction_files": files}
            if changed or missing:
                if changed:
                    prospective["configured_at"] = now()
                for key in missing:
                    data.setdefault("policies", {})[key] = copy.deepcopy(POLICY[key])
                data["assistants"] = prospective
                data["revision"] += 1
            # Render the prospective choice; preserve any confirmed role assignment.
            results = self._install_instructions(files, prospective,
                                                context_data=data if changed or missing else None)
        return {"selection": choice, "instruction_files": files, "files": results,
                "warnings": self.assistant_warnings(),
                "role_question": role_question(prospective),
                "assistant_action": "Read the installed instruction files now. If both assistants are selected and assistant_roles is unanswered, ask about an optional role split; do not assume a lead. Start a new assistant session if needed for instruction discovery."}

    def configure_roles(self, *, preset=None, assignments=None, actor=None):
        candidate = role_record(preset=preset, assignments=assignments, actor=actor)
        with locked(self.directory / "state/locks/context.lock"):
            data = self.load()
            state = data.get("assistants", {})
            if state.get("selection") != "both":
                raise NAIAError("Assistant roles require both Codex and Claude to be selected")
            old_roles = state.get("roles")
            changed = (not isinstance(old_roles, dict)
                       or any(old_roles.get(key) != value for key, value in candidate.items()))
            roles = {**candidate, "confirmed_at": now()} if changed else old_roles
            prospective = {**state, "roles": roles}
            if changed:
                data["assistants"] = prospective
                data["revision"] += 1
            results = self._install_instructions(list(ASSISTANTS["both"]), prospective,
                                                context_data=data if changed else None)
        return {"roles": copy.deepcopy(roles), "files": results,
                "assistant_action": "Read each assistant's updated role section. Shared project approvals still apply; roles do not invoke agents."}

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
            proposal = data.get("proposals", {}).get(field)
            if proposal and proposal.get("status") == "pending":
                proposal.update(status="superseded", superseded_at=now())
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
        with locked(self.directory / "state/locks/context.lock"):
            state = self.load().get("assistants", {})
            return self._install_instructions(filenames, state)

    def _install_instructions(self, filenames, assistant_state, *, context_data=None):
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
                existed = path.exists()
                original = path.read_bytes().decode("utf-8") if existed else ""
                block = (INSTRUCTIONS_BEGIN + "\n## NAIA workflow\n\n" + ASSISTANT_RULES
                         + role_section(filename, assistant_state) + INSTRUCTIONS_END + "\n")
                present = [(begin, end) for begin, end in pairs if begin in original or end in original]
                if len(present) > 1:
                    raise NAIAError(f"Inspect mixed instruction markers in {filename} before updating")
                if present:
                    begin, end = present[0]
                    if original.count(begin) != 1 or original.count(end) != 1 or original.index(begin) > original.index(end):
                        raise NAIAError(f"Inspect malformed instruction markers in {filename} before updating")
                    start = original.index(begin)
                    stop = original.index(end) + len(end)
                    updated = original[:start] + block.rstrip("\n") + original[stop:]
                else:
                    updated = original + ("\n" if original and not original.endswith("\n\n") else "") + block
                plans.append((filename, path, original, updated, existed))
            results, written = [], []
            try:
                for filename, path, original, updated, existed in plans:
                    changed = original != updated
                    if changed:
                        atomic_text(path, updated)
                        written.append((path, original, existed))
                    results.append({"file": filename, "changed": changed})
                if context_data is not None:
                    write_json(self.context_path, context_data)
            except BaseException:
                for path, original, existed in reversed(written):
                    if existed:
                        atomic_text(path, original)
                    else:
                        path.unlink(missing_ok=True)
                raise
        return results
