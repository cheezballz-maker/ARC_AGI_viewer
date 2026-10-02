"""A localhost-only, dependency-free server for the ARC workspace."""

from __future__ import annotations

import argparse
import json
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if __package__:
    from .workspace import BASE, NOTEBOOK_FIELDS, STATUSES, Catalog, Notebook, validate_evidence
else:
    from workspace import BASE, NOTEBOOK_FIELDS, STATUSES, Catalog, Notebook, validate_evidence


def create_server(catalog: Catalog, notebook: Notebook, port: int = 0) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, value, status=200, content_type="application/json; charset=utf-8"):
            data = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def do_GET(self):
            if not self.valid_host():
                return self.respond({"error": "Invalid host."}, 403)
            parsed = urlparse(self.path)
            if parsed.path == "/":
                html = (BASE / "web" / "index.html").read_text(encoding="utf-8").replace("__SESSION_TOKEN__", token)
                return self.respond(html.encode("utf-8"), content_type="text/html; charset=utf-8")
            assets = {"/app.js": "text/javascript", "/style.css": "text/css"}
            if parsed.path in assets:
                return self.respond((BASE / "web" / parsed.path[1:]).read_bytes(), content_type=assets[parsed.path] + "; charset=utf-8")
            if parsed.path == "/favicon.ico":
                return self.respond(b"", 204)
            if self.headers.get("X-Workspace-Token") != token:
                return self.respond({"error": "Refresh the workspace to reconnect."}, 403)
            if parsed.path == "/api/library":
                return self.respond({"problems": catalog.index(), "annotations": notebook.snapshot(), "notebook_fields": NOTEBOOK_FIELDS, "review_statuses": STATUSES, "warnings": catalog.warnings, "migrated": notebook.migrated})
            if parsed.path == "/api/problem":
                problem_id = parse_qs(parsed.query).get("id", [""])[0]
                with catalog.lock:
                    problem = catalog.problems.get(problem_id)
                    return self.respond(problem["task"] if problem else {"error": "Problem not found."}, 200 if problem else 404)
            return self.respond({"error": "Not found."}, 404)

        def do_POST(self):
            if not self.valid_host() or self.headers.get("X-Workspace-Token") != token:
                return self.respond({"error": "Refresh the workspace to reconnect."}, 403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4_000_000:
                    raise ValueError("Request must be under 4 MB.")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object.")
                if self.path == "/api/annotate":
                    ids = data.get("ids")
                    if not isinstance(ids, list) or not ids or any(not isinstance(key, str) or key not in catalog.problems for key in ids):
                        raise ValueError("Select existing problems to annotate.")
                    patch = data.get("patch")
                    if isinstance(patch, dict) and "layers" in patch:
                        for problem_id in ids:
                            validate_evidence(patch["layers"], catalog.problems[problem_id]["task"])
                    return self.respond(notebook.update(ids, data.get("patch"), {key: catalog.metadata(key) for key in ids}))
                if self.path == "/api/import":
                    if not isinstance(data.get("filename"), str):
                        raise ValueError("A filename is required.")
                    return self.respond({"id": catalog.import_task(data["filename"], data.get("task"))})
                return self.respond({"error": "Not found."}, 404)
            except (ValueError, TypeError) as exc:
                return self.respond({"error": str(exc)}, 400)
            except OSError as exc:
                return self.respond({"error": f"Could not save locally: {exc}"}, 500)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Open the local ARC research workspace.")
    parser.add_argument("path", nargs="?", type=Path, help="Optional task JSON or dataset folder")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.path and not args.path.exists():
        parser.error(f"Path does not exist: {args.path}")
    try:
        catalog = Catalog(args.path)
        notebook = Notebook()
        server = create_server(catalog, notebook, args.port)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Could not open workspace: {exc}\n")
    url = f"http://127.0.0.1:{server.server_port}/"
    if args.path and args.path.is_file():
        from urllib.parse import quote
        url += "#" + quote(args.path.stem)
    print(f"ARC workspace: {url}\n{len(catalog.problems)} problems loaded. Keep this process running; press Ctrl+C to stop.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
