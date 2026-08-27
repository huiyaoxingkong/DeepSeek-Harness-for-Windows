"""Shell UI plugin manager.

Shell plugins are small web packages (``plugin.json`` + ``main.js`` + optional
assets) that extend the launcher UI itself — pages, cards and actions —
mirroring the core's plugin model at the shell level.

Two roots:

- bundled: ``<app>\\ui\\plugins\\<id>`` (ships with the app; the PyInstaller
  bundle serves it from ``_internal\\ui``), removable = no, disable = yes;
- user:    ``<data>\\shell-plugins\\<id>`` (installed from local zips,
  survives upgrades), removable = yes.

Enable state lives in ``config.json -> shell_plugins: {<id>: {"enabled": bool}}``;
bundled and freshly imported plugins default to enabled.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import zipfile

log = logging.getLogger("shellplugins")

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _read_manifest(root: str) -> dict | None:
    path = os.path.join(root, "plugin.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    return data


class ShellPluginManager:
    """Scan / manage shell UI plugins."""

    def __init__(self, app_dir: str, settings) -> None:
        self._app_dir = app_dir
        self._cfg = settings

    # ------------------------------------------------------------- paths

    def bundled_root(self) -> str:
        root = os.path.join(self._app_dir, "ui", "plugins")
        if not os.path.isdir(root):
            root = os.path.join(self._app_dir, "_internal", "ui", "plugins")
        return root

    def user_root(self) -> str:
        data = os.path.join(self._app_dir,
                            self._cfg.get("data_dir", "data"))
        return os.path.join(data, "shell-plugins")

    def resolve(self, plugin_id: str, relpath: str = "") -> str | None:
        """Resolve a plugin file; the user root shadows the bundled one."""
        for root in (self.user_root(), self.bundled_root()):
            base = os.path.join(root, plugin_id)
            full = os.path.normpath(os.path.join(base, relpath))
            if (os.path.isfile(full) and full.startswith(os.path.normpath(base))):
                return full
        return None

    # ------------------------------------------------------------- scan

    def _enabled_cfg(self) -> dict:
        cfg = self._cfg.get("shell_plugins", {})
        return cfg if isinstance(cfg, dict) else {}

    def _scan_root(self, root: str, builtin: bool) -> list[dict]:
        if not os.path.isdir(root):
            return []
        enabled_cfg = self._enabled_cfg()
        out = []
        for entry in sorted(os.listdir(root)):
            full = os.path.join(root, entry)
            if not os.path.isdir(full):
                continue
            manifest = _read_manifest(full)
            if manifest is None:
                continue
            plugin_id = str(manifest.get("id") or entry)
            entry_js = os.path.join(full, str(manifest.get("entry") or "main.js"))
            out.append({
                "id": plugin_id,
                "name": str(manifest.get("name") or plugin_id),
                "version": str(manifest.get("version") or ""),
                "description": str(manifest.get("description") or ""),
                "builtin": builtin,
                "root": full,
                "valid": os.path.isfile(entry_js),
                "enabled": bool(enabled_cfg.get(plugin_id, {}).get(
                    "enabled", True) if isinstance(
                        enabled_cfg.get(plugin_id), dict) else True),
            })
        return out

    def list(self) -> dict:
        plugins = self._scan_root(self.bundled_root(), builtin=True)
        plugins += self._scan_root(self.user_root(), builtin=False)
        return {"plugins": plugins, "userDir": self.user_root()}

    def manifest(self) -> dict:
        """Enabled plugins for the UI loader: id + entry URL (relative)."""
        entries = []
        for p in self.list()["plugins"]:
            if p["enabled"] and p["valid"]:
                entries.append({
                    "id": p["id"],
                    "name": p["name"],
                    "entry": f"/plugin/{p['id']}/main.js",
                })
        return {"plugins": entries}

    # ------------------------------------------------------------- actions

    def set_enabled(self, plugin_id: str, enabled: bool) -> tuple[bool, str]:
        plugin_id = (plugin_id or "").strip()
        if not _ID_RE.match(plugin_id):
            return False, "插件 id 不合法"
        found = [p for p in self.list()["plugins"] if p["id"] == plugin_id]
        if not found:
            return False, f"未找到外壳插件 {plugin_id}"
        cfg = dict(self._enabled_cfg())
        cfg[plugin_id] = {"enabled": bool(enabled)}
        self._cfg.set("shell_plugins", cfg)
        self._cfg.save()
        return True, f"已{'启用' if enabled else '停用'} {plugin_id}，重启应用后生效。"

    def import_from_file(self, path: str) -> tuple[bool, str]:
        """Install a shell plugin from a local zip (plugin.json + main.js)."""
        path = (path or "").strip().strip('"')
        if not os.path.isfile(path) or not path.lower().endswith(".zip"):
            return False, "请选择 zip 格式的外壳插件包。"
        # Stage inside the instance data dir (no C-drive/system-temp writes).
        staging = os.path.join(os.path.dirname(self.user_root()),
                               ".shell-plugin-staging")
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(staging, exist_ok=True)
        try:
            with zipfile.ZipFile(path) as zf:
                zf.extractall(staging)
            candidates = []
            for name in os.listdir(staging):
                full = os.path.join(staging, name)
                if os.path.isdir(full) and _read_manifest(full):
                    candidates.append(full)
            root = os.path.join(staging, "plugin.json")
            if os.path.isfile(root):
                candidates.append(staging)
            if not candidates:
                return False, "压缩包中未找到 plugin.json，请确认是外壳插件包。"
            src = candidates[0]
            manifest = _read_manifest(src) or {}
            plugin_id = str(manifest.get("id") or "")
            if not _ID_RE.match(plugin_id):
                return False, "plugin.json 的 id 不合法（字母/数字/._-，最长 64）"
            if not os.path.isfile(os.path.join(
                    src, str(manifest.get("entry") or "main.js"))):
                return False, "插件包缺少入口脚本 main.js（或 plugin.json 中 entry 指定的文件）"
            dest = os.path.join(self.user_root(), plugin_id)
            if os.path.isdir(dest):
                shutil.rmtree(dest, ignore_errors=True)
            os.makedirs(self.user_root(), exist_ok=True)
            shutil.move(src, dest)
            cfg = dict(self._enabled_cfg())
            cfg[plugin_id] = {"enabled": True}
            self._cfg.set("shell_plugins", cfg)
            self._cfg.save()
            return True, f"已安装外壳插件 {plugin_id}（重启应用后生效）。"
        except (OSError, zipfile.BadZipFile) as exc:
            log.exception("shell plugin import failed")
            return False, f"导入失败: {exc}"
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def remove(self, plugin_id: str) -> tuple[bool, str]:
        plugin_id = (plugin_id or "").strip()
        for p in self.list()["plugins"]:
            if p["id"] == plugin_id:
                if p["builtin"]:
                    return False, "内置外壳插件不可卸载（可停用）"
                break
        else:
            return False, f"未找到外壳插件 {plugin_id}"
        target = os.path.join(self.user_root(), plugin_id)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        cfg = dict(self._enabled_cfg())
        cfg.pop(plugin_id, None)
        self._cfg.set("shell_plugins", cfg)
        self._cfg.save()
        return True, f"已卸载外壳插件 {plugin_id}（重启应用后生效）。"
