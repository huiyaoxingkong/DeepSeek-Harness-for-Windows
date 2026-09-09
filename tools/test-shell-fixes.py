"""Regression tests for shell fixes (ui_server / shellplugins / homes).

Usage: python tools\\test-shell-fixes.py
Runs entirely inside the repo: builds a fake app dir under .tmp-itest, drives
the real UiServer over HTTP, and exercises the heal helpers with stub pnpm.
"""
import json
import os
import shutil
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(REPO, "app")
sys.path.insert(0, APP_DIR)

import ui_server  # noqa: E402
import shellplugins  # noqa: E402
import homes  # noqa: E402

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name} {detail}")


BASE = os.path.join(REPO, ".tmp-itest")
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(os.path.join(BASE, "ui", "plugins", "p1"), exist_ok=True)
os.makedirs(os.path.join(BASE, "ui", "plugins", "p1-evil"), exist_ok=True)
os.makedirs(os.path.join(BASE, "data", "shell-plugins", "p2"), exist_ok=True)

with open(os.path.join(BASE, "ui", "index.html"), "w", encoding="utf-8") as fh:
    fh.write("<!doctype html><title>t</title>")
with open(os.path.join(BASE, "ui", "style.css"), "w", encoding="utf-8") as fh:
    fh.write("body{}")
with open(os.path.join(BASE, "ui", "plugins", "p1", "plugin.json"), "w", encoding="utf-8") as fh:
    json.dump({"id": "p1", "name": "P1", "entry": "index.js"}, fh)
with open(os.path.join(BASE, "ui", "plugins", "p1", "index.js"), "w", encoding="utf-8") as fh:
    fh.write("// custom entry")
with open(os.path.join(BASE, "ui", "plugins", "p1-evil", "x.js"), "w", encoding="utf-8") as fh:
    fh.write("// evil")
with open(os.path.join(BASE, "data", "shell-plugins", "p2", "plugin.json"), "w", encoding="utf-8") as fh:
    json.dump({"id": "p2", "name": "P2"}, fh)
with open(os.path.join(BASE, "data", "shell-plugins", "p2", "main.js"), "w", encoding="utf-8") as fh:
    fh.write("// p2")


class FakeCfg:
    def __init__(self):
        self.data = {"data_dir": "data", "shell_plugins": {}}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        pass


class FakeBridge:
    def fast(self):
        return {"n": 1}

    def slow(self):
        time.sleep(2.0)
        return {"n": 2}

    def boom(self):
        raise RuntimeError("boom-msg")

    def with_payload(self, payload):
        return {"got": payload.get("k")}


cfg = FakeCfg()
shell = shellplugins.ShellPluginManager(BASE, cfg)
srv = ui_server.UiServer(BASE, bridge=FakeBridge(), shell_plugins=shell)
check("ui_server start", srv.start())
url = f"http://127.0.0.1:{srv.port}"


def get(path):
    try:
        with urllib.request.urlopen(url + path, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def post(path, payload):
    req = urllib.request.Request(url + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or b"{}")


# --- static files + MIME ---
st, hd, body = get("/")
check("GET / 200 html", st == 200 and hd.get("Content-Type", "").startswith("text/html"))
st, hd, body = get("/style.css")
check("CSS mime", st == 200 and hd.get("Content-Type") == "text/css; charset=utf-8",
      str(hd.get("Content-Type")))

# --- shell plugin serving ---
st, hd, body = get("/plugin/p1/index.js")
check("custom entry served as JS", st == 200 and hd.get("Content-Type", "").startswith("text/javascript"),
      f"{st} {hd.get('Content-Type')}")
st, hd, body = get("/plugin/p1/main.js")
check("missing main.js -> 404", st == 404, str(st))
st, hd, body = get("/plugin/p2/main.js")
check("user plugin served", st == 200 and body == b"// p2")
st, hd, body = get("/plugin/p1/../p1-evil/x.js")
check("traversal blocked", st in (403, 404), f"{st} {body[:60]!r}")
st, hd, body = get("/plugin/..%2f..%2f..%2fWindows/win.ini")
check("encoded traversal blocked", st in (403, 404), f"{st} {body[:60]!r}")

# --- bridge ---
st, data = post("/api/bridge/fast", {})
check("bridge fast", st == 200 and data.get("data", {}).get("n") == 1, str(data))
st, data = post("/api/bridge/with_payload", {"k": "v"})
check("bridge payload arg", st == 200 and data.get("data", {}).get("got") == "v", str(data))
st, data = post("/api/bridge/boom", {})
check("bridge exception -> 500", st == 500 and "boom-msg" in data.get("message", ""), f"{st} {data}")
st, data = post("/api/bridge/nonexistent", {})
check("unknown bridge -> 404", st == 404, str(st))

# --- concurrency: slow must not block fast ---
slow_result = {}

def call_slow():
    try:
        st, d = post("/api/bridge/slow", {})
        slow_result["st"] = st
    except Exception as exc:
        slow_result["err"] = str(exc)

th = threading.Thread(target=call_slow)
th.start()
time.sleep(0.4)  # slow() is now sleeping inside the server
t1 = time.time()
st, data = post("/api/bridge/fast", {})
fast_ms = (time.time() - t1) * 1000
check("fast served while slow blocked", st == 200 and fast_ms < 1000,
      f"{st} {fast_ms:.0f}ms (single-threaded server would take ~1600ms)")
th.join(5)
check("slow completed", slow_result.get("st") == 200, str(slow_result))

# --- security: underscore bridge methods blocked ---
st, data = post("/api/bridge/_api_key", {})
check("underscore bridge method blocked", st == 404, f"{st} {data}")
st, data = post("/api/bridge/_pick_file", {})
check("underscore bridge method blocked (2)", st == 404, f"{st}")

# --- security: GET bridge dispatch removed ---
st, hd, body = get("/api/bridge/fast")
check("GET bridge dispatch removed (405)", st == 405, str(st))
st, hd, body = get("/api/ping")
check("GET /api/ping still works", st == 200, str(st))

# --- security: DNS-rebinding Host guard ---
sock = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
sock.sendall(b"POST /api/bridge/fast HTTP/1.1\r\nHost: evil.example\r\n"
             b"Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}")
resp = sock.recv(512)
sock.close()
check("hostile Host header rejected", b"403" in resp.split(b"\r\n", 1)[0], resp.split(b"\r\n", 1)[0].decode())

# --- security: oversized body rejected before read ---
sock = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
sock.sendall(b"POST /api/bridge/fast HTTP/1.1\r\nHost: 127.0.0.1\r\n"
             b"Content-Type: application/json\r\nContent-Length: 99999999\r\n\r\n{}")
resp = sock.recv(512)
sock.close()
check("oversized body rejected (413)", b"413" in resp.split(b"\r\n", 1)[0], resp.split(b"\r\n", 1)[0].decode())

# --- abrupt client abort must not crash the server ---
sock = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
sock.sendall(b"POST /api/bridge/slow HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\n\r\n{")
sock.close()
time.sleep(0.5)
st, data = post("/api/bridge/fast", {})
check("server survives aborted request", st == 200, str(st))

srv.stop()

# --- shellplugins manifest ---
entries = shell.manifest()["plugins"]
check("manifest custom entry url", any(e["id"] == "p1" and e["entry"].endswith("/index.js") for e in entries),
      str(entries))

# --- shellplugins zip slip ---
zip_path = os.path.join(BASE, "evil.zip")
with zipfile.ZipFile(zip_path, "w") as zf:
    zf.writestr("../evil.txt", "boom")
    zf.writestr("plugin.json", json.dumps({"id": "ok", "entry": "main.js"}))
    zf.writestr("main.js", "// x")
ok, msg = shell.import_from_file(zip_path)
check("zip slip rejected", not ok, str(msg))
check("no plugin leaked from bad zip",
      not os.path.isdir(os.path.join(BASE, "data", "shell-plugins", "ok")))

# --- homes helpers ---
profile = os.path.join(BASE, "data", ".dsh", "profiles", "web")
os.makedirs(os.path.join(profile, "node_modules"), exist_ok=True)
with open(os.path.join(profile, "node_modules", ".modules.yaml"), "w", encoding="utf-8") as fh:
    fh.write('{"storeDir": "C:\\\\Users\\\\hw\\\\AppData\\\\Local\\\\pnpm\\\\store\\\\v11"}')
check("modules yaml store dir parse",
      homes._modules_yaml_store_dir(profile) == r"C:\Users\hw\AppData\Local\pnpm\store\v11")

src_store = os.path.join(BASE, "src-store")
dst_store = os.path.join(BASE, "dst-store")
os.makedirs(os.path.join(src_store, "files", "ab", "cdef"), exist_ok=True)
os.makedirs(os.path.join(dst_store, "files", "ab", "cdef"), exist_ok=True)
with open(os.path.join(src_store, "files", "ab", "cdef", "0000"), "wb") as fh:
    fh.write(b"new")
with open(os.path.join(src_store, "files", "ab", "cdef", "1111"), "wb") as fh:
    fh.write(b"src")
with open(os.path.join(dst_store, "files", "ab", "cdef", "1111"), "wb") as fh:
    fh.write(b"dst")
copied, skipped = homes._merge_store_files(src_store, dst_store)
check("store merge copies missing, keeps existing", copied == 1 and skipped == 1,
      f"{copied}/{skipped}")
with open(os.path.join(dst_store, "files", "ab", "cdef", "1111"), "rb") as fh:
    check("store merge preserves existing content", fh.read() == b"dst")

# --- heal_profile_store: skip when store matches the instance ---
profile_dir = os.path.join(BASE, "data", ".dsh", "profiles", "web")
os.makedirs(profile_dir, exist_ok=True)
with open(os.path.join(profile_dir, "package.json"), "w", encoding="utf-8") as fh:
    json.dump({"dependencies": {"p": "1.0.0"}}, fh)
with open(os.path.join(profile_dir, "node_modules", ".modules.yaml"), "w", encoding="utf-8") as fh:
    json.dump({"storeDir": os.path.join(BASE, "data", "store", "v11")}, fh)
result = homes.heal_profile_store(os.path.join(BASE, "data", ".dsh"),
                                  os.path.join(BASE, "data"),
                                  os.path.join(BASE, "runtime", "node.exe"))
check("heal skips when store matches", result.get("skipped") == "store-ok", str(result))

# --- heal_profile_store: full rebuild flow with a stub pnpm ---
os.makedirs(os.path.join(BASE, "runtime"), exist_ok=True)
with open(os.path.join(BASE, "runtime", "pnpm.cmd"), "w", encoding="utf-8") as fh:
    fh.write("@echo off\r\necho stub pnpm install\r\n")
foreign = os.path.join(BASE, "foreign-store")
os.makedirs(os.path.join(foreign, "files"), exist_ok=True)
with open(os.path.join(profile_dir, "node_modules", ".modules.yaml"), "w", encoding="utf-8") as fh:
    json.dump({"storeDir": foreign}, fh)
result = homes.heal_profile_store(os.path.join(BASE, "data", ".dsh"),
                                  os.path.join(BASE, "data"),
                                  os.path.join(BASE, "runtime", "node.exe"))
check("heal rebuilds on mismatch", result.get("rebuilt") is True, str(result))
check("heal removed foreign-linked modules",
      not os.path.isdir(os.path.join(profile_dir, "node_modules")))
snap = os.path.join(BASE, "data", "store-heal-snapshot")
check("heal snapshots manifest before rebuild",
      os.path.isdir(snap) and any(f.startswith("package.json.") for f in os.listdir(snap)),
      str(os.listdir(snap) if os.path.isdir(snap) else "missing"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
