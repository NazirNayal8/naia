"""Check installed distributions outside the source tree; no GPU or scheduler."""
from importlib import metadata
from importlib.resources import files
from html import unescape
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import naia
import naia_arch
import research_workbench
import workbench_arch


def main():
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    executable_directory = Path(sys.executable).parent
    commands = {name: executable_directory / (name + (".exe" if os.name == "nt" else ""))
                for name in ("naia", "lab", "naia-arch", "lab-arch")}
    installed = metadata.distribution("naia")
    print(f"naia {installed.version}")
    if any(package.__version__ != installed.version
           for package in (naia, naia_arch, research_workbench, workbench_arch)):
        raise RuntimeError("Package versions do not match the installed distribution")
    if installed.metadata.get("License-Expression") != "MIT":
        raise RuntimeError("Missing MIT metadata")
    if installed.requires:
        raise RuntimeError("NAIA installation must not require PyTorch or other external packages")
    licenses = [item for item in installed.files or []
                if str(item).endswith(".dist-info/licenses/LICENSE")]
    if len(licenses) != 1 or "Copyright (c) 2026 Nazir Nayal" not in installed.locate_file(licenses[0]).read_text():
        raise RuntimeError("Missing packaged MIT license")
    for package, script in (("naia", "app.js"), ("naia_arch", "viewer.js")):
        extra = ('blocks.js',) if package == 'naia_arch' else ('reports.js', 'reports.css', 'reports_viewer.js', 'report_kit.js', 'report_editor.js')
        for asset in ("index.html", "style.css", script, *extra):
            if not files(package).joinpath("assets", asset).is_file():
                raise RuntimeError(f"Missing installed asset: {package}/{asset}")
    if "torch" in sys.modules:
        raise RuntimeError("Package import must not load PyTorch")
    if workbench_arch.capture is not naia_arch.capture:
        raise RuntimeError("Legacy architecture import is incompatible")
    from naia.context import Project
    from research_workbench.context import Project as LegacyProject
    if LegacyProject is not Project:
        raise RuntimeError("Legacy workflow import is incompatible")

    with tempfile.TemporaryDirectory(prefix="naia-installed-") as directory:
        root = Path(directory)

        def run(*arguments):
            return subprocess.run([str(commands["naia"]), *arguments], cwd=root, env=environment,
                                  check=True, capture_output=True, text=True)

        for command in commands.values():
            subprocess.run([str(command), "--help"], cwd=root, env=environment,
                           check=True, capture_output=True, text=True)
        graph = root / "graph.json"
        graph.write_text(json.dumps({"schema_version": 1,
                                     "nodes": [{"id": "model", "parent": None, "kind": "module"}],
                                     "edges": [], "events": []}))
        result = json.loads(run("arch", "validate", str(graph)).stdout)
        if result != {"valid": True, "nodes": 1}:
            raise RuntimeError("Unified architecture validation failed")
        if (root / ".lab").exists():
            raise RuntimeError("Standalone validation unexpectedly initialized a project")
        subprocess.run([str(commands["naia-arch"]), "validate", str(graph)], cwd=root,
                       env=environment, check=True, capture_output=True, text=True)
        named_graph = root / "named-graph.json"
        semantics = {"model": {"name": "Dynamics model", "role": "predictor",
                               "evidence": ["Installed smoke fixture explicitly defines the model role"]}}
        original = graph.read_bytes()
        run("arch", "annotate", str(graph), "--semantics", json.dumps(semantics),
            "--output", str(named_graph))
        if (json.loads(named_graph.read_text())["nodes"][0]["semantic"] != semantics["model"]
                or graph.read_bytes() != original or (root / ".lab").exists()):
            raise RuntimeError("Standalone semantic annotation changed captured evidence or initialized a project")
        run("arch", "validate", str(named_graph))
        onboarding = root / "onboarding"
        initialized = json.loads(run("--project", str(onboarding), "init", "--assistant", "both").stdout)
        role_questions = [question for question in initialized["questions"]
                          if question["field"] == "assistant_roles"]
        if len(role_questions) != 1 or not role_questions[0]["optional"]:
            raise RuntimeError("Dual-assistant onboarding is missing the optional role question")
        for filename in ("AGENTS.md", "CLAUDE.md"):
            text = (onboarding / filename).read_text()
            if text.count("<!-- naia:instructions -->") != 1:
                raise RuntimeError(f"Instruction contract missing from {filename}")
        run("--project", str(onboarding), "instructions", "roles", "--preset", "codex-lead",
            "--by", "smoke-user")
        for filename, role in (("AGENTS.md", "You are Codex: Lead."),
                               ("CLAUDE.md", "You are Claude: Support.")):
            if role not in (onboarding / filename).read_text():
                raise RuntimeError(f"Assistant-specific role missing from {filename}")
        project = root / "demo"
        run("--project", str(project), "demo")
        report = project / ".lab/reports/DEMO_REPORT"
        report.mkdir(parents=True)
        (report / "meta.json").write_text(json.dumps({"id": "DEMO_REPORT", "title": "Demo report",
            "date": "2026-10-07", "summary": "Installed report smoke test", "tags": ["smoke"]}))
        (report / "index.html").write_text("<!doctype html><html><head><title>Demo report</title></head>"
            "<body>Installed report search works.</body></html>")
        checked = json.loads(run("--project", str(project), "report", "check", "DEMO_REPORT").stdout)
        found = json.loads(run("--project", str(project), "report", "list", "--query", "search", "--tag", "smoke").stdout)
        if not checked["valid"] or [item["id"] for item in found["reports"]] != ["DEMO_REPORT"]:
            raise RuntimeError("Installed report discovery, validation, or search failed")
        run("--project", str(project), "report", "new", "KIT_DRAFT", "--title", "Kit draft")
        draft = json.loads(run("--project", str(project), "report", "check", "KIT_DRAFT").stdout)
        from naia.reports import Reports
        from naia.report_editing import ReportEditor
        editor = ReportEditor(Reports(project, ".lab/reports"))
        snapshot = editor.snapshot("KIT_DRAFT")
        if not snapshot["editable"]:
            raise RuntimeError("Installed report draft has no text editor")
        saved = editor.save("KIT_DRAFT", snapshot["revision"], {"finding": "Installed text editor works."})
        if not (project / saved["backup"]).is_file() or saved["revision"] == snapshot["revision"]:
            raise RuntimeError("Installed text editor or recovery backup failed")
        if not saved.get("layout"):
            raise RuntimeError("Installed draft has no section editor")
        layout = {"orders": {"report": ["followup", "findings"]}, "hidden": ["findings"],
                  "add": [{"id": "followup", "container": "report", "title": "Follow-up",
                           "text": "First line.\nSecond line."}]}
        arranged = editor.save("KIT_DRAFT", saved["revision"], {}, layout=layout)
        if arranged["layout"]["containers"][0]["order"] != ["followup", "findings"]:
            raise RuntimeError("Installed section editor did not persist its layout")
        exported = json.loads(run("--project", str(project), "report", "export", "KIT_DRAFT",
                                 "--out", "exports/kit-draft.html").stdout)
        standalone = Path(exported["path"]).read_text()
        if (not draft["valid"] or '/reports/_kit/' in standalone
                or 'window.NAIAReport' not in standalone or "connect-src 'none'" not in unescape(standalone)
                or "Installed text editor works." not in standalone or "First line.\nSecond line." not in standalone
                or '[data-naia-section][hidden]{display:none!important}' not in standalone):
            raise RuntimeError("Installed report scaffolding or offline export failed")
        run("--project", str(project), "suite", "launch", "DEMO")
        run("--project", str(project), "sync")
        registry = json.loads((project / ".lab/state/registry.json").read_text())
        if not registry["suites"][0]["results_ready"]:
            raise RuntimeError("Demo evaluations did not sync")
        attempts = list((project / ".lab/state/runs").glob("*/*/*/record.json"))
        run("--project", str(project), "suite", "launch", "DEMO")
        if len(list((project / ".lab/state/runs").glob("*/*/*/record.json"))) != len(attempts):
            raise RuntimeError("Completed runs were duplicated")
        queue = json.loads((project / ".lab/tasks.json").read_text())
        if set(queue["items"]) != {"REVIEW-DEMO"}:
            raise RuntimeError("Expected one automatic review task")
        saved_graph = project / "architecture.json"
        saved_graph.write_text(graph.read_text())
        run("--project", str(project), "arch", "add", "DEMO-MODEL",
            "--graph", str(saved_graph), "--title", "Demo model",
            "--suite", "DEMO", "--task", "REVIEW-DEMO")
        architectures = json.loads(run("--project", str(project), "arch", "list").stdout)
        if (len(architectures) != 1 or architectures[0]["id"] != "DEMO-MODEL"
                or architectures[0]["suite"] != "DEMO"
                or architectures[0]["task"] != "REVIEW-DEMO"
                or not architectures[0]["available"]):
            raise RuntimeError("Project architecture did not link to its suite and review task")
    print("Unified installation, MIT licensing, assets, command/import aliases, reports, architecture annotation/viewing, onboarding, auto-evaluation, and reuse: OK")


if __name__ == "__main__":
    main()
