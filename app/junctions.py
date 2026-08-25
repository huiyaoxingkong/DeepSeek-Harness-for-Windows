"""Portable core junction restoration.

The shipped core contains pnpm workspace junctions (see
scripts/write-junctions-manifest.py for the junctions.json manifest). A
generic archive extraction cannot be relied on to recreate them, so this
module detects missing links and restores them with mklink /J (no admin
required) from the manifest, resolved against the actual install location.
"""

from __future__ import annotations

import logging
import os
import subprocess

log = logging.getLogger("junctions")

PROBE = os.path.join("apps", "cli", "node_modules", "@deepseek-ai", "dsh-app-boot")


def needs_restore(core_dir: str) -> bool:
    """True when the manifest exists but the probe link is not a junction
    (e.g. right after a generic archive extraction)."""
    manifest = os.path.join(core_dir, "junctions.json")
    probe = os.path.join(core_dir, *PROBE.split(os.sep))
    if not os.path.isfile(manifest):
        return False
    try:
        return os.path.isdir(probe) and os.path.realpath(probe) == os.path.abspath(probe)
    except OSError:
        return True


def restore(core_dir: str, script_path: str) -> bool:
    """Run scripts/restore-junctions.ps1 against the core; True on success."""
    if not os.path.isfile(script_path):
        log.warning("restore script missing: %s", script_path)
        return False
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", script_path, core_dir],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=900, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            log.warning("junction restore failed: %s", result.stderr[-300:])
            return False
        return not needs_restore(core_dir)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("junction restore error: %s", exc)
        return False
