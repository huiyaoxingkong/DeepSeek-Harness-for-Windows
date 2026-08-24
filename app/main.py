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
import plugins
import providers
import settings
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

    # ------------------------------------------------------------- providers

    def list_providers(self) -> dict:
        return providers.list_providers(
            app_key_set=bool(self._cfg.get("api_key", "")))

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
            threading.Thread(target=bridge.start_server, daemon=True).start()

    try:
        webview.start(func=_after_start, debug=False, http_server=False)
    finally:
        log.info("launcher exiting; stopping core server")
        bridge._core.stop()
        ui.stop()


if __name__ == "__main__":
    main()
