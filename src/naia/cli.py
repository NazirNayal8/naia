"""Stable assistant-neutral commands. Outputs are JSON except the policy contract."""
from __future__ import annotations

import argparse
import json
import sys

from .context import ASSISTANTS, POLICY_TEXT, ROLE_PRESETS, Project
from .execution import launch, reconcile, run_stage
from .storage import NAIAError, read_json
from .suites import Suites, import_analysis
from .tasks import Tasks
from .reports import ReportError
from .report_authoring import AuthoringError, new_report, export_report


def parser():
    p = argparse.ArgumentParser(prog="naia", description="NAIA (Nazir's AI Assistant): local-first research workflow (development alpha)")
    p.add_argument("--project", help="Project root; otherwise discover .lab in ancestors")
    p.add_argument("--reports-root", help="Project-relative report directory (default: .lab/reports)")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--assistant", choices=ASSISTANTS, help="Install NAIA rules for Codex, Claude, or both")
    init.add_argument("--exclude", action="append", default=[], help="Do not inspect this relative path or glob (repeatable)")
    init.add_argument("--no-scan", action="store_true", help="Skip initial repository discovery")
    sub.add_parser("doctor")
    sub.add_parser("policy")
    sub.add_parser("sync")
    sub.add_parser("demo")
    reports = sub.add_parser("report", help="Find and validate existing HTML reports").add_subparsers(dest="report_action", required=True)
    listing = reports.add_parser("list")
    listing.add_argument("--query", default="")
    listing.add_argument("--tag", action="append", default=[])
    check = reports.add_parser("check")
    check.add_argument("id", nargs="?")
    new = reports.add_parser("new", help="Create a report draft without overwriting existing work")
    new.add_argument("id")
    new.add_argument("--title", required=True)
    new.add_argument("--summary", default="Report draft.")
    export = reports.add_parser("export", help="Bundle a report into one offline HTML file")
    export.add_argument("id")
    export.add_argument("--out", required=True)
    arch = sub.add_parser("arch", aliases=["lens"], help="Capture, view, and link model architectures")
    from naia_arch.cli import add_graph_commands
    arch_commands = add_graph_commands(arch)
    add = arch_commands.add_parser("add", help="Register saved architecture evidence in this project")
    add.add_argument("id")
    add.add_argument("--graph", required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--suite")
    add.add_argument("--task")
    arch_commands.add_parser("list", help="List registered project architectures")
    context = sub.add_parser("context").add_subparsers(dest="context_action", required=True)
    context.add_parser("show")
    context.add_parser("questions")
    scan = context.add_parser("scan", help="Refresh bounded repository evidence for assistant-led onboarding")
    scan.add_argument("--exclude", action="append", default=[])
    proposal = context.add_parser("propose", help="Record an inferred setting for user confirmation")
    proposal.add_argument("field")
    proposal.add_argument("--value", required=True, help="JSON value, or @path/to/JSON")
    proposal.add_argument("--evidence", action="append", required=True, help="Relative file[:line] supporting the proposal")
    accept = context.add_parser("accept", help="Accept a proposed setting after user confirmation")
    accept.add_argument("field")
    accept.add_argument("--by", required=True)
    answer = context.add_parser("set")
    answer.add_argument("field")
    answer.add_argument("--value", required=True, help="JSON value, or @path/to/JSON")
    answer.add_argument("--confirmed", action="store_true", help="User explicitly confirmed this answer")
    confirm = context.add_parser("confirm")
    confirm.add_argument("--by", required=True)
    backend = context.add_parser("backend")
    backend.add_argument("id")
    backend.add_argument("--file", required=True)
    backend.add_argument("--confirmed", action="store_true")
    instructions = sub.add_parser("instructions").add_subparsers(dest="instructions_action", required=True)
    install = instructions.add_parser("install")
    # Validate filenames in dispatch: older argparse versions reject an empty
    # nargs='*' positional when choices are supplied (including --assistant).
    install.add_argument("files", nargs="*", metavar="INSTRUCTION_FILE", help="AGENTS.md and/or CLAUDE.md (legacy explicit files)")
    install.add_argument("--assistant", choices=ASSISTANTS, help="Configure a named assistant integration")
    roles = instructions.add_parser("roles", help="Record user-confirmed assistant roles and refresh both instruction files")
    source = roles.add_mutually_exclusive_group(required=True)
    source.add_argument("--preset", choices=ROLE_PRESETS)
    source.add_argument("--file", help="JSON codex/claude roles, responsibilities and boundaries")
    roles.add_argument("--by", required=True, help="User who explicitly confirmed the role arrangement")
    tasks = sub.add_parser("task").add_subparsers(dest="task_action", required=True)
    tasks.add_parser("list")
    tasks.add_parser("next")
    add = tasks.add_parser("add")
    add.add_argument("id")
    add.add_argument("--title", required=True)
    add.add_argument("--goal", required=True)
    add.add_argument("--decision", required=True)
    add.add_argument("--owner", default="unassigned")
    add.add_argument("--depends-on", action="append", default=[])
    add.add_argument("--material", action="append", default=[])
    add.add_argument("--top", action="store_true")
    for action in ("start", "pause", "resume", "done", "cancel", "move-top", "assign"):
        task = tasks.add_parser(action)
        task.add_argument("id")
        task.add_argument("--note", default="")
        if action == "assign":
            task.add_argument("--owner", required=True)
    suites = sub.add_parser("suite").add_subparsers(dest="suite_action", required=True)
    add = suites.add_parser("add")
    add.add_argument("file")
    add.add_argument("--approved-by", required=True)
    seal = suites.add_parser("seal")
    seal.add_argument("id")
    seal.add_argument("--by", required=True)
    for action in ("validate", "show", "launch", "evaluate"):
        suite = suites.add_parser(action)
        suite.add_argument("id")
        if action in ("launch", "evaluate"):
            suite.add_argument("--backend", default="local")
            suite.add_argument("--dry-run", action="store_true")
            suite.add_argument("--retry", action="store_true")
            suite.add_argument("--cell")
            suite.add_argument("--profile")
            suite.add_argument("--no-auto-eval", action="store_true")
    analysis = sub.add_parser("analysis").add_subparsers(dest="analysis_action", required=True)
    add = analysis.add_parser("add")
    add.add_argument("file")
    add.add_argument("--approved-by", required=True)
    ui = sub.add_parser("ui")
    ui.add_argument("--port", type=int, default=8767)
    worker = sub.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("record")
    worker.add_argument("--profile")
    return p


def dispatch(args):
    project = Project.discover(args.project)
    if args.command == "policy":
        print(POLICY_TEXT, end="")
        return None
    if args.command == "init":
        context = project.initialize(args.assistant, excluded_paths=args.exclude, scan=not args.no_scan)
        return {"project": str(project.root), "context": str(project.context_path),
                "onboarding": context["onboarding"],
                "assistants": context.get("assistants", {"selection": None, "instruction_files": []}),
                "warnings": project.assistant_warnings(),
                "discovery": context.get("discovery"),
                "questions": project.questions(),
                "assistant_action": "If needed, ask Codex, Claude, or both and configure that integration. Read existing instructions and respect inspection exclusions. For an existing project, use discovery evidence to infer goal, training, evaluation, configuration, and hardware; record proposals with file references and show one concise summary for confirmation or correction. Do not ask the user to describe settings already established by files or confirmed context. Ask only about missing, uncertain, or conflicting details. For a new project, ask the unresolved setup questions. Discovery never confirms assumptions or authorizes launches; confirm settings and the execution backend before launching."}
    if args.command == "demo":
        from .demo import install
        return install(project)
    project.load()
    if args.command == "report":
        reports = project.reports(args.reports_root)
        if args.report_action == "list":
            return reports.search(args.query, args.tag)
        if args.report_action == "check":
            return reports.check(args.id)
        if args.report_action == "new":
            return new_report(reports, args.id, args.title, summary=args.summary)
        from importlib.resources import files
        from .reports import KIT_JS_ROUTE, KIT_CSS_ROUTE
        assets = {}
        for route, filename in ((KIT_JS_ROUTE, "report_kit.js"), (KIT_CSS_ROUTE, "report_kit.css")):
            asset = files("naia").joinpath("assets", filename)
            if asset.is_file():
                assets[route] = asset.read_bytes()
        return export_report(reports, args.id, args.out, kit_assets=assets)
    if args.command in ("arch", "lens"):
        from .architectures import Architectures
        registry = Architectures(project)
        if args.action == "list":
            return registry.list()
        return registry.add(args.id, args.graph, args.title, suite=args.suite, task=args.task)
    if args.command == "context":
        if args.context_action == "show":
            return project.context_view()
        if args.context_action == "questions":
            return project.questions()
        if args.context_action == "scan":
            return project.scan(excluded_paths=args.exclude)
        if args.context_action == "propose":
            value = read_json(args.value[1:]) if args.value.startswith("@") else json.loads(args.value)
            return project.propose(args.field, value, evidence=args.evidence)
        if args.context_action == "accept":
            return project.accept_proposal(args.field, args.by)
        if args.context_action == "set":
            value = read_json(args.value[1:]) if args.value.startswith("@") else json.loads(args.value)
            return project.answer(args.field, value, confirmed=args.confirmed)
        if args.context_action == "backend":
            return project.configure_backend(args.id, read_json(args.file), confirmed=args.confirmed)
        return project.confirm(args.by)
    if args.command == "instructions":
        if args.instructions_action == "roles":
            return project.configure_roles(preset=args.preset,
                                           assignments=read_json(args.file) if args.file else None,
                                           actor=args.by)
        if args.assistant and args.files:
            raise NAIAError("Use --assistant or instruction filenames, not both")
        if args.assistant:
            return project.configure_assistant(args.assistant)
        if args.files:
            selected = next((key for key, files in ASSISTANTS.items() if set(files) == set(args.files)), None)
            if selected is None or len(set(args.files)) != len(args.files):
                raise NAIAError("Choose distinct AGENTS.md and/or CLAUDE.md instruction files")
            return project.configure_assistant(selected)
        selected = project.load().get("assistants", {}).get("selection")
        if not selected:
            raise NAIAError("Choose --assistant codex, claude, or both")
        return project.configure_assistant(selected)
    if args.command == "doctor":
        return project.doctor()
    if args.command == "task":
        tasks = Tasks(project)
        if args.task_action == "list":
            return tasks.load()
        if args.task_action == "next":
            return tasks.next()
        if args.task_action == "add":
            return tasks.add(args.id, args.title, args.goal, args.decision, owner=args.owner,
                             dependencies=args.depends_on, materials=args.material, top=args.top)
        return tasks.action(args.id, args.task_action, note=args.note, owner=getattr(args, "owner", None))
    if args.command == "suite":
        suites = Suites(project)
        if args.suite_action == "add":
            return suites.add(read_json(args.file), args.approved_by)
        if args.suite_action == "seal":
            return suites.seal(args.id, args.by)
        if args.suite_action in ("show", "validate"):
            data = suites.load(args.id)
            if args.suite_action == "validate":
                return {"valid": True, "suite": data["id"], "rows_reserved": len(data["cells"]) * len(data["evaluation"])}
            return data
        return launch(project, args.id, backend=args.backend, dry_run=args.dry_run,
                      auto_eval=not args.no_auto_eval, retry=args.retry, cell_id=args.cell,
                      evaluate_only=args.suite_action == "evaluate", evaluation_id=args.profile)
    if args.command == "analysis":
        return import_analysis(project, read_json(args.file), args.approved_by)
    if args.command == "sync":
        suites = Suites(project)
        for suite in suites.definitions():
            for cell in suite["cells"]:
                record = suites.pointer(suite["id"], cell["id"])
                if record:
                    reconcile(project, record["record_path"])
        return suites.sync()
    if args.command == "_worker":
        return run_stage(project, args.record, "eval-" + args.profile if args.profile else "train", args.profile)
    if args.command == "ui":
        from .ui import serve
        serve(project, args.port, reports_root=args.reports_root)
        return None
    raise NAIAError("Unknown command")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command in ("arch", "lens") and args.action in ("capture", "annotate", "view", "validate"):
            from naia_arch.cli import dispatch as graph_command
            return graph_command(args)
        result = dispatch(args)
        if result is not None:
            print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        if args.command == "report" and args.report_action == "check" and not result["valid"]:
            return 1
        return 1 if isinstance(result, dict) and result.get("ok") is False else 0
    except (NAIAError, ReportError, AuthoringError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
