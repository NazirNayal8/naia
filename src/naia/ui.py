"""Loopback-only browser UI. No CDN, public binding, or arbitrary command endpoint."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import mimetypes
import secrets
from urllib.parse import parse_qs, urlparse, unquote

from .architectures import Architectures
from .materials import MaterialRenderer, MATHJAX_ROOT
from .storage import NAIAError, read_json
from .suites import Suites, UI_STATUSES
from .tasks import Tasks
from .reports import ReportError, report_csp, KIT_JS_ROUTE, KIT_CSS_ROUTE
from .report_view import viewer_html


def handler(project, token, *, reports_root=None):
    reports = project.reports(reports_root)
    def state():
        registry_path = project.directory / "state/registry.json"
        suites = read_json(registry_path)["suites"]
        renderer = MaterialRenderer(project)
        cards, projected = {}, []
        for suite in suites:
            item = {**suite, "card_url": "/suite-card?id=" + suite["id"]}
            try:
                cards[suite["id"]] = renderer.read_text(suite["card"])
                item["card_available"] = True
            except (NAIAError, OSError) as exc:
                item.update(card_available=False, card_error=str(exc))
            projected.append(item)
        suites = projected
        tasks = Tasks(project)
        focus = tasks.next()
        return {"tasks": tasks.load(), "suites": suites, "cards": cards,
                "architectures": Architectures(project).list(), "context": project.context_view(),
                "suite_statuses": UI_STATUSES, "focus_id": focus["id"] if focus else "", "token": token}

    def task_action(data):
        tasks = Tasks(project)
        action = data.get("action")
        if not isinstance(action, str):
            raise NAIAError("A task action is required")
        if action in ("add", "edit"):
            allowed = {"action", "id", "title", "goal", "decision", "owner", "type", "materials", "depends_on", "placement"}
            if set(data) - allowed:
                raise NAIAError("Unknown task fields")
            fields = {"title": data["title"], "goal": data["goal"], "decision": data["decision"],
                      "owner": data.get("owner", "unassigned"), "task_type": data.get("type", "task"),
                      "dependencies": data.get("depends_on", []), "materials": data.get("materials", []),
                      "placement": data.get("placement", "bottom" if action == "add" else "keep")}
            return (tasks.add if action == "add" else tasks.edit)(data["id"], **fields)
        if action == "reorder":
            if set(data) - {"action", "ordered_ids"}:
                raise NAIAError("Unknown reorder fields")
            return tasks.reorder(data["ordered_ids"])
        if set(data) - {"action", "id", "note", "owner", "placement"}:
            raise NAIAError("Unknown task fields")
        if action == "resolve":
            task_id = data.get("id")
            if task_id is not None:
                return tasks.action(task_id, "done", note=data.get("note", ""))
            item = tasks.next()
            if not item:
                raise NAIAError("No open tasks to resolve")
            return tasks.action(item["id"], "done", note=data.get("note", ""))
        return tasks.action(data["id"], action, note=data.get("note", ""), owner=data.get("owner"),
                            placement=data.get("placement", "bottom"))

    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, content_type="application/json", *, embeddable=False, csp=None):
            content = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            ancestors = "'self'" if embeddable else "'none'"
            self.send_header("Content-Security-Policy", csp or f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; frame-src 'self'; frame-ancestors {ancestors}")
            self.send_header("Referrer-Policy", "no-referrer")
            if csp is not None and content_type.startswith("font/"):
                self.send_header("Access-Control-Allow-Origin", "null")
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
            if path.startswith("/api/") and self.headers.get("Origin") not in (
                    None, f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"):
                return self.send(403, {"error": "Local API origin required"})
            kit_assets = {KIT_JS_ROUTE: ("report_kit.js", "text/javascript; charset=utf-8"),
                          KIT_CSS_ROUTE: ("report_kit.css", "text/css; charset=utf-8")}
            if path in kit_assets:
                filename, mime = kit_assets[path]
                asset = files("naia").joinpath("assets", filename)
                if not asset.is_file():
                    return self.send(404, {"error": "Report kit asset is unavailable"})
                return self.send(200, asset.read_bytes(), mime)
            if path in ("/api/reports", "/report") or path.startswith("/reports/"):
                try:
                    query = parse_qs(request_url.query, keep_blank_values=True)
                    if path == "/api/reports":
                        if set(query) - {"q", "tag"} or len(query.get("q", [])) > 1:
                            raise ReportError("Expected one query and repeatable tag filters")
                        return self.send(200, reports.search(query.get("q", [""])[0], query.get("tag", [])))
                    if path == "/report":
                        if len(query.get("id", [])) != 1 or not query["id"][0]:
                            raise ReportError("One report ID is required")
                        return self.send(200, viewer_html(reports.get(query["id"][0])).encode(), "text/html; charset=utf-8")
                    report_id, separator, filename = unquote(path[len("/reports/"):]).partition("/")
                    if not separator or query:
                        raise ReportError("One report asset is required")
                    body, mime = reports.asset(report_id, filename)
                    return self.send(200, body, mime, embeddable=True,
                                     csp=report_csp(f"http://{self.headers['Host']}", f"/reports/{report_id}/"))
                except (ReportError, OSError, ValueError) as exc:
                    return self.send(404, {"error": str(exc)})
            if path == "/api/state":
                try:
                    return self.send(200, state())
                except (NAIAError, OSError) as exc:
                    return self.send(400, {"error": str(exc)})
            if path == "/api/archive":
                try:
                    return self.send(200, Tasks(project).archive())
                except (NAIAError, OSError) as exc:
                    return self.send(400, {"error": str(exc)})
            if path in ("/suite-card", "/material", "/asset"):
                try:
                    query = parse_qs(request_url.query, keep_blank_values=True)
                    key = "id" if path == "/suite-card" else "path"
                    if set(query) != {key} or len(query[key]) != 1 or not query[key][0]:
                        raise NAIAError("One material path or suite ID is required")
                    relative = (str((Suites(project).location(query[key][0]) / "card.md").relative_to(project.root))
                                if path == "/suite-card" else query[key][0])
                    renderer = MaterialRenderer(project)
                    report_target = reports.match_path(relative)
                    if report_target is not None:
                        report_id, filename = report_target
                        body, mime = reports.asset(report_id, filename)
                        if path != "/asset" and filename == "index.html":
                            return self.send(200, viewer_html(reports.get(report_id)).encode(), "text/html; charset=utf-8")
                        return self.send(200, body, mime, embeddable=True,
                                         csp=report_csp(f"http://{self.headers['Host']}", f"/reports/{report_id}/"))
                    if path == "/asset":
                        target = project.path(relative)
                        if target.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"):
                            raise NAIAError("Only raster images and PDFs are served as assets")
                        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                        return self.send(200, renderer.read_bytes(relative), mime, embeddable=True)
                    renderer.read_text(relative)  # Validate the original URL path before resolving it.
                    return self.send(200, renderer.render_material_page(project.path(relative)),
                                     "text/html; charset=utf-8", embeddable=True)
                except (NAIAError, ReportError, OSError, ValueError) as exc:
                    return self.send(400, {"error": str(exc)})
            if path == "/mathjax-config.js":
                config = r'''window.MathJax={messageStyle:"none",showMathMenu:false,tex2jax:{inlineMath:[["$","$"],["\\(","\\)"]],displayMath:[["$$","$$"],["\\[","\\]"]],processEscapes:true,skipTags:["script","noscript","style","textarea","pre","code"]},SVG:{font:"TeX"}};'''
                return self.send(200, config.encode(), "text/javascript; charset=utf-8")
            if path.startswith("/mathjax/"):
                try:
                    target = (MATHJAX_ROOT / unquote(path[len("/mathjax/"):])).resolve()
                    if not target.is_relative_to(MATHJAX_ROOT) or not target.is_file():
                        raise NAIAError("Invalid MathJax asset path")
                    return self.send(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")
                except (NAIAError, OSError) as exc:
                    return self.send(404, {"error": str(exc)})
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
                           "/architecture/blocks.js": ("blocks.js", "text/javascript; charset=utf-8"),
                           "/architecture/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in lens_assets:
                filename, mime = lens_assets[path]
                content = files("naia_arch").joinpath("assets", filename).read_bytes()
                if filename == "index.html":
                    content = content.replace(b'href="/style.css"', b'href="/architecture/style.css"')
                    content = content.replace(b'src="/viewer.js"', b'src="/architecture/viewer.js"')
                    content = content.replace(b'src="/blocks.js"', b'src="/architecture/blocks.js"')
                return self.send(200, content, mime, embeddable=filename == "index.html")
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/archive": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8"),
                      "/reports.js": ("reports.js", "text/javascript; charset=utf-8"),
                      "/reports_viewer.js": ("reports_viewer.js", "text/javascript; charset=utf-8"),
                      "/reports.css": ("reports.css", "text/css; charset=utf-8")}
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
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                return self.send(415, {"error": "JSON content type required"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise NAIAError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise NAIAError("Request body must be a JSON object")
                if self.path in ("/api/task", "/api/action"):
                    item = task_action(data)
                    tasks = Tasks(project)
                    focus = tasks.next()
                    result = {"ok": True, "item": item, "tasks": tasks.load(), "focus_id": focus["id"] if focus else ""}
                elif self.path == "/api/suite-status":
                    if set(data) - {"id", "status", "by"}:
                        raise NAIAError("Unknown suite status fields")
                    actor = data.get("by") or project.load().get("onboarding", {}).get("confirmed_by")
                    suite = Suites(project).set_status(data["id"], data["status"], actor)
                    result = {"ok": True, "suite": suite, "suites": state()["suites"]}
                elif self.path == "/api/sync":
                    result = Suites(project).sync()
                else:
                    return self.send(404, {"error": "Not found"})
                return self.send(200, result)
            except (NAIAError, OSError, ValueError, KeyError, TypeError) as exc:
                return self.send(400, {"error": str(exc)})
    return Handler


def serve(project, port=8767, *, reports_root=None):
    server = ThreadingHTTPServer(("127.0.0.1", port), handler(project, secrets.token_urlsafe(32), reports_root=reports_root))
    print(f"NAIA: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
