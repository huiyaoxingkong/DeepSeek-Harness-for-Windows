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
        "core_dir": "core",
        "runtime_dir": "runtime",
        "app_version": "1.0.0",
        "last_updated_core": "",
        "onboarding_done": False,
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
