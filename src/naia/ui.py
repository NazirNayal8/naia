"""Loopback-only browser UI. No CDN, public binding, or arbitrary command endpoint."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import secrets
from urllib.parse import parse_qs, urlparse

from .architectures import Architectures
from .storage import NAIAError, read_json
from .suites import Suites
from .tasks import Tasks


def handler(project, token):
    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, content_type="application/json", *, embeddable=False):
            content = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            ancestors = "'self'" if embeddable else "'none'"
            self.send_header("Content-Security-Policy", f"default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-src 'self'; frame-ancestors {ancestors}")
            self.end_headers()
            self.wfile.write(content)

        def host_valid(self):
            host = self.headers.get("Host", "")
            return host in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def do_GET(self):
            if not self.host_valid():
                return self.send(403, {"error": "Unexpected Host"})
            request_url = urlparse(self.path)
            path = request_url.path
            if path == "/api/state":
                try:
                    registry_path = project.directory / "state/registry.json"
                    suites = read_json(registry_path)["suites"]
                    cards = {s["id"]: project.path(s["card"]).read_text() for s in suites}
                    return self.send(200, {"tasks": Tasks(project).load(), "suites": suites,
                                          "cards": cards, "architectures": Architectures(project).list(),
                                          "context": project.load(), "token": token})
                except (NAIAError, OSError) as exc:
                    return self.send(400, {"error": str(exc)})
            if path == "/api/architecture":
                try:
                    query = parse_qs(request_url.query, keep_blank_values=True)
                    if set(query) != {"id"} or len(query["id"]) != 1 or not query["id"][0]:
                        raise NAIAError("A registered architecture ID is required")
                    return self.send(200, Architectures(project).graph(query["id"][0]))
                except (NAIAError, OSError, ValueError) as exc:
                    return self.send(400, {"error": str(exc)})
            lens_assets = {"/architecture": ("index.html", "text/html; charset=utf-8"),
                           "/architecture/": ("index.html", "text/html; charset=utf-8"),
                           "/architecture/viewer.js": ("viewer.js", "text/javascript; charset=utf-8"),
                           "/architecture/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in lens_assets:
                filename, mime = lens_assets[path]
                content = files("naia_arch").joinpath("assets", filename).read_bytes()
                if filename == "index.html":
                    content = content.replace(b'href="/style.css"', b'href="/architecture/style.css"')
                    content = content.replace(b'src="/viewer.js"', b'src="/architecture/viewer.js"')
                return self.send(200, content, mime, embeddable=filename == "index.html")
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path not in assets:
                return self.send(404, {"error": "Not found"})
            filename, mime = assets[path]
            return self.send(200, files("naia").joinpath("assets", filename).read_bytes(), mime)

        def do_POST(self):
            origin = self.headers.get("Origin")
            allowed_origin = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
            session_token = self.headers.get("X-NAIA-Token", self.headers.get("X-Lab-Token"))
            if not self.host_valid() or origin not in allowed_origin or session_token != token:
                return self.send(403, {"error": "Local origin and session token required"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise NAIAError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                if self.path == "/api/task":
                    result = Tasks(project).action(data["id"], data["action"], note=data.get("note", ""), owner=data.get("owner"))
                elif self.path == "/api/sync":
                    result = Suites(project).sync()
                else:
                    return self.send(404, {"error": "Not found"})
                return self.send(200, result)
            except (NAIAError, ValueError, KeyError, TypeError) as exc:
                return self.send(400, {"error": str(exc)})
    return Handler


def serve(project, port=8767):
    server = ThreadingHTTPServer(("127.0.0.1", port), handler(project, secrets.token_urlsafe(32)))
    print(f"NAIA: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
