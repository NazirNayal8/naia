"""Standalone capture in the model environment, or graph viewing without torch."""
import argparse
import importlib
from importlib.resources import files
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys

from .schema import validate_graph
from ._semantics import MAX_SEMANTICS_BYTES, _json, annotate_graph, parse_semantics


MAX_ALIASES_BYTES = 64 * 1024


def parse_aliases(value):
    """Read labels only; never import configuration or execute it as Python."""
    if value is None:
        return {}
    if value.startswith("@"):
        if not value[1:]:
            raise ValueError("--aliases requires JSON or @FILE")
        with Path(value[1:]).open("rb") as stream:
            content = stream.read(MAX_ALIASES_BYTES + 1)
    else:
        content = value.encode("utf-8")
    if len(content) > MAX_ALIASES_BYTES:
        raise ValueError("Alias mapping exceeds the 64 KiB limit")

    def unique_object(pairs):
        result = {}
        for key, label in pairs:
            if key in result:
                raise ValueError(f"Duplicate alias module path: {key}")
            result[key] = label
        return result

    def reject_constant(constant):
        raise ValueError(f"Alias mapping contains non-finite JSON: {constant}")

    aliases = json.loads(content, object_pairs_hook=unique_object, parse_constant=reject_constant)
    if not isinstance(aliases, dict) or any(
        not isinstance(path, str) or any(ord(character) < 32 for character in path)
        or not isinstance(label, str) or not label.strip() or any(ord(character) < 32 for character in label)
        for path, label in aliases.items()
    ):
        raise ValueError("--aliases must map module paths to nonempty, single-line labels")
    return aliases


def make_handler(graph):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Host") not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
                self.send_error(403)
                return
            assets = {"/": ("index.html", "text/html"), "/viewer.js": ("viewer.js", "text/javascript"),
                      "/blocks.js": ("blocks.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
            if self.path == "/graph.json":
                content, mime = json.dumps(graph, allow_nan=False).encode(), "application/json"
            elif self.path in assets:
                filename, mime = assets[self.path]
                content = files("naia_arch").joinpath("assets", filename).read_bytes()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(content)
    return Handler


def add_graph_commands(p):
    commands = p.add_subparsers(dest="action", required=True)
    view = commands.add_parser("view")
    view.add_argument("graph")
    view.add_argument("--port", type=int, default=8768)
    validate = commands.add_parser("validate")
    validate.add_argument("graph")
    annotate = commands.add_parser("annotate", help="Add cited module/boundary names to an unchanged capture")
    annotate.add_argument("graph")
    annotate.add_argument("--semantics", required=True, metavar="JSON|@FILE",
                          help="Exact node IDs mapped to name, evidence citations, and optional role")
    annotate.add_argument("--output", required=True, help="New graph filename; existing files are never overwritten")
    capture = commands.add_parser("capture")
    capture.add_argument("--factory", required=True, help="Trusted module:function returning (model, example_args, example_kwargs)")
    capture.add_argument("--output", required=True)
    evidence = capture.add_mutually_exclusive_group()
    evidence.add_argument("--trace", dest="trace", action="store_true", default=True,
                          help="Capture sample tensor dependencies (default; retained compatibility flag)")
    evidence.add_argument("--no-trace", dest="trace", action="store_false",
                          help="Record sample calls and shapes without tensor dependency capture")
    evidence.add_argument("--structure-only", action="store_true",
                          help="Record module hierarchy only; do not run the sample forward")
    capture.add_argument("--aliases", metavar="JSON|@FILE",
                         help='Module-path labels, for example {"encoder":"Token encoder"} or @labels.json')
    capture.add_argument("--semantics", metavar="JSON|@FILE",
                         help="Explicit cited descriptions for exact module/input/output node IDs")
    return commands


def parser():
    p = argparse.ArgumentParser(prog="naia-arch", description="Config-independent architecture viewer (development alpha)")
    add_graph_commands(p)
    return p


def _write_graph(output, graph):
    # Serialize before creating the destination; invalid JSON cannot leave a
    # partial graph. Exclusive creation also closes the output-exists race.
    content = json.dumps(graph, indent=2, allow_nan=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(content)


def dispatch(args):
    """Also used by `naia arch`; graph commands do not require project onboarding."""
    try:
        if args.action == "annotate":
            output = Path(args.output)
            if output.exists() or output.is_symlink():
                raise ValueError("Output exists; choose a new graph filename")
            semantics = parse_semantics(args.semantics)
            graph = validate_graph(_json(Path(args.graph).read_text(encoding="utf-8")))
            graph = annotate_graph(graph, semantics)
            _write_graph(output, graph)
            print(json.dumps({"graph": str(output), "annotated": len(semantics)}))
            return 0
        if args.action == "capture":
            from . import capture as capture_model
            output = Path(args.output)
            if output.exists() or output.is_symlink():
                raise ValueError("Output exists; choose a new graph filename")
            aliases = parse_aliases(getattr(args, "aliases", None))
            semantics = parse_semantics(getattr(args, "semantics", None))
            module, separator, function = args.factory.partition(":")
            if not separator or not module or not function:
                raise ValueError("Factory must be module:function")
            sys.path.insert(0, str(Path.cwd()))
            model, example_args, example_kwargs = getattr(importlib.import_module(module), function)()
            structure_only = getattr(args, "structure_only", False)
            options = {"trace": False if structure_only else args.trace, "aliases": aliases}
            if semantics is not None:
                options["semantics"] = semantics
            graph = capture_model(model, None if structure_only else example_args,
                                  None if structure_only else example_kwargs,
                                  **options)
            _write_graph(output, graph)
            print(json.dumps({"graph": str(output), "mode": graph["capture_mode"]}))
            return 0
        graph = validate_graph(json.loads(Path(args.graph).read_text()))
        if args.action == "validate":
            print(json.dumps({"valid": True, "nodes": len(graph["nodes"])}))
            return 0
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(graph))
        print(f"NAIA Lens: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, AttributeError, TypeError, RecursionError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    return dispatch(args)


if __name__ == "__main__":
    raise SystemExit(main())
