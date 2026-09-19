"""Integration test: the launcher's launch-argument fallback ladder.

Boots a *real* dsh core from a real instance through ``CoreController`` with a
deliberately broken candidate list in front of the working one, exactly like a
future core that renamed a CLI flag would appear. The controller must notice
the rejection (commander prints "unknown option"), fall through to the next
candidate, open the HTTP port, and remember the working index.

Usage::

    python tools/core-update-test/test_launch_ladder.py --app-dir "dist/DeepSeek Harness"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "app"))

import core_api  # noqa: E402
import homes  # noqa: E402
import settings  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""),
          flush=True)


def http_ok(url: str, timeout: float = 20.0) -> tuple[int, str]:
    """GET *url* with cookies + redirects, like the WebView does.

    The token URL of dsh >= 0.1.6 redirects once and authenticates with a
    cookie; a cookie-less probe would report 401 for a perfectly good UI.
    """
    import http.cookiejar
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (dsh-desktop-test)"})
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read(400).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-dir", required=True)
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    app_dir = os.path.abspath(args.app_dir)
    cfg = settings.Settings(os.path.join(app_dir, "config.json"))
    data, home = homes.apply_home_env(app_dir, cfg)
    controller = core_api.CoreController(app_dir, cfg)
    print(json.dumps({
        "appDir": app_dir, "dshHome": home, "coreDir": controller.core_dir,
        "entry": controller.entry_rel, "version": controller._core_version(),
        "coreReady": controller.core_ready(),
    }, ensure_ascii=False, indent=2), flush=True)

    check("core is ready (node + CLI entry)", controller.core_ready(),
          f"{controller.node_exe} + {controller.bin_js}")
    if not controller.core_ready():
        return 2

    # 1) Baseline: the preferred candidate must start the core.
    cfg.set("core_launch_mode", "")
    cfg.save()
    ok, message = controller.start()
    port = int(cfg.get("port", 3080))
    check("real core starts with the preferred flags", ok, message[:300])
    if ok:
        status, body = http_ok(controller.status()["url"])
        check("web UI answers over HTTP", status == 200, f"status={status} {body[:120]}")
        check("launch mode remembered",
              str(cfg.get("core_launch_mode", "")) == "0",
              str(cfg.get("core_launch_mode")))
    controller.stop()
    check("core stops cleanly", not controller.is_running())

    # 2) Fallback: a bogus flag family in front of the real ones. This is what a
    #    future/older core that renamed a flag looks like to the launcher.
    original = core_api.CoreController.LAUNCH_CANDIDATES
    core_api.CoreController.LAUNCH_CANDIDATES = (
        ("web", "--no-open", "--port", "{port}", "--host", "127.0.0.1",
         "--definitely-not-a-flag"),
        ("--profile", "web", "--no-such-option", "{port}"),
        *original,
    )
    cfg.set("core_launch_mode", "")
    cfg.save()
    try:
        started_at = time.time()
        ok, message = controller.start()
        elapsed = time.time() - started_at
    finally:
        core_api.CoreController.LAUNCH_CANDIDATES = original
    check("core still starts when the first candidates are rejected", ok,
          f"{message[:280]} (elapsed {elapsed:.1f}s)")
    if ok:
        status, _ = http_ok(controller.status()["url"])
        check("fallback candidate really served the UI", status == 200, f"status={status}")
        remembered = str(cfg.get("core_launch_mode", ""))
        check("working candidate index (2) remembered", remembered == "2", remembered)
        log_tail = controller.read_log(40)
        check("rejection observed in the core log",
              "unknown option" in log_tail.lower() or "unknown" in log_tail.lower(),
              log_tail[-200:].replace("\n", " | "))
    controller.stop()

    # 3) The remembered mode is tried first on the next start.
    ok, message = controller.start()
    check("remembered mode starts without re-probing", ok, message[:200])
    controller.stop()

    failed = [name for name, ok, _ in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"launch ladder integration: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump({"appDir": app_dir, "results": RESULTS,
                       "version": controller._core_version()}, fh,
                      ensure_ascii=False, indent=2)
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
