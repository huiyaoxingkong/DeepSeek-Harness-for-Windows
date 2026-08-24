"""Tiny local HTTP server that serves the shell UI (app/ui/) over localhost.

The shell UI is plain HTML/CSS/JS in app/ui/ — edit those files to restyle or
re-skin the launcher. Served over HTTP (not file://) so fetch() to the Python
bridge proxy and iframes to the dsh web UI work without CORS hacks.
"""

from __future__ import annotations

import http.server
import inspect
import json
import logging
import mimetypes
import os
import socket
import socketserver
import threading
import urllib.parse

log = logging.getLogger("ui_server")

ROUTES = {
    "GET /api/ping": "ping",
}


class _Handler(http.server.SimpleHTTPRequestHandler):
    ui_root: str = ""
    bridge = None

    def log_message(self, *args) -> None:  # silence default stderr logging
        pass

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/ping":
            return self._send_json({"ok": True, "name": "dsh-desktop-ui"})
        if parsed.path.startswith("/api/bridge/"):
            method = parsed.path.rsplit("/", 1)[-1]
            fn = getattr(self.bridge, method, None)
            if fn is None or not callable(fn):
                return self._send_json({"ok": False, "message": f"no bridge method {method}"}, 404)
            try:
                result = fn()
                if isinstance(result, dict) or isinstance(result, (str, int, float, bool, list)):
                    return self._send_json({"ok": True, "data": result})
                return self._send_json({"ok": False, "message": "bridge result is not JSON-serializable"}, 500)
            except Exception as exc:  # surface bridge failures to the UI
                log.exception("bridge %s failed", method)
                return self._send_json({"ok": False, "message": str(exc)}, 500)
        return self._serve_file(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/api/bridge/"):
            return self._send_json({"ok": False, "message": "not found"}, 404)
        method = parsed.path.rsplit("/", 1)[-1]
        fn = getattr(self.bridge, method, None)
        if fn is None or not callable(fn):
            return self._send_json({"ok": False, "message": f"no bridge method {method}"}, 404)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except ValueError:
            payload = {}
        try:
            # The whole JSON body is passed as one positional argument so the
            # HTTP bridge matches the pywebview js_api calling convention
            # (method(payload_object)). Zero-argument methods (get_state etc.)
            # are called without arguments, mirroring how pywebview invokes them.
            params = list(inspect.signature(fn).parameters.values())
            if params and params[0].default is inspect.Parameter.empty:
                result = fn(payload)
            else:
                result = fn()
            if not isinstance(result, (dict, list, str, int, float, bool)) and result is not None:
                result = {"value": result}
            return self._send_json({"ok": True, "data": result})
        except TypeError as exc:
            log.exception("bridge %s arg mismatch", method)
            return self._send_json({"ok": False, "message": str(exc)}, 400)
        except Exception as exc:
            log.exception("bridge %s failed", method)
            return self._send_json({"ok": False, "message": str(exc)}, 500)

    def _serve_file(self, path: str) -> None:
        relative = urllib.parse.unquote(path.lstrip("/"))
        if not relative or relative.endswith("/"):
            relative = os.path.join(relative, "index.html")
        full = os.path.normpath(os.path.join(self.ui_root, relative))
        if not full.startswith(os.path.normpath(self.ui_root)):
            return self._send_json({"ok": False, "message": "forbidden"}, 403)
        if not os.path.isfile(full):
            return self._send_json({"ok": False, "message": "not found"}, 404)
        ctype, _ = mimetypes.guess_type(full)
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class UiServer:
    """Binds an ephemeral localhost port and serves app/ui/."""

    def __init__(self, app_dir: str, bridge=None) -> None:
        self.ui_root = os.path.join(app_dir, "ui")
        if not os.path.isdir(self.ui_root):
            bundled = os.path.join(app_dir, "_internal", "ui")
            if os.path.isdir(bundled):
                self.ui_root = bundled
        self.port = 0
        self.bridge = bridge
        self._httpd: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
            sock.close()
            handler = type("BoundHandler", (_Handler,), {
                "ui_root": self.ui_root,
                "bridge": self.bridge,
            })
            self._httpd = socketserver.TCPServer(("127.0.0.1", self.port), handler)
            self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
            self._thread.start()
            return True
        except OSError as exc:
            log.exception("ui server bind failed")
            return False

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
