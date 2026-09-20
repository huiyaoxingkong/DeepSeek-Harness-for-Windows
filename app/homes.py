"""Portable per-instance harness home for the desktop launcher.

1.0.2 moves every piece of user state (plugins, sessions, settings, skins,
pets, task board, …) out of the user profile into the installation folder:
``<app>\\data\\.dsh``. The dsh core resolves its home through ``$DSH_HOME``
(``resolveDshHome``: env override, else ``~/.dsh``), so the launcher sets the
env var once at startup — the core child, the plugin CLI and every plugin that
reads DSH_HOME (the whole @linxin666/dsh-web family ships a synced copy of the
same resolver) then agree on the same root. Two installations on one machine
get two independent homes: instance isolation.

The one-time migration copies the legacy ``~/.dsh`` into the data directory
(with robocopy so locked files are retried, never half-destroyed), rewrites
``file:`` plugin specs whose targets no longer exist against the bundled
``store`` folder, and heals the profile's ``pnpm-workspace.yaml`` with the
settings the dsh-web family needs (hoisted linker + allowBuilds entries +
minimum-release-age exclusion).
"""

from __future__ import annotations

import hashlib
import json
import locale
import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time

log = logging.getLogger("homes")

LEGACY_DIR_NAME = ".dsh"
HOME_DIR_NAME = ".dsh"
MARKER_NAME = ".home-migrated"

# pnpm settings the @linxin666/dsh-web plugin family requires inside the
# profile (aggregate package + native deps + pnpm 11 release-age gate).
WORKSPACE_TEMPLATE = """\
packages:
  - .

nodeLinker: hoisted
autoInstallPeers: false
allowBuilds:
  cloudflared: true
  cpu-features: true
  esbuild: true
  node-pty: true
  ssh2: true
minimumReleaseAgeExclude:
  - '@linxin666/*'
"""

ALLOW_BUILD_KEYS = ("cloudflared", "cpu-features", "esbuild", "node-pty", "ssh2")


def data_dir(app_dir: str, cfg) -> str:
    """The instance data directory: ``<app>\\<data_dir setting>``."""
    name = str(cfg.get("data_dir", "data") or "data")
    if os.path.isabs(name):
        return name
    return os.path.join(app_dir, name)


def dsh_home(data_dir: str) -> str:
    """The harness home handed to dsh: ``<data>\\ .dsh``."""
    return os.path.join(data_dir, HOME_DIR_NAME)


def legacy_home() -> str:
    """The pre-1.0.2 harness home in the user profile."""
    return os.path.join(os.path.expanduser("~"), LEGACY_DIR_NAME)


def apply_home_env(app_dir: str, cfg) -> tuple[str, str]:
    """Create the data directory and export DSH_HOME into the process env.

    Must run before any core/plugin operation; every child process inherits
    the variable, which is exactly what keeps core and plugins in agreement.
    DSH_DOCTOR_HOME is set alongside it so the dsh-doctor plugin keeps its
    state inside the instance instead of ``~/.dsh-doctor`` (portable data,
    no C-drive footprint, no antivirus/sync lock contention on the rename).
    """
    data = data_dir(app_dir, cfg)
    home = dsh_home(data)
    os.makedirs(home, exist_ok=True)
    os.environ["DSH_HOME"] = home
    os.environ["DSH_DOCTOR_HOME"] = os.path.join(home, ".dsh-doctor")
    # The bundled Python has no CA source of its own and cannot always load
    # the Windows certificate store; without a CA bundle every HTTPS call
    # (GitHub API checks, downloads) fails with CERTIFICATE_VERIFY_FAILED.
    # Pin SSL_CERT_FILE to a bundle shipped with the app; a user-provided
    # value wins (they may have their own trust store).
    if not os.environ.get("SSL_CERT_FILE"):
        for candidate in (
            os.path.join(app_dir, "cacert.pem"),
            os.path.join(app_dir, "_internal", "certifi", "cacert.pem"),
            os.path.join(app_dir, "runtime", "git", "mingw64", "etc",
                         "ssl", "certs", "ca-bundle.crt"),
            os.path.join(app_dir, "runtime", "git", "usr", "ssl",
                         "certs", "ca-bundle.crt"),
        ):
            if os.path.isfile(candidate):
                os.environ["SSL_CERT_FILE"] = candidate
                log.info("SSL_CERT_FILE -> %s", candidate)
                break
    return data, home


# ------------------------------------------------------------- migration


def _robocopy(src: str, dst: str) -> int:
    cmd = [
        "robocopy", src, dst,
        "/E", "/XJ", "/COPY:DAT", "/DCOPY:DAT",
        # node_modules dirs are hard-linked against the LEGACY pnpm store;
        # copying them makes every later pnpm op fail with
        # ERR_PNPM_UNEXPECTED_STORE. Metadata is kept (package.json etc.),
        # and the profile is reinstalled against the instance store instead.
        "/XD", "node_modules",
        "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=3600,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("robocopy failed: %s", exc)
        return 99


def migrate_legacy_home(app_dir: str, cfg) -> dict:
    """One-time move of ``~/.dsh`` into the instance data directory.

    robocopy copies across volumes with per-file retries; the source is only
    removed when every file copied (exit code < 8). A failure leaves the
    legacy home untouched and the marker unwritten, so the next launch
    retries. Junctions are excluded (``/XJ``): the flat
    ``profiles/node_modules`` fallback is healed by the core at boot.
    """
    data = data_dir(app_dir, cfg)
    home = dsh_home(data)
    marker = os.path.join(data, MARKER_NAME)
    src = legacy_home()
    result = {"from": src, "to": home, "moved": False, "message": ""}
    if os.path.isfile(marker):
        return result
    if not os.path.isdir(src):
        _write_marker(marker, src, home)
        return result
    if os.path.isdir(home) and os.listdir(home):
        # A home exists but no marker: a previous partial copy. Continue the
        # copy (robocopy is incremental) instead of starting over.
        log.info("legacy home migration: continuing into existing %s", home)
    os.makedirs(home, exist_ok=True)
    log.info("legacy home migration: %s -> %s", src, home)
    code = _robocopy(src, home)
    if code >= 8:
        result["message"] = f"迁移未完成（robocopy 退出码 {code}），旧数据保留在 C 盘，下次启动重试。"
        log.warning("legacy home migration incomplete (robocopy %d)", code)
        return result
    # Full success: remove the legacy tree, then record the migration.
    removed = _remove_tree(src)
    if not removed:
        result["message"] = "数据已复制到安装目录，但旧目录删除失败（可能被占用），将在下次启动清理。"
        log.warning("legacy home copied but %s could not be removed", src)
        return result
    _write_marker(marker, src, home)
    result["moved"] = True
    log.info("legacy home migrated and removed: %s", src)
    # The dsh-doctor plugin used a sibling `~/.dsh-doctor` state dir in its
    # older releases; newer releases keep it under $DSH_HOME/.dsh-doctor.
    _migrate_doctor_state(home)
    return result


def _modules_yaml_store_dir(profile: str) -> str:
    """The ``storeDir`` recorded in the profile's .modules.yaml ('' when
    absent or unreadable). This is the store the current node_modules is
    hard-linked against — the one piece of state needed to detect the
    ERR_PNPM_UNEXPECTED_STORE mismatch before pnpm hits it."""
    path = os.path.join(profile, "node_modules", ".modules.yaml")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ""
    match = re.search(r'"storeDir"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if not match:
        return ""
    return match.group(1).replace("\\\\", "\\")


def _merge_store_files(src_store: str, dst_store: str) -> tuple[int, int]:
    """Copy missing content-addressed files from one pnpm store into another.

    Only the ``files`` tree is merged: content is addressed by its own hash,
    so files from the same pnpm major's layout are interchangeable across
    store locations. The per-store ``index.db`` is deliberately left alone
    (it keys package metadata to a concrete store path); the instance pnpm
    rebuilds its view lazily, reusing the merged content instead of
    re-downloading it. Returns (copied, skipped).
    """
    src_files = os.path.join(src_store, "files")
    dst_files = os.path.join(dst_store, "files")
    if not os.path.isdir(src_files):
        return 0, 0
    copied = skipped = 0
    for dirpath, _dirnames, filenames in os.walk(src_files):
        rel = os.path.relpath(dirpath, src_files)
        for name in filenames:
            src = os.path.join(dirpath, name)
            dst = os.path.join(dst_files, rel, name)
            if os.path.isfile(dst):
                skipped += 1
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
            except OSError:
                log.warning("store merge copy failed: %s", src)
    return copied, skipped


def kill_process_tree(pid: int) -> bool:
    """Kill a process and every child it spawned (best effort).

    Needed because the wrappers used on Windows (``pnpm.cmd`` -> cmd.exe ->
    node.exe) do not die as a tree: killing only the direct child leaves node
    alive, holding the write end of any pipe it inherited.
    """
    if not pid:
        return False
    try:
        proc = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("taskkill %s failed: %s", pid, exc)
        return False
    return proc.returncode == 0


def run_capture(argv: list[str], *, cwd: str = "", env: dict | None = None,
                timeout: float = 60.0, log_path: str = "",
                encoding: str = "utf-8") -> tuple[int, str]:
    """Run *argv* and capture its output **without a pipe**.

    ``subprocess.run(capture_output=True, timeout=…)`` deadlocks on Windows
    when the timeout fires: the killed wrapper leaves its node grandchild alive
    with the pipe's write end open, so ``communicate()`` never sees EOF and the
    calling thread (here: the startup heal thread that owns ``_heal_done``, or
    the update worker) hangs forever. Output goes to a file instead, the whole
    tree is killed on timeout, and the caller always gets an answer.
    """
    fd, tmp = tempfile.mkstemp(prefix="dsh-capture-", suffix=".log")
    os.close(fd)
    target = log_path or tmp
    code = -1
    try:
        with open(target, "wb") as out:
            proc = subprocess.Popen(
                argv, cwd=cwd or None, env=env, stdout=out,
                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                log.warning("command timed out after %.0fs, killing tree: %s",
                            timeout, " ".join(argv))
                kill_process_tree(proc.pid)
                code = -1
            except BaseException:  # noqa: BLE001 - never leak the child
                kill_process_tree(proc.pid)
                raise
        try:
            with open(target, "r", encoding=encoding, errors="replace") as fh:
                return code, fh.read()
        except OSError:
            return code, ""
    except OSError as exc:
        log.warning("could not run %s: %s", " ".join(argv), exc)
        return -1, ""
    finally:
        if not log_path:
            try:
                os.remove(tmp)
            except OSError:
                pass


def run_stream(argv: list[str], *, cwd: str = "", env: dict | None = None,
               on_line=None, stop: "threading.Event | None" = None,
               timeout: float | None = None) -> int:
    """Run *argv*, streaming output, observably cancellable, hang-proof.

    The reader runs on a daemon thread, so the caller never blocks on a pipe
    whose writer outlived its parent. ``stop`` is polled every 0.5s: when it is
    set (the updater's 「取消更新」) the process tree is killed and -1 returned
    instead of waiting out a pnpm install that no longer matters.
    """
    proc = subprocess.Popen(
        argv, cwd=cwd or None, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert proc.stdout is not None

    def reader() -> None:
        try:
            for line in proc.stdout:
                if on_line is not None:
                    on_line(line.rstrip())
        except (OSError, ValueError):
            pass

    def reap() -> None:
        """Wait briefly for a killed child; never block the caller on it."""
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            log.warning("killed command did not exit: %s", " ".join(argv))
        except OSError:
            pass

    pump = threading.Thread(target=reader, daemon=True)
    pump.start()
    deadline = time.time() + timeout if timeout else None
    try:
        while True:
            if stop is not None and stop.is_set():
                log.info("command cancelled, killing tree: %s", " ".join(argv))
                kill_process_tree(proc.pid)
                reap()
                return -1
            try:
                return proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                if deadline is not None and time.time() >= deadline:
                    log.warning("command timed out after %.0fs, killing tree: %s",
                                timeout, " ".join(argv))
                    kill_process_tree(proc.pid)
                    reap()
                    return -1
    finally:
        pump.join(timeout=2)


def heal_profile_store(home: str, data: str, node_exe: str) -> dict:
    """Guarantee the web profile's node_modules is linked from the instance
    pnpm store (``PNPM_HOME=<data>`` derives the store at ``<data>\\store``).

    Two situations produce a profile linked against a foreign store: the
    legacy-home migration excluded node_modules (the reinstall never ran, or
    ran before this pin existed), and pre-1.0.3 installs ran pnpm without the
    instance store. Every pnpm op then fails with ERR_PNPM_UNEXPECTED_STORE.
    The heal is: merge the foreign store's content into the instance store
    (same layout version, so content-addressed files are interchangeable),
    drop the foreign-linked node_modules, and reinstall. It is cheap when the
    state is already consistent (one small file read) and never raises —
    designed to run in a background thread on every launch.
    """
    result: dict = {"ok": True, "skipped": "", "rebuilt": False,
                    "mergedCopied": 0, "mergedSkipped": 0}
    profile = os.path.join(home, "profiles", "web")
    manifest = os.path.join(profile, "package.json")
    if not os.path.isfile(manifest):
        result["skipped"] = "no-profile"
        return result
    try:
        with open(manifest, "r", encoding="utf-8") as fh:
            deps = json.load(fh).get("dependencies") or {}
    except (OSError, ValueError) as exc:
        result.update(ok=False, error=f"manifest unreadable: {exc}")
        return result
    if not deps:
        result["skipped"] = "no-deps"
        return result
    modules_dir = os.path.join(profile, "node_modules")
    store_prefix = os.path.normcase(os.path.join(data, "store"))
    foreign = _modules_yaml_store_dir(profile) if os.path.isdir(modules_dir) else ""
    if foreign and (os.path.normcase(foreign) == store_prefix
                    or os.path.normcase(foreign).startswith(store_prefix + os.sep)):
        result["skipped"] = "store-ok"
        return result
    if os.path.isdir(modules_dir):
        log.info("profile store heal: node_modules linked from %s, instance "
                 "store is %s — rebuilding", foreign or "(unknown)", store_prefix)
        if foreign and os.path.isdir(foreign):
            dst_store = os.path.join(data, "store", os.path.basename(foreign))
            copied, skipped = _merge_store_files(foreign, dst_store)
            result.update(mergedCopied=copied, mergedSkipped=skipped)
            log.info("profile store heal: merged %d files (%d present) from %s",
                     copied, skipped, foreign)
        # Snapshot manifest + lockfile before the rebuild: a rebuild prunes
        # packages whose manifest entries were dropped by an earlier failed
        # operation, and the snapshot makes that loss recoverable.
        snapshot_dir = os.path.join(data, "store-heal-snapshot")
        try:
            os.makedirs(snapshot_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            for name in ("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"):
                src = os.path.join(profile, name)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(snapshot_dir, f"{name}.{stamp}"))
        except OSError as exc:
            log.warning("profile store heal: snapshot failed: %s", exc)
        if not _remove_tree(modules_dir):
            result.update(ok=False, error="node_modules removal failed (files locked)")
            return result
    # Install against the instance store. Runs once per inconsistent state;
    # the merged store content keeps it (mostly) offline. Build scripts are
    # ignored to mirror the profile's historical install state (node-pty /
    # cpu-features compile and cloudflared download otherwise stall headless
    # installs for tens of minutes); prebuilt binaries ship in the tarballs.
    pnpm = os.path.join(os.path.dirname(node_exe), "pnpm.cmd")
    if not os.path.isfile(pnpm):
        pnpm = "pnpm"
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(node_exe) + os.pathsep + env.get("PATH", "")
    env["DSH_HOME"] = home
    env.update(pnpm_env(data, os.path.dirname(node_exe)))
    env["npm_config_fetch_timeout"] = "600000"
    env["npm_config_fetch_retries"] = "5"
    env["pnpm_config_fetch_timeout"] = "600000"
    env["pnpm_config_fetch_retries"] = "5"
    log.info("profile store heal: pnpm install in %s", profile)
    code, output = run_capture(
        [pnpm, "install", "--no-frozen-lockfile", "--ignore-scripts"],
        cwd=profile, env=env, timeout=1800,
        log_path=os.path.join(data, "store-heal-pnpm.log"),
    )
    log.info("profile store heal exit: %d", code)
    if code != 0:
        result.update(ok=False, error=f"pnpm exit {code}",
                      detail=(output or "").strip()[-800:])
        return result
    result["rebuilt"] = True
    # Leftovers from an earlier rename-based rebuild: locked native files may
    # have survived; retry once now that the fresh tree is in place.
    leftover = os.path.join(profile, "node_modules.old")
    if os.path.isdir(leftover):
        _remove_tree(leftover)
        log.info("profile store heal: leftover node_modules.old cleaned: %s",
                 not os.path.isdir(leftover))
    return result


def _migrate_doctor_state(home: str) -> None:
    src = os.path.join(os.path.expanduser("~"), ".dsh-doctor")
    dst = os.path.join(home, ".dsh-doctor")
    if os.path.isdir(src) and not os.path.isdir(dst):
        try:
            shutil.copytree(src, dst)
            log.info("migrated ~/.dsh-doctor -> %s", dst)
        except OSError as exc:
            log.warning("doctor state migration failed: %s", exc)


def _write_marker(marker: str, src: str, home: str) -> None:
    try:
        with open(marker, "w", encoding="utf-8") as fh:
            json.dump({"from": src, "to": home}, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        log.warning("marker write failed: %s", exc)


def _remove_tree(path: str) -> bool:
    """Backwards-compatible alias for :func:`remove_tree`."""
    return remove_tree(path)


# ------------------------------------------------------------- robust delete
#
# Windows refuses path strings longer than MAX_PATH (260 chars) unless they
# carry the extended-length ``\\?\`` prefix. A dsh core tree is full of pnpm
# directories that blow straight past that limit, e.g.
# ``core\node_modules\.pnpm\@mistralai+mistralai@2.2.6_...\node_modules\...
# \esm\models\operations\<120-char-operation-name>.d.ts``. Both
# ``shutil.rmtree`` and ``cmd /c rmdir /s /q`` fail there with WinError 3
# ("the system cannot find the path specified") and leave the tree in place —
# which is exactly how a failed core swap used to poison every later core
# update with "backup removal failed" (see updater.CoreUpdater._swap).
#
# Git also marks pack files read-only, and pnpm trees can contain junctions
# (reparse points) whose targets must never be followed into. The helpers
# below handle all three cases.

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def console_text_kwargs(utf8: bool = False) -> dict:
    """``subprocess`` kwargs that decode Windows console-tool output safely.

    Native tools (``mklink``, ``netstat``, ``robocopy``, ``taskkill``) write the
    OEM code page, not UTF-8. Decoding their output as UTF-8 raises
    ``UnicodeDecodeError`` inside subprocess's reader thread — on a Chinese
    Windows install that produced thousands of tracebacks during a core swap
    (one per recreated junction) and could abort the relinking step entirely.
    ``oem`` matches the console code page and never raises with
    ``errors="replace"``. PowerShell callers pass ``utf8=True`` and prefix their
    script with ``[Console]::OutputEncoding``.
    """
    if utf8:
        return {"text": True, "encoding": "utf-8", "errors": "replace"}
    for encoding in ("oem", locale.getpreferredencoding(False), "utf-8"):
        try:
            "".encode(encoding)
            return {"text": True, "encoding": encoding, "errors": "replace"}
        except (LookupError, TypeError):
            continue
    return {"text": True, "encoding": "utf-8", "errors": "replace"}


# Prepend to a PowerShell -Command script so its text output is UTF-8 on any
# console code page (pairs with console_text_kwargs(utf8=True)).
PS_UTF8_PREFIX = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "


def long_path(path: str) -> str:
    """Return the extended-length (``\\\\?\\``) spelling of *path*.

    Windows APIs called with such a path skip MAX_PATH validation entirely.
    UNC paths take the ``\\\\?\\UNC\\`` form; an already-prefixed path is
    returned unchanged.
    """
    abspath = os.path.abspath(path)
    if abspath.startswith("\\\\?\\"):
        return abspath
    if abspath.startswith("\\\\"):
        return "\\\\?\\UNC\\" + abspath[2:]
    return "\\\\?\\" + abspath


def version_parts(version: str) -> list:
    """Dotted version -> comparable parts (numeric chunks become ints)."""
    return [int(chunk) if chunk.isdigit() else chunk
            for chunk in str(version or "").split(".")]


def version_newer(candidate: str, reference: str) -> bool:
    """True when *candidate* sorts after *reference*.

    Used to keep version-aware refreshes forward-only: a live component that is
    newer than the one shipped in the package (half-applied payload, manual
    copy, downgraded app) is left alone instead of being silently rolled back.
    """
    cand, ref = version_parts(candidate), version_parts(reference)
    for left, right in zip(cand, ref):
        if left != right:
            try:
                return left > right
            except TypeError:  # mixed numeric/text segments
                return str(left) > str(right)
    return len(cand) > len(ref)


def _lexists(path: str) -> bool:
    """``os.path.lexists`` that also works past MAX_PATH."""
    if os.path.lexists(path):
        return True
    try:
        return os.path.lexists(long_path(path))
    except (OSError, ValueError):
        return False


def _is_reparse_point(path: str) -> bool:
    """True for a junction, symlink or other reparse point (never followed)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def _make_writable(path: str) -> None:
    """Clear the read-only attribute so a locked-by-attribute file can go."""
    try:
        st = os.lstat(path)
    except OSError:
        return
    if st.st_mode & stat.S_IWRITE:
        return
    try:
        os.chmod(path, st.st_mode | stat.S_IWRITE)
    except OSError:
        pass


def _unlink_any(path: str) -> None:
    """Remove one entry: file, symlink, junction or directory.

    Reparse points are removed as links (``rmdir`` for directory junctions),
    never recursed into, so a junction into the pnpm store cannot make the
    caller delete the store's content.
    """
    if _is_reparse_point(path):
        for attempt in (os.rmdir, os.unlink, os.remove):
            try:
                attempt(path)
                return
            except OSError:
                continue
        raise OSError(f"cannot remove reparse point: {path}")
    try:
        os.remove(path)
        return
    except (IsADirectoryError, PermissionError):
        pass
    except OSError as exc:
        if getattr(exc, "winerror", None) != 5:  # not "access denied"
            raise
    _make_writable(path)
    os.remove(path)


def _wipe(path: str) -> None:
    """Recursively delete *path* (post-order), tolerating long paths."""
    try:
        entries = list(os.scandir(path))
    except FileNotFoundError:
        return
    except NotADirectoryError:
        _unlink_any(path)
        return
    failures: list[str] = []
    for entry in entries:
        child = os.path.join(path, entry.name)
        try:
            if entry.is_dir(follow_symlinks=False) and not _is_reparse_point(child):
                _wipe(child)
            else:
                _unlink_any(child)
        except OSError as exc:
            failures.append(f"{child}: {exc}")
    try:
        os.rmdir(path)
    except OSError as exc:
        failures.append(f"{path}: {exc}")
    if failures:
        raise OSError("; ".join(failures[:3]))


def _robocopy_purge(path: str) -> bool:
    """Empty a directory tree with robocopy, which is long-path aware.

    ``/MIR`` from an empty source deletes everything under the destination;
    ``/XJ`` keeps robocopy out of junctions so a store link is never followed
    into. This is the same fallback build.ps1 uses for the >260-char paths
    Remove-Item chokes on.
    """
    empty = tempfile.mkdtemp(prefix="dsh-empty-")
    try:
        for target in (path, long_path(path)):
            try:
                subprocess.run(
                    ["robocopy", empty, target, "/MIR", "/XJ", "/R:1", "/W:1",
                     "/NFL", "/NDL", "/NJH", "/NJS", "/NP"],
                    capture_output=True, timeout=1800,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                log.warning("robocopy purge failed for %s: %s", target, exc)
                continue
            if not _lexists(path):
                return True
        return False
    finally:
        shutil.rmtree(empty, ignore_errors=True)


def remove_tree(path: str, attempts: int = 3) -> bool:
    """Delete a file or directory tree as thoroughly as Windows allows.

    Order of attack per attempt: a direct recursive delete with the
    ``\\\\?\\`` prefix (long-path safe, read-only aware, junction safe), then
    the same via the plain path, then a robocopy purge plus ``rmdir`` for
    anything a scanner still holds. Returns True when the path is gone; never
    raises.
    """
    if not path:
        return True
    for attempt in range(max(1, attempts)):
        if not _lexists(path):
            return True
        if attempt:
            time.sleep(1.5)
        for candidate in (path, long_path(path)):
            if not _lexists(candidate):
                continue
            try:
                if os.path.isdir(candidate) and not _is_reparse_point(candidate):
                    _wipe(candidate)
                else:
                    _unlink_any(candidate)
            except OSError as exc:
                log.debug("remove_tree pass failed for %s: %s", candidate, exc)
            if not _lexists(path):
                return True
        # Last resort: empty the tree with robocopy, then drop the shell.
        _robocopy_purge(path)
        if _lexists(path):
            try:
                subprocess.run(
                    ["cmd", "/c", "rmdir", "/s", "/q", path],
                    capture_output=True, timeout=600,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        if not _lexists(path):
            return True
    gone = not _lexists(path)
    if not gone:
        log.warning("remove_tree could not delete %s", path)
    return gone


# Files written by pre-1.0.2 installers whose Chinese names were decoded
# with the wrong codepage (UTF-8 name bytes read as GBK on Chinese Windows);
# safe to delete — the corrected scripts ship under app\assets since 1.0.3.
_GARBLED_LEGACY = (
    "鍋滄 DeepSeek Harness.bat",  # 停止
    "鍚姩 DeepSeek Harness.bat",  # 启动
)


def cleanup_legacy_garbled_files(app_dir: str) -> int:
    """Remove mojibake-named legacy helper bats left by older installers."""
    removed = 0
    for name in _GARBLED_LEGACY:
        path = os.path.join(app_dir, name)
        if os.path.isfile(path):
            try:
                os.remove(path)
                removed += 1
                log.info("removed legacy garbled file: %s", name)
            except OSError as exc:
                log.warning("failed to remove garbled file %s: %s", name, exc)
    return removed


# ------------------------------------------------------------- healing


def heal_profile_file_deps(home: str, app_dir: str) -> dict:
    """Rewrite broken ``file:`` specs in the web profile manifest.

    pnpm stores local installs as absolute ``file:`` paths; after a migration
    or an install-directory move those targets no longer exist. When a
    missing target's basename matches a bundled package under
    ``<app>\\store``, the spec is rewritten to the live path.
    """
    profile_dir = os.path.join(home, "profiles", "web")
    manifest_path = os.path.join(profile_dir, "package.json")
    store_dir = os.path.join(app_dir, "store")
    result = {"fixed": [], "warned": []}
    if not os.path.isfile(manifest_path):
        return result
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        return result
    deps = manifest.get("dependencies") or {}
    changed = False
    for name, spec in list(deps.items()):
        if not isinstance(spec, str) or not spec.startswith("file:"):
            continue
        target = spec[len("file:"):].strip().strip('"').strip("'")
        if os.path.isfile(target):
            continue
        basename = os.path.basename(target)
        fallback = os.path.join(store_dir, basename)
        if os.path.isfile(fallback):
            deps[name] = "file:" + os.path.abspath(fallback)
            changed = True
            result["fixed"].append(name)
        else:
            result["warned"].append(name)
    if changed:
        try:
            with open(manifest_path, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            log.warning("manifest rewrite failed: %s", exc)
    return result


def ensure_profile_workspace(home: str) -> dict:
    """Create/heal the web profile's pnpm-workspace.yaml.

    The @linxin666/dsh-web family (aggregate package, cloudflared/ssh2 native
    deps, fresh releases) requires the hoisted linker, allowBuilds entries and
    the minimum-release-age exclusion. A missing file gets the full template;
    an existing file is patched in place — placeholder values pnpm writes
    (``set this to true or false``) are replaced, missing keys appended.
    """
    profile_dir = os.path.join(home, "profiles", "web")
    path = os.path.join(profile_dir, "pnpm-workspace.yaml")
    if not os.path.isdir(profile_dir):
        # First plugin install ever: the dsh CLI will create the profile, but
        # pnpm must already find allowBuilds etc. by then or native deps fail
        # with ERR_PNPM_IGNORED_BUILDS. Pre-create the dir + template.
        try:
            os.makedirs(profile_dir, exist_ok=True)
        except OSError as exc:
            log.warning("profile dir create failed: %s", exc)
            return {"created": False, "changed": False}
    if not os.path.isfile(path):
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(WORKSPACE_TEMPLATE)
            return {"created": True, "changed": True}
        except OSError as exc:
            log.warning("workspace write failed: %s", exc)
            return {"created": False, "changed": False}
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            text = fh.read()
    except OSError:
        return {"created": False, "changed": False}
    original = text

    # nodeLinker must be hoisted (the web-all aggregate resolves its family
    # packages through hoisted deps of the profile).
    if re.search(r"(?m)^\s*nodeLinker:", text):
        text = re.sub(r"(?m)^(\s*nodeLinker:\s*)\S+.*$", r"\1hoisted", text)
    else:
        text = text.rstrip("\n") + "\nnodeLinker: hoisted\n"

    # allowBuilds: replace placeholder values, append missing keys.
    if re.search(r"(?m)^\s*allowBuilds:", text):
        for key in ALLOW_BUILD_KEYS:
            pattern = re.compile(rf"(?m)^(\s*{re.escape(key)}:\s*)\S+.*$")
            if pattern.search(text):
                text = pattern.sub(lambda m: m.group(1) + "true", text)
            else:
                text = re.sub(
                    r"(?m)^(\s*allowBuilds:.*)$",
                    lambda m: m.group(1) + f"\n  {key}: true",
                    text,
                    count=1,
                )
    else:
        block = "\nallowBuilds:\n" + "".join(f"  {k}: true\n" for k in ALLOW_BUILD_KEYS)
        text = text.rstrip("\n") + block

    if not re.search(r"(?m)^\s*minimumReleaseAgeExclude:", text):
        text = text.rstrip("\n") + "\nminimumReleaseAgeExclude:\n  - '@linxin666/*'\n"

    if text != original:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            log.warning("workspace heal write failed: %s", exc)
            return {"created": False, "changed": False}
    return {"created": False, "changed": text != original}


def ensure_dsh_shim(runtime_dir: str, core_bin: str) -> str:
    """Write ``dsh.cmd`` into the runtime dir so plugins that spawn the dsh
    CLI (dsh-doctor, dsh-plugin-manager) can find it on PATH."""
    os.makedirs(runtime_dir, exist_ok=True)
    shim = os.path.join(runtime_dir, "dsh.cmd")
    content = '@echo off\r\n"%~dp0node.exe" "{}" %*\r\n'.format(core_bin)
    try:
        # cmd reads batch files in the console codepage; ANSI keeps a
        # non-ASCII install path intact, ASCII is the portable fallback.
        try:
            with open(shim, "w", encoding="mbcs") as fh:
                fh.write(content)
        except (LookupError, UnicodeEncodeError):
            with open(shim, "w", encoding="ascii") as fh:
                fh.write(content)
    except OSError as exc:
        log.warning("dsh shim write failed: %s", exc)
    return shim


def pnpm_env(data: str, runtime_dir: str) -> dict:
    """Env overrides that keep pnpm/npm/corepack writes inside the instance.

    ``PNPM_HOME`` is the reliable handle: pnpm derives its store (packages +
    metadata, the big disk consumer) as ``$PNPM_HOME/store``. ``dsh plugin``
    forwards to pnpm; plugins (dsh-remote-web-ui) spawn pnpm/npx themselves,
    so both the plugin ops and the core child get these values. The npm
    cache vars are harmless extras (honored by npm, ignored by pnpm).
    """
    return {
        "PNPM_HOME": data,
        "npm_config_store_dir": os.path.join(data, ".pnpm-store"),
        "npm_config_cache_dir": os.path.join(data, ".pnpm-cache"),
        "COREPACK_HOME": os.path.join(runtime_dir, ".corepack"),
    }


_TOOLS_CACHE: dict[str, dict] = {}


def detect_tools(app_dir: str, cfg) -> dict:
    """Locate the runtimes the shell, core and plugins need.

    Lazy package: bundled portable Node + Git under ``<app>\\runtime``.
    Minimal package: no bundled runtimes — system Node/Git/Bash are used
    and missing pieces degrade gracefully (documented tradeoff).

    Results are cached per app_dir: runtimes do not change while the app is
    running, and get_state() calls this on every poll.
    """
    cached = _TOOLS_CACHE.get(app_dir)
    if cached is not None:
        return cached
    runtime_dir = os.path.join(app_dir, cfg.get("runtime_dir", "runtime"))
    bundled_node = os.path.join(runtime_dir, "node.exe")
    bundled_git = os.path.join(runtime_dir, "git", "cmd", "git.exe")
    bundled_bash = os.path.join(runtime_dir, "git", "bin", "bash.exe")

    def locate(bundled: str, tool: str) -> dict:
        if os.path.isfile(bundled):
            return {"mode": "bundled", "path": bundled}
        found = shutil.which(tool)
        if found:
            return {"mode": "system", "path": found}
        return {"mode": "missing", "path": ""}

    def locate_bash() -> dict:
        # Prefer the bash shipped next to git (Git Bash), not the WSL stub
        # that `bash` resolves to on Windows.
        if os.path.isfile(bundled_bash):
            return {"mode": "bundled", "path": bundled_bash}
        git = locate(bundled_git, "git")
        if git["path"]:
            cand = os.path.join(os.path.dirname(os.path.dirname(git["path"])),
                                "bin", "bash.exe")
            if os.path.isfile(cand):
                return {"mode": "system", "path": cand}
        found = shutil.which("bash")
        if found:
            return {"mode": "system", "path": found}
        return {"mode": "missing", "path": ""}

    minimal = not os.path.isfile(bundled_node)
    result = {
        "flavor": "minimal" if minimal else "lazy",
        "node": locate(bundled_node, "node"),
        "git": locate(bundled_git, "git"),
        "bash": locate_bash(),
    }
    _TOOLS_CACHE[app_dir] = result
    return result


def git_path_entries(runtime_dir: str) -> list[str]:
    """Bundled-Git dirs to prepend to child PATH (cmd: git.exe, bin: bash)."""
    entries = []
    for sub in ("git\\cmd", "git\\bin", "git\\usr\\bin", "git\\mingw64\\bin"):
        path = os.path.join(runtime_dir, sub)
        if os.path.isdir(path):
            entries.append(path)
    return entries


_SPACE_FREE_JUNCTION: dict[str, str] = {}


def _space_free_junction(app_dir: str) -> str:
    """Space-free junction in %TEMP% pointing at the app dir.

    The dsh CLI forwards path specs to pnpm through a shell that splits
    unquoted space paths; install dirs like ``C:\\DeepSeek Harness`` break.
    8.3 short names are disabled on many systems, so stage a junction
    (mklink /J needs no elevation) and pass paths through it instead.
    """
    key = os.path.normcase(os.path.abspath(app_dir))
    cached = _SPACE_FREE_JUNCTION.get(key)
    if cached and os.path.isdir(cached):
        return cached
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    junction = os.path.join(tempfile.gettempdir(), f"dsh-j{digest}")
    if not os.path.isdir(junction):
        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", junction, app_dir],
                capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    if os.path.isdir(junction):
        _SPACE_FREE_JUNCTION[key] = junction
        return junction
    return app_dir  # fall back to the original (space-y) path


def cli_path(app_dir: str, path: str) -> str:
    """Rewrite a path under a space-y app dir through a space-free junction
    so shell-based CLIs (pnpm) don't split it. No-op when unnecessary."""
    if " " not in path:
        return path
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(app_dir))
    except (ValueError, OSError):
        return path
    if rel == "." or rel.startswith(".."):
        return path
    return os.path.join(_space_free_junction(app_dir), rel)


def proxy_env(cfg) -> dict:
    """HTTP(S)_PROXY overrides when the user configured a proxy (D4)."""
    url = (cfg.get("proxy_url") or "").strip()
    if not url:
        return {}
    return {"HTTP_PROXY": url, "HTTPS_PROXY": url,
            "http_proxy": url, "https_proxy": url}


def registry_env(cfg) -> dict:
    """npm registry override (B3) — honored by pnpm and npm alike."""
    reg = (cfg.get("npm_registry") or "").strip()
    if not reg:
        return {}
    return {"npm_config_registry": reg}


def run_health_check(app_dir: str, cfg, node_exe: str, bin_js: str) -> None:
    """A6: post-migration/upgrade verification.

    When a web profile exists, run the core's config dump (``dsh --profile web
    --dump-config``) against the instance DSH_HOME and record the outcome to
    ``logs\\health.json``. A non-zero exit or a crash surfaces here and in the
    launcher log instead of failing silently at the next server start.

    Version tolerance: the invocation is tried in the forms the CLI has
    accepted across releases, and a core that simply does not know the flag is
    reported as ``unsupported`` (skipped) instead of as a broken install — an
    older core must keep working after a downgrade.
    """
    import subprocess
    import time as _time

    home = os.environ.get("DSH_HOME") or dsh_home(data_dir(app_dir, cfg))
    profile = os.path.join(home, "profiles", "web")
    ts = _time.strftime("%Y-%m-%d %H:%M:%S")
    result: dict = {"ok": False, "skipped": True, "ts": ts}
    if (os.path.isdir(profile) and os.path.isfile(node_exe)
            and os.path.isfile(bin_js)):
        env = dict(os.environ)
        env["DSH_HOME"] = home
        candidates = (
            ["--profile", "web", "--dump-config"],
            ["web", "--dump-config"],
            ["--profile", "web", "--dump-default-config"],
        )
        usage_re = re.compile(
            r"unknown option|unknown argument|unrecognized|invalid option|"
            r"not a valid|too many arguments",
            re.IGNORECASE,
        )
        last: dict = {"ok": False, "skipped": False, "ts": ts, "error": "no invocation succeeded"}
        for args in candidates:
            # The core spawns plugin CLIs of its own, so this must not use a
            # pipe: on timeout the killed node would leave those children
            # holding the read end and the caller would block forever.
            code, output = run_capture(
                [node_exe, bin_js, *args], env=env, timeout=60,
            )
            if code == 0:
                last = {
                    "ok": True, "skipped": False, "exit": 0, "ts": ts,
                    "args": " ".join(args), "tail": output[-400:],
                }
                break
            if usage_re.search(output):
                # This core does not implement the dump invocation: not a fault.
                last = {
                    "ok": False, "skipped": True, "unsupported": True, "ts": ts,
                    "exit": code, "args": " ".join(args),
                    "tail": output[-400:],
                }
                continue
            last = {
                "ok": False, "skipped": False, "exit": code, "ts": ts,
                "args": " ".join(args), "tail": output[-400:],
            }
            break
        result = last
    path = os.path.join(app_dir, "logs", "health.json")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        log.warning("health.json write failed: %s", exc)
    log.info("post-migration health check: %s", result)


def read_health(app_dir: str) -> dict:
    try:
        with open(os.path.join(app_dir, "logs", "health.json"),
                  "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}
