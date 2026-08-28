"""
DeepSeek Harness Desktop — Windows launcher entry point.

A pywebview (WebView2) shell around the dsh web server. The launcher owns a
small local HTTP server that serves the shell UI (app/ui/), controls the dsh
child process, reads/writes config.json, and can download + rebuild the core
from the upstream GitHub source.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time

import webview

import core_api
import crypto
import homes
import junctions
import plugins
import providers
import settings
import shellplugins
import store
import tray
import ui_server
import updater

APP_NAME = "DeepSeek Harness"
APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))

LOG_DIR = os.path.join(APP_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "launcher.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("main")


class Bridge:
    """JS <-> Python bridge exposed to the shell UI as window.pywebview.api."""

    def __init__(self) -> None:
        self._cfg = settings.Settings(os.path.join(APP_DIR, "config.json"))
        self._core = core_api.CoreController(APP_DIR, self._cfg)
        self._updater = updater.CoreUpdater(APP_DIR, self._cfg, self._core)
        self._app_updater = updater.AppUpdateController(APP_DIR, self._cfg)
        self._plugins = plugins.PluginManager(APP_DIR, self._cfg, self._core)
        self._store = store.StoreManager(APP_DIR, self._cfg, self._plugins)
        self._shell = shellplugins.ShellPluginManager(APP_DIR, self._cfg)
        self._tray = tray.TrayController(APP_DIR)
        self._quitting = False
        # Core workspace junctions may be missing right after a generic
        # archive extraction; restore them before the server can start.
        self._junctions_ok = threading.Event()
        threading.Thread(target=self._ensure_junctions, daemon=True).start()

    def _scripts_dir(self) -> str:
        bundled = os.path.join(APP_DIR, "scripts", "restore-junctions.ps1")
        if os.path.isfile(bundled):
            return bundled
        # dev layout: the repo's scripts/ sits next to app/
        return os.path.join(os.path.dirname(APP_DIR), "scripts",
                            "restore-junctions.ps1")

    def _ensure_junctions(self) -> None:
        try:
            core_dir = self._core.core_dir
            if junctions.needs_restore(core_dir):
                ok = junctions.restore(core_dir, self._scripts_dir())
                log.info("core junction restore: %s",
                         "ok" if ok else "failed")
            else:
                log.info("core junctions: ok")
        except Exception as exc:  # never block startup
            log.warning("junction check failed: %s", exc)
        finally:
            self._junctions_ok.set()

    def _wait_junctions(self, timeout: float = 600.0) -> bool:
        return self._junctions_ok.wait(timeout=timeout)

    # ------------------------------------------------------------- state

    def _api_key(self) -> str:
        """Decrypted API key (DPAPI at rest since 1.0.3; legacy plaintext tolerated)."""
        try:
            return crypto.unprotect(self._cfg.get("api_key", "") or "")
        except (OSError, ValueError):
            log.warning("api key decrypt failed")
            return ""

    def get_state(self) -> dict:
        data = homes.data_dir(APP_DIR, self._cfg)
        state = {
            "app": {
                "name": APP_NAME,
                "version": self._cfg.get("app_version", "0.1.0"),
                "port": self._cfg.get("port", 3080),
                "apiKeySet": bool(self._api_key()),
                "apiKeyMasked": self._mask_key(self._api_key()),
                "baseUrl": self._cfg.get("base_url", ""),
                "proxyUrl": self._cfg.get("proxy_url", ""),
                "npmRegistry": self._cfg.get("npm_registry", ""),
                "githubMirror": self._cfg.get("github_mirror", ""),
                "autoStart": self._cfg.get("auto_start", False),
                "openBrowser": self._cfg.get("open_browser", False),
                "onboardingDone": self._cfg.get("onboarding_done", False),
                "closeToTray": self._cfg.get("close_to_tray", False),
                "autoLaunch": self._auto_launch_enabled(),
                "dataDir": data,
                "dshHome": os.environ.get("DSH_HOME", ""),
                "uiState": self._cfg.get("ui_state", {"immersive": False}),
                "health": homes.read_health(APP_DIR),
            },
            "server": self._core.status(),
            "tools": homes.detect_tools(APP_DIR, self._cfg),
            "update": self._updater.status(),
        }
        return state

    @staticmethod
    def _mask_key(key: str) -> str:
        if not key:
            return ""
        if len(key) <= 8:
            return "•" * len(key)
        return key[:6] + "•" * 12 + key[-4:]

    def get_api_key(self) -> str:
        """Plain-text API key, requested only when the user clicks the
        reveal button in the settings page."""
        return self._api_key()

    def set_onboarding_done(self, payload: dict = None) -> dict:
        self._cfg.set("onboarding_done", True)
        self._cfg.save()
        return {"ok": True}

    def set_ui_state(self, payload: dict) -> dict:
        """Persist shell UI state (immersive mode memory, active theme)."""
        state = dict(self._cfg.get("ui_state", {"immersive": False}))
        if not isinstance(state, dict):
            state = {}
        if "immersive" in (payload or {}):
            state["immersive"] = bool((payload or {}).get("immersive"))
        if "theme" in (payload or {}):
            state["theme"] = str((payload or {}).get("theme") or "")
        if "lang" in (payload or {}):
            state["lang"] = str((payload or {}).get("lang") or "")
        self._cfg.set("ui_state", state)
        self._cfg.save()
        return {"ok": True, "uiState": state}

    # ------------------------------------------------------------- auto launch

    @staticmethod
    def _run_key_path() -> str:
        return r"Software\Microsoft\Windows\CurrentVersion\Run"

    def _auto_launch_enabled(self) -> bool:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                self._run_key_path()) as key:
                value, _ = winreg.QueryValueEx(key, "DeepSeekHarness")
                return bool(value)
        except OSError:
            return False

    def set_auto_launch(self, payload: dict) -> dict:
        import winreg
        enabled = bool((payload or {}).get("enabled", False))
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._run_key_path(),
                                0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    winreg.SetValueEx(key, "DeepSeekHarness", 0, winreg.REG_SZ,
                                      f'"{os.path.join(APP_DIR, "DeepSeek Harness.exe")}"')
                else:
                    try:
                        winreg.DeleteValue(key, "DeepSeekHarness")
                    except FileNotFoundError:
                        pass
            return {"ok": True, "enabled": self._auto_launch_enabled()}
        except OSError as exc:
            log.warning("set_auto_launch failed: %s", exc)
            return {"ok": False, "message": f"写入开机自启失败: {exc}"}

    def save_settings(self, patch: dict) -> dict:
        allowed = {"api_key", "base_url", "port", "auto_start",
                   "open_browser", "close_to_tray", "proxy_url",
                   "npm_registry", "github_mirror"}
        for key, value in patch.items():
            if key not in allowed:
                continue
            if value is None:
                continue  # masked key unchanged; keep the stored value
            if key == "api_key":
                try:
                    value = crypto.protect(str(value))
                except (OSError, ValueError):
                    log.warning("api key encrypt failed; stored as-is")
            if key == "port":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            if key in ("auto_start", "open_browser", "close_to_tray"):
                value = bool(value)
            if key in ("proxy_url", "npm_registry", "github_mirror"):
                value = str(value).strip()
            self._cfg.set(key, value)
        self._cfg.save()
        return {"ok": True}

    # ------------------------------------------------------------- server

    def start_server(self) -> dict:
        if not self._wait_junctions():
            return {"ok": False, "message": "核心组件链接恢复超时，请重启应用重试。"}
        ok, msg = self._core.start()
        return {"ok": ok, "message": msg, "port": self._cfg.get("port", 3080)}

    def stop_server(self) -> dict:
        ok, msg = self._core.stop()
        return {"ok": ok, "message": msg}

    def restart_server(self) -> dict:
        ok, msg = self._core.restart()
        return {"ok": ok, "message": msg}

    def server_status(self) -> dict:
        return self._core.status()

    # ------------------------------------------------------------- tray

    def poll_tray(self) -> dict:
        """Executed by the shell UI timer; runs pending tray commands on the
        bridge thread (the same thread pywebview window calls already use)."""
        cmd = self._tray.pop()
        if cmd == "show":
            return self.show_window()
        if cmd == "start":
            return self.start_server()
        if cmd == "stop":
            return self.stop_server()
        if cmd == "quit":
            return self.quit_app()
        return {"ok": True, "cmd": ""}

    def show_window(self) -> dict:
        try:
            if webview.windows:
                webview.windows[0].show()
                webview.windows[0].restore()
        except Exception as exc:
            log.warning("tray show failed: %s", exc)
        return {"ok": True}

    def quit_app(self) -> dict:
        if self._quitting:
            return {"ok": True}
        self._quitting = True
        try:
            self._core.stop()
        except Exception as exc:
            log.warning("core stop on quit failed: %s", exc)
        try:
            self._tray.stop()
        except Exception as exc:
            log.warning("tray stop failed: %s", exc)
        try:
            if webview.windows:
                webview.windows[0].destroy()
        except Exception as exc:
            log.warning("window destroy failed: %s", exc)
            os._exit(0)
        return {"ok": True}

    def _on_closing(self) -> bool:
        """Window close: exit, or hide to tray when close_to_tray is set."""
        if self._quitting or not self._cfg.get("close_to_tray", False):
            return True
        try:
            if webview.windows:
                webview.windows[0].hide()
        except Exception as exc:
            log.warning("hide to tray failed: %s", exc)
        return False

    def read_log(self, tail: int = 200) -> str:
        return self._core.read_log(tail)

    # ------------------------------------------------------------- plugins

    def list_plugins(self) -> dict:
        return self._plugins.list()

    def install_plugin(self, payload: dict) -> dict:
        specs = (payload or {}).get("specs")
        if isinstance(specs, list) and specs:
            ok, msg = self._plugins.install_many(specs)
        else:
            spec = (payload or {}).get("spec", "")
            ok, msg = self._plugins.install(spec)
        return {"ok": ok, "message": msg}

    def remove_plugin(self, payload: dict) -> dict:
        name = (payload or {}).get("name", "")
        ok, msg = self._plugins.remove(name)
        return {"ok": ok, "message": msg}

    def set_plugin_enabled(self, payload: dict) -> dict:
        name = (payload or {}).get("name", "")
        enabled = bool((payload or {}).get("enabled", False))
        ok, msg = self._plugins.set_enabled(name, enabled)
        return {"ok": ok, "message": msg}

    def plugin_state(self) -> dict:
        return self._plugins.status()

    # ------------------------------------------------------------- shell plugins

    def list_shell_plugins(self) -> dict:
        return self._shell.list()

    def get_shell_plugin_manifest(self) -> dict:
        return self._shell.manifest()

    def set_shell_plugin_enabled(self, payload: dict) -> dict:
        ok, msg = self._shell.set_enabled(
            (payload or {}).get("id", ""), bool((payload or {}).get("enabled", False)))
        return {"ok": ok, "message": msg}

    def remove_shell_plugin(self, payload: dict) -> dict:
        ok, msg = self._shell.remove((payload or {}).get("id", ""))
        return {"ok": ok, "message": msg}

    def pick_shell_plugin_file(self) -> dict:
        return {"path": self._pick_file("外壳插件包", "*.zip")}

    def import_shell_plugin(self, payload: dict) -> dict:
        ok, msg = self._shell.import_from_file((payload or {}).get("path", ""))
        return {"ok": ok, "message": msg}

    # ------------------------------------------------------------- local import

    def _pick_file(self, description: str, patterns: str) -> str:
        try:
            if not webview.windows:
                return ""
            selected = webview.windows[0].create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=(f"{description} ({patterns})",),
            )
            if not selected:
                return ""
            return selected[0]
        except Exception as exc:  # dialog unavailable (e.g. headless debug)
            log.warning("file dialog failed: %s", exc)
            return ""

    def pick_core_archive(self) -> dict:
        return {"path": self._pick_file("核心源码压缩包", "*.zip")}

    def pick_plugin_file(self) -> dict:
        return {"path": self._pick_file("插件包", "*.tgz;*.zip;*.tar.gz")}

    def import_core(self, payload: dict) -> dict:
        result = self._updater.import_from_zip((payload or {}).get("path", ""))
        return {"ok": result["ok"], "message": result["message"]}

    def import_plugin(self, payload: dict) -> dict:
        ok, msg = self._plugins.import_from_file((payload or {}).get("path", ""))
        return {"ok": ok, "message": msg}

    # ------------------------------------------------------------- store

    def store_list(self) -> dict:
        return self._store.list()

    def store_catalog(self, payload: dict = None) -> dict:
        return self._store.catalog((payload or {}).get("source") or None)

    def store_install(self, payload: dict) -> dict:
        ok, msg = self._store.install_from_catalog((payload or {}).get("name", ""))
        return {"ok": ok, "message": msg}

    def store_uninstall(self, payload: dict) -> dict:
        ok, msg = self._plugins.remove((payload or {}).get("name", ""))
        return {"ok": ok, "message": msg}

    def store_update(self, payload: dict) -> dict:
        ok, msg = self._store.update_from_catalog((payload or {}).get("name", ""))
        return {"ok": ok, "message": msg}

    def store_add(self, payload: dict) -> dict:
        ok, msg = self._store.add(
            (payload or {}).get("name", ""),
            (payload or {}).get("spec", ""),
            (payload or {}).get("catalog", ""),
            (payload or {}).get("homepage", ""))
        return {"ok": ok, "message": msg}

    def store_remove(self, payload: dict) -> dict:
        ok, msg = self._store.remove((payload or {}).get("name", ""))
        return {"ok": ok, "message": msg}

    def store_set_enabled(self, payload: dict) -> dict:
        name = (payload or {}).get("name", "")
        enabled = bool((payload or {}).get("enabled", False))
        ok, msg = self._store.set_enabled(name, enabled)
        return {"ok": ok, "message": msg}

    # ------------------------------------------------------------- store preseed

    def _preseed_store(self) -> None:
        """First-run background task: install the builtin store package into
        the profile (offline, from the bundled tarball) but keep it disabled.
        Runs once per launch; idempotent once installed."""
        try:
            if self._core.is_running():
                log.info("preseed skipped: server running")
                return
            ok, msg = self._store.preseed()
            log.info("store preseed: %s (%s)", msg, "ok" if ok else "failed")
        except Exception as exc:  # never crash the launch thread
            log.exception("store preseed crashed: %s", exc)

    def _boot_with_preseed(self) -> None:
        self._preseed_store()
        self.start_server()

    # ------------------------------------------------------------- providers

    def list_providers(self) -> dict:
        return providers.list_providers(
            app_key_set=bool(self._api_key()))

    # ------------------------------------------------------------- app update

    def check_app_update(self) -> dict:
        return updater.check_app_release(self._cfg.get("app_version", ""))

    def app_update_state(self) -> dict:
        return self._app_updater.status()

    def download_app_update(self) -> dict:
        return self._app_updater.download()

    def install_app_update(self) -> dict:
        return self._app_updater.install()

    def quit_for_update(self) -> dict:
        """Close the shell so the upgrade bootstrap can replace files."""
        threading.Thread(target=self._shutdown_for_update, daemon=True).start()
        return {"ok": True}

    def _shutdown_for_update(self) -> None:
        time.sleep(0.4)
        self._core.stop()
        try:
            if webview.windows:
                webview.windows[0].destroy()
        except Exception as exc:  # window may already be gone
            log.warning("window destroy failed: %s", exc)

    # ------------------------------------------------------------- instances

    def list_instances(self) -> dict:
        """E4: running DeepSeek Harness instances on this machine."""
        import csv
        import io
        rows = []
        try:
            script = ("Get-CimInstance Win32_Process -Filter \"Name='DeepSeek Harness.exe'\" | "
                      "Select-Object ProcessId, ExecutablePath | ConvertTo-Csv -NoTypeInformation")
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for row in csv.DictReader(io.StringIO(out.stdout.strip())):
                pid = (row.get("ProcessId") or "").strip()
                exe = (row.get("ExecutablePath") or "").strip()
                if not pid.isdigit() or not exe:
                    continue
                rows.append({
                    "pid": int(pid),
                    "path": exe,
                    "isSelf": (os.path.normcase(os.path.dirname(exe))
                               == os.path.normcase(APP_DIR)),
                })
        except (OSError, subprocess.TimeoutExpired, csv.Error):
            pass
        for row in rows:
            row["port"] = self._port_of_pid(row["pid"])
        return {"ok": True, "instances": rows, "selfDir": APP_DIR}

    @staticmethod
    def _port_of_pid(pid: int) -> str:
        try:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True, text=True, timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        ports = []
        for line in out.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[4] == str(pid):
                addr = parts[1]
                if addr.startswith(("127.0.0.1:", "0.0.0.0:")):
                    port = addr.rsplit(":", 1)[-1]
                    if port not in ports:
                        ports.append(port)
        return ",".join(sorted(ports, key=int)[:4])

    # ------------------------------------------------------------- update

    def check_update(self) -> dict:
        return self._updater.check()

    def list_core_releases(self) -> dict:
        try:
            return {"ok": True, "releases": updater.list_core_releases()}
        except Exception as exc:
            log.warning("list core releases failed: %s", exc)
            return {"ok": False, "message": str(exc), "releases": []}

    def update_core(self, payload: dict) -> dict:
        """B2: build the core from a chosen release tag (empty = master)."""
        tag = (payload or {}).get("tag", "") or ""
        return self._updater.download_and_build(tag)

    def download_update(self) -> dict:
        return self._updater.download_and_build()

    def cancel_update(self) -> dict:
        self._updater.cancel()
        return {"ok": True}


def main() -> None:
    cfg = settings.Settings(os.path.join(APP_DIR, "config.json"))
    # Upgraded installs keep the pre-upgrade config.json: re-sync the version
    # so the about page and the app-update check see the real build.
    if cfg.get("app_version") != settings.VERSION:
        cfg.set("app_version", settings.VERSION)
        cfg.save()
        log.info("app_version synced to %s", settings.VERSION)
    # D3: migrate a legacy plaintext API key to DPAPI-encrypted storage once.
    raw_key = cfg.get("api_key", "") or ""
    if raw_key and not raw_key.startswith("dpapi:"):
        try:
            cfg.set("api_key", crypto.protect(raw_key))
            cfg.save()
            log.info("api key migrated to DPAPI storage")
        except (OSError, ValueError) as exc:
            log.warning("api key DPAPI migration failed: %s", exc)
    # Per-instance portable home: <app>\data\.dsh holds plugins, sessions,
    # settings and skins. Set DSH_HOME first, then migrate the legacy
    # ~/.dsh (move, one-time) and heal the profile for the plugin family.
    data_dir, home = homes.apply_home_env(APP_DIR, cfg)
    migration = homes.migrate_legacy_home(APP_DIR, cfg)
    homes.cleanup_legacy_garbled_files(APP_DIR)
    homes.heal_profile_file_deps(home, APP_DIR)
    homes.ensure_profile_workspace(home)
    core_stub = core_api.CoreController(APP_DIR, cfg)
    if homes.detect_tools(APP_DIR, cfg)["node"]["mode"] == "bundled":
        homes.ensure_dsh_shim(core_stub.runtime_dir, core_stub.bin_js)
    # Migration excluded node_modules (legacy store links): reinstall the
    # profile against the instance store, in the background.
    if migration.get("moved"):
        threading.Thread(target=homes.reinstall_profile,
                         args=(home, data_dir, core_stub.node_exe),
                         daemon=True).start()
    # A6: verify the migrated/upgraded profile once, in the background.
    threading.Thread(target=homes.run_health_check,
                     args=(APP_DIR, cfg, core_stub.node_exe, core_stub.bin_js),
                     daemon=True).start()
    log.info("instance data dir: %s (dsh home: %s)", data_dir, home)

    bridge = Bridge()
    port = cfg.get("port", 3080)
    ui = ui_server.UiServer(APP_DIR, bridge, shell_plugins=bridge._shell)
    if not ui.start():
        log.error("failed to start shell UI server")
        sys.exit(1)
    log.info("shell UI listening on http://127.0.0.1:%s", ui.port)

    state = bridge.get_state()
    window = webview.create_window(
        APP_NAME,
        url=f"http://127.0.0.1:{ui.port}/",
        width=1280,
        height=820,
        min_size=(980, 640),
        js_api=bridge,
        background_color="#101318",
        easy_drag=False,
        frameless=False,
    )
    window.events.closing += bridge._on_closing

    # Tray icon runs on its own thread; commands are drained by the shell UI
    # timer via bridge.poll_tray.
    bridge._tray.start()

    def _after_start() -> None:
        if state["app"]["autoStart"]:
            # Preseed first (instant once done), then start the server.
            threading.Thread(target=bridge._boot_with_preseed, daemon=True).start()
        else:
            threading.Thread(target=bridge._preseed_store, daemon=True).start()

    try:
        webview.start(func=_after_start, debug=False, http_server=False)
    finally:
        log.info("launcher exiting; stopping core server")
        bridge._core.stop()
        bridge._tray.stop()
        ui.stop()


if __name__ == "__main__":
    main()
