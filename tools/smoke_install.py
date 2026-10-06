"""Check installed distributions outside the source tree; no GPU or scheduler."""
from importlib import metadata
from importlib.resources import files
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
    if installed.metadata.get("License-Expression") != "MIT":
        raise RuntimeError("Missing MIT metadata")
    if installed.requires:
        raise RuntimeError("NAIA installation must not require PyTorch or other external packages")
    licenses = [item for item in installed.files or []
                if str(item).endswith(".dist-info/licenses/LICENSE")]
    if len(licenses) != 1 or "Copyright (c) 2026 Nazir Nayal" not in installed.locate_file(licenses[0]).read_text():
        raise RuntimeError("Missing packaged MIT license")
    for package, script in (("naia", "app.js"), ("naia_arch", "viewer.js")):
        for asset in ("index.html", "style.css", script):
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
                                     "nodes": [{"id": "model", "parent": None}],
                                     "edges": [], "events": []}))
        result = json.loads(run("arch", "validate", str(graph)).stdout)
        if result != {"valid": True, "nodes": 1}:
            raise RuntimeError("Unified architecture validation failed")
        if (root / ".lab").exists():
            raise RuntimeError("Standalone validation unexpectedly initialized a project")
        subprocess.run([str(commands["naia-arch"]), "validate", str(graph)], cwd=root,
                       env=environment, check=True, capture_output=True, text=True)
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
    print("Unified installation, MIT licensing, assets, command/import aliases, architecture viewing, onboarding, auto-evaluation, and reuse: OK")


if __name__ == "__main__":
    main()
