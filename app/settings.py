"""JSON config persistence for the desktop launcher."""

from __future__ import annotations

import json
import os
import threading


class Settings:
    """Thread-safe JSON settings file with a minimal default schema."""

    DEFAULTS = {
        "api_key": "",
        "base_url": "",
        "port": 3080,
        "auto_start": False,
        "open_browser": False,
        "close_to_tray": False,
        "proxy_url": "",
        "npm_registry": "",
        "github_mirror": "",
        "core_dir": "core",
        "runtime_dir": "runtime",
        "data_dir": "data",
        "app_version": "1.0.3",
        "last_updated_core": "",
        "onboarding_done": False,
        "shell_plugins": {},
        "ui_state": {"immersive": False},
        "store_sources": [
            {
                "name": "dshmarket",
                "label": "dshmarket 插件商店",
                "spec": "store/dshmarket-1.33.0.tgz",
                "homepage": "https://github.com/dsh-market/dsh-market",
                "catalog": "https://awesome-dsh-plugin.com/plugins.json",
                "builtin": True,
            },
        ],
    }

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            self._data = dict(self.DEFAULTS)
            if os.path.isfile(self._path):
                try:
                    # utf-8-sig tolerates a BOM (e.g. files written by
                    # PowerShell Set-Content -Encoding UTF8).
                    with open(self._path, "r", encoding="utf-8-sig") as fh:
                        loaded = json.load(fh)
                    if isinstance(loaded, dict):
                        self._data.update({k: v for k, v in loaded.items() if k in self.DEFAULTS})
                except (OSError, ValueError):
                    pass

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value

    def save(self) -> None:
        with self._lock:
            try:
                with open(self._path, "w", encoding="utf-8") as fh:
                    json.dump(self._data, fh, ensure_ascii=False, indent=2)
            except OSError:
                pass
