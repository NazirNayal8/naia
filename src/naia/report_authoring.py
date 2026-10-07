"""Explicit, bounded report creation and offline export using the stdlib only.

All report reads use the validated library's ``asset`` method. Export never
fetches resources or executes JavaScript. Limits derive from library.limits:
report_bytes bounds unique input bytes, files bounds dependencies, and twice
report_bytes bounds output; dependency recursion is capped at 32 levels.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import date as calendar_date, datetime, timezone
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import posixpath
import re
import secrets
import stat
from urllib.parse import unquote, urlsplit


class AuthoringError(ValueError):
    """The requested creation or export cannot safely satisfy its contract."""


KIT_URL = "/reports/_kit/naia_report_kit.js"
KIT_CSS_URL = "/reports/_kit/naia_report_kit.css"
EDITOR_URL = "/reports/_kit/naia_report_editor.js"
OFFLINE_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data:; font-src data:; media-src data:; connect-src 'none'; "
    "frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; worker-src 'none'"
)
_ID = re.compile(r"^[A-Z0-9_]+$")
_SENSITIVE = re.compile(
    r"(?:^|[._-])(?:credentials?|secrets?|passwords?|passwd|tokens?|keys?|"
    r"api[._-]?keys?|private[._-]?keys?|secret[._-]?keys?|client[._-]?secrets?|"
    r"service[._-]?account|id_rsa|id_ed25519|auth|oauth|kubeconfig|checkpoints?)(?:$|[._-])", re.I
)
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_URL = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s)]*))\s*\)", re.I)
_IMPORT = re.compile(
    r"@import\s+(?:url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s)]*))\s*\)|\"([^\"]*)\"|'([^']*)')\s*([^;]*);", re.I
)
_NETWORK_JS = re.compile(r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource|Worker|SharedWorker|importScripts|import)\s*\(|\bnavigator\s*\.\s*sendBeacon\s*\(")


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise AuthoringError("Report ID must use uppercase letters, digits and underscores")
    return value


def _path(library, value, *, creating=False):
    root = Path(library.root).resolve()
    supplied = Path(value)
    if any(part in {".", ".."} for part in supplied.parts):
        raise AuthoringError("Output must use a direct project path")
    target = supplied if supplied.is_absolute() else root / supplied
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise AuthoringError("Output must be inside the project") from exc
    if not relative.parts:
        raise AuthoringError("The project root cannot be an output")
    configured = Path(library.directory).relative_to(root).parts
    current = root
    for index, part in enumerate(relative.parts):
        trusted_prefix = creating and relative.parts[:index + 1] == configured[:index + 1]
        if (part in {"", ".", ".."} or part.startswith(".") and not trusted_prefix
                or any(ord(char) < 32 or ord(char) == 127 or char in "\\%" for char in part)
                or _SENSITIVE.search(part)):
            raise AuthoringError("Hidden or sensitive output path is not allowed")
        current = current / part
        excluded = getattr(library, "excluded", None)
        if excluded is not None:
            try:
                denied = excluded(current.relative_to(root).as_posix())
            except Exception as exc:
                raise AuthoringError("Output exclusion check failed") from exc
            if denied:
                raise AuthoringError("Output path is excluded")
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise AuthoringError("Output path is unavailable") from exc
        if stat.S_ISLNK(info.st_mode):
            raise AuthoringError("Symlink output paths are not allowed")
    return target


@contextmanager
def _parent(library, target, *, creating=False):
    """Create safe parent directories, preserving a descriptor at every step."""
    target = _path(library, target, creating=creating)
    root = Path(library.root).resolve()
    parts = target.relative_to(root).parts
    descriptor = None
    try:
        if not (hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd):
            raise AuthoringError("Safe report writes require descriptor-relative filesystem support")
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in parts[:-1]:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(part, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield target, descriptor, parts[-1]
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write(descriptor, name, content):
    temporary = ".naia-report-" + secrets.token_hex(12) + ".tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=descriptor)
    identity = os.fstat(fd)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        # Hard-link publication is atomic and fails if any output already exists.
        os.link(temporary, name, src_dir_fd=descriptor, dst_dir_fd=descriptor, follow_symlinks=False)
    finally:
        try:
            current = os.stat(temporary, dir_fd=descriptor, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                os.unlink(temporary, dir_fd=descriptor)
        except OSError:
            pass


def new_report(library, report_id, title, *, summary="Report draft.", date=None, report_date=None):
    """Create one empty, valid kit-based draft; never replace an existing folder."""
    report_id = _identifier(report_id)
    if not isinstance(title, str) or not title.strip() or not isinstance(summary, str) or not summary.strip():
        raise AuthoringError("Report title and summary must be non-empty strings")
    if date is not None and report_date is not None:
        raise AuthoringError("Specify only one report date")
    day = date if date is not None else report_date
    day = day if day is not None else datetime.now(timezone.utc).date().isoformat()
    try:
        if not isinstance(day, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day):
            raise ValueError
        calendar_date.fromisoformat(day)
    except ValueError as exc:
        raise AuthoringError("Report date must be a real YYYY-MM-DD date") from exc
    meta = {"schema_version": 1, "id": report_id, "title": title, "date": day,
            "summary": summary, "tags": [], "suites": [], "naia_tasks": [], "sources": []}
    metadata = (json.dumps(meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    document = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>" + escape(title) + "</title><style>"
        ":root{color-scheme:dark;--bg:#111317;--ink:#f2f3f5}"
        ":root[data-theme=light]{color-scheme:light;--bg:#f6f7f9;--ink:#0f1419}"
        "body{background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,sans-serif;margin:0}"
        "main{max-width:68ch;margin:auto;padding:36px 24px}"
        "[data-naia-section][hidden]{display:none!important}section{margin:28px 0}"
        "</style></head><body><main><h1 data-naia-edit=\"heading\">" + escape(title) + "</h1>"
        "<p data-naia-edit=\"summary\">" + escape(summary) + "</p>"
        "<div data-naia-layout=\"report\"><section data-naia-section=\"findings\" data-naia-layout=\"findings\">"
        "<h2 data-naia-item=\"findings-title\" data-naia-edit=\"findings-title\">Findings</h2>"
        "<p data-naia-item=\"findings-text\" data-naia-edit=\"finding\">Add approved findings and their source tables here.</p>"
        "</section></div>"
        "</main><script id=\"report-data\" type=\"application/json\">{}</script>"
        "<script src=\"" + KIT_URL + "\"></script>"
        "<script>const R=NAIAReport.init({data:'#report-data',controls:{},series:{}});</script>"
        "<script src=\"" + EDITOR_URL + "\" defer></script>"
        "</body></html>\n").encode("utf-8")
    limits = getattr(library, "limits", {})
    if len(metadata) > limits.get("meta_bytes", 65536) or len(document) > limits.get("html_bytes", 2097152):
        raise AuthoringError("Draft exceeds the configured metadata or HTML limit")
    target = _path(library, Path(library.directory) / report_id, creating=True)
    folder_descriptor = None
    created = []
    identity = None
    try:
        with _parent(library, target, creating=True) as (_, parent_descriptor, name):
            os.mkdir(name, dir_fd=parent_descriptor)
            folder_descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_descriptor)
            identity = os.fstat(folder_descriptor)
            try:
                for filename, content in (("meta.json", metadata), ("index.html", document)):
                    _write(folder_descriptor, filename, content)
                    created.append(filename)
                checked = library.check(report_id)
                if not checked.get("valid"):
                    raise AuthoringError("Draft validation failed: " + json.dumps(checked, ensure_ascii=False))
            except BaseException:
                for filename in reversed(created):
                    try:
                        os.unlink(filename, dir_fd=folder_descriptor)
                    except OSError:
                        pass
                try:
                    current = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                        os.rmdir(name, dir_fd=parent_descriptor)
                except OSError:
                    pass
                raise
    except (OSError, ValueError) as exc:
        raise AuthoringError(str(exc)) from exc
    finally:
        if folder_descriptor is not None:
            os.close(folder_descriptor)
    return {"id": report_id, "path": str(target), "meta": meta}


class _Bundle:
    def __init__(self, library, report_id, kit_assets):
        self.library, self.report_id = library, report_id
        if kit_assets is not None and (not isinstance(kit_assets, dict)
                or any(key not in {KIT_URL, KIT_CSS_URL} or not isinstance(value, bytes) for key, value in kit_assets.items())):
            raise AuthoringError("Only the fixed trusted kit URL and byte content may be supplied")
        self.kit = kit_assets or {}
        limits = getattr(library, "limits", {})
        self.input_limit = limits.get("report_bytes", 64 * 1024 * 1024)
        self.output_limit = self.input_limit * 2
        self.file_limit = limits.get("files", 512)
        self.cache = {}
        self.images = {}
        self.image_bytes = 0
        self.css_cache = {}
        self.css_cache_bytes = 0
        self.total = 0

    def read(self, relative):
        if relative not in self.cache:
            if len(self.cache) >= self.file_limit:
                raise AuthoringError("Export dependency count exceeds report limit")
            if relative in {KIT_URL, KIT_CSS_URL}:
                if relative not in self.kit:
                    raise AuthoringError("Export requires the trusted report kit bytes")
                raw, mime = self.kit[relative], "text/javascript" if relative == KIT_URL else "text/css"
            else:
                try:
                    raw, mime = self.library.asset(self.report_id, relative)
                except (OSError, ValueError) as exc:
                    raise AuthoringError(str(exc)) from exc
            self.total += len(raw)
            if self.total > self.input_limit:
                raise AuthoringError("Export input exceeds report byte limit")
            self.cache[relative] = raw, mime.split(";", 1)[0]
        return self.cache[relative]

    def text(self, relative):
        raw, mime = self.read(relative)
        try:
            return raw.decode("utf-8"), mime
        except UnicodeError as exc:
            raise AuthoringError("Text dependencies must be UTF-8") from exc

    def reference(self, raw, base):
        if not isinstance(raw, str) or any(c in raw for c in "\x00\r\n\\"):
            raise AuthoringError("Invalid export resource URL")
        raw = raw.strip()
        if not raw or raw.startswith("#") or raw.lower().startswith("data:"):
            return raw, ""
        try:
            parsed = urlsplit(raw)
        except ValueError as exc:
            raise AuthoringError("Invalid export resource URL") from exc
        if parsed.scheme or parsed.netloc:
            raise AuthoringError("Required remote resources cannot be exported")
        decoded = unquote(parsed.path)
        if "%" in decoded or "\\" in decoded or "\x00" in decoded:
            raise AuthoringError("Invalid encoded export resource path")
        if decoded in {KIT_URL, KIT_CSS_URL}:
            return decoded, parsed.fragment
        prefix = f"/reports/{self.report_id}/"
        if decoded.startswith("/"):
            if not decoded.startswith(prefix):
                raise AuthoringError("Resource is outside the report")
            relative = decoded[len(prefix):]
        else:
            relative = posixpath.normpath(posixpath.join(posixpath.dirname(base), decoded))
        if any(part in {"", ".", ".."} for part in relative.split("/")):
            raise AuthoringError("Resource escapes the report")
        return relative, parsed.fragment

    @staticmethod
    def optional_font(raw):
        try:
            parsed = urlsplit(raw)
            return (parsed.scheme == "https" and not parsed.username and not parsed.password
                    and parsed.hostname in {"fonts.googleapis.com", "fonts.gstatic.com"}
                    and parsed.port in {None, 443})
        except ValueError:
            return False

    def data(self, raw, base, chain):
        relative, fragment = self.reference(raw, base)
        if not relative or relative.startswith("#") or relative.lower().startswith("data:"):
            return relative
        if relative in {KIT_URL, KIT_CSS_URL}:
            raise AuthoringError("Kit assets must be scripts or stylesheet links")
        if relative in chain or len(chain) >= 32:
            raise AuthoringError("Cyclic or excessively deep export asset dependencies")
        if relative not in self.images:
            content, mime = self.read(relative)
            if mime == "image/svg+xml":
                text, _ = self.text(relative)
                parser = _HTMLBundle(self, relative, (*chain, relative), svg=True)
                parser.feed(text)
                parser.close()
                content = parser.result().encode("utf-8")
            elif mime not in {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/x-icon",
                              "font/woff", "font/woff2", "font/ttf", "font/otf"}:
                raise AuthoringError("Only raster, SVG and font resources can be embedded as data URLs")
            encoded = "data:" + mime + ";base64," + base64.b64encode(content).decode("ascii")
            if self.image_bytes + len(encoded) > self.output_limit:
                raise AuthoringError("Embedded asset cache exceeds export byte limit")
            self.image_bytes += len(encoded)
            self.images[relative] = encoded
        return self.images[relative] + ("#" + fragment if fragment else "")

    def css(self, source, base, chain):
        if len(chain) >= 32:
            raise AuthoringError("CSS dependency depth exceeds export limit")
        cache_key = (base, source)
        if cache_key in self.css_cache:
            return self.css_cache[cache_key]
        source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
        if re.search(r"\b(?:-webkit-)?image-set\s*\(", source, re.I):
            raise AuthoringError("CSS image-set dependencies are unsupported; use url() assets")
        if "\\" in source and re.search(r"(?:url|import|font-face)", source, re.I):
            raise AuthoringError("Escaped CSS dependencies are unsupported")
        def imported(match):
            raw = next(value for value in match.groups()[:5] if value is not None)
            if self.optional_font(raw):
                return ""
            relative, _ = self.reference(raw, base)
            if relative in chain or not relative or relative.startswith(("data:", "#")):
                raise AuthoringError("Cyclic or unsupported CSS import")
            text, mime = self.text(relative)
            if mime != "text/css":
                raise AuthoringError("CSS imports must refer to CSS files")
            expanded = self.css(text, relative, (*chain, relative))
            media = match.group(6).strip()
            if media and re.search(r"\b(?:layer|supports)\b", media, re.I):
                raise AuthoringError("Layered or conditional CSS imports are unsupported")
            return "@media " + media + "{" + expanded + "}" if media else expanded
        source = _IMPORT.sub(imported, source)
        if re.search(r"@import\b", source, re.I):
            raise AuthoringError("Unsupported CSS import syntax")
        def url(match):
            raw = next(value for value in match.groups() if value is not None)
            if self.optional_font(raw):
                return 'url("data:font/woff2;base64,")'
            return 'url("' + self.data(raw, base, chain).replace('"', "%22") + '")'
        source = _URL.sub(url, source)
        size = len(source.encode("utf-8"))
        if size > self.output_limit:
            raise AuthoringError("Bundled CSS exceeds export byte limit")
        cache_size = size + len(cache_key[1].encode("utf-8"))
        if len(self.css_cache) < self.file_limit and self.css_cache_bytes + cache_size <= 8 * 1024 * 1024:
            self.css_cache[cache_key] = source
            self.css_cache_bytes += cache_size
        return source

    def js(self, source):
        if _NETWORK_JS.search(source):
            raise AuthoringError("Scripts using network APIs or dynamic imports cannot be exported offline")
        return re.sub(r"</script", r"<\\/script", source, flags=re.I)

    def srcset(self, source, base, chain):
        candidates = []
        index = 0
        while index < len(source):
            while index < len(source) and (source[index].isspace() or source[index] == ","):
                index += 1
            if index >= len(source):
                break
            start = index
            embedded = source[index:index + 5].lower() == "data:"
            while index < len(source) and not source[index].isspace() and (embedded or source[index] != ","):
                index += 1
            raw = source[start:index]
            terminated = raw.endswith(",")
            if terminated:
                raw = raw.rstrip(",")
            descriptor = ""
            if not terminated:
                start = index
                while index < len(source) and source[index] != ",":
                    index += 1
                descriptor = source[start:index].strip()
            if descriptor and not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]+)?x|[0-9]+w)", descriptor):
                raise AuthoringError("Unsupported srcset descriptor")
            candidates.append(self.data(raw, base, chain) + (" " + descriptor if descriptor else ""))
            index += 1
        return ", ".join(candidates)


class _HTMLBundle(HTMLParser):
    def __init__(self, bundle, base, chain=(), *, svg=False):
        super().__init__(convert_charrefs=False)
        self.bundle, self.base, self.chain, self.svg = bundle, base, chain, svg
        self.parts, self.deferred = [], []
        self.size = 0
        self.deferred_size = 0
        self.skip_script = False
        self.style = None
        self.script = None
        self.stack = []
        self.heads = 0

    def append(self, value):
        self.size += len(value.encode("utf-8"))
        if self.size + self.deferred_size > self.bundle.output_limit:
            raise AuthoringError("Export exceeds its byte limit")
        self.parts.append(value)

    def tag(self, tag, attrs, *, closed=False):
        raw = self.get_starttag_text() or ""
        original_tag = re.match(r"<([^\s/>]+)", raw)
        names = {match.group(1).lower(): match.group(1) for match in re.finditer(r"\s+([^\s=/>]+)(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+))?", raw)}
        name = original_tag.group(1) if original_tag else tag
        return "<" + name + "".join(" " + names.get(key, key) + ("" if value is None else '=\"' + escape(value, quote=True) + '\"') for key, value in attrs.items()) + ("/>" if closed else ">")

    def handle_starttag(self, tag, attrs):
        self.start(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self.start(tag, attrs, closed=True)

    def start(self, tag, pairs, *, closed=False):
        if self.skip_script:
            return
        attrs = dict(pairs)
        if len(attrs) != len(pairs):
            raise AuthoringError("Duplicate HTML attributes are unsupported")
        if not closed and tag not in _VOID:
            original = re.match(r"<([^\s/>]+)", self.get_starttag_text())
            self.stack.append((tag, original.group(1) if original else tag))
        if tag == "head" and not self.svg:
            self.heads += 1
            self.append(self.get_starttag_text())
            self.append('<meta http-equiv="Content-Security-Policy" content="' + escape(OFFLINE_CSP, quote=True) + '">')
            self.append('<style>[data-naia-section][hidden]{display:none!important}</style>')
            return
        if tag == "meta" and attrs.get("http-equiv", "").lower() == "content-security-policy":
            return
        if tag in {"base", "iframe", "object", "embed"}:
            raise AuthoringError("Base, frame and object elements cannot be exported")
        if tag == "link":
            rel = set((attrs.get("rel") or "").lower().split())
            href = attrs.get("href") or ""
            if self.bundle.optional_font(href) and rel & {"stylesheet", "preconnect", "dns-prefetch", "preload"}:
                return
            if "stylesheet" in rel:
                relative, _ = self.bundle.reference(href, self.base)
                if relative in self.chain:
                    raise AuthoringError("Cyclic stylesheet dependency")
                text, mime = self.bundle.text(relative)
                if mime != "text/css":
                    raise AuthoringError("Stylesheet links must refer to CSS")
                css = self.bundle.css(text, relative, (*self.chain, relative))
                media = attrs.get("media")
                if media:
                    css = "@media " + media + "{" + css + "}"
                self.append("<style>" + re.sub(r"</style", r"<\\/style", css, flags=re.I) + "</style>")
                return
            if rel & {"preconnect", "dns-prefetch", "preload", "modulepreload", "manifest"}:
                return  # Bundled resources no longer need network hints.
        script_url = attrs.get("src") if tag == "script" else None
        if self.svg and tag == "script":
            script_url = script_url or attrs.get("href") or attrs.get("xlink:href")
        if script_url:
            if script_url == EDITOR_URL:
                # Offline snapshots have no source-writing wrapper. Strip its
                # bridge rather than exporting a nonfunctional editing control.
                self.skip_script = not closed
                return
            if (attrs.get("type") or "").strip().lower() == "module":
                raise AuthoringError("Module script dependencies are unsupported")
            if "async" in attrs:
                raise AuthoringError("Async scripts cannot preserve execution order offline; use classic or defer scripts")
            relative, _ = self.bundle.reference(script_url, self.base)
            text, mime = self.bundle.text(relative)
            if mime not in {"text/javascript", "application/javascript"}:
                raise AuthoringError("Script dependencies must be classic JavaScript")
            deferred = "defer" in attrs
            attrs = {key: value for key, value in attrs.items() if key not in {"src", "href", "xlink:href", "defer", "async", "integrity", "crossorigin", "referrerpolicy"}}
            inlined = self.tag(tag, attrs) + self.bundle.js(text) + "</script>"
            if deferred:
                self.deferred_size += len(inlined.encode("utf-8"))
                if self.size + self.deferred_size > self.bundle.output_limit:
                    raise AuthoringError("Deferred scripts exceed export byte limit")
                self.deferred.append(inlined)
            else:
                self.append(inlined)
            self.skip_script = not closed
            return
        changed = False
        if attrs.get("style"):
            attrs["style"] = self.bundle.css(attrs["style"], self.base, self.chain)
            changed = True
        for key in ("src", "poster", "data", "xlink:href"):
            if attrs.get(key) and tag != "a":
                attrs[key] = self.bundle.data(attrs[key], self.base, self.chain)
                changed = True
        in_svg = self.svg or any(parent == "svg" for parent, _ in self.stack)
        if tag != "a" and attrs.get("href") and (tag in {"image", "use", "link"} or in_svg):
            attrs["href"] = self.bundle.data(attrs["href"], self.base, self.chain)
            changed = True
        if attrs.get("srcset"):
            attrs["srcset"] = self.bundle.srcset(attrs["srcset"], self.base, self.chain)
            changed = True
        if tag == "style":
            self.style = (self.tag(tag, attrs) if changed else self.get_starttag_text(), [])
            return
        if tag == "script":
            kind = (attrs.get("type") or "").strip().lower()
            if kind == "module":
                raise AuthoringError("Module scripts cannot be exported offline")
            self.script = (self.tag(tag, attrs) if changed else self.get_starttag_text(), [],
                           kind in {"", "text/javascript", "application/javascript"})
            return
        self.append(self.tag(tag, attrs, closed=closed) if changed else self.get_starttag_text())

    def handle_endtag(self, tag):
        original = tag
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                original = self.stack[index][1]
                del self.stack[index:]
                break
        if self.skip_script:
            if tag == "script":
                self.skip_script = False
            return
        if tag == "script" and self.script is not None:
            start, parts, classic = self.script
            self.script = None
            source = "".join(parts)
            self.append(start + (self.bundle.js(source) if classic else source) + "</" + original + ">")
            return
        if tag == "style" and self.style is not None:
            start, parts = self.style
            self.style = None
            css = self.bundle.css("".join(parts), self.base, self.chain)
            self.append(start + re.sub(r"</style", r"<\\/style", css, flags=re.I) + "</" + original + ">")
            return
        if tag == "body" and self.deferred:
            for script in self.deferred:
                self.deferred_size -= len(script.encode("utf-8"))
                self.append(script)
            self.deferred.clear()
        self.append("</" + original + ">")

    def handle_data(self, value):
        if not self.skip_script:
            if self.style is not None:
                self.style[1].append(value)
            elif self.script is not None:
                self.script[1].append(value)
            else:
                self.append(value)

    def handle_entityref(self, name):
        self.handle_data("&" + name + ";")

    def handle_charref(self, name):
        self.handle_data("&#" + name + ";")

    def handle_comment(self, value):
        self.handle_data("<!--" + value + "-->")

    def handle_decl(self, value):
        if self.svg and re.search(r"\b(?:SYSTEM|PUBLIC)\b", value, re.I):
            raise AuthoringError("External SVG declarations cannot be exported")
        self.handle_data("<!" + value + ">")

    def handle_pi(self, value):
        self.handle_data("<?" + value + ">")

    def unknown_decl(self, value):
        self.handle_data("<![" + value + "]>")

    def result(self):
        if self.style is not None or self.script is not None or self.skip_script:
            raise AuthoringError("Unclosed script or style element")
        if not self.svg and self.heads != 1:
            raise AuthoringError("Offline exports require one head element")
        for script in self.deferred:
            self.deferred_size -= len(script.encode("utf-8"))
            self.append(script)
        self.deferred.clear()
        return "".join(self.parts)


class _Offline(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.in_title, self.csp = [], False, False
        self.skipped = 0

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        if tag in {"svg", "template"}:
            self.skipped += 1
        if tag == "title" and not self.skipped:
            self.in_title = True
        if tag == "meta" and (attrs.get("http-equiv") or "").lower() == "content-security-policy":
            self.csp = attrs.get("content") == OFFLINE_CSP
        if tag in {"base", "iframe", "object", "embed"}:
            raise AuthoringError("Export retains an unsupported active resource")
        for key in ("src", "poster", "data", "xlink:href"):
            value = attrs.get(key)
            if value and tag != "a" and not value.startswith(("data:", "#")):
                raise AuthoringError("Export retains an unbundled resource")
        if tag != "a" and (tag in {"image", "use", "link"} or self.skipped) and attrs.get("href") and not attrs["href"].startswith(("data:", "#")):
            raise AuthoringError("Export retains an unbundled link resource")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in {"svg", "template"}:
            self.skipped = max(0, self.skipped - 1)

    def handle_data(self, value):
        if self.in_title:
            self.title.append(value)


def export_report(library, report_id, out, *, kit_assets=None):
    """Bundle a validated report into one new offline HTML file in the project."""
    report_id = _identifier(report_id)
    target = _path(library, out)
    if target.suffix.lower() != ".html":
        raise AuthoringError("Export output must end in .html")
    if target.is_relative_to(Path(library.directory)):
        raise AuthoringError("Exports must be outside the live report library")
    if target.exists():
        raise AuthoringError("Export output already exists")
    try:
        meta = library.get(report_id)
        bundle = _Bundle(library, report_id, kit_assets)
        source, _ = bundle.text("index.html")
        parser = _HTMLBundle(bundle, "index.html", ("index.html",))
        parser.feed(source)
        parser.close()
        document = parser.result()
        checked = _Offline()
        checked.feed(document)
        checked.close()
        if not checked.csp or "".join(checked.title) != meta["title"]:
            raise AuthoringError("Export failed its offline CSP or title validation")
        content = document.encode("utf-8")
        if len(content) > bundle.output_limit:
            raise AuthoringError("Export exceeds its byte limit")
        with _parent(library, target) as (_, descriptor, name):
            _write(descriptor, name, content)
    except (OSError, ValueError, RecursionError) as exc:
        raise AuthoringError(str(exc)) from exc
    return {"id": report_id, "path": str(target), "bytes": len(content), "meta": meta}
