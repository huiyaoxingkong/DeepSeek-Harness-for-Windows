"""Store source management for the desktop launcher.

A "store source" is a plugin package that provides a plugin market UI inside
the dsh web app (e.g. `dshmarket` from the dsh-market project). Sources are
registered in config.json under `store_sources`; the preset store plugin is
built from a bundled source archive, so installing it needs no network.

The SHELL store is the catalog browser in the launcher itself: it fetches a
plugin catalog (`store_sources[].catalog`, defaulting to the awesome-dsh-plugin
registry the dsh-market project uses), shows plugin cards and installs /
updates / uninstalls through the same profile plugin pipeline.

Extension model for future store kinds: each source entry carries `name`
(the installed package name), `label`, `spec` (npm name / git URL / local
path — anything `pnpm add` accepts), optional `homepage` (origin annotation
shown in the UI), optional `catalog` (a plugins.json URL the shell store
browses), and `builtin` (preset, cannot be removed). The management UI
renders every registered source generically.

The store plugin is INSTALLED but not ENABLED by default (preseed): install
adds it as a profile dependency (dsh's reconcile auto-joins bundles), and a
`disabled: true` row in the profile's user patch layer (`cordis.patch.yml`,
the official mechanism the dsh-market project itself uses) keeps the loader
from mounting it until the user enables it. Enable/disable therefore manage
that patch row, not bundle membership — reconcile would re-add a dep removed
from bundles on the next plugin operation.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger("store")

PRESEED_TIMEOUT = 300

CATALOG_DEFAULT = "https://awesome-dsh-plugin.com/plugins.json"
CATALOG_TTL = 10 * 60

# Per-URL catalog cache so multiple store sources can be browsed together
# without refetching a source on every open.
_CATALOG_CACHE_BY_URL: dict = {}


def _catalog_cache_get(url: str) -> dict | None:
    entry = _CATALOG_CACHE_BY_URL.get(url)
    if entry and time.time() - entry["ts"] < CATALOG_TTL:
        return entry["result"]
    return None


def _catalog_cache_set(url: str, result: dict) -> None:
    _CATALOG_CACHE_BY_URL[url] = {"ts": time.time(), "result": result}


def _version_parts(version: str) -> list:
    parts = []
    for chunk in str(version).split("."):
        parts.append(int(chunk) if chunk.isdigit() else chunk)
    return parts


def version_newer(newer: str, older: str) -> bool:
    """Compare dotted version strings; non-numeric segments compare as text."""
    n_parts = _version_parts(newer)
    o_parts = _version_parts(older)
    for n, o in zip(n_parts, o_parts):
        if n != o:
            return n > o
    return len(n_parts) > len(o_parts)


class StoreManager:
    """List / add / remove / enable-disable store sources + first-run preseed."""

    def __init__(self, app_dir: str, settings, plugins) -> None:
        self._app_dir = app_dir
        self._cfg = settings
        self._plugins = plugins
        self._lock = threading.Lock()
        self._preseed_state: dict = {
            "phase": "idle",       # idle|running|done|failed
            "message": "",
        }

    # ------------------------------------------------------------- list

    def list(self) -> dict:
        manifest = self._plugins._read_manifest() or {}
        deps = manifest.get("dependencies") or {}
        bundles = manifest.get("dsh", {}).get("profile", {}).get("bundles") or []
        sources = []
        for src in self._sources():
            name = src.get("name", "")
            installed = name in deps
            entry_id = self._bundle_entry_id(name) if installed else None
            disabled = self._is_patch_disabled(entry_id) if entry_id else False
            sources.append({
                "name": name,
                "label": src.get("label") or name,
                "spec": src.get("spec", ""),
                "homepage": src.get("homepage", ""),
                "catalog": src.get("catalog", ""),
                "hasPackage": bool(src.get("spec")),
                "builtin": bool(src.get("builtin")),
                "installed": installed,
                "enabled": installed and not disabled,
                "version": self._plugins._installed_version(name) if installed else "",
            })
        with self._lock:
            preseed = {**self._preseed_state}
        return {"sources": sources, "preseed": preseed}

    def _sources(self) -> list[dict]:
        value = self._cfg.get("store_sources") or []
        return [s for s in value if isinstance(s, dict) and s.get("name")]

    def _source(self, name: str) -> dict | None:
        return next((s for s in self._sources() if s.get("name") == name), None)

    # ------------------------------------------------------------- catalog

    def catalog(self, source_name: str | None = None) -> dict:
        """Fetch and normalize the shell-store plugin catalog.

        With no source name, every source that declares a `catalog` URL is
        fetched and merged (each entry annotated with its origin source for
        the "来源" label). A source name restricts browsing to that source.
        """
        if source_name:
            src = self._source(source_name)
            if src is None or not src.get("catalog"):
                return {"ok": False,
                        "message": "商店源未配置目录地址（catalog）。",
                        "plugins": [], "categories": {}, "sources": [],
                        "count": 0}
            merged = self._catalog_from_sources([src])
            merged["sources"] = [self._source_meta(src)]
            return merged

        sources = [s for s in self._sources() if s.get("catalog")]
        if not sources:
            return {"ok": False,
                    "message": "商店源未配置目录地址（catalog）。",
                    "plugins": [], "categories": {}, "sources": [],
                    "count": 0}
        merged = self._catalog_from_sources(sources)
        merged["sources"] = [self._source_meta(s) for s in sources]
        return merged

    @staticmethod
    def _source_meta(src: dict) -> dict:
        return {
            "name": src.get("name"),
            "label": src.get("label") or src.get("name"),
            "homepage": src.get("homepage", ""),
            "catalog": src.get("catalog", ""),
        }

    def _catalog_from_sources(self, sources: list[dict]) -> dict:
        manifest = self._plugins._read_manifest() or {}
        deps = manifest.get("dependencies") or {}
        bundles = manifest.get("dsh", {}).get("profile", {}).get("bundles") or []
        categories: dict = {}
        plugins: list[dict] = []
        errors: list[str] = []
        updated = ""
        for src in sources:
            url = src.get("catalog", "")
            payload = self._fetch_catalog(url)
            if payload.get("ok") is False:
                errors.append(f"{src.get('name')}: {payload.get('message', '加载失败')}")
                continue
            raw = payload["raw"]
            if not updated and raw.get("updated"):
                updated = raw["updated"]
            for cid, meta in (raw.get("categories") or {}).items():
                categories.setdefault(cid, meta)
            for entry in raw.get("plugins") or []:
                npm = entry.get("npm") or ""
                installed = bool(npm) and npm in deps
                plugins.append({
                    "name": entry.get("name", ""),
                    "owner": entry.get("owner", ""),
                    "repo": entry.get("url", ""),
                    "page": entry.get("page", ""),
                    "category": entry.get("category", ""),
                    "description": (entry.get("description") or {}).get("zh")
                                   or (entry.get("description") or {}).get("en") or "",
                    "stars": entry.get("stars") or 0,
                    "downloads": entry.get("downloads") or 0,
                    "added": entry.get("added", ""),
                    "npm": npm,
                    "spec": self._catalog_spec(entry),
                    "sourceName": src.get("name"),
                    "sourceLabel": src.get("label") or src.get("name"),
                    "sourceHomepage": src.get("homepage", ""),
                    "installed": installed,
                    "enabled": installed and npm in bundles,
                    "version": self._plugins._installed_version(npm) if installed else "",
                })
        ok = bool(plugins) or not errors
        return {
            "ok": ok,
            "message": "；".join(errors) if errors else "",
            "categories": categories,
            "plugins": plugins,
            "count": len(plugins),
            "updated": updated,
            "errors": errors,
            "cached": bool(payload.get("cached")) if payload else False,
        }

    @staticmethod
    def _catalog_spec(entry: dict) -> str:
        """The pnpm spec for a catalog entry: npm package name preferred,
        the github repo URL otherwise."""
        npm = entry.get("npm") or ""
        if npm:
            return npm
        return entry.get("url") or ""

    @staticmethod
    def _fetch_catalog(url: str) -> dict:
        """Fetch a plugins.json document (cached for CATALOG_TTL seconds)."""
        cached = _catalog_cache_get(url)
        if cached is not None:
            return {**cached, "cached": True}
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "DeepSeek-Harness-Desktop/0.1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                import json
                raw = json.loads(resp.read().decode("utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("plugins"), list):
                return {"ok": False, "message": "目录格式不正确。",
                        "plugins": [], "categories": {}}
            result = {"ok": True, "raw": raw, "url": url,
                      "cached": False,
                      "fetchedAt": time.strftime("%Y-%m-%d %H:%M:%S")}
            _catalog_cache_set(url, result)
            return {**result, "cached": False}
        except urllib.error.HTTPError as exc:
            return {"ok": False,
                    "message": f"目录加载失败（HTTP {exc.code}）。",
                    "plugins": [], "categories": {}}
        except Exception as exc:  # network or parse failure: never block the UI
            log.warning("catalog fetch failed: %s", exc)
            return {"ok": False, "message": f"目录加载失败：{exc}",
                    "plugins": [], "categories": {}}

    # ------------------------------------------------------------- catalog ops

    def install_from_catalog(self, name: str) -> tuple[bool, str]:
        """Install a catalog plugin by its display name (any source)."""
        sources = [s for s in self._sources() if s.get("catalog")]
        if not sources:
            return False, "商店源未配置目录地址（catalog）。"
        for src in sources:
            payload = self._fetch_catalog(src.get("catalog", ""))
            if payload.get("ok") is False:
                continue
            entry = next((e for e in (payload["raw"].get("plugins") or [])
                          if e.get("name") == name), None)
            if entry is None:
                continue
            spec = self._catalog_spec(entry)
            if not spec:
                return False, f"插件 {name} 没有可安装来源（无 npm 包与仓库地址）。"
            return self._plugins.install(spec)
        return False, f"目录中未找到插件 {name}。"

    def update_from_catalog(self, name: str) -> tuple[bool, str]:
        """Update an installed catalog plugin to its latest version."""
        name = (name or "").strip()
        if not name:
            return False, "请输入要更新的插件名。"
        return self._plugins._run(["update", name], "updating")

    # ------------------------------------------------------------- actions

    def add(self, name: str, spec: str, catalog: str = "",
            homepage: str = "") -> tuple[bool, str]:
        """Register a store source. `spec` (the core plugin package) and
        `catalog` (a plugins.json URL for the shell store) are both optional,
        but at least one is required — a catalog-only source is the
        extension point for future store kinds."""
        name = (name or "").strip()
        spec = (spec or "").strip()
        catalog = (catalog or "").strip()
        homepage = (homepage or "").strip()
        if not name:
            return False, "名称不能为空。"
        if not spec and not catalog:
            return False, "安装来源与目录地址至少填一项。"
        sources = self._sources()
        if any(s.get("name") == name for s in sources):
            return False, "同名商店源已存在。"
        sources.append({
            "name": name,
            "label": name,
            "spec": spec,
            "homepage": homepage,
            "catalog": catalog,
            "builtin": False,
        })
        self._cfg.set("store_sources", sources)
        self._cfg.save()
        return True, "已添加商店源" + ("（含插件目录，已出现在上方商店中）" if catalog
                                else "，点击「启用」开始安装。")

    def remove(self, name: str) -> tuple[bool, str]:
        name = (name or "").strip()
        sources = self._sources()
        if not any(s.get("name") == name for s in sources):
            return False, "未找到该商店源。"
        if any(s.get("name") == name and s.get("builtin") for s in sources):
            return False, "内置商店源不可移除（可停用）。"
        manifest = self._plugins._read_manifest() or {}
        if name in (manifest.get("dependencies") or {}):
            return False, "该源对应的插件已安装，请先在插件列表卸载后再移除商店源。"
        self._cfg.set("store_sources", [s for s in sources if s.get("name") != name])
        self._cfg.save()
        return True, "已移除商店源。"

    def set_enabled(self, name: str, enabled: bool) -> tuple[bool, str]:
        name = (name or "").strip()
        src = self._source(name)
        if src is None:
            return False, "未找到该商店源。"
        spec = self._resolve_spec(src.get("spec", ""))
        manifest = self._plugins._read_manifest() or {}
        deps = manifest.get("dependencies") or {}
        installed = name in deps
        if enabled:
            if not installed:
                if not spec:
                    return False, "该源未配置安装来源（仅提供插件目录）。"
                return self._plugins.install(spec)
            entry_id = self._bundle_entry_id(name)
            if entry_id is None:
                return False, "无法确定该商店的加载条目（未找到 bundle 补丁）。"
            return self._set_patch_disabled(entry_id, False)
        if not installed:
            return True, "该源尚未安装，无需停用。"
        entry_id = self._bundle_entry_id(name)
        if entry_id is None:
            return False, "无法确定该商店的加载条目（未找到 bundle 补丁）。"
        return self._set_patch_disabled(entry_id, True)

    # ------------------------------------------------------------- preseed

    def preseed(self) -> tuple[bool, str]:
        """Install the builtin store package if missing, then keep it disabled
        (installed but not enabled). Blocking; safe to call from a thread."""
        with self._lock:
            if self._preseed_state["phase"] == "running":
                return False, "内置商店预装进行中。"
            src = next((s for s in self._sources() if s.get("builtin")), None)
            if src is None:
                self._preseed_state.update(phase="idle", message="")
                return True, "无内置商店源。"
            name = src.get("name", "")
            self._preseed_state.update(phase="running",
                                       message=f"正在预装 {name}…")
        try:
            manifest = self._plugins._read_manifest() or {}
            if name not in (manifest.get("dependencies") or {}):
                if self._plugins.status()["phase"] != "idle":
                    self._preseed_state.update(
                        phase="failed", message="已有插件操作进行中，将在下次启动时重试。")
                    return False, "已有插件操作进行中。"
                ok, msg = self._plugins.install(self._resolve_spec(src.get("spec", "")))
                if not ok:
                    self._preseed_state.update(phase="failed", message=msg)
                    return False, msg
                deadline = time.time() + PRESEED_TIMEOUT
                while time.time() < deadline:
                    st = self._plugins.status()
                    if st["phase"] == "idle":
                        break
                    time.sleep(1)
                else:
                    self._preseed_state.update(phase="failed", message="预装超时。")
                    return False, "内置商店预装超时。"
                if st.get("error"):
                    self._preseed_state.update(phase="failed",
                                               message=f"预装失败: {st['error']}")
                    return False, f"内置商店预装失败: {st['error']}"
                # dsh reconcile auto-joins bundles; keep the store OFF.
                entry_id = self._bundle_entry_id(name)
                if entry_id is not None:
                    self._set_patch_disabled(entry_id, True)
            with self._lock:
                self._preseed_state.update(phase="done",
                                           message="内置商店已安装（未启用）。")
            return True, "内置商店已安装（未启用）。"
        except Exception as exc:  # never let preseed crash the launch thread
            log.exception("preseed failed")
            with self._lock:
                self._preseed_state.update(phase="failed", message=str(exc))
            return False, f"内置商店预装失败: {exc}"

    # ------------------------------------------------------------- patch layer

    @property
    def _patch_path(self) -> str:
        return os.path.join(self._plugins.profile_dir, "cordis.patch.yml")

    def _bundle_entry_id(self, name: str) -> str | None:
        """The loader entry id a bundle inserts, read from the installed
        package's own bundle patch (`dsh.bundle.patch` -> first `- id:`)."""
        manifest = self._plugins._read_manifest() or {}
        if name not in (manifest.get("dependencies") or {}):
            return None
        pkg_dir = os.path.join(self._plugins.profile_dir, "node_modules",
                               *name.split("/"))
        try:
            with open(os.path.join(pkg_dir, "package.json"), "r",
                      encoding="utf-8") as fh:
                import json
                pj = json.load(fh)
        except (OSError, ValueError):
            return None
        patch_rel = (pj.get("dsh") or {}).get("bundle", {}).get("patch")
        if not patch_rel:
            return name
        try:
            with open(os.path.join(pkg_dir, patch_rel), "r",
                      encoding="utf-8-sig") as fh:
                for line in fh:
                    match = re.match(r"\s*-\s*id:\s*(.+)", line)
                    if match:
                        return match.group(1).strip().strip("'\"")
        except OSError:
            return None
        return name

    def _is_patch_disabled(self, entry_id: str) -> bool:
        lines = self._read_patch()
        idx = self._find_entry(lines, entry_id)
        if idx is None:
            return False
        for line in lines[idx + 1:self._block_end(lines, idx)]:
            match = re.match(r"^\s+disabled:\s*(\S+)", line)
            if match:
                return match.group(1).strip().lower() == "true"
        return False

    def _set_patch_disabled(self, entry_id: str, disabled: bool) -> tuple[bool, str]:
        lines = self._read_patch()
        idx = self._find_entry(lines, entry_id)
        value = "true" if disabled else "false"
        if idx is None:
            meaningful = [l for l in lines
                          if l.strip() and not l.strip().startswith("#")]
            if meaningful and not (
                    len(meaningful) == 1 and meaningful[0].strip() == "[]"):
                # A malformed file (no entry list) is never made worse.
                return False, "profile 补丁文件格式异常，无法写入停用标记。"
            head = "\n".join(
                l for l in lines
                if not l.strip() or l.strip().startswith("#"))
            if head:
                head += "\n"
            text = f"{head}- id: {entry_id}\n  disabled: {value}\n"
        else:
            end = self._block_end(lines, idx)
            replaced = False
            for j in range(idx + 1, end):
                if re.match(r"^\s+disabled:\s*", lines[j]):
                    lines[j] = f"  disabled: {value}"
                    replaced = True
                    break
            if not replaced:
                lines.insert(idx + 1, f"  disabled: {value}")
            text = "\n".join(lines) + "\n"
        try:
            with open(self._patch_path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            return False, f"写入补丁文件失败: {exc}"
        return True, ("已停用，重启服务器后生效。" if disabled
                      else "已启用，重启服务器后生效。")

    def _read_patch(self) -> list[str]:
        if not os.path.isfile(self._patch_path):
            return []
        try:
            with open(self._patch_path, "r", encoding="utf-8-sig") as fh:
                return fh.read().splitlines()
        except OSError:
            return []

    @staticmethod
    def _find_entry(lines: list[str], entry_id: str) -> int | None:
        for i, line in enumerate(lines):
            match = re.match(r"^\s*-\s*id:\s*(.+)", line)
            if match and match.group(1).strip().strip("'\"") == entry_id:
                return i
        return None

    @staticmethod
    def _block_end(lines: list[str], start: int) -> int:
        for j in range(start + 1, len(lines)):
            if lines[j].startswith("- "):
                return j
        return len(lines)

    # ------------------------------------------------------------- helpers

    def _resolve_spec(self, spec: str) -> str:
        """Anchor a spec that points at a bundled local file to an absolute
        path so pnpm (running in the profile dir) finds it."""
        spec = spec.strip()
        if not spec or spec.startswith(("file:", "link:")):
            return spec
        candidate = os.path.join(self._app_dir, spec)
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
        return spec
