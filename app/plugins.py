"""Plugin manager for the desktop launcher.

dsh profiles live under `~/.dsh/profiles/<name>` (or $DSH_HOME). Plugins are
dependencies of the profile package that declare a `dsh.bundle` patch; the CLI
command `dsh plugin --profile web add/remove <spec>` forwards to pnpm inside
the profile directory and reconciles the bundle layer list. This module wraps
that command with live output capture and reads the profile manifest for the
plugin list.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading

import homes

log = logging.getLogger("plugins")

PROFILE = "web"


class PluginManager:
    """List / install / remove / enable-disable profile plugins."""

    def __init__(self, app_dir: str, settings, core) -> None:
        self._app_dir = app_dir
        self._cfg = settings
        self._core = core
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._state: dict = {
            "phase": "idle",       # idle|installing|removing|toggling
            "message": "",
            "output": [],
            "error": None,
        }

    # ------------------------------------------------------------- paths

    @property
    def profile_dir(self) -> str:
        """The web profile directory inside the instance data home.

        The launcher exports DSH_HOME (= <app>\\data\\.dsh) at startup, so
        the core's own profile resolution and this manager agree on the same
        directory — everything plugin-related stays inside the installation.
        """
        home = os.environ.get("DSH_HOME") or homes.dsh_home(
            homes.data_dir(self._app_dir, self._cfg))
        return os.path.join(home, "profiles", PROFILE)

    def _read_manifest(self) -> dict | None:
        path = os.path.join(self.profile_dir, "package.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    # ------------------------------------------------------------- list

    def list(self) -> dict:
        manifest = self._read_manifest() or {}
        deps = manifest.get("dependencies") or {}
        bundles = manifest.get("dsh", {}).get("profile", {}).get("bundles") or []
        plugins: list[dict] = []
        for name in bundles:
            version = self._installed_version(name)
            if name in deps:
                plugins.append({"name": name, "version": version,
                                "spec": deps[name], "enabled": True, "builtin": False})
            else:
                plugins.append({"name": name, "version": version,
                                "spec": "", "enabled": True, "builtin": True})
        for name, spec in deps.items():
            if name in bundles:
                continue
            plugins.append({"name": name, "version": self._installed_version(name),
                            "spec": spec, "enabled": False, "builtin": False})
        plugins.sort(key=lambda p: (p["builtin"], p["name"]))
        return {"plugins": plugins, "profileDir": self.profile_dir,
                "running": self._core.is_running()}

    def _installed_version(self, name: str) -> str:
        try:
            manifest = os.path.join(self.profile_dir, "node_modules", *name.split("/"),
                                    "package.json")
            with open(manifest, "r", encoding="utf-8") as fh:
                return json.load(fh).get("version", "")
        except (OSError, ValueError):
            return ""

    # ------------------------------------------------------------- actions

    def install(self, spec: str) -> tuple[bool, str]:
        spec = spec.strip()
        if not spec:
            return False, "请输入插件包名或仓库地址"
        if os.path.isfile(spec) and (" " in os.path.dirname(spec)
                                     or " " in os.path.basename(spec)):
            spec = self._stage(spec)
        return self._run(["add", spec], "installing")

    def import_from_file(self, path: str) -> tuple[bool, str]:
        """Install a plugin from a local file: npm tarball (.tgz / .tar.gz)
        or a source zip (.zip). No network is needed to transfer the package;
        pnpm resolves transitive dependencies from its store/registry."""
        path = (path or "").strip().strip('"')
        if not os.path.isfile(path):
            return False, "文件不存在，请重新选择插件包。"
        lowered = path.lower()
        if lowered.endswith(".tgz") or lowered.endswith(".tar.gz"):
            spec = self._stage(os.path.abspath(path))
        elif lowered.endswith(".zip"):
            spec = self._extract_zip(path)
            if spec is None:
                return False, "压缩包中未找到 package.json，请确认是插件源码或插件包。"
        else:
            return False, "仅支持 .tgz / .tar.gz / .zip 格式的插件包。"
        return self._run(["add", spec], "installing")

    def _cache_dir(self) -> str:
        """Space-free cache for local plugin files, kept inside the instance
        data directory (no C-drive footprint). The dsh CLI forwards path
        specs to pnpm through a cmd shim that splits unquoted space paths
        (the app folder itself is "DeepSeek Harness"), so anything with a
        space in its path must be staged here first."""
        cache = os.path.join(
            homes.data_dir(self._app_dir, self._cfg), "plugin-cache")
        os.makedirs(cache, exist_ok=True)
        return cache

    def _stage(self, path: str) -> str:
        """Copy a local plugin file into the space-free cache dir."""
        dst = os.path.join(self._cache_dir(), os.path.basename(path))
        if os.path.abspath(path) != os.path.abspath(dst):
            shutil.copy2(path, dst)
        return dst

    def _extract_zip(self, path: str) -> str | None:
        """Unpack a plugin source zip into the space-free cache dir and
        return the dir containing package.json (None when the zip is not a
        plugin)."""
        import zipfile
        name = os.path.splitext(os.path.basename(path))[0]
        out = os.path.join(self._cache_dir(), name)
        if os.path.isdir(out):
            shutil.rmtree(out, ignore_errors=True)
        try:
            with zipfile.ZipFile(path) as zf:
                zf.extractall(out)
        except (OSError, zipfile.BadZipFile):
            return None
        if os.path.isfile(os.path.join(out, "package.json")):
            return os.path.abspath(out)
        entries = [d for d in os.listdir(out)
                   if os.path.isdir(os.path.join(out, d))]
        if len(entries) == 1:
            inner = os.path.join(out, entries[0])
            if os.path.isfile(os.path.join(inner, "package.json")):
                return os.path.abspath(inner)
        return None

    def remove(self, name: str) -> tuple[bool, str]:
        name = (name or "").strip()
        if not name:
            return False, "请输入要卸载的插件名。"
        return self._run(["remove", name], "removing")

    def set_enabled(self, name: str, enabled: bool) -> tuple[bool, str]:
        manifest = self._read_manifest()
        if manifest is None:
            return False, "profile 尚未初始化"
        deps = manifest.get("dependencies") or {}
        if name not in deps:
            return False, "该插件不是已安装的依赖，无法停用"
        bundles = list(manifest.get("dsh", {}).get("profile", {}).get("bundles") or [])
        was = name in bundles
        if enabled == was:
            return True, "状态未变化"
        if enabled:
            bundles.append(name)
        else:
            bundles.remove(name)
        manifest.setdefault("dsh", {})["profile"] = {"bundles": bundles}
        try:
            with open(os.path.join(self.profile_dir, "package.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            return False, f"写入 profile 清单失败: {exc}"
        with self._lock:
            self._state.update(phase="idle", message=(
                f"已{'启用' if enabled else '停用'} {name}，重启服务器后生效。"),
                output=[], error=None)
        return True, "已修改，重启服务器后生效"

    # ------------------------------------------------------------- runner

    def _run(self, args: list[str], phase: str) -> tuple[bool, str]:
        with self._lock:
            if self._state["phase"] != "idle":
                return False, "已有插件操作正在进行，请稍候"
            self._state.update(phase=phase, message="", output=[], error=None)
            if self._core.is_running():
                self._core.stop()
        node_dir = self._core.runtime_dir
        bundled = os.path.isfile(os.path.join(
            self._app_dir, self._cfg.get("runtime_dir", "runtime"), "node.exe"))
        # Keep the profile compatible with the @linxin666/dsh-web plugin
        # family (hoisted linker, allowBuilds, release-age exclusion) and
        # make the dsh CLI findable for plugins that spawn it themselves.
        data = homes.data_dir(self._app_dir, self._cfg)
        home = os.environ.get("DSH_HOME") or homes.dsh_home(data)
        homes.ensure_profile_workspace(home)
        if bundled:
            homes.ensure_dsh_shim(node_dir, self._core.bin_js)
        cmd = [self._core.node_exe, self._core.bin_js, "plugin",
               "--profile", PROFILE]
        # Local file specs (staged tarballs/zips) live under the app dir which
        # may contain spaces; the dsh CLI splits unquoted space paths, so map
        # them through a space-free junction instead.
        cmd += [homes.cli_path(self._app_dir, a) if os.path.exists(a) else a
                for a in args]
        env = dict(os.environ)
        paths = [node_dir] if os.path.isdir(node_dir) else []
        paths.extend(homes.git_path_entries(node_dir))
        if paths:
            env["PATH"] = os.pathsep.join(paths) + os.pathsep + env.get("PATH", "")
        env["DSH_HOME"] = home
        env.update(homes.pnpm_env(data, node_dir if bundled else data))
        env.update(homes.proxy_env(self._cfg))
        env.update(homes.registry_env(self._cfg))
        # Slow networks: relax pnpm's fetch budget for plugin installs too
        # (large native tarballs like dsh-pet's assets stall otherwise).
        env["npm_config_fetch_timeout"] = "600000"
        env["npm_config_fetch_retries"] = "5"
        env["pnpm_config_fetch_timeout"] = "600000"
        env["pnpm_config_fetch_retries"] = "5"
        log.info("plugin run: %s", " ".join(cmd))
        worker = threading.Thread(
            target=self._run_worker, args=(cmd, env, phase), daemon=True)
        worker.start()
        return True, "操作已开始，进度见下方输出"

    def _run_worker(self, cmd: list[str], env: dict, phase: str) -> None:
        try:
            proc = subprocess.Popen(
                cmd, cwd=self._app_dir, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self._proc = proc
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                with self._lock:
                    self._state["output"].append(line)
                    if len(self._state["output"]) > 200:
                        self._state["output"].pop(0)
                    self._state["message"] = line[:90]
            proc.wait()
            with self._lock:
                if proc.returncode == 0:
                    self._state.update(phase="idle", message="操作完成，重启服务器后生效。")
                else:
                    self._state.update(
                        phase="idle", message=f"操作失败（退出码 {proc.returncode}）",
                        error=f"exit code {proc.returncode}")
        except OSError as exc:
            with self._lock:
                self._state.update(phase="idle", message=f"无法启动插件命令: {exc}",
                                   error=str(exc))

    # ------------------------------------------------------------- state

    def status(self) -> dict:
        with self._lock:
            return {**self._state}
