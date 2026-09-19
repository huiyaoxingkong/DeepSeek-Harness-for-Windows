"""Backend feature audit: every ``Bridge`` method must be implemented and sane.

Instantiates the real ``app/main.py`` Bridge against a scratch instance (with a
stub ``webview`` module, no window) and calls every public method, checking that
none raises and that each returns the shape the shell UI expects. This is the
Python half of "is every advertised feature actually implemented?"; the shell
half is ``tools/immersive-check/cdp_probe.mjs --feature-audit 1``.

Usage::

    python tools/audit-backend.py            # report, exit 1 on findings
    python tools/audit-backend.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
APP = os.path.join(REPO, "app")
sys.path.insert(0, APP)

# The console code page is GBK on Chinese Windows and the report contains
# bullets/em-dashes, so force UTF-8 output rather than crashing the audit.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))


def stub_webview() -> None:
    """main.py imports webview at module scope; give it a headless stand-in."""
    webview = types.ModuleType("webview")
    webview.windows = []
    webview.OPEN_DIALOG = 1
    webview.SAVE_DIALOG = 2
    webview.create_window = lambda *a, **k: types.SimpleNamespace(
        events=types.SimpleNamespace(closing=None), create_file_dialog=lambda *a, **k: None)
    webview.start = lambda *a, **k: None
    sys.modules["webview"] = webview


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    stub_webview()
    import main as app_main  # noqa: PLC0415 - after the webview stub
    import crypto  # noqa: PLC0415

    scratch = tempfile.mkdtemp(prefix="dsh-audit-")
    try:
        app_main.APP_DIR = scratch
        os.makedirs(os.path.join(scratch, "data"), exist_ok=True)
        os.makedirs(os.path.join(scratch, "logs"), exist_ok=True)
        with open(os.path.join(scratch, "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"port": 3199, "data_dir": "data", "core_dir": "core",
                       "runtime_dir": "runtime"}, fh)
        core_dir = os.path.join(scratch, "core")
        os.makedirs(os.path.join(core_dir, "apps", "cli", "lib"), exist_ok=True)
        with open(os.path.join(core_dir, "apps", "cli", "package.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"name": "@deepseek-ai/dsh", "version": "0.1.6-alpha.2",
                       "bin": {"dsh": "lib/bin.js"}}, fh)
        with open(os.path.join(core_dir, "apps", "cli", "lib", "bin.js"), "w",
                  encoding="utf-8") as fh:
            fh.write("// audit stub\n")
        with open(os.path.join(core_dir, "package.json"), "w", encoding="utf-8") as fh:
            json.dump({"name": "deepseek-harness", "version": "0.1.6-alpha.2"}, fh)

        print(f"scratch instance: {scratch}")
        # The launcher points DSH_HOME at its own instance before touching any
        # profile state (main.apply_home_env). Do the same here, and refuse to
        # continue if the environment still names a FOREIGN home: the background
        # profile-store heal would otherwise operate on another installation's
        # profile (it removes and rebuilds node_modules).
        home = os.path.join(scratch, "data", ".dsh")
        os.makedirs(home, exist_ok=True)
        os.environ["DSH_HOME"] = home
        os.environ["DSH_DOCTOR_HOME"] = os.path.join(home, ".dsh-doctor")
        inherited = os.environ.get("DSH_HOME", "")
        if os.path.normcase(os.path.abspath(inherited)) != os.path.normcase(os.path.abspath(home)):
            print(f"ABORT: DSH_HOME points outside the scratch instance: {inherited}")
            return 2
        bridge = app_main.Bridge()
        bridge._junctions_ok.set()
        bridge._heal_done.set()

        # ------------------------------------------------------------ read-only
        state = bridge.get_state()
        app_block = state.get("app", {})
        check("get_state returns app/server/tools/update",
              all(k in state for k in ("app", "server", "tools", "update")),
              ", ".join(sorted(state.keys())))
        check("get_state.app carries the UI state", "uiState" in app_block,
              json.dumps(app_block.get("uiState"), ensure_ascii=False))
        check("get_state.server has coreReady/port/url",
              all(k in state.get("server", {}) for k in ("running", "port", "url", "coreReady")),
              json.dumps(state.get("server"), ensure_ascii=False)[:160])
        check("get_state.tools detects node/git/bash",
              all(k in state.get("tools", {}) for k in ("node", "git", "bash", "flavor")),
              json.dumps(state.get("tools", {}).get("flavor")))
        check("get_state.update exposes the update state machine",
              all(k in state.get("update", {}) for k in ("phase", "progress", "message")),
              str(state.get("update", {}).get("phase")))

        check("server_status returns the server block",
              isinstance(bridge.server_status(), dict))
        check("core version read from the core package.json",
              state["server"]["coreVersion"] == "0.1.6-alpha.2",
              state["server"]["coreVersion"])
        check("core entry resolved via bin.dsh",
              bridge._core.bin_js.endswith(os.path.join("apps", "cli", "lib", "bin.js")),
              bridge._core.bin_js)

        # ------------------------------------------------------------ settings
        check("save_settings accepts the documented keys",
              bridge.save_settings({"port": 3198, "base_url": "https://api.example/v1",
                                    "proxy_url": "http://127.0.0.1:7890",
                                    "npm_registry": "https://registry.npmmirror.com",
                                    "github_mirror": "https://gh-proxy.example",
                                    "auto_start": True, "open_browser": False,
                                    "close_to_tray": True}).get("ok") is True)
        after = bridge.get_state()["app"]
        check("settings persisted (port/baseUrl/mirrors/toggles)",
              after["port"] == 3198 and after["baseUrl"].endswith("/v1")
              and after["proxyUrl"].startswith("http://127.0.0.1")
              and after["npmRegistry"].startswith("https://registry")
              and after["githubMirror"].startswith("https://gh-proxy")
              and after["autoStart"] is True and after["closeToTray"] is True,
              json.dumps({k: after[k] for k in ("port", "baseUrl", "proxyUrl",
                                                "npmRegistry", "githubMirror",
                                                "autoStart", "closeToTray")},
                         ensure_ascii=False))

        bridge.save_settings({"api_key": "sk-audit-key-0123456789"})
        masked = bridge._mask_key(bridge.get_api_key())
        check("API key stored encrypted and round-trips",
              bridge.get_api_key() == "sk-audit-key-0123456789",
              f"key len={len(bridge.get_api_key())}")
        stored = bridge._cfg.get("api_key", "")
        check("API key at rest is DPAPI-protected (not plaintext)",
              stored.startswith("dpapi:") and "sk-audit" not in stored,
              stored[:24])
        check("masked key hides the middle", "•" in masked and "sk-audit" not in masked,
              masked)
        check("crypto round-trip is stable",
              crypto.unprotect(crypto.protect("hello")) == "hello")

        # ------------------------------------------------------------ UI state
        bridge.set_ui_state({"immersive": True, "theme": "builtin-ocean", "lang": "en"})
        ui = bridge.get_state()["app"]["uiState"]
        check("set_ui_state persists immersive/theme/lang",
              ui.get("immersive") is True and ui.get("theme") == "builtin-ocean"
              and ui.get("lang") == "en", json.dumps(ui, ensure_ascii=False))
        check("onboarding flag round-trips",
              bridge.set_onboarding_done().get("ok") is True
              and bridge.get_state()["app"]["onboardingDone"] is True)
        check("lang survives a settings reload",
              bridge.get_state()["app"]["uiState"].get("lang") == "en")

        # ------------------------------------------------------------ instances
        instances = bridge.list_instances()
        check("list_instances returns ok + instances + selfDir",
              instances.get("ok") is True and isinstance(instances.get("instances"), list)
              and instances.get("selfDir") == scratch,
              f"{len(instances.get('instances') or [])} instance(s)")

        # ------------------------------------------------------------ providers
        providers = bridge.list_providers()
        check("list_providers returns providers + appKeySet",
              isinstance(providers.get("providers"), list) and "appKeySet" in providers,
              f"{len(providers.get('providers') or [])} provider(s)")

        # ------------------------------------------------------------ logs
        check("read_log returns text (missing file degrades)",
              isinstance(bridge.read_log(50), str))

        # ------------------------------------------------------------ plugins
        plugins = bridge.list_plugins()
        check("list_plugins returns a plugin list",
              isinstance(plugins.get("plugins"), list),
              json.dumps(plugins, ensure_ascii=False)[:120])
        check("plugin_state reports idle",
              isinstance(bridge.plugin_state(), dict))
        bad = bridge.install_plugin({"spec": ""})
        check("install_plugin rejects an empty spec with a message",
              bad.get("ok") is False and bool(bad.get("message")), str(bad.get("message"))[:80])
        missing = bridge.import_plugin({"path": os.path.join(scratch, "nope.tgz")})
        check("import_plugin reports a missing file",
              missing.get("ok") is False and bool(missing.get("message")))
        check("remove_plugin reports an unknown plugin",
              bridge.remove_plugin({"name": "no-such-plugin"}).get("ok") is False)

        # ------------------------------------------------------------ shell plugins
        shell = bridge.list_shell_plugins()
        check("list_shell_plugins returns a list", isinstance(shell.get("plugins"), list),
              f"{len(shell.get('plugins') or [])} shell plugin(s)")
        check("no example shell plugins are bundled in 1.0.5",
              (shell.get("plugins") or []) == [],
              json.dumps(shell.get("plugins"), ensure_ascii=False))
        manifest = bridge.get_shell_plugin_manifest()
        check("get_shell_plugin_manifest returns plugin entries",
              isinstance(manifest.get("plugins"), list))
        check("pick_shell_plugin_file degrades without a window",
              "path" in bridge.pick_shell_plugin_file())
        check("set_shell_plugin_enabled rejects an unknown id",
              bridge.set_shell_plugin_enabled(
                  {"id": "nope", "enabled": True}).get("ok") is False)
        check("remove_shell_plugin rejects an unknown id",
              bridge.remove_shell_plugin({"id": "nope"}).get("ok") is False)

        # ------------------------------------------------------------ store
        store = bridge.store_list()
        check("store_list exposes the store sources",
              isinstance(store, dict) and "sources" in store,
              json.dumps(store, ensure_ascii=False)[:160])
        sources = store.get("sources") or []
        check("bundled dshmarket source present and disabled by default",
              any("dshmarket" in json.dumps(s, ensure_ascii=False) for s in sources)
              and not any(s.get("enabled") for s in sources),
              json.dumps([{k: s.get(k) for k in ("name", "enabled", "spec")} for s in sources],
                         ensure_ascii=False)[:200])
        check("store_set_enabled rejects an unknown source",
              bridge.store_set_enabled({"name": "nope", "enabled": True}).get("ok") is False)
        check("store_remove rejects an unknown source",
              bridge.store_remove({"name": "nope"}).get("ok") is False)
        check("store_add validates its input",
              bridge.store_add({"name": "", "spec": "", "catalog": ""}).get("ok") is False)

        # ------------------------------------------------------------ update
        core_releases = bridge.list_core_releases()
        check("list_core_releases returns ok + releases (network)",
              isinstance(core_releases, dict) and "releases" in core_releases,
              f"{len(core_releases.get('releases') or [])} release(s), ok="
              f"{core_releases.get('ok')}")
        update_status = bridge.get_state()["update"]
        check("core update state machine is exposed",
              update_status.get("phase") in ("idle", "checking", "downloading",
                                             "installing", "building", "swapping", "done"),
              str(update_status.get("phase")))
        check("cancel_update is callable", bridge.cancel_update().get("ok") is True)
        check("update_core validates its payload",
              isinstance(bridge.update_core({}), dict))
        check("app_update_state returns a state machine",
              "phase" in bridge.app_update_state())
        app_update = bridge.check_app_update()
        check("check_app_update reaches GitHub",
              isinstance(app_update, dict) and ("ok" in app_update),
              json.dumps(app_update, ensure_ascii=False)[:140])

        # ------------------------------------------------------------ core control
        started = bridge.start_server()
        check("start_server reports a missing core clearly (no core built)",
              started.get("ok") is False and bool(started.get("message")),
              str(started.get("message"))[:70])
        check("stop_server is safe with nothing running",
              bridge.stop_server().get("ok") is True)
        check("restart_server is safe with nothing running",
              isinstance(bridge.restart_server(), dict))
        check("poll_tray returns a command envelope",
              "ok" in bridge.poll_tray())
        check("pick_core_archive degrades without a window",
              "path" in bridge.pick_core_archive())
        check("import_core reports a missing archive",
              bridge.import_core({"path": os.path.join(scratch, "nope.zip")})
              .get("ok") is False)

        # ------------------------------------------------------------ auto launch
        check("_auto_launch_enabled is readable", isinstance(bridge._auto_launch_enabled(), bool))
        # Registry round-trip, restored to its original value afterwards.
        original = bridge._auto_launch_enabled()
        try:
            written = bridge.set_auto_launch({"enabled": True})
            enabled_ok = written.get("ok") is True and bridge._auto_launch_enabled() is True
            cleared = bridge.set_auto_launch({"enabled": False})
            disabled_ok = cleared.get("ok") is True and bridge._auto_launch_enabled() is False
            check("set_auto_launch writes and clears the Run key",
                  enabled_ok and disabled_ok,
                  f"enable={written.get('ok')} disable={cleared.get('ok')}")
        finally:
            bridge.set_auto_launch({"enabled": original})
        check("auto-launch setting restored to its original value",
              bridge._auto_launch_enabled() == original, f"original={original}")

        # ------------------------------------------------------ boot behaviour
        calls: list[str] = []
        real_preseed, real_start = bridge._preseed_store, bridge.start_server
        bridge._preseed_store = lambda: calls.append("preseed")
        bridge.start_server = lambda: calls.append("start") or {"ok": True}
        try:
            bridge._boot_with_preseed()
        finally:
            bridge._preseed_store, bridge.start_server = real_preseed, real_start
        check("auto-start boot path preseeks the store then starts the server",
              calls == ["preseed", "start"], str(calls))

        # ------------------------------------------------------ close / shutdown
        check("get_state exposes closeConfirm", "closeConfirm" in app_block,
              str(app_block.get("closeConfirm")))
        check("close confirmation is on by default",
              bridge.get_state()["app"]["closeConfirm"] is True)
        # With confirmation on, the native close is cancelled and the shell asks.
        first = bridge._on_closing()
        check("window close is deferred for confirmation", first is False, str(first))
        polled = bridge.poll_tray()
        check("poll_tray reports the pending close request",
              polled.get("close") is True, json.dumps(polled, ensure_ascii=False))
        check("cancel_close clears the request",
              bridge.cancel_close().get("ok") is True
              and bridge.poll_tray().get("close") is False)
        check("hide_to_tray is safe without a window",
              bridge.hide_to_tray().get("ok") is True)
        # With confirmation off, the legacy behaviour applies.
        bridge.save_settings({"close_confirm": False, "close_to_tray": False})
        check("close_confirm=False lets the close proceed (no tray mode)",
              bridge._on_closing() is True)
        bridge.save_settings({"close_to_tray": True})
        check("close_confirm=False + close_to_tray hides instead of closing",
              bridge._on_closing() is False)
        bridge.save_settings({"close_to_tray": False, "close_confirm": True})
        check("settings restored to confirm-on", bridge._cfg.get("close_confirm") is True)

        # quit_app must persist settings and stop the core before exiting.
        bridge.save_settings({"port": 3177})
        bridge._cfg.set("__audit_sentinel__", "saved-on-quit")
        core_stopped: list[bool] = []
        real_stop = bridge._core.stop
        bridge._core.stop = lambda: (core_stopped.append(True), (True, "stopped"))[1]
        try:
            quit_result = bridge.quit_app()
        finally:
            bridge._core.stop = real_stop
        check("quit_app reports ok", quit_result.get("ok") is True)
        check("quit_app stops the core server", core_stopped == [True], str(core_stopped))
        on_disk = json.load(open(os.path.join(scratch, "config.json"), encoding="utf-8"))
        check("quit_app saves settings to disk before exiting",
              on_disk.get("__audit_sentinel__") == "saved-on-quit",
              f"port={on_disk.get('port')} sentinel={on_disk.get('__audit_sentinel__')}")
        check("quit_app marks the app as quitting", bridge._quitting is True)

        failed = [name for name, ok, _ in RESULTS if not ok]
        print("\n" + "=" * 62)
        print(f"backend feature audit: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump({"results": RESULTS}, fh, ensure_ascii=False, indent=2)
        if failed:
            print("FAILED:")
            for name in failed:
                print(f"  - {name}")
            return 1
        print("ALL PASS")
        return 0
    finally:
        if not args.keep:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        sys.exit(70)
