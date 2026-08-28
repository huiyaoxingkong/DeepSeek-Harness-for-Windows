"""Controls the dsh web-server child process for the desktop launcher."""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import threading
import time

import crypto
import homes

log = logging.getLogger("core_api")

READY_MARKER = "Ready"  # dsh logs readiness when the web server is up


class CoreController:
    """Spawns `node core/apps/cli/lib/bin.js web` and watches it."""

    def __init__(self, app_dir: str, settings) -> None:
        self._app_dir = app_dir
        self._cfg = settings
        self._proc: subprocess.Popen | None = None
        self._logfh = None
        self._lock = threading.Lock()
        self._log_path = os.path.join(app_dir, "logs", "core.log")
        os.makedirs(os.path.dirname(self._log_path), exist_ok=True)

    # ------------------------------------------------------------- paths

    @property
    def core_dir(self) -> str:
        return os.path.join(self._app_dir, self._cfg.get("core_dir", "core"))

    @property
    def node_exe(self) -> str:
        bundled = os.path.join(self._app_dir,
                               self._cfg.get("runtime_dir", "runtime"), "node.exe")
        if os.path.isfile(bundled):
            return bundled
        # Minimal package: fall back to a system Node.js installation.
        return shutil.which("node") or bundled

    @property
    def runtime_dir(self) -> str:
        return os.path.dirname(self.node_exe)

    @property
    def bin_js(self) -> str:
        return os.path.join(self.core_dir, "apps", "cli", "lib", "bin.js")

    def core_ready(self) -> bool:
        return os.path.isfile(self.node_exe) and os.path.isfile(self.bin_js)

    # ------------------------------------------------------------- status

    def status(self) -> dict:
        with self._lock:
            running = self._proc is not None and self._proc.poll() is None
            port = self._cfg.get("port", 3080)
            return {
                "running": running,
                "port": port,
                "url": f"http://127.0.0.1:{port}",
                "coreReady": self.core_ready(),
                "coreVersion": self._core_version(),
                "dshHome": os.environ.get("DSH_HOME", ""),
            }

    def _core_version(self) -> str:
        try:
            manifest = os.path.join(self.core_dir, "package.json")
            with open(manifest, "r", encoding="utf-8") as fh:
                import json
                return json.load(fh).get("version", "")
        except (OSError, ValueError):
            return ""

    # ------------------------------------------------------------- control

    def start(self) -> tuple[bool, str]:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return True, "server is already running"
            if not os.path.isfile(self.bin_js):
                return False, (
                    "核心尚未构建。请先在“更新”页面构建/更新核心，"
                    "或在构建目录运行 build.ps1。"
                )
            if not os.path.isfile(self.node_exe):
                return False, (
                    "未找到 Node.js。当前为极简包：请自行安装 Node.js LTS "
                    "（nodejs.org）并加入 PATH，或改用懒人包（内置 Node）。"
                )
            port = self._pick_port()
            env = dict(os.environ)
            # Per-instance harness home: plugins, sessions, settings, skins
            # all live under <app>\data\.dsh. The core child and everything
            # it spawns (plugin CLIs, pnpm) inherit this.
            data = homes.data_dir(self._app_dir, self._cfg)
            env["DSH_HOME"] = homes.dsh_home(data)
            bundled = os.path.isfile(os.path.join(
                self._app_dir, self._cfg.get("runtime_dir", "runtime"), "node.exe"))
            # Minimal package: keep corepack writes inside the instance
            # instead of the (likely read-only) system node dir.
            env.update(homes.pnpm_env(data, self.runtime_dir if bundled else data))
            # Make node/pnpm/dsh shim resolvable for plugins that spawn the
            # CLI themselves (dsh-doctor, dsh-plugin-manager, remote-web-ui),
            # and expose bundled Git (git.exe + Git Bash) on PATH.
            paths = []
            if os.path.isdir(self.runtime_dir):
                paths.append(self.runtime_dir)
            paths.extend(homes.git_path_entries(self.runtime_dir))
            if paths:
                env["PATH"] = os.pathsep.join(paths) + os.pathsep + env.get("PATH", "")
            try:
                api_key = crypto.unprotect(self._cfg.get("api_key") or "")
            except (OSError, ValueError):
                api_key = ""
            if api_key:
                env["DEEPSEEK_API_KEY"] = api_key
            env.update(homes.proxy_env(self._cfg))
            env.update(homes.registry_env(self._cfg))
            # Relaxed fetch budget for plugin-triggered pnpm runs.
            env["npm_config_fetch_timeout"] = "600000"
            env["npm_config_fetch_retries"] = "5"
            env["pnpm_config_fetch_timeout"] = "600000"
            env["pnpm_config_fetch_retries"] = "5"
            base_url = self._cfg.get("base_url") or ""
            if base_url:
                env["DEEPSEEK_BASE_URL"] = base_url
            cmd = [
                self.node_exe,
                self.bin_js,
                "web",
                "--no-open",
                "--port", str(port),
                "--host", "127.0.0.1",
            ]
            log.info("starting core: %s (cwd=%s)", " ".join(cmd), self.core_dir)
            try:
                with open(self._log_path, "a", encoding="utf-8") as fh:
                    fh.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                self._logfh = open(self._log_path, "a", encoding="utf-8", buffering=1)
                self._proc = subprocess.Popen(
                    cmd,
                    cwd=self.core_dir,
                    env=env,
                    stdout=self._logfh,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except OSError as exc:
                log.exception("failed to start core")
                self._proc = None
                self._logfh = None
                return False, f"无法启动核心: {exc}"
        deadline = time.time() + 90
        while time.time() < deadline:
            if self._proc.poll() is not None:
                return False, f"核心进程已退出(code={self._proc.returncode})，详见 日志页面。"
            if self._wait_port(port):
                return True, f"服务已启动: http://127.0.0.1:{port}"
            time.sleep(0.5)
        return False, "等待核心启动超时(90s)，请查看日志页面。"

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            proc = self._proc
            self._proc = None
            self._logfh = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        self._kill_orphans()
        return True, "服务已停止"

    def _kill_orphans(self) -> None:
        """Kill node processes still serving THIS instance's dsh core CLI
        (e.g. left behind when the launcher was force-closed). Matches on the
        canonical `apps/cli/lib/bin.js` argument AND this instance's core
        directory, so another installation's server is never touched."""
        import csv
        import io
        marker = os.path.normcase(self.core_dir).lower()
        try:
            # wmic is gone on modern Windows 11; use CIM via PowerShell.
            script = ("Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
                      "Select-Object ProcessId, CommandLine | ConvertTo-Csv -NoTypeInformation")
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        try:
            text = out.stdout.strip()
            rows = csv.DictReader(io.StringIO(text))
            for row in rows:
                pid = (row.get("ProcessId") or "").strip()
                cmdline = (row.get("CommandLine") or "").lower()
                if (pid.isdigit() and "apps/cli/lib/bin.js" in cmdline
                        and marker in cmdline):
                    log.warning("killing orphaned core process pid=%s", pid)
                    try:
                        subprocess.run(
                            ["taskkill", "/PID", pid, "/T", "/F"],
                            capture_output=True, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        pass
        except (csv.Error, ValueError):
            return

    def restart(self) -> tuple[bool, str]:
        self.stop()
        time.sleep(0.8)
        return self.start()

    # ------------------------------------------------------------- helpers

    def _pick_port(self) -> int:
        """The configured port when free, otherwise an ephemeral one.

        A second instance on the same machine must not collide with the
        first: fall back to an OS-assigned port and persist it so restarts
        reuse the same value.
        """
        port = int(self._cfg.get("port", 3080) or 3080)
        if not self._port_in_use(port):
            return port
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                chosen = sock.getsockname()[1]
        except OSError:
            chosen = port + 1
        log.warning("port %d is busy; using %d for this instance", port, chosen)
        self._cfg.set("port", chosen)
        self._cfg.save()
        return chosen

    @staticmethod
    def _port_in_use(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return False
            except OSError:
                return True

    @staticmethod
    def _wait_port(port: int, timeout: float = 3.0) -> bool:
        import socket
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.25)
        return False

    def read_log(self, tail: int = 200) -> str:
        try:
            tail = max(1, int(tail))
        except (TypeError, ValueError):
            tail = 200
        try:
            with open(self._log_path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            return "".join(lines[-tail:])
        except OSError:
            return "(日志文件不存在)"

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None
