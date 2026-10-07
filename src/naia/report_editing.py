"""Bounded prose and layout editing of explicitly marked report source.

Prose edits replace marked leaf contents. Layout edits move intact marked source
chunks, hide sections, or add a fixed escaped-text template; chart data, scripts
and metadata are retained. The lock coordinates NAIA writers. Hash/inode checks
detect ordinary concurrent changes, but cannot serialize arbitrary editors that
ignore the lock. One previous source is retained outside the report inventory.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
import copy
import hashlib
from html import escape, unescape
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import secrets
import stat
from threading import RLock


class EditError(ValueError):
    """An edit or report does not satisfy the plain-text editing contract."""


class EditConflict(EditError):
    """The report changed after the editor's source snapshot."""


EDITOR_JS_ROUTE = "/reports/_kit/naia_report_editor.js"
MAX_BLOCKS = 128
MAX_BLOCK_CHARS = 8192
MAX_TEXT_BYTES = 32768
MAX_SECTIONS = 64
MAX_ITEMS = 256
MAX_ADDITIONS = 32
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_RESERVED = {"id", "view", "constructor", "prototype", "__proto__"}
_REVISION = re.compile(r"^[0-9a-f]{64}$")
_LEAVES = {"p", "li", "dt", "dd", "blockquote", "figcaption", "span", "strong",
           "em", "b", "i", "small", "cite", "q", "h1", "h2", "h3", "h4", "h5", "h6"}
_FORBIDDEN = {"head", "table", "caption", "thead", "tbody", "tfoot", "tr", "td", "th",
              "script", "style", "svg", "math", "form", "button", "select", "option",
              "optgroup", "textarea", "template", "noscript", "iframe", "object", "embed",
              "canvas", "pre", "code", "a", "audio", "video", "datalist", "output"}
_FORBIDDEN.update({"plaintext", "xmp", "listing", "title", "frameset", "frame"})
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
         "param", "source", "track", "wbr"}
_P_CLOSE = {"address", "article", "aside", "blockquote", "details", "div", "dl", "fieldset",
            "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
            "header", "hgroup", "hr", "main", "menu", "nav", "ol", "p", "pre", "section",
            "table", "ul"}


def _text(value):
    if not isinstance(value, str) or len(value) > MAX_BLOCK_CHARS:
        raise EditError(f"Editable text must be a string of at most {MAX_BLOCK_CHARS} characters")
    if any(ord(char) < 32 and char not in "\n\r\t" or ord(char) == 127 for char in value):
        raise EditError("Editable text contains unsupported control characters")
    try:
        return len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise EditError("Editable text must be valid Unicode") from exc


class _Source(HTMLParser):
    """Locate exact source spans while rejecting ambiguous marked markup."""

    # Older stdlib parsers recognize only script/style as raw text. Markup-like
    # text in these other HTML raw-text elements is never an editable DOM node.
    CDATA_CONTENT_ELEMENTS = tuple(dict.fromkeys(HTMLParser.CDATA_CONTENT_ELEMENTS
                                                + ("xmp", "iframe", "noembed", "noframes", "plaintext")))

    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0]
        self.lines.extend(index + 1 for index, char in enumerate(source) if char == "\n")
        self.stack = []
        self.readonly = []
        self.nodes = []
        self.node_stack = []
        self.layout = None
        self.blocks = []
        self.seen = set()
        self.active = None
        self.bridge = False
        self.bad_structure = False

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if self.active is not None:
            raise EditError("Editable blocks must contain plain text without nested markup")
        names = [name for name, _ in attrs]
        values = dict(attrs)
        if (("p" in self.stack and tag in _P_CLOSE)
                or tag in {"h1", "h2", "h3", "h4", "h5", "h6"}
                and any(item in {"h1", "h2", "h3", "h4", "h5", "h6"} for item in self.stack)):
            self.bad_structure = True
        if (tag == "script" and values.get("src") == EDITOR_JS_ROUTE
                and names.count("src") == 1
                and (values.get("type") or "").strip().lower() in {"", "text/javascript", "application/javascript"}
                and not any(item in {"template", "svg", "math", "noscript"} for item in self.stack)):
            self.bridge = True
        if "data-naia-edit" in values:
            block_id = values["data-naia-edit"]
            if (names.count("data-naia-edit") != 1 or not isinstance(block_id, str)
                    or not _ID.fullmatch(block_id) or block_id.lower() in _RESERVED):
                raise EditError("Editable block IDs must be unique stable ASCII identifiers")
            if block_id in self.seen:
                raise EditError(f"Duplicate editable block ID: {block_id}")
            if (tag not in _LEAVES or "body" not in self.stack
                    or any(item in _FORBIDDEN for item in self.stack)
                    or any(self.readonly) or "data-naia-readonly" in values):
                raise EditError("Editable markers are allowed only on prose leaves in the report body")
            if len(self.seen) >= MAX_BLOCKS:
                raise EditError(f"Report has more than {MAX_BLOCKS} editable blocks")
            self.seen.add(block_id)
            self.active = {"id": block_id, "tag": tag,
                           "start": self.position() + len(self.get_starttag_text())}
        node = {"tag": tag, "attrs": values, "names": names, "start": self.position(),
                "open_end": self.position() + len(self.get_starttag_text()), "children": [],
                "parent": self.node_stack[-1] if self.node_stack else None}
        if node["parent"] is not None:
            node["parent"]["children"].append(node)
        self.nodes.append(node)
        if tag in _VOID:
            node["close_start"] = node["end"] = node["open_end"]
        if tag not in _VOID:
            self.stack.append(tag)
            self.readonly.append("data-naia-readonly" in values)
            self.node_stack.append(node)

    def handle_startendtag(self, tag, attrs):
        if any(name in {"data-naia-edit", "data-naia-layout", "data-naia-section", "data-naia-item"} for name, _ in attrs):
            raise EditError("Editable prose leaves require an explicit closing tag")
        bridge = self.bridge
        self.handle_starttag(tag, attrs)
        if tag == "script":
            self.bridge = bridge
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.bad_structure = True
            if self.active is not None:
                raise EditError("Editable block has mismatched closing markup")
            if tag in self.stack:
                index = len(self.stack) - 1 - self.stack[::-1].index(tag)
                del self.stack[index:]
                del self.readonly[index:]
                del self.node_stack[index:]
            return
        if self.active is not None:
            block = self.active
            block["end"] = self.position()
            raw = self.source[block["start"]:block["end"]]
            block["text"] = unescape(raw.replace("\r\n", "\n").replace("\r", "\n"))
            _text(block["text"])
            self.blocks.append(block)
            self.active = None
        self.stack.pop()
        self.readonly.pop()
        node = self.node_stack.pop()
        node["close_start"] = self.position()
        node["end"] = self.source.find(">", self.position()) + 1

    def handle_comment(self, value):
        if self.active is not None:
            raise EditError("Editable blocks cannot contain comments")

    def handle_decl(self, value):
        if self.active is not None:
            raise EditError("Editable blocks cannot contain declarations")

    def handle_pi(self, value):
        if self.active is not None:
            raise EditError("Editable blocks cannot contain processing instructions")

    def unknown_decl(self, value):
        if self.active is not None:
            raise EditError("Editable blocks cannot contain declarations")

    def finish(self):
        self.feed(self.source)
        self.close()
        structural = any(any(name in node["attrs"] for name in ("data-naia-layout", "data-naia-section", "data-naia-item")) for node in self.nodes)
        if self.active is not None or (self.blocks or structural) and (self.stack or self.bad_structure):
            raise EditError("Marked reports require unambiguous, balanced HTML markup")
        if sum(_text(block["text"]) for block in self.blocks) > MAX_TEXT_BYTES:
            raise EditError(f"Editable report text exceeds {MAX_TEXT_BYTES} UTF-8 bytes")
        self.layout = _structure(self) if structural else None
        return self

    def public(self):
        return [{"id": block["id"], "text": block["text"]} for block in self.blocks]


def _parse(content):
    try:
        return _Source(content.decode("utf-8")).finish()
    except UnicodeError as exc:
        raise EditError("Report source must be UTF-8") from exc


def _marker(value):
    if not isinstance(value, str) or not _ID.fullmatch(value) or value.lower() in _RESERVED:
        raise EditError("Layout IDs must be stable ASCII identifiers")
    return value


def _ancestors(node):
    parent = node["parent"]
    while parent is not None:
        yield parent
        parent = parent["parent"]


def _gaps(source, node):
    positions = [(child["start"], child["end"]) for child in node["children"]]
    ends = [node["open_end"]] + [end for _, end in positions]
    starts = [start for start, _ in positions] + [node["close_start"]]
    gaps = [source[end:start] for end, start in zip(ends, starts)]
    if any(re.sub(r"<!--.*?-->", "", value, flags=re.S).strip() for value in gaps):
        raise EditError("Managed layouts allow only whitespace and comments between marked children")
    return gaps


def _label(source, node, fallback):
    declared = node["attrs"].get("data-naia-label")
    if declared:
        return declared[:120]
    headings = [child for child in node["children"] if child["tag"] in {"h1", "h2", "h3", "h4", "h5", "h6"}]
    target = headings[0] if headings else node
    raw = source[target["open_end"]:target["close_start"]]
    text = unescape(re.sub(r"<[^>]*>", " ", raw))
    return " ".join(text.split())[:120] or fallback


def _structure(parsed):
    source = parsed.source
    marked = [node for node in parsed.nodes if any(name in node["attrs"] for name in
              ("data-naia-edit", "data-naia-layout", "data-naia-section", "data-naia-item"))]
    owners = {}
    for node in marked:
        for name in ("data-naia-edit", "data-naia-layout", "data-naia-section", "data-naia-item"):
            if name in node["attrs"]:
                value = _marker(node["attrs"][name])
                if node["names"].count(name) != 1 or value in owners and owners[value] is not node:
                    raise EditError("Layout and prose IDs must be unique across source elements")
                owners[value] = node
    roots = [node for node in marked if "data-naia-layout" in node["attrs"] and "data-naia-section" not in node["attrs"]]
    if len(roots) != 1:
        raise EditError("Managed reports require exactly one layout root")
    root = roots[0]
    if (root["tag"] not in {"main", "div", "article"} or "end" not in root
            or "data-naia-item" in root["attrs"]
            or "body" not in {node["tag"] for node in _ancestors(root)}
            or any(node["tag"] in _FORBIDDEN or "data-naia-readonly" in node["attrs"] for node in [root, *_ancestors(root)])):
        raise EditError("Report layout root must be a body container outside protected content")
    sections = root["children"]
    if len(sections) > MAX_SECTIONS:
        raise EditError(f"Report has more than {MAX_SECTIONS} sections")
    _gaps(source, root)
    items = []
    for section in sections:
        attrs = section["attrs"]
        if (section["tag"] not in {"section", "article", "div"}
                or "data-naia-section" not in attrs or attrs.get("data-naia-layout") != attrs["data-naia-section"]
                or "data-naia-item" in attrs or "data-naia-edit" in attrs or "data-naia-readonly" in attrs
                or section["names"].count("hidden") > 1):
            raise EditError("Every layout root child must be an explicitly marked section")
        _gaps(source, section)
        for item in section["children"]:
            values = item["attrs"]
            if ("data-naia-item" not in values or "data-naia-layout" in values or "data-naia-section" in values
                    or item["tag"] in _VOID or values.get("data-naia-kind", "text") not in {"text", "visual"}
                    or item["names"].count("data-naia-kind") > 1):
                raise EditError("Every managed section child must be an explicitly marked text or visual item")
            descendants = [node for node in parsed.nodes if item["start"] <= node["start"] < item["end"]]
            if any(node["tag"] in {"script", "style", "template", "iframe", "object", "embed", "form", "plaintext", "xmp", "noembed", "noframes"} for node in descendants):
                raise EditError("Movable items cannot contain scripts, styles, templates or active embedded content")
            items.append(item)
    if len(items) > MAX_ITEMS:
        raise EditError(f"Report has more than {MAX_ITEMS} movable items")
    expected = {id(root), *(id(node) for node in sections), *(id(node) for node in items)}
    if any(id(node) not in expected for node in marked if any(name in node["attrs"] for name in ("data-naia-layout", "data-naia-section", "data-naia-item"))):
        raise EditError("Layout markers must identify the root, its direct sections, and their direct items")
    root_id = root["attrs"]["data-naia-layout"]
    public = {"root": root_id,
              "containers": [{"id": root_id, "kind": "sections", "order": [node["attrs"]["data-naia-section"] for node in sections]}]
                + [{"id": node["attrs"]["data-naia-section"], "kind": "items", "order": [item["attrs"]["data-naia-item"] for item in node["children"]]} for node in sections],
              "sections": [{"id": node["attrs"]["data-naia-section"], "container": root_id,
                            "label": _label(source, node, node["attrs"]["data-naia-section"]), "hidden": "hidden" in node["attrs"]} for node in sections],
              "items": [{"id": node["attrs"]["data-naia-item"], "container": node["parent"]["attrs"]["data-naia-section"],
                         "label": _label(source, node, node["attrs"]["data-naia-item"]), "kind": node["attrs"].get("data-naia-kind", "text")} for node in items]}
    return {"root": root, "sections": sections, "items": items, "ids": set(owners), "public": public}


def _assemble(gaps, chunks):
    result = gaps[0]
    for index, chunk in enumerate(chunks):
        result += chunk + (gaps[index + 1] if index + 1 < len(gaps) else "")
    return result + "".join(gaps[len(chunks) + 1:])


def _hidden(opening, present, desired):
    if present == desired:
        return opening
    if desired:
        return opening[:-1] + " hidden>"
    attribute = re.compile(r'''\s+([^\s=/>]+)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?''')
    position = re.match(r"<[^\s/>]+", opening).end()
    while position < len(opening):
        match = attribute.match(opening, position)
        if match is None:
            break
        if match.group(1).lower() == "hidden":
            return opening[:match.start()] + opening[match.end():]
        position = match.end()
    raise EditError("Could not safely locate the section hidden attribute")


def _apply_layout(parsed, payload):
    if parsed.layout is None:
        raise EditError("This report has no explicitly managed section layout")
    if not isinstance(payload, dict) or set(payload) - {"orders", "hidden", "add"}:
        raise EditError("Layout changes have unexpected fields")
    additions = payload.get("add", [])
    if not isinstance(additions, list) or len(additions) > MAX_ADDITIONS:
        raise EditError(f"Layout supports at most {MAX_ADDITIONS} added sections per save")
    root_id = parsed.layout["public"]["root"]
    used = set(parsed.layout["ids"])
    fragments = []
    for addition in additions:
        if not isinstance(addition, dict) or set(addition) != {"id", "container", "title", "text"}:
            raise EditError("New sections require id, container, title and plain text")
        section_id = _marker(addition["id"])
        if len(section_id) > 58 or addition["container"] != root_id:
            raise EditError("New sections require a bounded ID and the report root container")
        generated = {section_id, section_id + "-title", section_id + "-text"}
        if generated & used:
            raise EditError("New section identifiers collide with existing report identifiers")
        used.update(generated)
        _text(addition["title"])
        _text(addition["text"])
        if not addition["title"].strip():
            raise EditError("New sections require a non-empty plain text title")
        fragments.append('<section data-naia-section="' + section_id + '" data-naia-layout="' + section_id + '">\n'
            '<h2 data-naia-item="' + section_id + '-title" data-naia-edit="' + section_id + '-title">' + escape(addition["title"]) + '</h2>\n'
            '<p data-naia-item="' + section_id + '-text" data-naia-edit="' + section_id + '-text" style="white-space: pre-line;">' + escape(addition["text"]) + '</p>\n</section>')
    source = parsed.source
    if fragments:
        position = parsed.layout["root"]["close_start"]
        source = source[:position] + "\n" + "\n".join(fragments) + "\n" + source[position:]
        parsed = _parse(source.encode("utf-8"))
    layout = parsed.layout
    containers = {item["id"]: item["order"] for item in layout["public"]["containers"]}
    orders = payload.get("orders", {})
    if not isinstance(orders, dict) or set(orders) - set(containers):
        raise EditError("Layout orders contain unknown containers")
    for container, order in orders.items():
        if not isinstance(order, list) or len(order) > MAX_ITEMS or any(not isinstance(value, str) for value in order):
            raise EditError("Layout orders must be bounded lists of known identifiers")
        containers[container] = order
    section_ids = [node["attrs"]["data-naia-section"] for node in layout["sections"]]
    if len(containers[root_id]) != len(section_ids) or set(containers[root_id]) != set(section_ids):
        raise EditError("Root order must contain every existing and added section exactly once")
    item_ids = [node["attrs"]["data-naia-item"] for node in layout["items"]]
    placement = [value for section_id in section_ids for value in containers[section_id]]
    if len(placement) != len(item_ids) or set(placement) != set(item_ids):
        raise EditError("Item orders must place every immutable item exactly once without deletion")
    hidden = payload.get("hidden", [node["attrs"]["data-naia-section"] for node in layout["sections"] if "hidden" in node["attrs"]])
    if (not isinstance(hidden, list) or any(not isinstance(value, str) for value in hidden)
            or len(hidden) != len(set(hidden)) or not set(hidden) <= set(section_ids)):
        raise EditError("Hidden sections must be a unique list of known section identifiers")
    item_sources = {node["attrs"]["data-naia-item"]: source[node["start"]:node["end"]] for node in layout["items"]}
    section_sources = {}
    for node in layout["sections"]:
        section_id = node["attrs"]["data-naia-section"]
        opening = _hidden(source[node["start"]:node["open_end"]], "hidden" in node["attrs"], section_id in hidden)
        body = _assemble(_gaps(source, node), [item_sources[value] for value in containers[section_id]])
        section_sources[section_id] = opening + body + source[node["close_start"]:node["end"]]
    root = layout["root"]
    body = _assemble(_gaps(source, root), [section_sources[value] for value in containers[root_id]])
    return source[:root["open_end"]] + body + source[root["close_start"]:]


def _hash(content):
    return hashlib.sha256(content).hexdigest()


def _identity(info):
    return info.st_dev, info.st_ino


def _stamp(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class ReportEditor:
    """Edit an existing validated ``Reports`` library without expanding its scope."""

    def __init__(self, library):
        self.library = library

    def _validated(self, report_id):
        try:
            self.library.get(report_id)
            content, _ = self.library.asset(report_id, "index.html")
            return content, _parse(content)
        except EditError:
            raise
        except (ValueError, OSError, RecursionError) as exc:
            raise EditError(str(exc)) from exc

    @staticmethod
    def _result(report_id, content, parsed):
        result = {"id": report_id, "revision": _hash(content), "blocks": parsed.public(),
                  "editable": bool((parsed.blocks or parsed.layout is not None) and parsed.bridge)}
        if parsed.layout is not None:
            result["layout"] = parsed.layout["public"]
        if not parsed.blocks and parsed.layout is None:
            result["reason"] = "This report has no explicitly marked editable prose."
        elif not parsed.bridge:
            result["reason"] = "This report does not include the trusted report editor bridge."
        return result

    def snapshot(self, report_id):
        """Return source revision and text blocks; legacy reports remain read-only."""
        content, parsed = self._validated(report_id)
        return self._result(report_id, content, parsed)

    def _candidate(self, report_id, content):
        """Validate the candidate through the library without publishing it."""
        parsed = _parse(content)
        if (not parsed.blocks and parsed.layout is None) or not parsed.bridge:
            raise EditError("Report does not support inline prose editing")
        library = self.library
        if len(content) > library.limits["html_bytes"]:
            raise EditError("Edited report exceeds the HTML byte limit")
        candidate = copy.copy(library)
        candidate._cache = OrderedDict()
        candidate._cache_size = 0
        candidate._lock = RLock()
        index = Path(library.directory) / report_id / "index.html"
        original_read = library._read
        original_inventory = library._inventory

        def read(path, limit, *, within):
            if Path(path) == index:
                library._safe_path(index, within=within)
                if len(content) > limit:
                    raise EditError("Edited report exceeds its byte limit")
                return content
            return original_read(path, limit, within=within)

        def inventory(value):
            folder, files, _ = original_inventory(value)
            files = dict(files)
            previous = files["index.html"]
            files["index.html"] = previous[:2] + (len(content),) + previous[3:]
            if sum(item[2] for item in files.values()) > library.limits["report_bytes"]:
                raise EditError("Edited report exceeds the report byte limit")
            return folder, files, tuple(sorted(files.items()))

        candidate._read = read
        candidate._inventory = inventory
        try:
            candidate.get(report_id)
            if candidate.asset(report_id, "index.html")[0] != content:
                raise EditError("Candidate validation returned different source")
        except EditError:
            raise
        except (ValueError, OSError, RecursionError) as exc:
            raise EditError(str(exc)) from exc
        return parsed

    def _exclude(self, path):
        if self.library.excluded is not None:
            try:
                denied = self.library.excluded(path.relative_to(self.library.root).as_posix())
            except Exception as exc:
                raise EditError("Report editing exclusion check failed") from exc
            if denied:
                raise EditError("Report editing path is excluded from project access")

    @contextmanager
    def _directories(self, report_id):
        """Keep descriptors for all ancestors and reject path swaps before writing."""
        if not (hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
                and os.open in os.supports_dir_fd):
            raise EditError("Safe report edits require descriptor-relative filesystem support")
        library = self.library
        folder = Path(library.directory) / report_id
        library._safe_path(folder, within=library.directory)
        root = Path(library.root)
        descriptors = []
        chain = []
        try:
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(descriptor)
            root_descriptor = descriptor
            for component in folder.relative_to(root).parts:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=descriptor)
                descriptors.append(child)
                chain.append((descriptor, component, child))
                descriptor = child
            report_descriptor = descriptor
            reports_descriptor = chain[-1][0]
            path = Path(library.directory)
            descriptor = reports_descriptor
            for component in (".naia-edit", report_id):
                path = path / component
                self._exclude(path)
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=descriptor)
                descriptors.append(child)
                chain.append((descriptor, component, child))
                descriptor = child

            def check():
                library._safe_path(folder, within=library.directory)
                if _identity(root.lstat()) != _identity(os.fstat(root_descriptor)):
                    raise EditConflict("Project root changed during report edit")
                for parent, name, child in chain:
                    current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if not stat.S_ISDIR(current.st_mode) or _identity(current) != _identity(os.fstat(child)):
                        raise EditConflict("Report directory changed during edit")
                for name in ("editor.lock", "index.previous.html"):
                    self._exclude(path / name)

            check()
            yield report_descriptor, descriptor, path, check
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    def _read_current(self, descriptor):
        fd = os.open("index.html", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            limit = self.library.limits["html_bytes"]
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise EditError("Report source is not regular or exceeds its byte limit")
            content = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        if len(content) > limit or _stamp(info) != _stamp(after):
            raise EditConflict("Report source changed during access")
        current = os.stat("index.html", dir_fd=descriptor, follow_symlinks=False)
        if _stamp(current) != _stamp(info):
            raise EditConflict("Report source changed during access")
        return content, info

    def _temporary(self, descriptor, directory, content, mode):
        name = ".naia-edit-" + secrets.token_hex(12) + ".tmp"
        self._exclude(directory / name)
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     mode, dir_fd=descriptor)
        identity = os.fstat(fd)
        try:
            with os.fdopen(fd, "wb") as handle:
                os.fchmod(handle.fileno(), mode)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                identity = os.fstat(handle.fileno())
        except BaseException:
            self._remove_temporary(descriptor, (name, _stamp(identity)))
            raise
        return name, _stamp(identity)

    @staticmethod
    def _verify_temporary(descriptor, temporary):
        name, expected = temporary
        current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode) or _stamp(current) != expected:
            raise EditConflict("Report temporary source changed during edit")

    @staticmethod
    def _remove_temporary(descriptor, temporary):
        name, expected = temporary
        try:
            current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISREG(current.st_mode) and _identity(current) == expected[:2]:
                os.unlink(name, dir_fd=descriptor)
        except FileNotFoundError:
            pass

    def save(self, report_id, revision, changes, layout=None):
        """Save text/layout changes if revision still matches; retain one backup."""
        if not isinstance(revision, str) or not _REVISION.fullmatch(revision):
            raise EditError("Report revision must be a lowercase SHA-256 digest")
        if not isinstance(changes, dict) or not changes and layout is None or len(changes) > MAX_BLOCKS:
            raise EditError("Report changes must be a bounded block-to-text mapping")
        total = 0
        for block_id, value in changes.items():
            if not isinstance(block_id, str) or not _ID.fullmatch(block_id) or block_id.lower() in _RESERVED:
                raise EditError("Invalid editable block ID")
            total += _text(value)
        if total > MAX_TEXT_BYTES:
            raise EditError(f"Report changes exceed {MAX_TEXT_BYTES} UTF-8 bytes")
        self._validated(report_id)
        try:
            import fcntl
        except ImportError as exc:
            raise EditError("Safe report edits require cooperative filesystem locking") from exc
        temporary = backup_temporary = None
        try:
            with self.library._lock, self._directories(report_id) as (report_fd, private_fd, private_path, check):
                lock_fd = os.open("editor.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                                  0o600, dir_fd=private_fd)
                with os.fdopen(lock_fd, "r+b") as lock:
                    if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
                        raise EditError("Report editor lock must be a regular file")
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    check()
                    if _identity(os.stat("editor.lock", dir_fd=private_fd, follow_symlinks=False)) != _identity(os.fstat(lock.fileno())):
                        raise EditConflict("Report editor lock changed during access")
                    content, info = self._read_current(report_fd)
                    if _hash(content) != revision:
                        raise EditConflict("Report changed since editing began; reload before saving")
                    validated, parsed = self._validated(report_id)
                    if validated != content:
                        raise EditConflict("Report changed during validation")
                    if not parsed.bridge or not parsed.blocks and parsed.layout is None:
                        raise EditError("Report does not support inline prose editing")
                    source = parsed.source
                    if layout is not None:
                        source = _apply_layout(parsed, layout)
                    editable_source = _parse(source.encode("utf-8")) if layout is not None else parsed
                    by_id = {block["id"]: block for block in editable_source.blocks}
                    if any(block_id not in by_id for block_id in changes):
                        raise EditError("Changes contain an unknown editable block ID")
                    for block in sorted((by_id[key] for key in changes), key=lambda item: item["start"], reverse=True):
                        source = source[:block["start"]] + escape(changes[block["id"]]) + source[block["end"]:]
                    if not changes and source == parsed.source:
                        raise EditError("Layout save contains no changes")
                    candidate = source.encode("utf-8")
                    result_parsed = self._candidate(report_id, candidate)
                    check()
                    if os.fstat(report_fd).st_dev != os.fstat(private_fd).st_dev:
                        raise EditError("Report recovery directory must share the source filesystem")
                    current, current_info = self._read_current(report_fd)
                    if current != content or _stamp(current_info) != _stamp(info):
                        raise EditConflict("Report changed before saving")
                    try:
                        previous = os.stat("index.previous.html", dir_fd=private_fd, follow_symlinks=False)
                        if not stat.S_ISREG(previous.st_mode):
                            raise EditError("Report recovery file must be a regular file")
                    except FileNotFoundError:
                        previous = None
                    try:
                        backup_temporary = self._temporary(private_fd, private_path, content, 0o600)
                        temporary = self._temporary(private_fd, private_path, candidate, stat.S_IMODE(info.st_mode))
                        check()
                        current, current_info = self._read_current(report_fd)
                        if current != content or _stamp(current_info) != _stamp(info):
                            raise EditConflict("Report changed before replacement")
                        try:
                            latest = os.stat("index.previous.html", dir_fd=private_fd, follow_symlinks=False)
                        except FileNotFoundError:
                            latest = None
                        if ((latest is None) != (previous is None)
                                or latest is not None and (not stat.S_ISREG(latest.st_mode)
                                                          or _stamp(latest) != _stamp(previous))):
                            raise EditConflict("Report recovery file changed during edit")
                        self._verify_temporary(private_fd, backup_temporary)
                        self._verify_temporary(private_fd, temporary)
                        os.replace(backup_temporary[0], "index.previous.html", src_dir_fd=private_fd, dst_dir_fd=private_fd)
                        backup_temporary = None
                        os.fsync(private_fd)
                        check()
                        current, current_info = self._read_current(report_fd)
                        if current != content or _stamp(current_info) != _stamp(info):
                            raise EditConflict("Report changed before replacement")
                        self._verify_temporary(private_fd, temporary)
                        os.replace(temporary[0], "index.html", src_dir_fd=private_fd, dst_dir_fd=report_fd)
                        temporary = None
                        os.fsync(report_fd)
                    finally:
                        if temporary is not None:
                            self._remove_temporary(private_fd, temporary)
                            temporary = None
                        if backup_temporary is not None:
                            self._remove_temporary(private_fd, backup_temporary)
                            backup_temporary = None
                    result = self._result(report_id, candidate, result_parsed)
                    result["backup"] = (private_path / "index.previous.html").relative_to(self.library.root).as_posix()
                    return result
        except EditError:
            raise
        except (ValueError, OSError, RecursionError) as exc:
            raise EditError(str(exc)) from exc
