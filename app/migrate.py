"""Profile migrations for shipped-plugin changes.

1.0.5 replaces the retired dsh-web aggregate with the author's current family.
Upstream retired the old packages themselves: ``@linxin666/dsh-web-ui-all`` is
deprecated on npm ("迁移到 @linxin666/dsh-web-all，请勿用此版本"), its last
publish is 0.3.6 (2026-08-27) against the current family's 0.3.23
(2026-09-16), and the tarball carries the author's own migration directive
``dsh.migrate = {to: "@linxin666/dsh-web-all", since: "0.3.6"}``. Its pinned
0.3.6 closure patches the client alongside the 0.1.6-alpha.2 kernel and breaks
the Web UI; the replacement family declares ``dsh.engines.dsh >= 0.1.5-rc.1``.
An existing profile keeps the retired packages in ``dsh.profile.bundles``
forever unless something removes them — this module does, and it also repoints
the preseeded store plugin at the bundled tarball so upgraded installs get the
same store version a fresh install does.

The migration is manifest-first: editing ``profiles/web/package.json`` is what
actually stops the core from loading a plugin, so it is applied even when the
dsh CLI or pnpm cannot run (offline, no runtime). pnpm is then asked to
reconcile ``node_modules`` with the new manifest (a bounded, best-effort run
whose output goes to ``profiles/web/.plugin-manager/logs/profile-migration-pnpm.log``);
a failure there only leaves unused files on disk.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time

import homes

log = logging.getLogger("migrate")

PROFILE = "web"
HOME_DIR_NAME = ".dsh"

# Packages upstream retired. ``@linxin666/dsh-web-ui-all`` is deprecated on npm
# with the author's own ``dsh.migrate.to`` directive pointing at the package in
# NEW_AGGREGATE; the other four left the repository's current package set. They
# were all part of the pre-1.0.5 preset, so an upgraded profile still lists
# them and must have them removed.
OBSOLETE_PLUGINS = (
    "@linxin666/dsh-web-ui-all",
    "@linxin666/dsh-chat-recovery",
    "@linxin666/dsh-desktop-launcher",
    "@linxin666/dsh-perf",
    "@linxin666/dsh-client-ui-aionui-panel",
)

# Plugin that the new family replaces the old aggregate with (for the log/UI).
NEW_AGGREGATE = "@linxin666/dsh-web-all"

_STORE_TGZ_RE = re.compile(r"^dshmarket-(?P<version>\d+(?:\.\d+)+)\.tgz$", re.IGNORECASE)


def bundled_store(app_dir: str) -> tuple[str, str]:
    """Highest ``dshmarket-<version>.tgz`` shipped under ``<app>\\store``.

    Returns ``(absolute_path, version)`` or ``("", "")``.
    """
    store_dir = os.path.join(app_dir, "store")
    best, best_ver = "", ""
    try:
        names = os.listdir(store_dir)
    except OSError:
        return "", ""
    for fname in names:
        match = _STORE_TGZ_RE.match(fname)
        if not match:
            continue
        version = match.group("version")
        if not best_ver or _newer(version, best_ver):
            best, best_ver = os.path.join(store_dir, fname), version
    return best, best_ver


def _newer(candidate: str, reference: str) -> bool:
    def parts(value: str) -> list:
        return [int(chunk) if chunk.isdigit() else chunk for chunk in value.split(".")]
    left, right = parts(candidate), parts(reference)
    for a, b in zip(left, right):
        if a != b:
            return a > b
    return len(left) > len(right)


def _read_json(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path: str, data: dict) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        return True
    except OSError as exc:
        log.warning("profile manifest write failed: %s", exc)
        return False


def _upstream_target(profile: str, removed: list[str]) -> list[dict]:
    """``dsh.migrate`` directives of the removed packages, when published.

    Read from the installed ``node_modules`` before the prune; purely
    informational and never fatal.
    """
    found: list[dict] = []
    for name in removed:
        manifest = _read_json(os.path.join(profile, "node_modules", *name.split("/"),
                                           "package.json"))
        if not manifest:
            continue
        directive = (manifest.get("dsh") or {}).get("migrate") if isinstance(
            manifest.get("dsh"), dict) else None
        target = directive.get("to") if isinstance(directive, dict) else None
        if target:
            found.append({"from": name, "to": str(target),
                          "version": str(manifest.get("version") or "")})
    return found


def _pnpm_install(home: str, node_exe: str, timeout: float) -> tuple[bool, str]:
    """Reconcile the profile's node_modules with its package.json.

    Returns ``(ok, log_path)`` and never raises: a failure only leaves unused
    files on disk, which the next plugin operation (dsh's own pnpm run) cleans
    up anyway. ``--ignore-scripts`` mirrors the launcher's profile-store heal —
    native build scripts (dsh-ssh's cpu-features) are not needed to remove
    packages and would stall on a machine without a C++ toolchain.

    pnpm's output goes to a *file*, not a pipe: on Windows, killing the timed-out
    ``pnpm.cmd`` leaves the node child alive holding the write end of a pipe, and
    ``subprocess.run(capture_output=True)`` would then block in ``communicate()``
    forever — which keeps ``_heal_done`` unset and blocks every plugin operation
    (observed on a real profile). The whole process tree is killed instead.
    """
    profile = os.path.join(home, "profiles", PROFILE)
    if not os.path.isdir(profile):
        return False, ""
    log_dir = os.path.join(profile, ".plugin-manager", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "profile-migration-pnpm.log")
        log_file = open(log_path, "wb")
    except OSError as exc:
        log.warning("profile prune: cannot open the pnpm log: %s", exc)
        return False, ""
    # DSH_HOME is <data>\.dsh, and pnpm's store/home vars hang off <data>.
    data_dir = os.path.dirname(home) if os.path.basename(home) == HOME_DIR_NAME else home
    runtime_dir = os.path.dirname(node_exe)
    pnpm = os.path.join(runtime_dir, "pnpm.cmd")
    if not os.path.isfile(pnpm):
        pnpm = shutil.which("pnpm") or "pnpm"
    env = dict(os.environ)
    env["DSH_HOME"] = home
    # CI makes pnpm default to --frozen-lockfile, and this migration just
    # rewrote package.json, so the install would always fail.
    env.pop("CI", None)
    env.pop("ci", None)
    env["PATH"] = runtime_dir + os.pathsep + env.get("PATH", "")
    env.update(homes.pnpm_env(data_dir, runtime_dir))
    env["npm_config_fetch_timeout"] = "600000"
    env["npm_config_fetch_retries"] = "5"
    env["pnpm_config_fetch_timeout"] = "600000"
    env["pnpm_config_fetch_retries"] = "5"
    proc = None
    try:
        with log_file:
            proc = subprocess.Popen(
                [pnpm, "install", "--no-frozen-lockfile", "--ignore-scripts"],
                cwd=profile, env=env, stdout=log_file, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                log.warning("profile prune timed out after %.0fs; killing pnpm", timeout)
                _kill_tree(proc.pid)
                return False, log_path
    except OSError as exc:
        log.warning("profile prune (pnpm install) could not start: %s", exc)
        if proc is not None:
            _kill_tree(proc.pid)
        return False, log_path
    if code != 0:
        log.warning("profile prune (pnpm install) exit=%s: %s", code,
                    _tail(log_path))
        return False, log_path
    log.info("profile prune: node_modules reconciled with the migrated manifest")
    return True, log_path


def _kill_tree(pid: int) -> None:
    """Kill a process and its children (pnpm.cmd is a cmd.exe wrapper)."""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=60,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover
        log.warning("could not kill pnpm tree %s: %s", pid, exc)


def _tail(path: str, limit: int = 300) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()[-limit:].strip()
    except OSError:
        return ""


def migrate_profile(app_dir: str, node_exe: str, bin_js: str, home: str,
                    timeout: float = 600.0) -> dict:
    """Apply shipped-plugin migrations to the web profile (best effort).

    Never raises: the caller runs this on the launcher's startup path.
    """
    result: dict = {"ok": True, "skipped": "", "removed": [], "bundlesDropped": [],
                    "storeFrom": "", "storeTo": "", "pruned": False,
                    "reinstalled": False, "error": "", "migrateTo": [],
                    "pruneLog": ""}
    profile = os.path.join(home, "profiles", PROFILE)
    manifest_path = os.path.join(profile, "package.json")
    manifest = _read_json(manifest_path)
    if manifest is None:
        result["skipped"] = "no-profile"
        return result

    deps = manifest.get("dependencies")
    deps = deps if isinstance(deps, dict) else {}
    profile_block = manifest.get("dsh", {}).get("profile") if isinstance(manifest.get("dsh"), dict) else None
    bundles = profile_block.get("bundles") if isinstance(profile_block, dict) else None
    bundles = list(bundles) if isinstance(bundles, list) else []

    changed = False
    for name in OBSOLETE_PLUGINS:
        if name in deps:
            deps.pop(name)
            result["removed"].append(name)
            changed = True
        if name in bundles:
            bundles = [entry for entry in bundles if entry != name]
            result["bundlesDropped"].append(name)
            changed = True

    # Record where upstream says users should go instead (the deprecated
    # aggregate ships ``dsh.migrate = {to: ...}``). Informational only: the
    # launcher deliberately does not install a replacement behind the user.
    result["migrateTo"] = _upstream_target(profile, result["removed"])

    tgz, version = bundled_store(app_dir)
    if tgz and "dshmarket" in deps:
        current = str(deps.get("dshmarket") or "")
        target = os.path.abspath(tgz)
        current_path = current[len("file:"):].strip().strip('"') if current.startswith("file:") else ""
        if os.path.normcase(os.path.abspath(current_path or current)) != os.path.normcase(target):
            result["storeFrom"] = current
            result["storeTo"] = target
            deps["dshmarket"] = "file:" + target
            changed = True

    if changed:
        manifest["dependencies"] = deps
        if isinstance(profile_block, dict):
            profile_block["bundles"] = bundles
            manifest.setdefault("dsh", {})["profile"] = profile_block
        if not _write_json(manifest_path, manifest):
            result.update(ok=False, error="manifest write failed")
            return result
        log.info("profile migration: removed=%s bundles=%s store=%s->%s",
                 result["removed"], result["bundlesDropped"],
                 result["storeFrom"], result["storeTo"])

    if not (result["removed"] or result["bundlesDropped"] or result["storeFrom"]):
        result["skipped"] = "up-to-date"
        return result

    # Prune / materialize with pnpm when a runtime is available.
    if not (os.path.isfile(node_exe) and os.path.isfile(bin_js)):
        result["skipped"] = "no-core-cli"
        return result
    # Reconcile node_modules with the manifest we just rewrote: `pnpm install`
    # drops the retired packages and materializes the bundled store tarball.
    # `dsh plugin --profile web remove …` cannot be used here — the manifest no
    # longer lists those packages, and pnpm then refuses with
    # ERR_PNPM_CANNOT_REMOVE_MISSING_DEPS (verified on a real profile, where
    # the prune silently never happened).
    pruned, prune_log = _pnpm_install(home, node_exe, timeout)
    result["pruned"] = pruned
    result["pruneLog"] = prune_log
    result["reinstalled"] = pruned and bool(result["storeFrom"])
    time.sleep(0.2)
    return result
