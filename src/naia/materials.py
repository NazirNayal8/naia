"""Read-only project material rendering, matching the local NAIA card viewer."""
from __future__ import annotations

import html
import os
from pathlib import Path, PurePosixPath
import re
import stat
import urllib.parse
from typing import Any

from .discovery import is_excluded, _read, _SENSITIVE
from .storage import NAIAError

DARKPLUS_CSS = (
    "pre.hl{color:#d4d4d4}"
    "pre.hl .c{color:#6a9955}"            # comment
    "pre.hl .s{color:#ce9178}"            # string
    "pre.hl .n{color:#b5cea8}"            # number
    "pre.hl .kc{color:#c586c0}"           # control-flow keyword
    "pre.hl .k{color:#569cd6}"            # declaration keyword / constant
    "pre.hl .f{color:#dcdcaa}"            # function name
    "pre.hl .t{color:#4ec9b0}"            # class / type / yaml anchor
    "pre.hl .v{color:#9cdcfe}"            # variable / yaml key
    "pre.hl .d{color:#dcdcaa}"            # decorator
    "pre.hl .o{color:#d4d4d4}"            # operator / punctuation
)

PY_CONTROL = frozenset(
    "if elif else for while break continue return yield pass raise try except "
    "finally with as assert await async import from del match case".split()
)
PY_DECLARE = frozenset(
    "def class lambda and or not in is global nonlocal None True False".split()
)
PY_SOFT = frozenset(("self", "cls"))
# Builtin types and CapitalizedNames render teal in Dark+, including when called,
# so they take precedence over the call heuristic. ALL_CAPS stays a variable.
PY_TYPES = frozenset(
    "int str float bool bytes bytearray complex list dict set frozenset tuple "
    "object type range enumerate".split()
)

PYTHON_TOKENS = re.compile(
    r"(?P<comment>\#[^\n]*)"
    r"|(?P<string>[rRbBuUfF]{0,3}(?:\'\'\'(?:\\.|[^\\])*?\'\'\'"
    r"|\"\"\"(?:\\.|[^\\])*?\"\"\""
    r"|\'(?:\\.|[^\'\\\n])*\'|\"(?:\\.|[^\"\\\n])*\"))"
    r"|(?P<decorator>@[A-Za-z_][\w.]*)"
    r"|(?P<number>\b(?:0[xXbBoO][0-9a-fA-F_]+"
    r"|\d[\d_]*(?:\.[\d_]*)?(?:[eE][-+]?\d+)?[jJ]?)\b)"
    r"|(?P<name>[A-Za-z_]\w*)",
    re.S,
)


def highlight_python(text: str) -> str:
    parts: list[str] = []
    position = 0
    previous = ""
    for match in PYTHON_TOKENS.finditer(text):
        parts.append(html.escape(text[position:match.start()]))
        position = match.end()
        kind, value = match.lastgroup, match.group()
        if kind == "comment":
            css = "c"
        elif kind == "string":
            css = "s"
        elif kind == "decorator":
            css = "d"
        elif kind == "number":
            css = "n"
        elif previous == "def":
            css = "f"
        elif previous == "class":
            css = "t"
        elif value in PY_CONTROL:
            css = "kc"
        elif value in PY_DECLARE or value in PY_SOFT:
            css = "v" if value in PY_SOFT else "k"
        elif value in PY_TYPES or (value[:1].isupper() and not value.isupper()):
            css = "t"
        elif text[match.end():match.end() + 40].lstrip(" \t").startswith("("):
            css = "f"
        else:
            css = "v"
        previous = value if kind == "name" else ""
        parts.append(f'<span class="{css}">{html.escape(value)}</span>')
    parts.append(html.escape(text[position:]))
    return "".join(parts)


YAML_CONST = frozenset(
    "true false yes no on off null ~ True False Null NULL None".split()
)
YAML_NUMBER = re.compile(r"[-+]?(?:0[xX][0-9a-fA-F]+|\d[\d_]*\.?\d*(?:[eE][-+]?\d+)?)")
YAML_KEY = re.compile(
    r"^(?P<indent>[ \t]*)(?P<dash>(?:-[ \t]+)*)"
    r"(?P<key>\"[^\"]*\"|\'[^\']*\'|[^:#\n]+?)(?P<colon>[ \t]*:)(?P<rest>[ \t].*|)$"
)
YAML_ITEM = re.compile(r"^(?P<indent>[ \t]*)(?P<dash>-[ \t]*)(?P<rest>.*)$")
YAML_FLOW = re.compile(
    r"(?P<s>\"[^\"]*\"|\'[^\']*\')"
    r"|(?P<n>[-+]?\b\d[\d_]*\.?\d*(?:[eE][-+]?\d+)?\b)"
    r"|(?P<k>\b(?:true|false|null|yes|no)\b)"
    r"|(?P<o>[\[\]{},:])"
)


def _yaml_split_comment(line: str) -> tuple[str, str]:
    """Split a trailing ``#`` comment that is not inside a quoted scalar."""
    quote = ""
    for index, character in enumerate(line):
        if quote:
            if character == quote:
                quote = ""
        elif character in "\"\'":
            quote = character
        elif character == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index], line[index:]
    return line, ""


def _yaml_flow(value: str) -> str:
    parts: list[str] = []
    position = 0
    for match in YAML_FLOW.finditer(value):
        parts.append(html.escape(value[position:match.start()]))
        position = match.end()
        parts.append(f'<span class="{match.lastgroup}">{html.escape(match.group())}</span>')
    parts.append(html.escape(value[position:]))
    return "".join(parts)


def _yaml_value(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return html.escape(value)
    lead = value[: len(value) - len(value.lstrip())]
    tail = value[len(lead) + len(stripped):]
    if stripped[0] in "[{":
        return html.escape(lead) + _yaml_flow(stripped) + html.escape(tail)
    if stripped in YAML_CONST:
        css = "k"
    elif YAML_NUMBER.fullmatch(stripped):
        css = "n"
    elif stripped[0] in "&*":
        css = "t"
    elif stripped in {"|", ">", "|-", ">-", "|+", ">+"}:
        css = "o"
    else:
        css = "s"
    return f'{html.escape(lead)}<span class="{css}">{html.escape(stripped)}</span>{html.escape(tail)}'


def highlight_yaml(text: str) -> str:
    rendered: list[str] = []
    for line in text.split("\n"):
        body, comment = _yaml_split_comment(line)
        stripped = body.strip()
        if not stripped:
            piece = html.escape(body)
        elif stripped in {"---", "..."}:
            piece = f'<span class="o">{html.escape(body)}</span>'
        elif (match := YAML_KEY.match(body)) is not None:
            dash = f'<span class="o">{html.escape(match["dash"])}</span>' if match["dash"] else ""
            piece = (
                html.escape(match["indent"]) + dash
                + f'<span class="v">{html.escape(match["key"])}</span>'
                + f'<span class="o">{html.escape(match["colon"])}</span>'
                + _yaml_value(match["rest"])
            )
        elif (match := YAML_ITEM.match(body)) is not None and match["dash"]:
            piece = (
                html.escape(match["indent"])
                + f'<span class="o">{html.escape(match["dash"])}</span>'
                + _yaml_value(match["rest"])
            )
        else:
            piece = _yaml_value(body)
        rendered.append(piece + (f'<span class="c">{html.escape(comment)}</span>' if comment else ""))
    return "\n".join(rendered)


HIGHLIGHTERS = {"python": highlight_python, "yaml": highlight_yaml}
LANGUAGE_BY_SUFFIX = {".py": "python", ".yaml": "yaml", ".yml": "yaml"}
LANGUAGE_ALIASES = {"py": "python", "python": "python", "yaml": "yaml", "yml": "yaml"}


def highlight_block(code: str, language: str | None) -> str:
    """Return highlighted HTML for a supported language, else escaped text."""
    function = HIGHLIGHTERS.get(LANGUAGE_ALIASES.get((language or "").lower(), ""))
    return function(code) if function else html.escape(code)


MAX_MATERIAL_BYTES = 2 * 1024 * 1024
SENSITIVE = _SENSITIVE
MATHJAX_ROOT = Path(os.environ.get("NAIA_MATHJAX_ROOT", "/usr/share/javascript/mathjax")).resolve()


class MaterialRenderer:
    def __init__(self, project):
        self.project = project

    def read_bytes(self, relative):
        if (not isinstance(relative, str) or not relative or relative.startswith(("/", "\\"))
                or "\\" in relative or any(part in ("", ".", "..") for part in relative.split("/"))):
            raise NAIAError("Material must use a relative project path")
        parts = PurePosixPath(relative).parts
        if (relative.lower() == ".lab/project.json" or relative.lower().startswith(".lab/state/")
                or any(part.startswith(".") and part != ".lab" for part in parts)
                or any(SENSITIVE.search(part) for part in parts)
                or PurePosixPath(relative).suffix.lower() in (".pem", ".key", ".p12", ".pfx")
                or is_excluded(relative, self.project._exclusions(self.project.load()))):
            raise NAIAError("Material is sensitive or excluded")
        target = self.project.path(relative)
        if not target.is_file():
            raise NAIAError("Material must be a file")
        if hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd:
            root_fd = os.open(self.project.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                raw, partial = _read(root_fd, relative, MAX_MATERIAL_BYTES + 1)
            finally:
                os.close(root_fd)
        else:
            # Unsupported platforms still reject symlinks rather than following them.
            if any((self.project.root.joinpath(*parts[:i])).is_symlink() for i in range(1, len(parts) + 1)):
                raise NAIAError("Symlink materials are not supported")
            with target.open("rb") as stream:
                raw = stream.read(MAX_MATERIAL_BYTES + 1)
            partial = len(raw) > MAX_MATERIAL_BYTES
        if partial or len(raw) > MAX_MATERIAL_BYTES:
            raise NAIAError("Material exceeds the 2 MiB viewer limit")
        return raw

    def read_text(self, relative):
        try:
            value = self.read_bytes(relative).decode("utf-8")
        except UnicodeError as exc:
            raise NAIAError("Material is not UTF-8 text") from exc
        if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
            raise NAIAError("Binary material cannot be rendered as text")
        return value

    def material_url(self, target, source):
        target = target.strip()
        if target.startswith("report:"):
            from .reports import valid_id
            try:
                report_id = valid_id(target[len("report:"):])
            except ValueError:
                return "#"
            return "/report?id=" + urllib.parse.quote(report_id)
        parsed = urllib.parse.urlparse(target)
        if parsed.scheme:
            return target if parsed.scheme in ("http", "https", "mailto") else "#"
        if target.startswith("#"):
            return target
        if target.startswith("//"):
            return "#"
        path_text, separator, fragment = target.partition("#")
        candidate = Path(urllib.parse.unquote(path_text))
        resolved = candidate.resolve() if candidate.is_absolute() else (source.parent / candidate).resolve()
        if not resolved.is_relative_to(self.project.root):
            return "#"
        relative = resolved.relative_to(self.project.root).as_posix()
        report_target = self.project.reports().match_path(relative)
        if report_target is not None and report_target[1] == "index.html":
            return "/report?id=" + urllib.parse.quote(report_target[0])
        route = "/asset" if resolved.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf") else "/material"
        url = route + "?path=" + urllib.parse.quote(relative)
        return url + ("#" + urllib.parse.quote(fragment) if separator else "")

    def math_head(self):
        if not (MATHJAX_ROOT / "MathJax.js").is_file():
            return ""
        return '<script src="/mathjax-config.js"></script><script src="/mathjax/MathJax.js?config=TeX-AMS_SVG-full"></script>'


    def render_inline_markdown(self, value: str, source: Path) -> str:
        tokens: list[str] = []

        def stash(value: str) -> str:
            tokens.append(value)
            return f"@@SECRETARYTOKEN{len(tokens) - 1}@@"

        value = re.sub(
            r"`([^`]+)`",
            lambda match: stash(f"<code>{html.escape(match.group(1))}</code>"),
            value,
        )

        def inline_math(match: re.Match[str]) -> str:
            expression = match.group(1) if match.group(1) is not None else match.group(2)
            return stash(f'<span class="math-inline">\\({html.escape(expression)}\\)</span>')

        # Stash math before Markdown emphasis so TeX subscripts remain intact.
        value = re.sub(r"\\\((.+?)\\\)|(?<!\$)\$([^$\n]+?)\$(?!\$)", inline_math, value)

        def image(match: re.Match[str]) -> str:
            alt, target = match.group(1), match.group(2)
            url = html.escape(self.material_url(target, source), quote=True)
            return stash(f'<img src="{url}" alt="{html.escape(alt, quote=True)}" loading="lazy">')

        def link(match: re.Match[str]) -> str:
            label, target = match.group(1), match.group(2)
            url = html.escape(self.material_url(target, source), quote=True)
            external = ' target="_blank" rel="noopener"' if target.startswith(("http://", "https://")) else ""
            return stash(f'<a href="{url}"{external}>{html.escape(label)}</a>')

        value = re.sub(r"!\[([^]]*)\]\(([^)]+)\)", image, value)
        value = re.sub(r"\[([^]]+)\]\(([^)]+)\)", link, value)
        value = html.escape(value)
        value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
        value = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", value)
        value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", value)
        value = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"<em>\1</em>", value)
        for index, token in enumerate(tokens):
            value = value.replace(f"@@SECRETARYTOKEN{index}@@", token)
        return value

    def render_markdown(self, value: str, source: Path) -> str:
        """Render the repo's research Markdown with a small, dependency-free subset."""
        lines = value.expandtabs(4).splitlines()
        output: list[str] = []
        index = 0

        def is_table_separator(line: str) -> bool:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            return len(cells) > 1 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)

        def cells(line: str) -> list[str]:
            return [cell.strip() for cell in line.strip().strip("|").split("|")]

        def starts_block(position: int) -> bool:
            line = lines[position]
            stripped = line.strip()
            if not stripped:
                return True
            if (
                re.match(r"^(#{1,6})\s+", stripped)
                or stripped.startswith("```")
                or stripped.startswith("$$")
                or stripped.startswith(r"\[")
            ):
                return True
            if re.match(r"^([-*_])(?:\s*\1){2,}$", stripped):
                return True
            if re.match(r"^\s*([-+*]|\d+[.)])\s+", line) or stripped.startswith(">"):
                return True
            return position + 1 < len(lines) and "|" in line and is_table_separator(lines[position + 1])

        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if not stripped:
                index += 1
                continue
            if stripped.startswith("$$") or stripped.startswith(r"\["):
                dollar_delimited = stripped.startswith("$$")
                opener = "$$" if dollar_delimited else r"\["
                closer = "$$" if dollar_delimited else r"\]"
                first = stripped[len(opener) :]
                math_lines: list[str] = []
                if closer in first:
                    math_lines.append(first.split(closer, 1)[0])
                    index += 1
                else:
                    if first:
                        math_lines.append(first)
                    index += 1
                    while index < len(lines):
                        current = lines[index]
                        if closer in current:
                            math_lines.append(current.split(closer, 1)[0])
                            index += 1
                            break
                        math_lines.append(current)
                        index += 1
                expression = html.escape(chr(10).join(math_lines).strip())
                output.append(f'<div class="math-display">\\[{expression}\\]</div>')
                continue
            if stripped.startswith("```"):
                language = stripped[3:].strip()
                index += 1
                code: list[str] = []
                while index < len(lines) and not lines[index].strip().startswith("```"):
                    code.append(lines[index])
                    index += 1
                index += index < len(lines)
                language_class = f' class="language-{html.escape(language, quote=True)}"' if language else ""
                body = highlight_block(chr(10).join(code), language)
                output.append(f'<pre class="hl"><code{language_class}>{body}</code></pre>')
                continue
            heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading:
                level = len(heading.group(1))
                content = self.render_inline_markdown(heading.group(2), source)
                anchor = re.sub(r"[^a-z0-9]+", "-", heading.group(2).lower()).strip("-")
                output.append(f'<h{level} id="{html.escape(anchor, quote=True)}">{content}</h{level}>')
                index += 1
                continue
            if re.match(r"^([-*_])(?:\s*\1){2,}$", stripped):
                output.append("<hr>")
                index += 1
                continue
            if index + 1 < len(lines) and "|" in line and is_table_separator(lines[index + 1]):
                headers = cells(line)
                index += 2
                rows: list[list[str]] = []
                while index < len(lines) and "|" in lines[index] and lines[index].strip():
                    rows.append(cells(lines[index]))
                    index += 1
                head = "".join(f"<th>{self.render_inline_markdown(cell, source)}</th>" for cell in headers)
                body = "".join(
                    "<tr>" + "".join(f"<td>{self.render_inline_markdown(cell, source)}</td>" for cell in row) + "</tr>"
                    for row in rows
                )
                output.append(f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
                continue
            list_match = re.match(r"^\s*([-+*]|\d+[.)])\s+(.+)$", line)
            if list_match:
                ordered = list_match.group(1)[0].isdigit()
                tag = "ol" if ordered else "ul"
                entries: list[str] = []
                while index < len(lines):
                    match = re.match(r"^\s*([-+*]|\d+[.)])\s+(.+)$", lines[index])
                    if not match or match.group(1)[0].isdigit() != ordered:
                        break
                    entries.append(f"<li>{self.render_inline_markdown(match.group(2), source)}</li>")
                    index += 1
                output.append(f"<{tag}>{''.join(entries)}</{tag}>")
                continue
            if stripped.startswith(">"):
                quoted: list[str] = []
                while index < len(lines) and lines[index].strip().startswith(">"):
                    quoted.append(lines[index].strip()[1:].lstrip())
                    index += 1
                output.append(f"<blockquote>{self.render_markdown(chr(10).join(quoted), source)}</blockquote>")
                continue
            paragraph = [stripped]
            index += 1
            while index < len(lines) and not starts_block(index):
                paragraph.append(lines[index].strip())
                index += 1
            output.append(f"<p>{self.render_inline_markdown(' '.join(paragraph), source)}</p>")
        return "\n".join(output)

    def render_material_page(self, source: Path) -> bytes:
        source = source.resolve()
        value = self.read_text(source.relative_to(self.project.root).as_posix())
        if source.suffix.lower() in {".md", ".markdown"}:
            content = self.render_markdown(value, source)
        else:
            language = LANGUAGE_BY_SUFFIX.get(source.suffix.lower())
            content = f'<pre class="hl">{highlight_block(value, language)}</pre>'
        relative = source.relative_to(self.project.root).as_posix()
        math_head = self.math_head()
        return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{html.escape(source.name)}</title>{math_head}<style>
    :root{{color-scheme:dark;--bg:#181818;--paper:#1f1f1f;--ink:#d4d4d4;--muted:#9d9d9d;--line:#3c3c3c;--accent:#4daafc;--soft:#252526}}
    *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.68 -apple-system,BlinkMacSystemFont,"Segoe UI",ui-sans-serif,system-ui,sans-serif}}
    .bar{{position:sticky;top:0;z-index:2;padding:10px max(20px,calc((100vw - 920px)/2));background:#181818ee;border-bottom:1px solid var(--line);backdrop-filter:blur(10px);display:flex;gap:14px;align-items:center}}
    .bar a{{font-weight:700}} .path{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font:13px ui-monospace,monospace}}
    article{{max-width:920px;margin:26px auto 70px;padding:38px 50px;background:var(--paper);border:1px solid var(--line);border-radius:18px;box-shadow:0 12px 35px #0006}}
    h1,h2,h3,h4{{line-height:1.22;margin:1.65em 0 .55em;font-family:ui-serif,Georgia,serif}} h1{{font-size:2.25em;margin-top:0}} h2{{font-size:1.6em;border-bottom:1px solid var(--line);padding-bottom:.25em}} h3{{font-size:1.25em}}
    p{{margin:.8em 0}} a{{color:var(--accent)}} code{{background:#2d2d30;color:#dcdcaa;border-radius:5px;padding:.12em .35em;font-size:.88em}} pre{{overflow:auto;background:#151515;color:#d4d4d4;padding:18px;border:1px solid #333;border-radius:11px;line-height:1.5}} pre code{{background:none;color:inherit;padding:0}}
    {DARKPLUS_CSS}
    blockquote{{border-left:4px solid #3794ff;margin:1.2em 0;padding:.1em 1.1em;color:#c5c5c5;background:#252526}} .table-wrap{{overflow:auto;margin:1.2em 0}} table{{width:100%;border-collapse:collapse;font-size:.93em}} th,td{{padding:9px 12px;border:1px solid var(--line);vertical-align:top}} th{{background:#2d2d30;color:#f0f0f0;text-align:left}} tr:nth-child(even){{background:#242424}} img{{display:block;max-width:100%;height:auto;margin:22px auto;border-radius:10px}} hr{{border:0;border-top:1px solid var(--line);margin:2em 0}}
    .math-inline{{white-space:nowrap}} .math-display{{overflow-x:auto;overflow-y:hidden;margin:1.1em 0;padding:.45em 0;text-align:center}} .math-display .MathJax_SVG_Display{{margin:0!important}}
    @media(max-width:720px){{article{{margin:0;border:0;border-radius:0;padding:26px 20px}}.bar{{padding:10px 16px}}}}
    </style></head><body><nav class="bar"><a href="/">← NAIA</a><span class="path">{html.escape(relative)}</span></nav><article>{content}</article></body></html>""".encode()
