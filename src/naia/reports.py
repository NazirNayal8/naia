"""Read-only, bounded discovery and serving of self-contained project reports.

This module intentionally uses only the standard library so the project-local
NAIA interface can use the same implementation. ``directory`` is a directory
inside ``root``; ``excluded`` receives project-relative POSIX paths.

``limits`` accepts positive integer overrides of these exact keys:
meta_bytes (64 KiB), html_bytes (2 MiB), asset_bytes (16 MiB), report_bytes
(64 MiB), files (512), reports (500), cache_bytes (8 MiB), cache_entries (128).
The cache stores validated metadata and static prose, never executable objects.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from functools import wraps
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import posixpath
import re
import stat
from threading import RLock
from typing import Callable, Iterable
from urllib.parse import unquote, urlsplit


class ReportError(ValueError):
    """A report or requested report path does not satisfy the contract."""


DEFAULT_LIMITS = {
    "meta_bytes": 64 * 1024,
    "html_bytes": 2 * 1024 * 1024,
    "asset_bytes": 16 * 1024 * 1024,
    "report_bytes": 64 * 1024 * 1024,
    "files": 512,
    "reports": 500,
    "cache_bytes": 8 * 1024 * 1024,
    "cache_entries": 128,
}

_ID = re.compile(r"^[A-Z0-9_]+$")
KIT_JS_ROUTE = "/reports/_kit/naia_report_kit.js"
KIT_CSS_ROUTE = "/reports/_kit/naia_report_kit.css"
EDITOR_JS_ROUTE = "/reports/_kit/naia_report_editor.js"
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_MIMES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".avif": "image/avif",
    ".ico": "image/x-icon", ".svg": "image/svg+xml; charset=utf-8",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
    ".otf": "font/otf",
}
_SENSITIVE = re.compile(
    r"(?:^|[._-])(?:credentials?|secrets?|passwords?|passwd|tokens?|keys?|"
    r"api[._-]?keys?|private[._-]?keys?|secret[._-]?keys?|client[._-]?secrets?|"
    r"service[._-]?account|id_rsa|id_ed25519|auth|oauth|kubeconfig|checkpoints?)(?:$|[._-])", re.I
)
_CSS_URL = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s)]*))\s*\)", re.I)
_CSS_IMPORT = re.compile(r"@import\s+(?:\"([^\"]*)\"|'([^']*)')", re.I)
_CSS_FAMILY = re.compile(r"font-family\s*:\s*([^;}]+)", re.I)
_CSS_VARIABLE = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;}]+)")
_CSS_VAR_USE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,\s*([^()]+))?\)")
_FALLBACK = re.compile(r"(?:^|[\s,])(?:system-ui|-apple-system|sans-serif|serif|monospace)(?:$|[\s,])", re.I)
_SKIP = {"script", "style", "svg", "template"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def valid_id(value: str) -> str:
    """Validate a report identifier without touching the filesystem."""
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ReportError("Invalid report ID; use uppercase letters, digits and underscores")
    return value


def _font_fallback(styles: list[tuple[str, str]]) -> bool:
    variables = {match.group(1): match.group(2) for _, css in styles for match in _CSS_VARIABLE.finditer(css)}
    for _, css in styles:
        for match in _CSS_FAMILY.finditer(css):
            family = match.group(1)
            if len(family) > 8192:
                continue
            for _ in range(16):
                substituted = _CSS_VAR_USE.sub(lambda m: variables.get(m.group(1), m.group(2) or "")[:8193], family)
                if len(substituted) > 8192:
                    family = ""
                    break
                if substituted == family:
                    break
                family = substituted
            if _FALLBACK.search(family):
                return True
    return False


def _locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


def report_csp(origin: str | None = None, report_route: str | None = None) -> str:
    """Return the CSP for report assets, including standalone HTML/SVG.

    Opaque sandbox origins cannot use ``'self'`` to load sibling resources.
    Servers may pass their trusted HTTP(S) origin and ``/reports/<ID>/`` route
    to permit that report's files. The origin must come from server configuration,
    never an unchecked Host header. Network APIs and frame navigation stay closed.
    """
    source = "'self'"
    kit_script = kit_style = ""
    if origin is not None or report_route is not None:
        if not isinstance(origin, str) or not isinstance(report_route, str):
            raise ReportError("CSP requires both a trusted origin and report route")
        try:
            parsed = urlsplit(origin)
            parsed.port
        except ValueError as exc:
            raise ReportError("Invalid report CSP origin") from exc
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or not re.fullmatch(r"[A-Za-z0-9.\-\[\]:]+", parsed.netloc)
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or any(c in origin for c in "\r\n; \t")):
            raise ReportError("Invalid report CSP origin")
        if (not report_route.startswith("/") or not report_route.endswith("/")
                or not re.fullmatch(r"/[A-Za-z0-9_/-]+/", report_route)
                or any(c in report_route for c in "\r\n; \t?#%\\")
                or any(p in {".", ".."} for p in report_route.split("/"))):
            raise ReportError("Invalid report CSP route")
        source = origin.rstrip("/") + report_route
        kit_script = " " + origin.rstrip("/") + KIT_JS_ROUTE + " " + origin.rstrip("/") + EDITOR_JS_ROUTE
        kit_style = " " + origin.rstrip("/") + KIT_CSS_ROUTE
    return (
        "sandbox allow-scripts allow-popups; default-src 'none'; "
        f"script-src 'unsafe-inline' {source}{kit_script}; "
        f"style-src 'unsafe-inline' {source}{kit_style}; "
        f"img-src data: {source}; font-src data: {source}; "
        f"media-src data: {source}; connect-src 'none'; frame-src 'none'; "
        "object-src 'none'; base-uri 'none'; form-action 'none'; worker-src 'none'"
    )


class _HTML(HTMLParser):
    """Collect static body prose, exact title, CSS and resource references."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.body: list[str] = []
        self.titles: list[list[str]] = []
        self.css: list[str] = []
        self.resources: list[tuple[str, str]] = []
        self.bad: list[str] = []
        self.body_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {k.lower(): v or "" for k, v in attrs}
        skipped = any(t in _SKIP for t in self.stack)
        if tag == "body":
            self.body_count += 1
        if tag == "title" and not skipped:
            self.titles.append([])
        if tag == "base" and attr.get("href"):
            self.bad.append("base href is not allowed")
        if tag == "meta" and attr.get("http-equiv", "").casefold() == "refresh":
            self.bad.append("meta refresh is not allowed")
        if tag == "script" and attr.get("src") and attr.get("type", "").strip().lower() == "module":
            self.bad.append("External module scripts are unsupported in the opaque report sandbox; use classic scripts")
        if attr.get("style"):
            self.css.append(attr["style"])
        for name in ("src", "poster", "data", "xlink:href"):
            if name in attr and tag not in {"a"}:
                self.resources.append((attr[name], "resource"))
        if tag in {"image", "use"} and "href" in attr:
            self.resources.append((attr["href"], "resource"))
        if "srcset" in attr:
            # A comma also occurs inside data URLs. They are self-contained;
            # reject a mixture with a remote entry rather than misparse it.
            value = attr["srcset"]
            if value.lstrip().lower().startswith("data:"):
                if re.search(r"(?:https?:)?//", value, re.I):
                    self.bad.append("remote srcset resource is not allowed")
            else:
                for candidate in value.split(","):
                    bits = candidate.strip().split()
                    if bits:
                        self.resources.append((bits[0], "resource"))
        if tag == "link" and attr.get("href"):
            rel = set(attr.get("rel", "").lower().split())
            if "stylesheet" in rel:
                self.resources.append((attr["href"], "stylesheet"))
            elif rel & {"preconnect", "dns-prefetch"}:
                self.resources.append((attr["href"], "font_hint"))
            elif rel & {"icon", "preload", "modulepreload", "manifest"}:
                self.resources.append((attr["href"], "resource"))
        if tag not in _VOID:
            self.stack.append(tag)
        if "body" in self.stack and not skipped and tag not in _SKIP:
            self.body.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.stack:
            # Recover conservatively from unclosed tags: skipped content stays
            # skipped until its own closing tag, as in ordinary report markup.
            i = len(self.stack) - 1 - self.stack[::-1].index(tag)
            del self.stack[i:]
        if "body" in self.stack and not any(t in _SKIP for t in self.stack):
            self.body.append(" ")

    def handle_data(self, value: str) -> None:
        if "title" in self.stack and self.titles and not any(t in _SKIP for t in self.stack):
            self.titles[-1].append(value)
        if "style" in self.stack:
            self.css.append(value)
        if "body" in self.stack and not any(t in _SKIP for t in self.stack):
            self.body.append(value)


@dataclass
class _Record:
    signature: tuple
    meta: dict
    body: str
    warnings: tuple[str, ...]
    cost: int


class Reports:
    """A read-only report registry. No metadata source path is ever opened."""

    def __init__(self, root: str | Path, directory: str | Path, *,
                 excluded: Callable[[str], bool] | None = None,
                 limits: dict[str, int] | None = None) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ReportError("Project root is not a directory")
        configured = Path(directory)
        self.directory = Path(os.path.abspath(configured if configured.is_absolute() else self.root / configured))
        try:
            self._relative_directory = self.directory.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise ReportError("Reports directory must be inside the project") from exc
        if self.directory == self.root:
            raise ReportError("Reports directory must be a dedicated project subdirectory")
        # The configured report location may deliberately be .lab/reports.
        # This exception applies only to its exact ancestor components, never
        # to hidden files or hidden subdirectories inside a report.
        self._configured_parts = self.directory.relative_to(self.root).parts
        self.excluded = excluded
        self.limits = dict(DEFAULT_LIMITS)
        if limits is not None and not isinstance(limits, dict):
            raise ReportError("Report limits must be a mapping")
        for key, value in (limits or {}).items():
            if key not in DEFAULT_LIMITS or type(value) is not int or value <= 0:
                raise ReportError(f"Invalid report limit: {key}")
            self.limits[key] = value
        self._cache: OrderedDict[str, _Record] = OrderedDict()
        self._cache_size = 0
        self._lock = RLock()
        self._safe_path(self.directory, missing=True)

    def _safe_path(self, path: Path, *, within: Path | None = None, missing: bool = False) -> None:
        """Reject forbidden components and symlinks before following anything."""
        try:
            relative = path.relative_to(self.root)
            if within is not None:
                path.relative_to(within)
        except ValueError as exc:
            raise ReportError("Report path is outside its permitted directory") from exc
        current = self.root
        for position, component in enumerate(relative.parts):
            configured_prefix = relative.parts[:position + 1] == self._configured_parts[:position + 1]
            if (component in {"", ".", ".."} or component.startswith(".")
                    and not configured_prefix
                    or "\\" in component or "%" in component
                    or _SENSITIVE.search(component)):
                raise ReportError("Hidden or sensitive report path is not allowed")
            current = current / component
            rel = current.relative_to(self.root).as_posix()
            if self.excluded is not None:
                try:
                    forbidden = self.excluded(rel)
                except Exception as exc:
                    raise ReportError("Report exclusion check failed") from exc
                if forbidden:
                    raise ReportError("Report path is excluded from project access")
            try:
                info = current.lstat()
            except FileNotFoundError:
                if missing:
                    continue
                raise ReportError("Report file does not exist") from None
            except OSError as exc:
                raise ReportError("Report path is unavailable") from exc
            if stat.S_ISLNK(info.st_mode):
                raise ReportError("Symlinks are not allowed in reports")
        # This second containment check detects a changed ancestor as well.
        try:
            resolved = path.resolve(strict=not missing)
            resolved.relative_to(self.root)
            if within is not None:
                resolved.relative_to(within)
        except (ValueError, OSError, RuntimeError) as exc:
            raise ReportError("Report path escapes its permitted directory") from exc

    @staticmethod
    def _id(report_id: str) -> str:
        return valid_id(report_id)

    def _discover(self) -> tuple[list[str], list[str]]:
        self._safe_path(self.directory, missing=True)
        if not self.directory.exists():
            self._cache.clear()
            self._cache_size = 0
            return [], []
        if not self.directory.is_dir():
            raise ReportError("Reports directory is not a directory")
        ids: list[str] = []
        warnings: list[str] = []
        try:
            with os.scandir(self.directory) as entries:
                entries_count = 0
                for entry in entries:
                    entries_count += 1
                    if entries_count > self.limits["reports"]:
                        warnings.append(f"Report discovery limited to {self.limits['reports']} directory entries")
                        break
                    if entry.name.startswith(".") or _SENSITIVE.search(entry.name):
                        continue
                    if self.excluded is not None:
                        try:
                            if self.excluded((self.directory / entry.name).relative_to(self.root).as_posix()):
                                continue
                        except Exception as exc:
                            raise ReportError("Report exclusion check failed") from exc
                    if entry.is_dir(follow_symlinks=False) or entry.is_symlink():
                        if len(ids) >= self.limits["reports"]:
                            warnings.append(f"Report discovery limited to {self.limits['reports']} reports")
                            break
                        ids.append(entry.name)
        except OSError as exc:
            raise ReportError("Reports directory is unavailable") from exc
        ids.sort()
        existing = set(ids)
        for key in list(self._cache):
            if key not in existing:
                self._cache_size -= self._cache.pop(key).cost
        return ids, warnings

    def _inventory(self, report_id: str) -> tuple[Path, dict[str, tuple], tuple]:
        folder = self.directory / self._id(report_id)
        self._safe_path(folder, within=self.directory)
        if not folder.is_dir():
            raise ReportError("Report directory does not exist")
        files: dict[str, tuple] = {}
        total = 0
        pending = [folder]
        entries_count = 0
        while pending:
            parent = pending.pop()
            self._safe_path(parent, within=folder)
            try:
                with os.scandir(parent) as entries:
                    for entry in entries:
                        entries_count += 1
                        if entries_count > self.limits["files"]:
                            raise ReportError(f"Report exceeds {self.limits['files']} file/directory entries")
                        path = Path(entry.path)
                        self._safe_path(path, within=folder)
                        info = path.lstat()
                        if stat.S_ISDIR(info.st_mode):
                            pending.append(path)
                            continue
                        if not stat.S_ISREG(info.st_mode):
                            raise ReportError("Report contains a non-regular file")
                        extension = path.suffix.lower()
                        if extension not in _MIMES:
                            raise ReportError(f"Unsupported report file type: {extension or '(none)'}")
                        rel = path.relative_to(folder).as_posix()
                        limit = self.limits["meta_bytes"] if rel == "meta.json" else (
                            self.limits["html_bytes"] if extension == ".html" else self.limits["asset_bytes"])
                        if info.st_size > limit:
                            raise ReportError(f"Report file exceeds byte limit: {rel}")
                        total += info.st_size
                        if total > self.limits["report_bytes"]:
                            raise ReportError(f"Report exceeds {self.limits['report_bytes']} bytes")
                        files[rel] = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            except ReportError:
                raise
            except OSError as exc:
                raise ReportError("Report inventory is unavailable") from exc
        if "meta.json" not in files or "index.html" not in files:
            raise ReportError("Report requires meta.json and index.html")
        return folder, files, tuple(sorted(files.items()))

    def _read(self, path: Path, limit: int, *, within: Path) -> bytes:
        self._safe_path(path, within=within)
        descriptor = None
        directory_descriptor = None
        try:
            if (hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
                    and os.open in os.supports_dir_fd):
                # Opening each component relative to an already-open parent
                # prevents ancestor symlink swaps from redirecting this read.
                directory_descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                parts = path.relative_to(self.root).parts
                for component in parts[:-1]:
                    child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                    dir_fd=directory_descriptor)
                    os.close(directory_descriptor)
                    directory_descriptor = child
                descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
                                     dir_fd=directory_descriptor)
            else:
                # Unsupported platforms retain explicit component symlink and
                # containment checks before and after the ordinary file open.
                self._safe_path(path, within=within)
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ReportError("Report file is not regular or exceeds its byte limit")
            self._safe_path(path, within=within)
            current = path.lstat()
            if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
                raise ReportError("Report file changed during access")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = None
                content = handle.read(limit + 1)
            if len(content) > limit:
                raise ReportError("Report file exceeds its byte limit")
            return content
        except ReportError:
            raise
        except OSError as exc:
            raise ReportError("Report file is unavailable") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if directory_descriptor is not None:
                os.close(directory_descriptor)

    def _text(self, path: Path, limit: int, *, within: Path) -> str:
        try:
            return self._read(path, limit, within=within).decode("utf-8")
        except UnicodeError as exc:
            raise ReportError("Report text must be UTF-8") from exc

    def _meta(self, raw: str, report_id: str) -> dict:
        def pairs(items: list[tuple[str, object]]) -> dict:
            result = {}
            for key, value in items:
                if key in result:
                    raise ReportError("Duplicate metadata field")
                result[key] = value
            return result
        try:
            meta = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda x: (_ for _ in ()).throw(ReportError("Invalid metadata number")))
        except (ValueError, RecursionError) as exc:
            raise ReportError(f"Invalid meta.json: {exc}") from exc
        if not isinstance(meta, dict):
            raise ReportError("Report metadata must be an object")
        for key in ("id", "title", "date", "summary"):
            if not isinstance(meta.get(key), str) or not meta[key].strip():
                raise ReportError(f"Report metadata requires non-empty {key}")
        if meta["id"] != report_id or not _ID.fullmatch(meta["id"]):
            raise ReportError("Metadata ID must equal the uppercase report directory ID")
        try:
            if not _DATE.fullmatch(meta["date"]):
                raise ValueError
            date.fromisoformat(meta["date"])
        except ValueError as exc:
            raise ReportError("Report date must be a real YYYY-MM-DD date") from exc
        if "schema_version" in meta and (type(meta["schema_version"]) is not int or meta["schema_version"] != 1):
            raise ReportError("Unsupported report schema_version; expected 1")
        for key in ("tags", "suites", "naia_tasks", "sources"):
            if key in meta and (not isinstance(meta[key], list)
                    or any(not isinstance(item, str) or not item.strip() for item in meta[key])):
                raise ReportError(f"Report metadata {key} must be a list of non-empty strings")
        for source in meta.get("sources", []):
            # Validate declarations without reading source files. The same
            # project exclusions apply to these metadata references.
            relative = self._relative_file(source.rstrip("/"))
            self._safe_path(self.root / relative, missing=True)
        return meta

    @staticmethod
    def _relative_file(relative: str) -> str:
        if (not isinstance(relative, str) or not relative or relative.startswith("/")
                or "\\" in relative or "%" in relative or "\x00" in relative
                or any(part in {"", ".", ".."} for part in relative.split("/"))):
            raise ReportError("Invalid relative report path")
        return relative

    def _resource(self, raw: str, kind: str, *, report_id: str, base: str,
                  files: dict[str, tuple], warnings: list[str], font_fallback: bool) -> None:
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            return
        if any(c in raw for c in "\x00\r\n\\"):
            raise ReportError("Invalid report resource URL")
        if ((raw in {KIT_JS_ROUTE, EDITOR_JS_ROUTE} and kind == "resource")
                or (raw == KIT_CSS_ROUTE and kind == "stylesheet")):
            # Trusted packaged assets only; this is not a general shared-file route.
            return
        try:
            parsed = urlsplit(raw)
        except ValueError as exc:
            raise ReportError("Invalid report resource URL") from exc
        if parsed.scheme.lower() == "data":
            if kind not in {"resource", "font"}:
                raise ReportError("Unsupported embedded stylesheet")
            return
        if parsed.scheme or parsed.netloc:
            try:
                host = (parsed.hostname or "").lower()
                port = parsed.port
            except ValueError as exc:
                raise ReportError("Invalid report resource URL") from exc
            optional_font = (
                parsed.scheme == "https" and not parsed.username and not parsed.password
                and port in {None, 443} and font_fallback
                and ((kind == "stylesheet" and host == "fonts.googleapis.com" and parsed.path in {"/css", "/css2"})
                     or (kind == "font" and host == "fonts.gstatic.com")
                     or (kind == "font_hint" and host in {"fonts.googleapis.com", "fonts.gstatic.com"}))
            )
            if optional_font:
                message = "Optional external web fonts require network access; system font fallback is available"
                if message not in warnings:
                    warnings.append(message)
                return
            raise ReportError("Required remote report resource is not allowed")
        decoded = unquote(parsed.path)
        if "%" in decoded or "\\" in decoded or "\x00" in decoded:
            raise ReportError("Invalid encoded report resource path")
        if decoded.startswith("/"):
            prefix = f"/reports/{report_id}/"
            if not decoded.startswith(prefix):
                raise ReportError("Report resource is outside this report")
            local = decoded[len(prefix):]
        else:
            local = posixpath.normpath(posixpath.join(posixpath.dirname(base), decoded))
        local = self._relative_file(local)
        if local not in files:
            raise ReportError(f"Report resource does not exist: {local}")

    def _css(self, css: str, *, report_id: str, base: str, files: dict[str, tuple],
             warnings: list[str], font_fallback: bool) -> None:
        # CSS escapes/comments can disguise URLs. Remove comments and reject
        # escaped resource syntax rather than interpreting arbitrary CSS.
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        if "\\" in css and re.search(r"(?:url|import|font-face)", css, re.I):
            raise ReportError("Escaped CSS resource declarations are not supported")
        for match in _CSS_URL.finditer(css):
            raw = next(value for value in match.groups() if value is not None)
            # Distinguish a stylesheet import from a font-face source. Other
            # URLs remain required resources even if the file also has fonts.
            prefix = css[:match.start()]
            block_start = prefix.rfind("{")
            declaration_start = max(prefix.rfind(";"), block_start)
            if re.search(r"@import\s*$", prefix, re.I):
                kind = "stylesheet"
            elif (re.search(r"@font-face\s*$", prefix[:block_start], re.I)
                    and re.match(r"\s*src\s*:", prefix[declaration_start + 1:], re.I)):
                kind = "font"
            else:
                kind = "resource"
            self._resource(raw, kind, report_id=report_id, base=base, files=files,
                           warnings=warnings, font_fallback=font_fallback)
        for match in _CSS_IMPORT.finditer(css):
            raw = next(value for value in match.groups() if value is not None)
            self._resource(raw, "stylesheet", report_id=report_id, base=base, files=files,
                           warnings=warnings, font_fallback=font_fallback)

    def _load(self, report_id: str) -> _Record:
        folder, files, signature = self._inventory(report_id)
        cached = self._cache.get(report_id)
        if cached is not None and cached.signature == signature:
            self._cache.move_to_end(report_id)
            return cached
        if cached is not None:
            self._cache_size -= self._cache.pop(report_id).cost
        meta = self._meta(self._text(folder / "meta.json", self.limits["meta_bytes"], within=folder), report_id)
        parsed: list[tuple[str, _HTML]] = []
        styles: list[tuple[str, str]] = []
        for relative in files:
            extension = Path(relative).suffix.lower()
            if extension in {".html", ".svg"}:
                parser = _HTML()
                parser.feed(self._text(folder / relative, self.limits["html_bytes"] if extension == ".html" else self.limits["asset_bytes"], within=folder))
                parser.close()
                parsed.append((relative, parser))
                styles.extend((relative, css) for css in parser.css)
            elif extension == ".css":
                styles.append((relative, self._text(folder / relative, self.limits["asset_bytes"], within=folder)))
        index = next(parser for relative, parser in parsed if relative == "index.html")
        if len(index.titles) != 1 or "".join(index.titles[0]) != meta["title"]:
            raise ReportError("HTML title must exactly equal metadata title")
        if index.body_count != 1:
            raise ReportError("Report index.html requires one body element")
        fallback = _font_fallback(styles)
        warnings: list[str] = []
        for relative, parser in parsed:
            if parser.bad:
                raise ReportError(parser.bad[0])
            for raw, kind in parser.resources:
                self._resource(raw, kind, report_id=report_id, base=relative, files=files,
                               warnings=warnings, font_fallback=fallback)
        for relative, css in styles:
            self._css(css, report_id=report_id, base=relative, files=files,
                      warnings=warnings, font_fallback=fallback)
        body = " ".join("".join(index.body).split())
        cost = (len(body.encode("utf-8"))
                + len(json.dumps(meta, ensure_ascii=False).encode("utf-8"))
                + sum(len(relative.encode("utf-8")) + 128 for relative in files)
                + sum(len(warning.encode("utf-8")) for warning in warnings))
        record = _Record(signature, meta, body, tuple(warnings), cost)
        if cost <= self.limits["cache_bytes"]:
            while self._cache and (len(self._cache) >= self.limits["cache_entries"]
                    or self._cache_size + cost > self.limits["cache_bytes"]):
                _, old = self._cache.popitem(last=False)
                self._cache_size -= old.cost
            self._cache[report_id] = record
            self._cache_size += cost
        return record

    @_locked
    def get(self, report_id: str) -> dict:
        """Return an independent copy of metadata after full report validation."""
        return json.loads(json.dumps(self._load(report_id).meta))

    @_locked
    def asset(self, report_id: str, relative: str) -> tuple[bytes, str]:
        """Serve only an allowed regular file in a fully validated report."""
        self._id(report_id)
        relative = self._relative_file(relative)
        if relative == "meta.json":
            raise ReportError("Report metadata is available only through the reports API")
        record = self._load(report_id)
        del record
        folder = self.directory / report_id
        path = folder / relative
        self._safe_path(path, within=folder)
        extension = path.suffix.lower()
        if extension not in _MIMES:
            raise ReportError("Unsupported report file type")
        limit = self.limits["meta_bytes"] if relative == "meta.json" else (
            self.limits["html_bytes"] if extension == ".html" else self.limits["asset_bytes"])
        return self._read(path, limit, within=folder), _MIMES[extension]

    def match_path(self, project_relative: str | Path) -> tuple[str, str] | None:
        """Identify paths needing the report guard on a generic asset route.

        This is deliberately lexical: malformed IDs or filenames still match
        and must be rejected by ``asset`` rather than exposed by a fallback.
        """
        value = str(project_relative).replace(os.sep, "/")
        prefix = self._relative_directory + "/"
        if not value.startswith(prefix):
            return None
        tail = value[len(prefix):]
        report_id, separator, relative = tail.partition("/")
        return report_id, relative if separator else ""

    @_locked
    def check(self, report_id: str | None = None) -> dict:
        """Validate one or all reports; individual failures are isolated."""
        if report_id is None:
            try:
                ids, warnings = self._discover()
            except ReportError as exc:
                return {"valid": False, "reports": [], "warnings": [str(exc)]}
        else:
            ids, warnings = [report_id], []
        reports = []
        for candidate in ids:
            row = {"id": candidate, "valid": True}
            try:
                record = self._load(candidate)
                if record.warnings:
                    row["warnings"] = list(record.warnings)
            except (ReportError, OSError, ValueError, RecursionError) as exc:
                row.update(valid=False, error=str(exc))
            reports.append(row)
        return {"valid": not warnings and all(row["valid"] for row in reports),
                "reports": reports, "warnings": warnings}

    @staticmethod
    def _snippet(body: str, words: list[str]) -> list[dict]:
        if not body:
            return []
        # Use case-insensitive regex on the original text so Unicode casefold
        # expansions cannot shift indices used to slice the displayed snippet.
        expression = re.compile("|".join(re.escape(word) for word in sorted(set(words), key=len, reverse=True)), re.I) if words else None
        first = expression.search(body) if expression else None
        start = max(0, first.start() - 60) if first else 0
        end = min(len(body), start + 160)
        if start:
            next_space = body.find(" ", start, min(start + 20, end))
            if next_space >= 0:
                start = next_space + 1
        text = body[start:end]
        segments: list[dict] = []
        if start:
            segments.append({"text": "…", "hit": False})
        position = 0
        for match in expression.finditer(text) if expression else ():
            if match.start() > position:
                segments.append({"text": text[position:match.start()], "hit": False})
            segments.append({"text": match.group(), "hit": True})
            position = match.end()
        if position < len(text):
            segments.append({"text": text[position:], "hit": False})
        if end < len(body):
            segments.append({"text": "…", "hit": False})
        return segments

    @_locked
    def search(self, query: str = "", tags: Iterable[str] = ()) -> dict:
        """Search static prose with AND terms and tags; return safe snippets."""
        if not isinstance(query, str):
            raise ReportError("Report query must be a string")
        if len(query.encode("utf-8")) > 8192:
            raise ReportError("Report query is too long")
        if isinstance(tags, str):
            tags = (tags,)
        selected = []
        for tag in tags:
            if len(selected) >= 128:
                raise ReportError("Too many report tag filters")
            selected.append(tag)
        if any(not isinstance(tag, str) or len(tag) > 1024 for tag in selected):
            raise ReportError("Report tags must be strings")
        words = list(dict.fromkeys(query.casefold().split()))
        wanted = {tag.casefold() for tag in selected}
        try:
            ids, warnings = self._discover()
        except ReportError as exc:
            return {"reports": [], "tags": [], "warnings": [str(exc)]}
        results = []
        available: set[str] = set()
        for report_id in ids:
            body = ""
            try:
                record = self._load(report_id)
                meta = json.loads(json.dumps(record.meta))
                body = record.body
                warnings.extend(f"{report_id}: {warning}" for warning in record.warnings)
            except (ReportError, OSError, ValueError, RecursionError) as exc:
                meta = {"id": report_id, "title": report_id, "date": "", "summary": "", "tags": [], "error": str(exc)}
            report_tags = meta.get("tags", [])
            available.update(report_tags)
            if not wanted.issubset({tag.casefold() for tag in report_tags}):
                continue
            haystacks = ((meta["title"].casefold(), 8),
                         (" ".join(report_tags).casefold(), 4),
                         (meta["summary"].casefold(), 2), (body.casefold(), 1))
            score = 0
            for word in words:
                matches = sum(weight for haystack, weight in haystacks if word in haystack)
                if not matches:
                    break
                score += matches
            else:
                meta["snippet"] = self._snippet(body, words)
                results.append((score, meta))
        results.sort(key=lambda row: (-row[0], -date.fromisoformat(row[1]["date"]).toordinal() if row[1]["date"] else 0, row[1]["id"]))
        return {"reports": [meta for _, meta in results],
                "tags": sorted(available, key=lambda value: (value.casefold(), value)),
                "warnings": list(dict.fromkeys(warnings))}
