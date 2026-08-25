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
import sys
import threading
import time

import webview

import core_api
import junctions
import plugins
import providers
import settings
import store
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
        self._plugins = plugins.PluginManager(APP_DIR, self._cfg, self._core)
        self._store = store.StoreManager(APP_DIR, self._cfg, self._plugins)
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

    def get_state(self) -> dict:
        state = {
            "app": {
                "name": APP_NAME,
                "version": self._cfg.get("app_version", "0.1.0"),
                "port": self._cfg.get("port", 3080),
                "apiKeySet": bool(self._cfg.get("api_key", "")),
                "apiKeyMasked": self._mask_key(self._cfg.get("api_key", "")),
                "baseUrl": self._cfg.get("base_url", ""),
                "autoStart": self._cfg.get("auto_start", False),
                "openBrowser": self._cfg.get("open_browser", False),
                "onboardingDone": self._cfg.get("onboarding_done", False),
            },
            "server": self._core.status(),
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
        return self._cfg.get("api_key", "")

    def set_onboarding_done(self, payload: dict = None) -> dict:
        self._cfg.set("onboarding_done", True)
        self._cfg.save()
        return {"ok": True}

    def save_settings(self, patch: dict) -> dict:
        allowed = {"api_key", "base_url", "port", "auto_start", "open_browser"}
        for key, value in patch.items():
            if key not in allowed:
                continue
            if value is None:
                continue  # masked key unchanged; keep the stored value
            if key == "port":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
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

    def read_log(self, tail: int = 200) -> str:
        return self._core.read_log(tail)

    # ------------------------------------------------------------- plugins

    def list_plugins(self) -> dict:
        return self._plugins.list()

    def install_plugin(self, payload: dict) -> dict:
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
            app_key_set=bool(self._cfg.get("api_key", "")))

    # ------------------------------------------------------------- app update

    def check_app_update(self) -> dict:
        return updater.check_app_release(self._cfg.get("app_version", ""))

    # ------------------------------------------------------------- update

    def check_update(self) -> dict:
        return self._updater.check()

    def download_update(self) -> dict:
        return self._updater.download_and_build()

    def cancel_update(self) -> dict:
        self._updater.cancel()
        return {"ok": True}


def main() -> None:
    cfg = settings.Settings(os.path.join(APP_DIR, "config.json"))
    bridge = Bridge()
    port = cfg.get("port", 3080)
    ui = ui_server.UiServer(APP_DIR, bridge)
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
        ui.stop()


if __name__ == "__main__":
    main()
