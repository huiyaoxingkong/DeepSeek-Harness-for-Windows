"""Drive the launcher's *own* core update pipeline against a real instance.

This is the end-to-end test for kernel upgrade/downgrade compatibility: it
uses the exact code path the app's "核心更新" page uses (``updater.CoreUpdater``)
against a target instance directory, then verifies the swapped-in core:

1. download the release source zip (or reuse a local zip),
2. pnpm install + pnpm build,
3. swap ``core/`` atomically (long-path safe backup removal),
4. post-swap checks: CLI entry resolves, ``core_ready()`` is true,
5. boot the server on the instance's port, HTTP GET ``/`` and stop it,
6. run the launcher's profile health check against the new core.

Usage::

    python tools/core-update-test/run_core_update.py --app-dir "dist/DeepSeek Harness" \
        --tag dsh-v0.1.6-alpha.2 --report .tmp-core-test/upgrade.json
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import traceback
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "app"))

import core_api  # noqa: E402
import homes  # noqa: E402
import settings  # noqa: E402
import updater  # noqa: E402

PHASES_DONE = {"done"}

# The console codepage on Chinese Windows is GBK: pnpm prints characters it
# cannot encode (✓, ↑, box drawing), and a UnicodeEncodeError inside the
# progress printer would kill this process — and with it the update thread.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - old interpreters
        pass


def log(message: str) -> None:
    try:
        print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)
    except UnicodeEncodeError:  # last-resort guard, never fatal
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        safe = str(message).encode(encoding, "replace").decode(encoding, "replace")
        print(f"{time.strftime('%H:%M:%S')} {safe}", flush=True)


def http_get(url: str, timeout: float = 20.0) -> tuple[int, str]:
    """GET *url* like a browser does: follow redirects and keep cookies.

    dsh >= 0.1.6 answers the token URL with a redirect to the plain path and
    authenticates the session with a cookie, so a cookie-less probe would see
    the follow-up request as unauthenticated (401) even though a browser — and
    the WebView — load the UI fine.
    """
    import http.cookiejar
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (dsh-desktop-test)"})
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read(4000).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - reported as part of the result
        return 0, f"{type(exc).__name__}: {exc}"


def wait_port(port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-dir", required=True)
    ap.add_argument("--tag", default="")
    ap.add_argument("--zip", default="")
    ap.add_argument("--report", default="")
    ap.add_argument("--skip-boot", action="store_true")
    ap.add_argument("--deadline-min", type=float, default=240.0)
    args = ap.parse_args()

    app_dir = os.path.abspath(args.app_dir)
    report: dict = {
        "appDir": app_dir,
        "tag": args.tag,
        "zip": args.zip,
        "startedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "steps": [],
        "ok": False,
    }

    def step(name: str, **fields) -> None:
        entry = {"step": name, "ts": time.strftime("%H:%M:%S"), **fields}
        report["steps"].append(entry)
        log(f"[{name}] " + json.dumps(fields, ensure_ascii=False)[:400])

    cfg = settings.Settings(os.path.join(app_dir, "config.json"))
    data, home = homes.apply_home_env(app_dir, cfg)
    core = core_api.CoreController(app_dir, cfg)

    step("instance", dataDir=data, dshHome=home, coreDir=core.core_dir,
         entry=core.bin_js, node=core.node_exe,
         versionBefore=core.status()["coreVersion"],
         entryExists=os.path.isfile(core.bin_js))
    if not os.path.isfile(core.node_exe):
        step("abort", reason="node runtime missing")
        report["finishedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _write(args.report, report)
        return 2

    # Stop anything still serving this instance before the swap.
    core.stop()
    time.sleep(1)

    up = updater.CoreUpdater(app_dir, cfg, core)
    if args.zip:
        res = up.import_from_zip(os.path.abspath(args.zip))
    else:
        res = up.download_and_build(args.tag)
    step("pipeline-start", result=res)
    if not res.get("ok"):
        report["finishedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _write(args.report, report)
        return 3

    deadline = time.time() + args.deadline_min * 60
    last_message = ""
    phase = ""
    while time.time() < deadline:
        try:
            status = up.status()
            message = str(status.get("message") or "")
            phase = str(status.get("phase") or "")
            if message != last_message:
                log(f"  {phase} {float(status.get('progress') or 0) * 100:5.1f}% {message}")
                last_message = message
        except Exception as exc:  # noqa: BLE001 - monitoring must never kill the update
            log(f"  (status read failed: {type(exc).__name__}: {exc})")
        if phase in PHASES_DONE:
            break
        if phase == "idle" and up.status().get("error"):
            break
        if phase == "idle" and "取消" in last_message:
            break
        time.sleep(5)
    status = up.status()
    step("pipeline-finish", phase=status.get("phase"), message=status.get("message"),
         error=status.get("error"))
    if status.get("phase") != "done":
        report["finishedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        report["error"] = status.get("error") or status.get("message")
        _write(args.report, report)
        return 4

    # ---------------------------------------------------------------- verify
    info = {}
    marker = os.path.join(core.core_dir, ".dsh-desktop-info.json")
    if os.path.isfile(marker):
        try:
            with open(marker, "r", encoding="utf-8") as fh:
                info = json.load(fh)
        except (OSError, ValueError):
            info = {}
    report["coreInfo"] = info
    entry_after = core_api.resolve_cli_entry(core.core_dir)
    step("swapped", entry=entry_after, entryExists=os.path.isfile(entry_after),
         coreReady=core.core_ready(), versionAfter=core._core_version(),
         backups=sorted(n for n in os.listdir(app_dir) if n.startswith("core.backup")),
         sourceCommit=info.get("commit"))

    if not core.core_ready():
        step("abort", reason="core not ready after swap")
        report["finishedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _write(args.report, report)
        return 5

    # Profile health check, exactly as the launcher runs it at boot.
    homes.run_health_check(app_dir, cfg, core.node_exe, core.bin_js)
    step("health", **homes.read_health(app_dir))

    if not args.skip_boot:
        ok, message = core.start()
        port = int(cfg.get("port", 3080))
        # Always probe the URL the core printed: dsh >= 0.1.6 puts its auth
        # token there and 401s a bare localhost URL.
        url = core.status()["url"]
        step("start", ok=ok, message=message[:300], port=port,
             url=url.replace(url.split("token=")[-1], "***") if "token=" in url else url,
             tokenUrl="token=" in url,
             portOpen=wait_port(port, 20))
        if ok:
            code, body = http_get(url)
            step("http", status=code, head=body[:200].replace("\n", " "))
        core.stop()
        step("stopped", running=core.is_running())

    report["ok"] = bool(core.core_ready())
    report["finishedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write(args.report, report)
    log(f"DONE ok={report['ok']}")
    return 0 if report["ok"] else 6


def _write(path: str, report: dict) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    log(f"report -> {path}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - always leave a readable trace
        traceback.print_exc()
        sys.exit(70)
