"""Controls the dsh web-server child process for the desktop launcher."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time

import crypto
import homes

log = logging.getLogger("core_api")

READY_MARKER = "Ready"  # dsh logs readiness when the web server is up

# Where the CLI entry has lived across dsh releases. ``apps/cli/package.json``
# declares it in ``bin.dsh``; the hard-coded path is the last-resort fallback
# for a core whose manifest is unreadable. Resolving instead of hard-coding is
# what keeps the launcher working after an upgrade *or* a downgrade that moves
# the entry (verified against dsh 0.1.1-rc.2 and 0.1.6-alpha.2).
CLI_ENTRY_FALLBACK = os.path.join("apps", "cli", "lib", "bin.js")
CLI_MANIFEST = os.path.join("apps", "cli", "package.json")


def resolve_cli_entry(core_dir: str) -> str:
    """Absolute path of the dsh CLI entry inside *core_dir*.

    Prefers the ``bin`` declaration of ``apps/cli/package.json`` (any release
    layout), then the historical ``apps/cli/lib/bin.js``.
    """
    fallback = os.path.join(core_dir, CLI_ENTRY_FALLBACK)
    manifest = os.path.join(core_dir, CLI_MANIFEST)
    try:
        with open(manifest, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return fallback
    bin_field = data.get("bin")
    rel = ""
    if isinstance(bin_field, str):
        rel = bin_field
    elif isinstance(bin_field, dict) and bin_field:
        rel = str(bin_field.get("dsh") or next(iter(bin_field.values())))
    if not rel:
        return fallback
    rel = rel.replace("/", os.sep).replace("\\", os.sep)
    candidate = os.path.normpath(os.path.join(core_dir, "apps", "cli", rel))
    return candidate if os.path.isfile(candidate) else fallback


def _manifest_stamp(core_dir: str) -> float:
    try:
        return os.path.getmtime(os.path.join(core_dir, CLI_MANIFEST))
    except OSError:
        return 0.0


class CoreController:
    """Spawns the dsh CLI's web server and watches it."""

    # Launch-argument candidates, most capable first. ``dsh web --no-open
    # --port N --host 127.0.0.1`` has worked from dsh 0.1.0 through
    # 0.1.6-alpha.2, but a core that renamed or dropped a flag (or the ``web``
    # shortcut) must not brick the launcher: on a fast usage failure the next
    # candidate is tried and the working one is remembered in config.json
    # (``core_launch_mode``) so ordinary starts skip the probe.
    LAUNCH_CANDIDATES: tuple[tuple[str, ...], ...] = (
        ("web", "--no-open", "--port", "{port}", "--host", "127.0.0.1"),
        ("--profile", "web", "--no-open", "--port", "{port}", "--host", "127.0.0.1"),
        ("web", "--no-open", "--port", "{port}"),
        ("--profile", "web", "--no-open", "--port", "{port}"),
        ("web", "--port", "{port}", "--no-open"),
        ("--profile", "web", "--port", "{port}"),
        ("web",),
    )

    # Text a CLI prints when it does not understand the invocation. Only these
    # failures are worth retrying with a different flag set.
    _USAGE_ERROR_RE = re.compile(
        r"unknown option|unknown command|unknown argument|unrecognized|"
        r"invalid option|not a valid|too many arguments|missing required|"
        r"is not a (?:known|recognized|valid)|usage:",
        re.IGNORECASE,
    )

    # The web URL the core prints at startup. dsh >= 0.1.6 prints
    # ``dsh web: http://127.0.0.1:<port>/?token=<secret>`` and answers every
    # unauthenticated request with 401 ("dsh web authentication required;
    # reopen the URL printed by dsh web") — loading the bare URL would leave
    # the workspace showing an error page. Older cores print the bare URL.
    CORE_URL_RE = re.compile(r"https?://(?:127\.0\.0\.1|localhost):\d+\S*")

    # How long to wait for that line after the port opens. Old cores print it
    # immediately, so ordinary starts do not pay this.
    URL_DISCOVERY_TIMEOUT = 12.0

    # How long a candidate may run without opening the port before it is judged
    # (early death right after launch = the invocation was rejected).
    FAST_FAILURE_WINDOW = 8.0

    def __init__(self, app_dir: str, settings) -> None:
        self._app_dir = app_dir
        self._cfg = settings
        self._proc: subprocess.Popen | None = None
        self._logfh = None
        self._lock = threading.Lock()
        self._log_path = os.path.join(app_dir, "logs", "core.log")
        os.makedirs(os.path.dirname(self._log_path), exist_ok=True)
        self._entry_cache: tuple[float, str] = (0.0, "")
        # Web URL as printed by the running core (carries the auth token on
        # dsh >= 0.1.6); empty means "use the plain http://127.0.0.1:<port>".
        self._web_url = ""

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
        """The dsh CLI entry, resolved for whatever layout this core uses.

        Cached against the CLI manifest's mtime so a core swap (upgrade or
        downgrade) re-resolves without a stat storm on every status poll.
        """
        core_dir = self.core_dir
        stamp = _manifest_stamp(core_dir)
        cached_stamp, cached_path = self._entry_cache
        if cached_stamp == stamp and cached_path and os.path.isfile(cached_path):
            return cached_path
        entry = resolve_cli_entry(core_dir)
        self._entry_cache = (stamp, entry)
        return entry

    @property
    def entry_rel(self) -> str:
        """CLI entry relative to core_dir, slash-separated (process matching)."""
        try:
            rel = os.path.relpath(self.bin_js, self.core_dir)
        except ValueError:
            rel = CLI_ENTRY_FALLBACK
        return rel.replace("\\", "/")

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
                "url": self.web_url(port) if running else f"http://127.0.0.1:{port}",
                "coreReady": self.core_ready(),
                "coreVersion": self._core_version(),
                "dshHome": os.environ.get("DSH_HOME", ""),
            }

    def web_url(self, port: int | None = None) -> str:
        """The URL to open for the web UI.

        Prefers the URL the core printed (``?token=…`` on dsh >= 0.1.6, which
        is mandatory there) and falls back to the bare localhost URL for cores
        that print nothing.
        """
        if self._web_url:
            return self._web_url
        port = port if port is not None else self._cfg.get("port", 3080)
        return f"http://127.0.0.1:{port}"

    def _core_version(self) -> str:
        """Installed core version: root manifest first, then the CLI package."""
        for candidate in ("package.json", os.path.join("apps", "cli", "package.json")):
            path = os.path.join(self.core_dir, candidate)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    version = json.load(fh).get("version", "")
                if version:
                    return str(version)
            except (OSError, ValueError):
                continue
        return ""

    # ------------------------------------------------------------- control

    def _launch_candidates(self) -> list[tuple[int, list[str]]]:
        """Ordered (index, argv-tail) candidates, the remembered one first."""
        remembered = str(self._cfg.get("core_launch_mode", "") or "")
        order = list(range(len(self.LAUNCH_CANDIDATES)))
        if remembered.isdigit() and int(remembered) < len(order):
            preferred = int(remembered)
            order.remove(preferred)
            order.insert(0, preferred)
        return [(index, list(self.LAUNCH_CANDIDATES[index])) for index in order]

    def _child_env(self, port: int) -> dict:
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
        return env

    def _spawn(self, argv: list[str], env: dict) -> subprocess.Popen:
        log.info("starting core: %s (cwd=%s)", " ".join(argv), self.core_dir)
        with open(self._log_path, "a", encoding="utf-8") as fh:
            fh.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        self._close_log()
        self._logfh = open(self._log_path, "a", encoding="utf-8", buffering=1)
        return subprocess.Popen(
            argv,
            cwd=self.core_dir,
            env=env,
            stdout=self._logfh,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def _close_log(self) -> None:
        """Release the child's stdout handle (one open per launch attempt)."""
        fh, self._logfh = self._logfh, None
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass

    def _log_size(self) -> int:
        try:
            return os.path.getsize(self._log_path)
        except OSError:
            return 0

    def _log_since(self, offset: int, max_chars: int = 1200) -> str:
        """Log text written since *offset* (this attempt only)."""
        try:
            with open(self._log_path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(max(0, offset))
                text = fh.read()
        except OSError:
            return ""
        return text.strip()[-max_chars:]

    def _log_tail(self, lines: int = 14) -> str:
        return self.read_log(lines).strip()

    def _terminate(self, proc: subprocess.Popen | None) -> None:
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        except OSError:
            pass

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
            env = self._child_env(port)
        deadline = time.time() + 90
        attempts: list[str] = []
        last_output = ""
        for index, tail_args in self._launch_candidates():
            if time.time() >= deadline:
                break
            argv = [self.node_exe, self.bin_js, *[a.replace("{port}", str(port))
                                                 for a in tail_args]]
            log_offset = self._log_size()
            with self._lock:
                try:
                    proc = self._spawn(argv, env)
                except OSError as exc:
                    log.exception("failed to start core")
                    self._proc = None
                    self._close_log()
                    return False, f"无法启动核心: {exc}"
                self._proc = proc
            ok, reason, fast = self._await_ready(proc, port, deadline)
            if ok:
                # The printed URL (and its auth token on dsh >= 0.1.6) is the
                # only thing the WebView may load; without it every request is
                # answered with 401.
                self._web_url = self._discover_web_url(log_offset)
                if str(self._cfg.get("core_launch_mode", "")) != str(index):
                    self._cfg.set("core_launch_mode", str(index))
                    self._cfg.save()
                return True, f"服务已启动: {self.web_url(port)}"
            # Only this attempt's output decides whether another flag set is
            # worth trying: an older run's words must not leak into the verdict
            # (or into the error the user reads).
            last_output = self._log_since(log_offset)
            attempts.append(f"[{' '.join(tail_args)}] {reason}")
            with self._lock:
                self._terminate(proc)
                self._close_log()
                self._proc = None
            retryable = bool(self._USAGE_ERROR_RE.search(last_output)) or (
                fast and len(last_output) < 600)
            if not retryable:
                break
            log.info("core launch candidate rejected, trying next: %s",
                     " ".join(tail_args))
        detail = last_output[-400:] or (attempts[-1] if attempts else "")
        return False, (
            "核心启动失败。\n尝试的启动参数：\n" + "\n".join(attempts)
            + (f"\n最近日志：\n{detail}" if detail else "")
            + "\n详见 日志页面。"
        )

    def _await_ready(self, proc: subprocess.Popen, port: int,
                     deadline: float) -> tuple[bool, str, bool]:
        """Wait for the core to open *port*.

        Returns ``(ok, reason, fast_death)``; ``fast_death`` marks a process
        that died inside the short probe window, i.e. most likely rejected the
        command line rather than failed to boot.
        """
        probe_until = time.time() + self.FAST_FAILURE_WINDOW
        fast = False
        while time.time() < probe_until:
            if proc.poll() is not None:
                fast = True
                return False, f"进程在启动窗口内退出(code={proc.returncode})", fast
            if self._wait_port(port, 0.5):
                return True, "", False
            time.sleep(0.2)
        while time.time() < deadline:
            if proc.poll() is not None:
                return False, f"核心进程已退出(code={proc.returncode})", False
            if self._wait_port(port, 0.5):
                return True, "", False
            time.sleep(0.5)
        if proc.poll() is not None:
            return False, f"核心进程已退出(code={proc.returncode})", False
        return False, "等待核心启动超时(90s)", False

    def _discover_web_url(self, log_offset: int) -> str:
        """Read the web URL the core printed since *log_offset*.

        dsh >= 0.1.6 prints ``dsh web: http://127.0.0.1:<port>/?token=…`` once
        the server is listening, and rejects requests without that token. The
        line is normally already in the log when the port opens; this polls
        briefly to cover the race, then falls back to the bare URL so cores
        that print nothing (or an unrecognized format) keep working.
        """
        deadline = time.time() + self.URL_DISCOVERY_TIMEOUT
        while True:
            text = self._log_since(log_offset, max_chars=8000)
            matches = self.CORE_URL_RE.findall(text)
            if matches:
                url = matches[-1].rstrip(".,;)\"'")
                if url != self._web_url:
                    log.info("core web url: %s", url)
                self._web_url = url
                return url
            if time.time() >= deadline:
                log.info("core printed no web url; using the plain localhost url")
                return self._web_url
            time.sleep(0.25)

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        with self._lock:
            self._close_log()
            # The token belongs to the process that just exited.
            self._web_url = ""
        self._kill_orphans()
        return True, "服务已停止"

    def _kill_orphans(self) -> None:
        """Kill node processes still serving THIS instance's dsh core CLI
        (e.g. left behind when the launcher was force-closed). Matches on the
        resolved CLI entry path AND this instance's core directory, so another
        installation's server is never touched."""
        import csv
        import io
        marker = os.path.normcase(self.core_dir).lower()
        entries = {self.entry_rel.lower(), CLI_ENTRY_FALLBACK.replace("\\", "/").lower()}
        try:
            # wmic is gone on modern Windows 11; use CIM via PowerShell. The
            # script forces UTF-8 output so a Chinese-locale console code page
            # cannot corrupt (or crash on) the CSV we parse here.
            script = homes.PS_UTF8_PREFIX + (
                "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
                "Select-Object ProcessId, CommandLine | ConvertTo-Csv -NoTypeInformation")
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW,
                **homes.console_text_kwargs(utf8=True),
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        try:
            text = out.stdout.strip()
            rows = csv.DictReader(io.StringIO(text))
            for row in rows:
                pid = (row.get("ProcessId") or "").strip()
                cmdline = (row.get("CommandLine") or "").lower().replace("\\", "/")
                if (pid.isdigit() and any(e in cmdline for e in entries)
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
