"""Rebase NTFS junctions after a directory move, for the core updater.

pnpm links workspace packages via junctions whose targets are absolute paths
into the checkout where `pnpm install` ran. When the updater moves a freshly
built tree from .update/src to core/, those junctions still point at the old
(now deleted) location. This module deletes every stale junction under the
moved root and recreates it against the new root, preserving the relative path.

Junction-aware walking is required: os.walk() descends into junction reparse
points on Windows (they look like directories), which cycles forever in pnpm
layouts, so traversal uses os.scandir() and never recurses through one.
"""

from __future__ import annotations

import os
import subprocess

IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003


def is_junction(path: str) -> bool:
    try:
        return getattr(os.lstat(path), "st_reparse_tag", 0) == IO_REPARSE_TAG_MOUNT_POINT
    except OSError:
        return False


def junction_target(path: str) -> str:
    try:
        target = os.readlink(path)
    except OSError:
        return ""
    if target.startswith("\\\\?\\") or target.startswith("\\??\\"):
        target = target[4:]
    return target


def collect_junctions(root: str) -> list[tuple[str, str]]:
    """All (link, absolute target) pairs under root; never descends through a
    junction. Targets are not filtered by location: rebase_junctions resolves
    staleness per-target instead."""
    found: list[tuple[str, str]] = []
    stack = [root]
    while stack:
        dirpath = stack.pop()
        try:
            entries = list(os.scandir(dirpath))
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir(follow_symlinks=False) and not entry.is_symlink():
                full = entry.path
                if is_junction(full):
                    target = junction_target(full)
                    if target:
                        found.append((full, target))
                else:
                    stack.append(full)
    return found


def create_junction(link: str, target: str) -> bool:
    try:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", link, target],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except OSError:
        return False


def rebase_junctions(link_root: str, target_root: str) -> tuple[int, int]:
    """Recreate junctions under link_root whose targets (relative to
    target_root) no longer exist, retargeting them to the same relative path
    under link_root.

    Usage after `os.replace(old_src, link_root)`: the junction entries moved
    along with the tree, but their absolute targets still name old_src paths,
    which are gone. Pass link_root = the new location, target_root = old_src.

    Returns (recreated, failed).
    """
    recreated = failed = 0
    for link, target in collect_junctions(link_root):
        if os.path.exists(target):
            continue  # target still valid; nothing to do
        rel = os.path.relpath(target, target_root)
        new_target = os.path.join(link_root, rel)
        try:
            os.rmdir(link)  # junction is an empty reparse-point dir
        except OSError:
            pass
        if os.path.exists(link) or os.path.islink(link):
            failed += 1
            continue
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if create_junction(link, new_target):
            recreated += 1
        else:
            failed += 1
    return recreated, failed
