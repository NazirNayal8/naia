"""Standalone capture in the model environment, or graph viewing without torch."""
import argparse
import importlib
from importlib.resources import files
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys

from .schema import validate_graph


def make_handler(graph):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Host") not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
                self.send_error(403)
                return
            assets = {"/": ("index.html", "text/html"), "/viewer.js": ("viewer.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
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
    capture = commands.add_parser("capture")
    capture.add_argument("--factory", required=True, help="Trusted module:function returning (model, example_args, example_kwargs)")
    capture.add_argument("--output", required=True)
    capture.add_argument("--trace", action="store_true")
    return commands


def parser():
    p = argparse.ArgumentParser(prog="naia-arch", description="Config-independent architecture viewer (development alpha)")
    add_graph_commands(p)
    return p


def dispatch(args):
    """Also used by `naia arch`; graph commands do not require project onboarding."""
    try:
        if args.action == "capture":
            from . import capture as capture_model
            output = Path(args.output)
            if output.exists():
                raise ValueError("Output exists; choose a new graph filename")
            module, separator, function = args.factory.partition(":")
            if not separator:
                raise ValueError("Factory must be module:function")
            sys.path.insert(0, str(Path.cwd()))
            model, example_args, example_kwargs = getattr(importlib.import_module(module), function)()
            graph = capture_model(model, example_args, example_kwargs, trace=args.trace)
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as stream:
                json.dump(graph, stream, indent=2, allow_nan=False)
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
