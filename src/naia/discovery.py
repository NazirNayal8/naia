"""Bounded static project evidence for onboarding; nothing is executed or confirmed."""
from __future__ import annotations

import codecs
from contextlib import contextmanager
import fnmatch
from functools import lru_cache
import ntpath
import os
from pathlib import Path, PurePosixPath
import re
import stat

from .storage import NAIAError


MAX_DEPTH = 6
MAX_FILES = 256
MAX_ENTRIES = 4096
MAX_DIRECTORY_ENTRIES = 256
MAX_SOURCE_BYTES = 16 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
MAX_SOURCES = 48
MAX_EXCERPT_BYTES = 24 * 1024
MAX_EXCERPT_LENGTH = 360

_ROOTS = frozenset("docs doc documentation scripts script bin tools config configs conf configuration settings src train training eval evaluation experiments launchers jobs cluster slurm examples recipes".split())
_SKIP_DIRS = frozenset("data datasets dataset logs log checkpoints checkpoint ckpts ckpt weights artifacts outputs output runs results result env envs venv venvs node_modules vendor vendors third_party external build dist target site-packages __pycache__ cache caches wandb tensorboard mlruns assets media generated".split())
_METADATA = frozenset("pyproject.toml setup.cfg setup.py requirements.txt requirements-dev.txt environment.yml environment.yaml conda.yml conda.yaml pipfile pixi.toml package.json cargo.toml go.mod pom.xml build.gradle build.gradle.kts project.toml cmakelists.txt makefile gnumakefile justfile dockerfile docker-compose.yml compose.yml compose.yaml tox.ini".split())
_INSTRUCTIONS = frozenset(("agents.md", "agents.override.md", "claude.md", "contributing.md"))
_DOC_NAMES = frozenset("training evaluation quickstart getting-started usage setup installation project overview configuration hardware cluster slurm running experiments".split())
_SCRIPT_EXTENSIONS = frozenset((".py", ".sh", ".bash", ".sbatch", ".slurm", ".pbs", ".r", ".jl", ".js", ".ts"))
_CONFIG_EXTENSIONS = frozenset((".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".py"))
_TRAIN = re.compile(r"(?:^|[_.-])(?:train(?:ing|er)?|fit|finetune|fine_tune)(?:$|[_.-])", re.I)
_EVAL = re.compile(r"(?:^|[_.-])(?:eval(?:uate|uation)?|validate|validation|benchmark|score)(?:$|[_.-])", re.I)
_SENSITIVE = re.compile(r"(?:^|[_.-])(?:secrets?|credentials?|passwords?|passwd|tokens?|keys?|api[_-]?keys?|private[_-]?keys?|secret[_-]?keys?|client[_-]?secrets?|service[_-]?account|id_rsa|id_ed25519|auth|oauth|kubeconfig)(?:$|[_.-])", re.I)
_CREDENTIAL = re.compile(r"\b(?:api[_ -]?(?:key|token)|access[_ -]?(?:key|token)|auth[_ -]?(?:key|token)|client[_ -]?secret|private[_ -]?key|secret[_ -]?key|password|passwd|pwd|secrets?|tokens?|credentials?|authorization)\b[\"']?\s*[:=]", re.I)
_SECRET_VALUE = re.compile(r"\bBearer\s+\S+|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\b(?:gh[pousr]_|github_pat_|glpat-|sk-)[A-Za-z0-9_-]{12,}|\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@|-----BEGIN (?:\w+ )?PRIVATE KEY-----", re.I)
_MARKER = re.compile(r"<!--\s*(/?)\s*(?:naia|research-workbench|lab):instructions\s*-->")
_REDACTED = "[redacted credential-like line]"
_TOPICS = {
    "project": re.compile(r"\b(?:goal|scope|objective|project|research|overview|success criterion)\b", re.I),
    "hardware": re.compile(r"\b(?:slurm|sbatch|srun|gpu|cuda|nvidia|vram|cpu|memory|conda|venv|environment|partition|gres)\b", re.I),
    "execution": re.compile(r"\b(?:train|training|trainer|fit|resume|checkpoint|python|bash|launch|command|torchrun|accelerate|deepspeed)\b", re.I),
    "evaluation": re.compile(r"\b(?:eval|evaluate|evaluation|validation|metric|metrics|accuracy|loss|reward|episode|episodes|seed|seeds|split|splits|benchmark)\b", re.I),
    "configuration": re.compile(r"\b(?:hydra|omegaconf|argparse|config|configuration|yaml|toml|json|defaults|_target_)\b", re.I),
}


def normalize_exclusions(excluded_paths):
    """Validate relative POSIX paths/globs without touching the filesystem."""
    if isinstance(excluded_paths, (str, bytes)) or excluded_paths is None:
        raise NAIAError("Exclusions must be a list of relative paths or globs")
    try:
        values = list(excluded_paths)
    except TypeError as exc:
        raise NAIAError("Exclusions must be a list of relative paths or globs") from exc
    result = []
    for value in values:
        if (not isinstance(value, str) or not value.strip() or value.startswith("/")
                or ntpath.splitdrive(value)[0] or "\\" in value
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise NAIAError("Exclusions must be safe relative POSIX paths or globs")
        parts = value.rstrip("/").split("/")
        if any(part in (".", "..") for part in parts):
            raise NAIAError("Exclusions cannot contain . or .. path components")
        normalized = "/".join(part for part in parts if part)
        if not normalized:
            raise NAIAError("An exclusion cannot be empty")
        if normalized not in result:
            result.append(normalized)
    return result


@lru_cache(maxsize=128)
def _path_glob(pattern):
    parts = pattern.split("/")
    pieces = []
    for index, part in enumerate(parts):
        if part == "**":
            pieces.append(".*" if index == len(parts) - 1 else "(?:.*/)?")
        else:
            # fnmatch translates bracket expressions and ordinary wildcards safely.
            pieces.append(fnmatch.translate(part)[4:-3])
            if index != len(parts) - 1:
                pieces.append("/")
    return re.compile("(?s:" + "".join(pieces) + ")\\Z")


def is_excluded(relative_path, patterns):
    """Match paths/ancestors; ** includes zero levels and basename globs recur."""
    parts = PurePosixPath(str(relative_path)).parts
    prefixes = ["/".join(parts[:index]) for index in range(1, len(parts) + 1)]
    for pattern in patterns:
        if "/" not in pattern:
            if any(fnmatch.fnmatchcase(part, pattern) for part in parts):
                return True
        elif any(_path_glob(pattern).fullmatch(prefix) for prefix in prefixes):
            return True
    return False


def _kind(relative):
    path = PurePosixPath(relative)
    name, suffix = path.name.lower(), path.suffix.lower()
    parents = {part.lower() for part in path.parts[:-1]}
    if name.startswith(".") or _SENSITIVE.search(name) or suffix in (".pem", ".key", ".p12", ".pfx", ".jks"):
        return None
    if name in _INSTRUCTIONS:
        return "instructions"
    if name == "readme" or (name.startswith("readme.") and suffix in (".md", ".rst", ".txt", ".adoc")):
        return "project"
    if name in _METADATA:
        return "metadata"
    if parents.intersection(("config", "configs", "conf", "configuration", "settings")) and suffix in _CONFIG_EXTENSIONS:
        return "configuration"
    if suffix in _SCRIPT_EXTENSIONS and (_TRAIN.search(path.stem) or _EVAL.search(path.stem)
            or path.stem.lower() in ("main", "run", "launch", "submit")
            or suffix in (".sbatch", ".slurm", ".pbs")
            or (parents.intersection(("scripts", "script", "bin", "launchers", "jobs", "cluster", "slurm")) and suffix in (".sh", ".bash"))):
        return "script"
    if suffix in (".md", ".rst", ".txt", ".adoc") and path.stem.lower() in _DOC_NAMES:
        return "project"
    return None


@contextmanager
def _directory(root_fd, parts):
    """Anchor reads to the root descriptor and refuse symlinks at every component."""
    descriptor = os.dup(root_fd)
    try:
        for part in parts:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def _read(root_fd, relative, limit):
    parts = PurePosixPath(relative).parts
    with _directory(root_fd, parts[:-1]) as directory:
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                return b"", False
            content = os.read(descriptor, limit)
            return content, info.st_size > len(content)
        finally:
            os.close(descriptor)


def _clean_lines(text):
    """Keep line numbers while hiding managed instructions and likely credentials."""
    result, managed, private_key, credential_indent, quoted_secret = [], False, False, None, None
    for line in text.splitlines():
        markers = list(_MARKER.finditer(line))
        if markers:
            managed = not bool(markers[-1].group(1))
            result.append("")
            continue
        if managed:
            result.append("")
            continue
        if quoted_secret:
            result.append(_REDACTED)
            if quoted_secret in line:
                quoted_secret = None
            continue
        indent = len(line) - len(line.lstrip())
        continuation = credential_indent is not None and (not line.strip() or indent > credential_indent)
        if credential_indent is not None and not continuation and line.strip():
            # JSON can put a field's string value on an unindented following line.
            continuation = bool(re.match(r"\s*[\"']", line) and not re.match(r"\s*[\"'][^\"']+[\"']\s*:", line))
        if not continuation:
            credential_indent = None
        if private_key or continuation or _CREDENTIAL.search(line) or _SECRET_VALUE.search(line):
            result.append(_REDACTED)
            if "BEGIN" in line and "PRIVATE KEY" in line:
                private_key = True
            if "END" in line and "PRIVATE KEY" in line:
                private_key = False
            if _CREDENTIAL.search(line):
                for quote in ('\"\"\"', "'''"):
                    if line.count(quote) % 2:
                        quoted_secret = quote
                if re.search(r"[:=]\s*(?:[|>][+-]?)?\s*$", line):
                    credential_indent = indent
        else:
            result.append(line)
    return result


def inspect_project(root, *, excluded_paths=()):
    """Return evidence and candidate settings, never confirmed onboarding answers.

    Only common project directories and relevant text filenames are inspected.
    Limits cover traversal, text reads, and returned excerpts; omissions are expected.
    POSIX descriptor-relative reads prevent following repository symlinks.
    """
    exclusions = normalize_exclusions(excluded_paths)
    root = Path(root).resolve()
    if not root.is_dir():
        raise NAIAError("Discovery root must be an existing directory")
    result = {"existing_project": False, "sources": [], "detected": {
        "training_candidates": [], "evaluation_candidates": [], "configuration": [], "scheduler": []},
        "excluded_paths": exclusions, "warnings": [], "truncated": False}
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        result.update(truncated=True, warnings=["Safe project inspection is unavailable on this platform"])
        return result
    counters = {"entries": 0, "files": 0, "bytes": 0, "excerpts": 0}

    def limited(reason):
        result["truncated"] = True
        if reason not in result["warnings"] and len(result["warnings"]) < 16:
            result["warnings"].append(reason)

    def add(field, value):
        if value not in result["detected"][field]:
            result["detected"][field].append(value)

    def inspect(relative):
        if counters["files"] >= MAX_FILES or counters["bytes"] >= MAX_TOTAL_BYTES:
            limited("Project file or total read limit reached")
            return
        kind = _kind(relative)
        if kind is None or is_excluded(relative, exclusions):
            return
        counters["files"] += 1
        try:
            raw, partial = _read(root_fd, relative, min(MAX_SOURCE_BYTES, MAX_TOTAL_BYTES - counters["bytes"]))
            counters["bytes"] += len(raw)
            if any(byte < 32 and byte not in (9, 10, 13) for byte in raw):
                return
            text = codecs.getincrementaldecoder("utf-8")().decode(raw, final=not partial)
        except (OSError, UnicodeError):
            limited(f"Skipped unreadable or non-text source: {relative}")
            return
        if partial:
            limited("Source text read limit reached; only file prefixes were inspected")
        lines = _clean_lines(text)
        meaningful = [index for index, line in enumerate(lines) if line.strip() and line != _REDACTED]
        if not meaningful:
            return
        result["existing_project"] = True
        clean = "\n".join(lines)
        stem, suffix = PurePosixPath(relative).stem, PurePosixPath(relative).suffix.lower()
        if kind == "script" and (_TRAIN.search(stem) or re.search(r"\b(?:def train|trainer\.fit|training_loop)\b", clean)):
            add("training_candidates", relative)
        if kind == "script" and (_EVAL.search(stem) or re.search(r"\b(?:def evaluate|def evaluation|def eval)\b", clean)):
            add("evaluation_candidates", relative)
        formats = {".toml": "toml", ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".ini": "ini", ".cfg": "ini", ".py": "python"}
        if kind in ("configuration", "metadata") and suffix in formats:
            add("configuration", formats[suffix])
        for label, pattern in (("hydra", r"\b(?:hydra-core|hydra\.main|import hydra|from hydra|_target_)\b"),
                               ("omegaconf", r"\b(?:import omegaconf|from omegaconf|OmegaConf\.)"),
                               ("argparse", r"\b(?:import argparse|from argparse|argparse\.ArgumentParser)\b")):
            if re.search(pattern, clean, re.I):
                add("configuration", label)
        if suffix in (".sbatch", ".slurm") or re.search(r"#SBATCH\b|\b(?:sbatch|srun)\b", clean):
            add("scheduler", "slurm")
        if suffix == ".pbs" or re.search(r"#PBS\b", clean):
            add("scheduler", "pbs")
        starts = [meaningful[0]] + [index for index in meaningful[1:]
                                   if any(pattern.search(lines[index]) for pattern in _TOPICS.values())]
        covered, count = set(), 0
        for index in starts:
            if index in covered:
                continue
            if count >= 4:
                break
            excerpt = "\n".join(lines[index:index + 3]).strip()[:MAX_EXCERPT_LENGTH]
            size = len(excerpt.encode("utf-8"))
            if len(result["sources"]) >= MAX_SOURCES or counters["excerpts"] + size > MAX_EXCERPT_BYTES:
                limited("Evidence excerpt limit reached")
                break
            topics = [topic for topic, pattern in _TOPICS.items() if pattern.search(excerpt)]
            defaults = {"instructions": ["project", "instructions"], "project": ["project"],
                        "metadata": ["configuration"], "configuration": ["configuration"], "script": ["execution"]}
            topics = list(dict.fromkeys(defaults[kind] + topics))
            result["sources"].append({"path": relative, "line": index + 1, "excerpt": excerpt, "topics": topics})
            counters["excerpts"] += size
            covered.update(range(index, index + 3))
            count += 1

    def walk(parts=()):
        if counters["entries"] >= MAX_ENTRIES:
            limited("Directory enumeration limit reached")
            return
        try:
            with _directory(root_fd, parts) as directory, os.scandir(directory) as entries:
                selected = []
                for index, entry in enumerate(entries):
                    if index >= MAX_DIRECTORY_ENTRIES or counters["entries"] >= MAX_ENTRIES:
                        limited("Directory enumeration limit reached")
                        break
                    counters["entries"] += 1
                    relative = "/".join((*parts, entry.name))
                    if entry.name.startswith(".") or is_excluded(relative, exclusions) or _SENSITIVE.search(entry.name):
                        continue
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.lower() in _SKIP_DIRS or (not parts and entry.name.lower() not in _ROOTS):
                            continue
                        if len(parts) >= MAX_DEPTH:
                            limited("Directory depth limit reached")
                            continue
                        selected.append((True, entry.name))
                    elif entry.is_file(follow_symlinks=False) and _kind(relative):
                        selected.append((False, entry.name))
            # Read root evidence and entry points before potentially large config trees.
            priority = {"scripts": 0, "script": 0, "train": 0, "training": 0,
                        "eval": 0, "evaluation": 0, "launchers": 0, "jobs": 0,
                        "docs": 1, "doc": 1, "documentation": 1, "src": 2,
                        "config": 4, "configs": 4, "conf": 4, "configuration": 4}
            ordered = sorted(selected, key=lambda item: (
                item[0], priority.get(item[1].lower(), 3) if item[0] else 0, item[1]))
            for directory, name in ordered:
                relative = "/".join((*parts, name))
                if directory:
                    walk((*parts, name))
                else:
                    inspect(relative)
        except OSError:
            limited("Skipped an unreadable project directory")

    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise NAIAError("Cannot open discovery root") from exc
    try:
        walk()
    finally:
        os.close(root_fd)
    for values in result["detected"].values():
        values.sort()
    return result
