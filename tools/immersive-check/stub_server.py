"""Stub servers for headless shell-UI regression tests (no core, no pywebview).

Two listeners:

* **shell server** -- serves ``app/ui`` exactly like ``app/ui_server.py`` does
  and answers ``/api/bridge/<method>`` with canned state, so ``app.js`` runs
  its real code paths (init -> refreshState -> startServer -> openFrame ->
  setImmersive) inside a real Chromium/Edge page.
* **fake core server** -- stands in for the dsh web UI inside the iframe: a
  full-viewport page that reports its own viewport size to the parent through
  ``postMessage``, which is how the probe detects a collapsed iframe.

Usage::

    python tools/immersive-check/stub_server.py --port 0 --json-port-file <path>

Prints the chosen shell port on stdout and (optionally) writes both ports to a
JSON file so the Node CDP driver can read them.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import sys
import threading
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
UI_ROOT = os.path.join(REPO, "app", "ui")
_MIME = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

FAKE_CORE_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>fake dsh web ui</title>
<style>
  html, body { margin:0; height:100%; }
  body { font-family: "Segoe UI", sans-serif; background:#0b0e13; color:#e6e9ef;
         display:flex; flex-direction:column; }
  header { flex:0 0 auto; padding:8px 12px; background:#161b23; }
  main { flex:1; display:flex; min-height:0; }
  nav { width:180px; background:#11151c; padding:8px; }
  #stage { flex:1; padding:8px; overflow:auto; }
  #tall { height: 1800px; background:linear-gradient(#1c2330,#0b0e13); }
</style></head>
<body>
  <header>fake dsh web ui</header>
  <main><nav>sessions</nav><div id="stage"><div id="tall">content</div></div></main>
<script>
  const report = () => {
    const msg = {
      type: "dsh-size",
      w: window.innerWidth, h: window.innerHeight,
      docH: document.documentElement.scrollHeight,
      docW: document.documentElement.scrollWidth,
      bodyH: document.body.getBoundingClientRect().height,
    };
    try { window.parent.postMessage(msg, "*"); } catch (e) {}
  };
  window.addEventListener("resize", report);
  new ResizeObserver(report).observe(document.documentElement);
  report();
  setInterval(report, 400);
</script>
</body></html>
"""


def _state(core_port: int, running: bool = False, immersive: bool = False,
           core_url: str = "", update: dict | None = None,
           onboarding_done: bool = True, ui_theme: str = "",
           ui_lang: str = "zh") -> dict:
    url = core_url or f"http://127.0.0.1:{core_port}"
    return {
        "app": {
            "name": "DeepSeek Harness",
            "version": "1.0.5-test",
            "port": core_port,
            "apiKeySet": False,
            "apiKeyMasked": "",
            "baseUrl": "",
            "proxyUrl": "",
            "npmRegistry": "",
            "githubMirror": "",
            "autoStart": False,
            "openBrowser": False,
            "onboardingDone": onboarding_done,
            "closeToTray": False,
            "autoLaunch": False,
            "dataDir": os.path.join(REPO, "app", "data"),
            "dshHome": "",
            "uiState": {"immersive": immersive, "theme": ui_theme, "lang": ui_lang},
            "health": {"skipped": True, "ok": False},
        },
        "server": {
            "running": running,
            "port": core_port,
            "url": url,
            "coreReady": True,
            "coreVersion": "0.1.6-alpha.2",
            "dshHome": "",
        },
        "tools": {
            "flavor": "lazy",
            "node": {"mode": "bundled", "path": "runtime\\node.exe"},
            "git": {"mode": "bundled", "path": "runtime\\git\\cmd\\git.exe"},
            "bash": {"mode": "bundled", "path": "runtime\\git\\bin\\bash.exe"},
        },
        "update": update or {
            "phase": "idle", "progress": 0.0, "message": "", "remote": None,
            "local": None, "canUpdate": False, "tag": "", "error": None,
        },
    }


class _ShellHandler(http.server.SimpleHTTPRequestHandler):
    core_port = 0
    core_url = ""
    running = False
    immersive = False
    onboarding_done = True
    ui_theme = ""
    ui_lang = "zh"
    # Core-update state the UI polls (phase/progress/message/canUpdate).
    update: dict = {
        "phase": "idle", "progress": 0.0, "message": "", "remote": None,
        "local": None, "canUpdate": False, "tag": "", "error": None,
    }
    # Every bridge method the shell asked for, in order (feature audit).
    calls: list = []

    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # keep the test output readable
        pass

    # ------------------------------------------------------------- helpers

    def _send(self, body: bytes, ctype: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def _json(self, payload, status: int = 200) -> None:
        self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    def _bridge(self, method: str, payload: dict):
        type(self).calls.append({"method": method, "payload": payload})
        if method == "get_state":
            return _state(self.core_port, self.running, self.immersive,
                          self.core_url, self.update, self.onboarding_done,
                          self.ui_theme, self.ui_lang)
        if method == "set_onboarding_done":
            type(self).onboarding_done = True
            return {"ok": True}
        if method == "check_update":
            type(self).update = {
                "phase": "done", "progress": 1.0, "message": "检查完成",
                "remote": {"commit": "deadbeef1234", "date": "2026-09-17T00:00:00Z",
                           "message": "audit remote commit"},
                "local": {"commit": "cafebabe0000", "updatedAt": "2026-09-20 00:00:00"},
                "canUpdate": True, "tag": "", "error": None,
            }
            return {"ok": True, "canUpdate": True, "remote": type(self).update["remote"],
                    "local": type(self).update["local"], "message": "发现新版本，可更新"}
        if method == "download_update":
            type(self).update.update(phase="downloading", progress=0.1,
                                     message="审计：正在下载源码…")
            return {"ok": True, "message": "更新已开始"}
        if method == "cancel_update":
            type(self).update.update(phase="idle", progress=0.0,
                                     message="更新已取消。", error=None)
            return {"ok": True, "message": "更新已取消。"}
        if method == "start_server":
            type(self).running = True
            return {"ok": True, "message": "服务已启动（stub）", "port": self.core_port,
                    "url": self.core_url or f"http://127.0.0.1:{self.core_port}"}
        if method == "stop_server":
            type(self).running = False
            return {"ok": True, "message": "服务已停止（stub）"}
        if method == "restart_server":
            type(self).running = True
            return {"ok": True, "message": "服务已重启（stub）",
                    "url": self.core_url or f"http://127.0.0.1:{self.core_port}"}
        if method == "server_status":
            return _state(self.core_port, self.running, self.immersive,
                          self.core_url)["server"]
        if method == "set_ui_state":
            if "immersive" in payload:
                type(self).immersive = bool(payload["immersive"])
            if "theme" in payload:
                type(self).ui_theme = str(payload["theme"])
            if "lang" in payload:
                type(self).ui_lang = str(payload["lang"])
            return {"ok": True}
        if method == "list_shell_plugins":
            return {"plugins": []}
        if method == "get_shell_plugin_manifest":
            return {"apiVersion": 1, "plugins": []}
        if method == "list_plugins":
            return {"plugins": [], "installing": False, "message": ""}
        if method == "store_list":
            return {"sources": [], "installing": False}
        if method == "store_catalog":
            return {"items": [], "sources": []}
        if method == "plugin_state":
            return {"busy": False, "message": ""}
        if method == "list_instances":
            return {"ok": True, "instances": [], "selfDir": REPO}
        if method == "list_providers":
            return {"providers": [], "appKeySet": False}
        if method == "read_log":
            return "(stub) no log"
        if method == "poll_tray":
            return {"ok": True, "cmd": ""}
        if method == "check_app_update":
            return {"ok": True, "current": "1.0.5-test", "hasUpdate": False, "latest": None}
        if method == "app_update_state":
            return {"phase": "idle", "progress": 0.0, "message": "", "error": None}
        if method == "list_core_releases":
            return {"ok": True, "releases": []}
        return {"ok": True}

    # ------------------------------------------------------------- routes

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/api/bridge/"):
            return self._json({"ok": False, "message": "not found"}, 404)
        method = parsed.path.rsplit("/", 1)[-1]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except ValueError:
            payload = {}
        return self._json({"ok": True, "data": self._bridge(method, payload)})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/ping":
            return self._json({"ok": True, "name": "dsh-desktop-ui-stub"})
        if parsed.path == "/api/control":
            # Test-driver hook: pin the canned state between scenarios.
            # keep_blank_values matters: `ui_theme=` is how a scenario asks for
            # the default theme again.
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            if "running" in query:
                type(self).running = query["running"][0] == "1"
            if "immersive" in query:
                type(self).immersive = query["immersive"][0] == "1"
            if "reset_calls" in query:
                type(self).calls = []
            if "update_phase" in query:
                type(self).update.update(
                    phase=query["update_phase"][0],
                    progress=float(query.get("update_progress", ["0.5"])[0]),
                    message=query.get("update_message", ["审计：更新进行中"])[0],
                    canUpdate=False)
            if "update_idle" in query:
                type(self).update.update(phase="idle", progress=0.0, message="")
            if "onboarding" in query:
                type(self).onboarding_done = query["onboarding"][0] == "1"
            if "ui_lang" in query:
                type(self).ui_lang = query["ui_lang"][0]
            if "ui_theme" in query:
                type(self).ui_theme = query["ui_theme"][0]
            return self._json({"ok": True, "running": self.running,
                               "immersive": self.immersive,
                               "calls": len(self.calls)})
        if parsed.path == "/api/control/calls":
            # Bridge-call journal for the feature audit.
            return self._json({"ok": True, "calls": type(self).calls})
        relative = urllib.parse.unquote(parsed.path.lstrip("/")) or "index.html"
        full = os.path.normpath(os.path.join(UI_ROOT, relative))
        if not full.startswith(os.path.normpath(UI_ROOT)):
            return self._json({"ok": False, "message": "forbidden"}, 403)
        if not os.path.isfile(full):
            return self._json({"ok": False, "message": "not found"}, 404)
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as fh:
            body = fh.read()
        return self._send(body, _MIME.get(ext, "application/octet-stream"))


class _CoreHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        body = FAKE_CORE_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass


class _Threading(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def _serve(handler_cls, port: int) -> tuple[_Threading, int]:
    httpd = _Threading(("127.0.0.1", port), handler_cls)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--json-port-file", default="")
    # Serve an installed/dev instance's ui\ folder instead of app\ui, so the
    # regression can be run against the exact files a released instance ships.
    ap.add_argument("--ui-root", default="")
    # Point the shell at a REAL running dsh core (the URL the core printed,
    # token included) instead of the built-in fake page.
    ap.add_argument("--core-url", default="")
    args = ap.parse_args()

    global UI_ROOT
    if args.ui_root:
        UI_ROOT = os.path.abspath(args.ui_root)
    if not os.path.isfile(os.path.join(UI_ROOT, "index.html")):
        print(json.dumps({"error": f"no index.html under {UI_ROOT}"}), flush=True)
        return 2

    core_httpd, core_port = _serve(_CoreHandler, 0)
    shell_handler = type("BoundShellHandler", (_ShellHandler,), {
        "core_port": core_port,
        "core_url": args.core_url.strip(),
    })
    shell_httpd, shell_port = _serve(shell_handler, args.port)

    if args.json_port_file:
        with open(args.json_port_file, "w", encoding="utf-8") as fh:
            json.dump({"shell": shell_port, "core": core_port,
                       "coreUrl": args.core_url.strip()}, fh)

    print(json.dumps({"shell": shell_port, "core": core_port}), flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        shell_httpd.shutdown()
        core_httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
