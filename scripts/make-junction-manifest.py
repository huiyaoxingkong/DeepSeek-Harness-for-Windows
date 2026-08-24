"""Generate a junction manifest for SFX packaging.

pnpm links workspace packages via NTFS junctions with absolute targets. The
SFX installer cannot preserve them (targets are absolute), so this script
writes junctions.json listing every junction under the core tree as
(link, relTarget) pairs relative to the core root. The installer recreates
them with rebuild-junctions.ps1.

Usage: python scripts/make-junction-manifest.py <core-dir> <out-json>
"""

from __future__ import annotations

import json
import os
import sys

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


def collect(root: str) -> list[tuple[str, str]]:
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


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: make-junction-manifest.py <core-dir> <out-json>")
        return 2
    core_dir = os.path.abspath(sys.argv[1]).rstrip("\\/")
    out_path = os.path.abspath(sys.argv[2])
    entries = []
    for link, target in collect(core_dir):
        rel_link = os.path.relpath(link, core_dir)
        rel_target = os.path.relpath(target, core_dir)
        entries.append({"link": rel_link, "target": rel_target})
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"core": os.path.basename(core_dir), "junctions": entries},
                  fh, ensure_ascii=False)
    print(f"manifest: {len(entries)} junctions -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
