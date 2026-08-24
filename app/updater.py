"""GitHub source updater for the dsh core.

Downloads the upstream repository source zip, rebuilds it with the bundled
Node/pnpm toolchain, and swaps it in atomically. The old core is kept as a
backup so a failed build never leaves the app without a working core.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
import urllib.request
import zipfile

import relink

log = logging.getLogger("updater")

UPSTREAM = "https://github.com/deepseek-ai/deepseek-harness"
BRANCH = "master"
ZIP_URL = f"{UPSTREAM}/archive/refs/heads/{BRANCH}.zip"
API_URL = "https://api.github.com/repos/deepseek-ai/deepseek-harness"
USER_AGENT = "DeepSeek-Harness-Desktop/0.1"


class CoreUpdater:
    """Download -> extract -> install -> build -> swap core from GitHub source."""

    def __init__(self, app_dir: str, settings, core) -> None:
        self._app_dir = app_dir
        self._cfg = settings
        self._core = core
        self._work_dir = os.path.join(app_dir, ".update")
        if os.path.isdir(self._work_dir):
            # stale temp dir from an interrupted update (e.g. launcher closed)
            self._remove_path(self._work_dir)
        self._state: dict = {
            "phase": "idle",           # idle|checking|downloading|installing|building|swapping
            "progress": 0.0,
            "message": "",
            "remote": None,            # {commit, date, message}
            "local": None,
            "canUpdate": False,
            "error": None,
        }
        self._lock = threading.Lock()
        self._cancel = threading.Event()

    # ------------------------------------------------------------- state

    def status(self) -> dict:
        with self._lock:
            local = self._read_local_info()
            return {
                **self._state,
                "local": local,
            }

    def _read_local_info(self) -> dict | None:
        core_dir = self._core.core_dir
        marker = os.path.join(core_dir, ".dsh-desktop-info.json")
        if not os.path.isfile(marker):
            return None
        try:
            with open(marker, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    # ------------------------------------------------------------- actions

    def check(self) -> dict:
        with self._lock:
            if self._state["phase"] not in ("idle", "done"):
                return {"ok": False, "message": f"正在{self._state['message']}，请稍候。"}
            self._state.update(phase="checking", progress=0.0,
                               message="正在检查 GitHub 上的最新版本…", error=None)
        try:
            remote = self._fetch_remote_info()
            with self._lock:
                local = self._read_local_info()
                same = bool(local and local.get("commit") == remote["commit"])
                self._state.update(
                    phase="done", progress=1.0,
                    message="检查完成", remote=remote, canUpdate=not same,
                )
                return {
                    "ok": True,
                    "remote": remote,
                    "local": local,
                    "canUpdate": not same,
                    "message": "已是最新" if same else "发现新版本，可更新",
                }
        except Exception as exc:  # network or parse failure
            log.exception("check update failed")
            with self._lock:
                self._state.update(phase="idle", error=str(exc),
                                   message=f"检查失败: {exc}")
            return {"ok": False, "message": f"检查失败: {exc}"}

    def cancel(self) -> None:
        self._cancel.set()

    def download_and_build(self) -> dict:
        with self._lock:
            if self._state["phase"] not in ("idle", "done"):
                return {"ok": False, "message": f"正在{self._state['message']}，请稍候。"}
            self._state.update(phase="downloading", progress=0.02,
                               message="开始更新核心…", error=None)
        self._cancel.clear()
        worker = threading.Thread(target=self._run_update, daemon=True)
        worker.start()
        return {"ok": True, "message": "更新已开始，进度将实时显示。"}

    # ------------------------------------------------------------- pipeline

    def _run_update(self) -> None:
        try:
            # The UI may trigger an update without a preceding check; make sure
            # the remote commit info used for the swap metadata is present.
            with self._lock:
                remote = self._state.get("remote")
            if not remote:
                try:
                    remote = self._fetch_remote_info()
                    with self._lock:
                        self._state["remote"] = remote
                except Exception as exc:  # network failure: non-fatal for the update
                    log.warning("remote info fetch failed: %s", exc)
            self._set("downloading", "正在下载源码压缩包…")
            zip_path = self._download()
            if self._cancel.is_set():
                return self._finish_cancelled()
            with self._lock:
                self._state["phase"] = "installing"
                self._state["progress"] = 0.25
                self._state["message"] = "正在解压源码…"
            src_dir = self._extract(zip_path)
            if self._cancel.is_set():
                return self._finish_cancelled()
            self._git_init(src_dir)
            with self._lock:
                self._state["phase"] = "installing"
                self._state["progress"] = 0.35
                self._state["message"] = "正在安装依赖 (pnpm install)…"
            self._run_install(src_dir)
            if self._cancel.is_set():
                return self._finish_cancelled()
            with self._lock:
                self._state["phase"] = "building"
                self._state["progress"] = 0.55
                self._state["message"] = "正在构建核心 (pnpm build)…"
            self._run_build(src_dir)
            if self._cancel.is_set():
                return self._finish_cancelled()
            with self._lock:
                self._state["phase"] = "swapping"
                self._state["progress"] = 0.95
                self._state["message"] = "正在切换核心版本…"
            self._swap(src_dir)
            with self._lock:
                self._state.update(phase="done", progress=1.0,
                                   message="核心更新完成，请重新启动服务器。")
        except KeyboardInterrupt:
            self._finish_cancelled()
        except Exception as exc:
            log.exception("update pipeline failed")
            self._fail(str(exc))
        finally:
            if os.path.isdir(self._work_dir):
                # Prefer a thorough removal; a partial leftover is fine (the
                # next launch cleans it up).
                self._remove_path(self._work_dir)

    def _finish_cancelled(self) -> None:
        with self._lock:
            self._state.update(phase="idle", progress=0.0,
                               message="更新已取消。")

    def _fail(self, message: str) -> None:
        with self._lock:
            self._state.update(phase="idle", progress=0.0,
                               message=f"更新失败: {message}", error=message)

    def _set(self, phase: str, message: str) -> None:
        with self._lock:
            self._state["phase"] = phase
            self._state["message"] = message

    # ------------------------------------------------------------- steps

    def _fetch_remote_info(self) -> dict:
        req = urllib.request.Request(
            f"{API_URL}/commits/{BRANCH}", headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {
            "commit": data["sha"][:12],
            "date": data["commit"]["committer"]["date"],
            "message": data["commit"]["message"].splitlines()[0],
        }

    def _download(self) -> str:
        os.makedirs(self._work_dir, exist_ok=True)
        zip_path = os.path.join(self._work_dir, "core-src.zip")
        req = urllib.request.Request(ZIP_URL, headers={"User-Agent": USER_AGENT})
        tmp = zip_path + ".part"
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            with open(tmp, "wb") as fh:
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    if total:
                        progress = 0.05 + 0.2 * (got / total)
                        with self._lock:
                            self._state["progress"] = progress
                            self._state["message"] = f"正在下载源码 {got / 1048576:.1f} MB"
                    if self._cancel.is_set():
                        fh.close()
                        os.remove(tmp)
                        raise KeyboardInterrupt
        os.replace(tmp, zip_path)
        return zip_path

    def _extract(self, zip_path: str) -> str:
        out = os.path.join(self._work_dir, "src")
        with zipfile.ZipFile(zip_path) as zf:
            top = zf.namelist()[0].split("/", 1)[0]
            zf.extractall(out)
        return os.path.join(out, top)

    def _run_install(self, src_dir: str) -> None:
        # Registry flakiness (e.g. UND_ERR_DESTROYED on optional packages)
        # can leave node_modules incomplete; retry the install a few times.
        last_error: Exception | None = None
        for attempt in range(3):
            if attempt:
                with self._lock:
                    self._state["message"] = f"依赖安装重试中 ({attempt}/3)…"
                time.sleep(3)
            try:
                self._run_pnpm(
                    src_dir,
                    ["install", "--node-linker=hoisted", "--no-frozen-lockfile"],
                )
                return
            except Exception as exc:
                last_error = exc
        raise last_error  # type: ignore[misc]

    def _run_build(self, src_dir: str) -> None:
        # pnpm 11 runs an implicit `install` before `run` when it thinks
        # node_modules is out of sync (verify-deps-before-run defaults to
        # "install"). That implicit install is network-fragile on flaky
        # connections; we already install explicitly above, so turn the check
        # off via the pnpm_config_* env form of the setting.
        self._run_pnpm(src_dir, ["run", "build"], extra_env={
            "pnpm_config_verify_deps_before_run": "false",
        })

    def _run_pnpm(self, src_dir: str, args: list[str],
                  extra_env: dict | None = None) -> None:
        node_dir = os.path.dirname(self._core.node_exe)
        pnpm = os.path.join(node_dir, "pnpm.cmd")
        if not os.path.isfile(pnpm):
            pnpm = "pnpm"
        cmd = [pnpm, *args]
        env = dict(os.environ)
        env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")
        env["COREPACK_HOME"] = os.path.join(node_dir, ".corepack")
        if extra_env:
            env.update(extra_env)
        log.info("run pnpm in %s: %s", src_dir, " ".join(args))
        proc = subprocess.Popen(
            cmd, cwd=src_dir, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert proc.stdout is not None
        last_lines: list[str] = []
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                last_lines.append(line)
                if len(last_lines) > 8:
                    last_lines.pop(0)
                with self._lock:
                    self._state["message"] = f"{line[:90]}"
        proc.wait()
        if proc.returncode != 0:
            detail = "\n".join(last_lines[-8:])
            raise RuntimeError(
                f"pnpm {' '.join(args)} 退出码 {proc.returncode}\n最近输出:\n{detail}"
            )

    def _swap(self, src_dir: str) -> None:
        core_dir = self._core.core_dir
        # Stop the server and any orphaned core processes that would hold
        # file locks on core/ and break the directory rename below.
        self._core.stop()
        backup = os.path.join(self._app_dir, "core.backup")
        # shutil.rmtree silently leaves partial trees behind when Defender or
        # another scanner holds transient locks; fall back to cmd rmdir, which
        # is more tolerant of stale junctions and locked files.
        for attempt in range(20):
            try:
                if not self._remove_path(backup):
                    raise OSError("backup removal failed")
                if os.path.isdir(core_dir):
                    os.replace(core_dir, backup)
                os.replace(src_dir, core_dir)
                break
            except OSError as exc:
                if attempt == 19:
                    raise RuntimeError(
                        f"无法切换核心目录（文件被占用）: {exc}\n"
                        "请关闭其他程序后重试。"
                    )
                time.sleep(2)
        # pnpm created junctions inside src_dir pointing at src_dir-absolute
        # targets; after the move they are stale, so recreate them under
        # core_dir with the same relative layout (relative to old src_dir).
        recreated, failed = relink.rebase_junctions(core_dir, src_dir)
        log.info("relinked %d junction(s), %d failed", recreated, failed)
        self._git_init(core_dir)
        remote = self._state.get("remote") or {}
        info = {
            "commit": remote.get("commit", ""),
            "date": remote.get("date", ""),
            "message": remote.get("message", ""),
            "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(os.path.join(core_dir, ".dsh-desktop-info.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(info, fh, ensure_ascii=False, indent=2)
        self._cfg.set("last_updated_core", info["updatedAt"])
        self._cfg.save()
        if os.path.isdir(backup) or os.path.islink(backup):
            self._remove_path(backup)

    @staticmethod
    def _remove_path(path: str) -> bool:
        """Remove a path (file or directory tree) with retries and a cmd
        rmdir fallback; returns True when the path is gone."""
        for _ in range(3):
            if not os.path.exists(path) and not os.path.islink(path):
                return True
            shutil.rmtree(path, ignore_errors=True)
            if not os.path.exists(path) and not os.path.islink(path):
                return True
            try:
                subprocess.run(
                    ["cmd", "/c", "rmdir", "/s", "/q", f'"{path}"'],
                    capture_output=True, timeout=120,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
            if not os.path.exists(path) and not os.path.islink(path):
                return True
            time.sleep(2)
        return not os.path.exists(path) and not os.path.islink(path)

    @staticmethod
    def _git_init(core_dir: str) -> None:
        """Make the extracted source a git repo so upstream build scripts
        that require `git rev-parse HEAD` keep working."""
        git = shutil.which("git")
        if not git:
            return
        for args in (
            ["init", "-b", "main"],
            ["add", "-A"],
            ["-c", "user.name=dsh-desktop", "-c", "user.email=dsh@local",
             "commit", "-m", "core snapshot", "--quiet"],
        ):
            try:
                subprocess.run(
                    [git, *args], cwd=core_dir, check=False,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except OSError:
                return
