"""Rebase NTFS junctions from a copied tree onto the destination location.

pnpm links workspace packages via junctions whose targets are absolute paths
into the source checkout (e.g. core\\packages\\core\\agent). After the tree is
copied to a new location (dist\\DeepSeek Harness\\core), every junction must
be recreated with the destination root substituted.

Usage: python scripts/relink.py <src> <dst>
The copy itself is done by robocopy /E /XJ (which skips junctions); this script
only recreates them at the destination with rebased targets.

Note: os.walk() descends into junction reparse points on Windows (they look
like directories), which cycles forever in pnpm layouts. This script walks
with os.scandir() and never recurses through a junction.
"""

from __future__ import annotations

import os
import subprocess
import sys

IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003


def is_junction(path: str) -> bool:
    try:
        return getattr(os.lstat(path), "st_reparse_tag", 0) == IO_REPARSE_TAG_MOUNT_POINT
    except OSError:
        return False


def junction_target(path: str) -> str:
    """Read a junction's absolute target via os.readlink (\\??\\ prefix stripped)."""
    try:
        target = os.readlink(path)
    except OSError:
        return ""
    if target.startswith("\\\\?\\") or target.startswith("\\??\\"):
        target = target[4:]
    return target


def collect_junctions(root: str) -> list[tuple[str, str]]:
    """Walk without entering junctions; return (link, absolute target) pairs
    for every junction whose target lives inside root."""
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
                    if target and target.lower().startswith(root.lower()):
                        found.append((full, target))
                else:
                    stack.append(full)
    return found


def create_junction(link: str, target: str) -> bool:
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", link, target],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return result.returncode == 0


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: relink.py <src> <dst>")
        return 2
    src = os.path.abspath(sys.argv[1]).rstrip("\\/")
    dst = os.path.abspath(sys.argv[2]).rstrip("\\/")
    if not os.path.isdir(dst):
        print(f"destination missing: {dst}")
        return 2
    junctions = collect_junctions(src)
    created = skipped = 0
    for link, target in junctions:
        rel = os.path.relpath(target, src)
        new_link = os.path.join(dst, os.path.relpath(link, src))
        new_target = os.path.join(dst, rel)
        if os.path.exists(new_link):
            skipped += 1
            continue
        os.makedirs(os.path.dirname(new_link), exist_ok=True)
        if create_junction(new_link, new_target):
            created += 1
        else:
            print(f"  ! failed to junction {new_link} -> {new_target}")
    print(f"relinked {created} junction(s), {skipped} skipped, from {src} to {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
