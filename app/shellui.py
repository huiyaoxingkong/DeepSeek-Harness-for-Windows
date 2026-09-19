"""Keeps the live shell UI (``<app>\\ui``) in step with the shipped one.

The desktop shell serves ``<app>\\ui`` when it exists, and that folder is also
the documented customization point ("edit index.html / style.css / app.js to
re-skin the shell"). Both facts collide on upgrade: a fix shipped inside
``<app>\\_internal\\ui`` would never take effect for an installation whose
``ui`` folder already exists — which is every install upgraded from 1.0.3
onward, because 1.0.4's ``post-update.bat`` refreshed the folder only when the
``ui\\.version`` marker was *missing* (pre-1.0.3 installs).

1.0.5 refreshes the live UI on every launch when the shipped copy is a
different version, and keeps the previous folder as ``ui-backup-<version>`` so
hand-edited shells are recoverable. The same rule is applied by
``post-update.bat`` at package-install time; this module is the authoritative
path because it also covers manual copies, the minimal package and a swapped
``_internal``.
"""

from __future__ import annotations

import logging
import os
import shutil

import homes

log = logging.getLogger("shellui")

MARKER = ".version"

# Files/dirs a refresh must never copy over the live folder even if the bundle
# ever grows them: the user plugin root lives in <data>\shell-plugins, but a
# future bundle could ship a staging folder worth protecting.
_SKIP = {".shell-plugin-staging"}

# Paths earlier releases shipped inside ui\ and 1.0.5 deliberately dropped
# (the example shell plugins now live in examples/shell-plugins). A refresh
# deletes them so upgraded installs match a fresh 1.0.5 install.
LEGACY_REMOVED = (
    "plugins/example-status",
    "plugins/example-pet",
    "plugins/plugin-dev-kit",
)


def bundled_ui_dir(app_dir: str) -> str:
    """The UI shipped with this build (``_internal\\ui`` for a packaged app)."""
    candidate = os.path.join(app_dir, "_internal", "ui")
    if os.path.isfile(os.path.join(candidate, "index.html")):
        return candidate
    return ""


def read_marker(ui_dir: str) -> str:
    """Version recorded in *ui_dir*'s marker file ('' when absent)."""
    try:
        with open(os.path.join(ui_dir, MARKER), "r", encoding="utf-8-sig") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def write_marker(ui_dir: str, version: str) -> None:
    try:
        with open(os.path.join(ui_dir, MARKER), "w", encoding="utf-8") as fh:
            fh.write(version)
    except OSError as exc:
        log.warning("could not write ui version marker: %s", exc)


def _copy_tree(src: str, dst: str) -> None:
    """Copy *src* over *dst* (created), skipping the protected names.

    A plain copy, not a mirror: files the user added to the live folder are
    left in place. The live folder is the documented customization point, so
    only files this bundle actually ships are replaced.
    """
    os.makedirs(dst, exist_ok=True)
    for entry in os.listdir(src):
        if entry in _SKIP:
            continue
        source = os.path.join(src, entry)
        target = os.path.join(dst, entry)
        if os.path.isdir(source):
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)


def _remove_legacy_paths(live: str) -> list[str]:
    """Drop shipped files that newer releases no longer include.

    A merge-refresh keeps everything it does not ship, so files we ourselves
    shipped earlier (and deliberately removed) must be deleted explicitly —
    otherwise the example shell plugins would live on in upgraded installs.
    """
    removed: list[str] = []
    for rel in LEGACY_REMOVED:
        target = os.path.join(live, *rel.split("/"))
        if os.path.isdir(target):
            if homes.remove_tree(target):
                removed.append(rel)
        elif os.path.isfile(target):
            try:
                os.remove(target)
                removed.append(rel)
            except OSError:
                pass
    return removed


def sync_shell_ui(app_dir: str, version: str) -> dict:
    """Refresh ``<app>\\ui`` from the shipped copy when the versions differ.

    Returns a small report: ``action`` is one of ``dev`` (no packaged bundle),
    ``none`` (already current), ``installed`` (live folder was missing) or
    ``refreshed`` (replaced, previous folder kept as ``ui-backup-<old>``).
    Never raises: a failed refresh restores the previous folder and the app
    keeps running with whatever UI is on disk.
    """
    result = {"action": "none", "version": version, "backup": "", "reason": ""}
    bundled = bundled_ui_dir(app_dir)
    live = os.path.join(app_dir, "ui")
    if not bundled:
        result.update(action="dev", reason="no packaged ui bundle next to the app")
        return result
    if os.path.normcase(os.path.abspath(bundled)) == os.path.normcase(os.path.abspath(live)):
        result.update(action="dev", reason="live folder is the bundled folder")
        return result

    shipped_version = read_marker(bundled) or version
    if not os.path.isdir(live):
        try:
            _copy_tree(bundled, live)
            write_marker(live, shipped_version)
            result.update(action="installed", version=shipped_version)
            log.info("shell UI installed from %s (version %s)", bundled, shipped_version)
        except OSError as exc:
            result.update(reason=f"install failed: {exc}")
            log.warning("shell UI install failed: %s", exc)
        return result

    live_version = read_marker(live)
    if live_version and live_version == shipped_version:
        result.update(reason="live ui already matches the shipped version")
        return result
    if live_version and homes.version_newer(live_version, shipped_version):
        # Forward-only: a live UI newer than the shipped one (half-applied
        # payload, manual copy with a downgraded app) is not rolled back.
        result.update(reason=(
            f"live ui {live_version} is newer than the shipped {shipped_version}"))
        log.info("shell UI left as-is: live %s is newer than shipped %s",
                 live_version, shipped_version)
        return result

    # Different (or unmarked) live UI: refresh ours in place, keep theirs.
    backup = os.path.join(
        app_dir, f"ui-backup-{live_version}" if live_version else "ui-backup")
    if not os.path.isdir(backup):
        # One-time snapshot for recovery (the shell UI is ~150 KB, so this is
        # cheap). Never overwrite an existing snapshot: it may hold the user's
        # pre-upgrade files.
        try:
            shutil.copytree(live, backup)
        except OSError as exc:
            log.warning("shell UI snapshot failed (%s); continuing with the refresh", exc)
    try:
        _copy_tree(bundled, live)
    except OSError as exc:
        log.warning("shell UI refresh failed: %s", exc)
        result.update(reason=f"refresh failed: {exc}")
        return result
    removed = _remove_legacy_paths(live)
    write_marker(live, shipped_version)
    result.update(action="refreshed", version=shipped_version,
                  backup=os.path.basename(backup), removed=removed,
                  reason=f"merged ui {live_version or '(unmarked)'} -> {shipped_version}")
    log.info("shell UI refreshed: %s -> %s (snapshot: %s%s)",
             live_version or "(unmarked)", shipped_version, os.path.basename(backup),
             f", removed {', '.join(removed)}" if removed else "")
    return result
