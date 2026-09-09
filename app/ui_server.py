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
import re
import socket
import socketserver
import threading
import urllib.parse

log = logging.getLogger("ui_server")

ROUTES = {
    "GET /api/ping": "ping",
}

# WebView2 enforces strict MIME checking on <script>/<style>: Windows' registry
# guesses (mimetypes) occasionally answer application/octet-stream for .js/.css
# and the plugin/shell scripts then silently refuse to load. Explicit map wins.
_MIME = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".map": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".yaml": "text/plain; charset=utf-8",
    ".yml": "text/plain; charset=utf-8",
}


def _mime_for(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return _MIME.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"


def _inside(path: str, root: str) -> bool:
    """Separator-aware containment check (the plain str.startswith form would
    also accept siblings like ``root`` vs ``root2``)."""
    path_n, root_n = os.path.normpath(path), os.path.normpath(root)
    return path_n == root_n or path_n.startswith(root_n + os.sep)


class _Handler(http.server.SimpleHTTPRequestHandler):
    ui_root: str = ""
    bridge = None
    shell_plugins = None

    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # silence default stderr logging
        pass

    def _write_body(self, body: bytes) -> bool:
        """Best-effort write; a vanished client (closed WebView, aborted
        fetch) raises OSError and is a normal UI event, not a server fault."""
        try:
            self.wfile.write(body)
            return True
        except OSError:
            log.debug("client connection aborted during write")
            return False

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        except OSError:
            return
        self._write_body(body)

    # Bridge method names come from the URL: only public API names are
    # dispatchable. Underscore-prefixed internals (_api_key, _pick_file, …)
    # and anything else getattr would resolve are never callable over HTTP.
    _BRIDGE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

    # DNS rebinding guard: the shell server only ever answers the exact
    # localhost hosts the WebView loads. A rebinding page that resolves a
    # hostile domain to 127.0.0.1 would otherwise become same-origin with
    # this server and could read/write the bridge.
    _LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
    MAX_BODY = 2 * 1024 * 1024

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host in self._LOCAL_HOSTS

    def _bridge_method(self) -> str:
        """The validated bridge method name, or '' when not dispatchable."""
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/api/bridge/"):
            return ""
        method = parsed.path.rsplit("/", 1)[-1]
        if not self._BRIDGE_NAME_RE.match(method) or method.startswith("_"):
            return ""
        return method

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/plugin/"):
            return self._serve_plugin_file(parsed.path)
        if parsed.path == "/api/ping":
            return self._send_json({"ok": True, "name": "dsh-desktop-ui"})
        if parsed.path.startswith("/api/bridge/"):
            # Bridge calls are POST-only: a GET dispatch lets a hostile
            # webpage trigger no-argument actions (quit/stop/start) through
            # an <img>/<script> tag without ever seeing the response.
            return self._send_json({"ok": False, "message": "bridge is POST-only"}, 405)
        return self._serve_file(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._send_json({"ok": False, "message": "bad host"}, 403)
        method = self._bridge_method()
        if not method:
            return self._send_json({"ok": False, "message": "not found"}, 404)
        fn = getattr(self.bridge, method, None)
        if fn is None or not callable(fn):
            return self._send_json({"ok": False, "message": f"no bridge method {method}"}, 404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send_json({"ok": False, "message": "bad Content-Length"}, 400)
        if length > self.MAX_BODY:
            return self._send_json({"ok": False, "message": "body too large"}, 413)
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

    def _serve_plugin_file(self, path: str) -> None:
        """Serve a shell-plugin asset: /plugin/<id>/<relpath>.

        The id is strictly validated and the resolved file must stay inside
        the plugin directory (user root shadows the bundled root).
        """
        parts = [p for p in urllib.parse.unquote(path).split("/") if p]
        if len(parts) < 2 or self.shell_plugins is None:
            return self._send_json({"ok": False, "message": "not found"}, 404)
        plugin_id, rel = parts[1], "/".join(parts[2:])
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", plugin_id):
            return self._send_json({"ok": False, "message": "forbidden"}, 403)
        if not rel:
            rel = "main.js"
        full = self.shell_plugins.resolve(plugin_id, rel)
        if not full:
            return self._send_json({"ok": False, "message": "not found"}, 404)
        try:
            with open(full, "rb") as fh:
                body = fh.read()
        except OSError:
            return self._send_json({"ok": False, "message": "read failed"}, 500)
        try:
            self.send_response(200)
            self.send_header("Content-Type", _mime_for(full))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        except OSError:
            return
        self._write_body(body)

    def _serve_file(self, path: str) -> None:
        relative = urllib.parse.unquote(path.lstrip("/"))
        if not relative or relative.endswith("/"):
            relative = os.path.join(relative, "index.html")
        full = os.path.normpath(os.path.join(self.ui_root, relative))
        if not _inside(full, self.ui_root):
            return self._send_json({"ok": False, "message": "forbidden"}, 403)
        if not os.path.isfile(full):
            return self._send_json({"ok": False, "message": "not found"}, 404)
        try:
            with open(full, "rb") as fh:
                body = fh.read()
        except OSError:
            return self._send_json({"ok": False, "message": "read failed"}, 500)
        try:
            self.send_response(200)
            self.send_header("Content-Type", _mime_for(full))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        except OSError:
            return
        self._write_body(body)


class _QuietThreadingTCPServer(socketserver.ThreadingTCPServer):
    """ThreadingTCPServer that treats aborted local connections as normal.

    Without this, every vanished WebView fetch (WinError 10053) prints a full
    traceback to the launcher console — the exact spam 1.0.4 removes."""

    def handle_error(self, request, client_address) -> None:
        log.debug("connection from %s failed", client_address)


class UiServer:
    """Binds an ephemeral localhost port and serves app/ui/.

    ThreadingTCPServer: bridge calls run concurrently — a slow network-bound
    method (list_core_releases, catalog fetches) must not queue the UI's
    polling calls behind it, or the WebView aborts them (WinError 10053 spam
    in the launcher log).
    """

    def __init__(self, app_dir: str, bridge=None, shell_plugins=None) -> None:
        self.ui_root = os.path.join(app_dir, "ui")
        if not os.path.isdir(self.ui_root):
            bundled = os.path.join(app_dir, "_internal", "ui")
            if os.path.isdir(bundled):
                self.ui_root = bundled
        self.port = 0
        self.bridge = bridge
        self.shell_plugins = shell_plugins
        self._httpd: socketserver.ThreadingTCPServer | None = None
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
                "shell_plugins": self.shell_plugins,
            })
            self._httpd = _QuietThreadingTCPServer(("127.0.0.1", self.port), handler)
            self._httpd.daemon_threads = True
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
