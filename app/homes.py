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
