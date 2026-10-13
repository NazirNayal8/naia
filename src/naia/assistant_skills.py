"""Explicit installation of the portable onboarding skill, without project setup."""
from __future__ import annotations

import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import sys

from .context import ASSISTANTS
from .storage import NAIAError, atomic_text


SKILL_NAME = "naia-setup"


def _targets(assistant):
    home = Path.home()
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude").expanduser()
    roots = {"codex": home / ".agents", "claude": claude}
    selected = ("codex", "claude") if assistant == "both" else (assistant,)
    return [(name, (roots[name] / "skills" / SKILL_NAME).absolute()) for name in selected]


def _plan(directory, content, metadata):
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise NAIAError(f"Inspect existing skill path before installing: {directory}")
    skill, record = directory / "SKILL.md", directory / "installation.json"
    for path in (skill, record):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise NAIAError(f"Inspect existing skill file before installing: {path}")
    try:
        previous = {path: path.read_text(encoding="utf-8") if path.exists() else None
                    for path in (skill, record)}
    except UnicodeError as exc:
        raise NAIAError(f"Existing {directory} is not a UTF-8 skill; it was not overwritten") from exc
    if any(value is not None for value in previous.values()):
        try:
            old = json.loads(previous[record] or "null")
        except ValueError:
            old = None
        if (not isinstance(old, dict) or old.get("schema_version") != 1
                or old.get("package") != "naia" or old.get("skill") != SKILL_NAME
                or previous[skill] is None
                or old.get("sha256") != hashlib.sha256(previous[skill].encode()).hexdigest()):
            raise NAIAError(f"Existing {directory} is custom or modified; it was not overwritten")
    elif directory.exists() and any(directory.iterdir()):
        raise NAIAError(f"Existing {directory} is not a NAIA-managed skill; it was not overwritten")
    wanted = {skill: content, record: metadata}
    return previous, wanted


def install_setup_skill(assistant):
    if assistant not in ASSISTANTS:
        raise NAIAError("Choose assistant codex, claude, or both")
    content = files("naia").joinpath("skills", SKILL_NAME, "SKILL.md").read_text(encoding="utf-8")
    metadata = json.dumps({"schema_version": 1, "package": "naia", "skill": SKILL_NAME,
                           "sha256": hashlib.sha256(content.encode()).hexdigest(),
                           "python": str(Path(sys.executable).absolute())}, indent=2) + "\n"
    targets = _targets(assistant)
    # Preflight both integrations before changing either one.
    plans = {directory: _plan(directory, content, metadata) for _, directory in targets}
    written = []
    try:
        for previous, wanted in plans.values():
            for path, text in wanted.items():
                if previous[path] != text:
                    atomic_text(path, text)
                    written.append((path, previous[path]))
    except BaseException:
        for path, original in reversed(written):
            if original is None:
                path.unlink(missing_ok=True)
            else:
                atomic_text(path, original)
        raise
    return {"skill": SKILL_NAME,
            "files": [{"assistant": name, "path": str(directory / "SKILL.md"),
                       "changed": plans[directory][0] != plans[directory][1]}
                      for name, directory in targets],
            "assistant_action": "Start a new assistant session if the skill is not visible. Ask to set up NAIA here, or invoke $naia-setup in Codex / /naia-setup in Claude Code. No project was initialized."}
