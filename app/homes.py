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

import json
import logging
import os
import re
import shutil
import subprocess

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
    """
    data = data_dir(app_dir, cfg)
    home = dsh_home(data)
    os.makedirs(home, exist_ok=True)
    os.environ["DSH_HOME"] = home
    return data, home


# ------------------------------------------------------------- migration


def _robocopy(src: str, dst: str) -> int:
    cmd = [
        "robocopy", src, dst,
        "/E", "/XJ", "/COPY:DAT", "/DCOPY:DAT",
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
    for _ in range(3):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        try:
            subprocess.run(
                ["cmd", "/c", "rmdir", "/s", "/q", f'"{path}"'],
                capture_output=True, timeout=600,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if not os.path.exists(path):
            return True
    return not os.path.exists(path)


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

    When a web profile exists, run ``dsh --profile web --dump-config`` against
    the instance DSH_HOME and record the outcome to ``logs\\health.json``.
    A non-zero exit or a crash surfaces here and in the launcher log instead
    of failing silently at the next server start.
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
        try:
            proc = subprocess.run(
                [node_exe, bin_js, "--profile", "web", "--dump-config"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            result = {
                "ok": proc.returncode == 0, "skipped": False,
                "exit": proc.returncode, "ts": ts,
                "tail": (proc.stderr or proc.stdout or "")[-400:],
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = {"ok": False, "skipped": False, "ts": ts, "error": str(exc)}
    path = os.path.join(app_dir, "logs", "health.json")
    try:
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
