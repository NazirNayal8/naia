"""Explicit installation of a synthetic, dependency-free example; not repo discovery."""
import sys

from .context import Project, QUESTIONS
from .storage import NAIAError, atomic_text
from .suites import Suites


WORKER = '''import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("stage", choices=["train", "eval"])
p.add_argument("--value", type=float)
p.add_argument("--artifact", required=True)
p.add_argument("--metrics")
a = p.parse_args()
artifact = Path(a.artifact)
if a.stage == "train":
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps({"value": a.value}))
else:
    value = json.loads(artifact.read_text())["value"]
    Path(a.metrics).write_text(json.dumps({"score": 1 / (1 + abs(value - 2))}))
'''


def install(project):
    if project.root.exists() and any(project.root.iterdir()):
        raise NAIAError("Demo requires a fresh project; never confirm or overwrite an existing project's context")
    project.initialize()
    for question in QUESTIONS:
        project.answer(question["field"], {"scope": "Synthetic CPU-only demo; no real research assumptions"}, confirmed=True)
    project.configure_backend("local", {"kind": "local", "command_python": sys.executable}, confirmed=True)
    project.confirm("demo-user")
    atomic_text(project.root / "demo_worker.py", WORKER)
    definition = {
        "schema_version": 1, "id": "DEMO", "title": "CPU workflow demonstration",
        "question": "Can declared cells run, evaluate, sync results, and queue one review?",
        "artifact": "model.json",
        "training": {"argv": ["{python}", "demo_worker.py", "train", "--value", "{value}", "--artifact", "{artifact}"]},
        "cells": [{"id": "value1", "parameters": {"value": 1}}, {"id": "value2", "parameters": {"value": 2}}],
        "evaluation": [{"id": "validation", "command": {"argv": ["{python}", "demo_worker.py", "eval", "--artifact", "{artifact}", "--metrics", "{metrics}"]},
                        "metrics": {"score": {"path": "score", "direction": "max"}}}],
    }
    Suites(project).add(definition, "demo-user")
    return {"project": str(project.root), "suite": "DEMO", "next": "naia suite launch DEMO"}
