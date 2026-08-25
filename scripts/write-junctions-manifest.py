"""Write a portable junction manifest for a built core tree.

The desktop installer archives the core with 7-Zip `-snl` (junctions stored
as links, extracted as empty directories). End-user extraction cannot rely on
the archiver recreating junctions, so the app restores them from this
manifest: a JSON list of `{link, target}` pairs, both relative to the core
root, recreated with `mklink /J` against the actual install location.

Usage: python scripts/write-junctions-manifest.py <core-dir>
Writes <core-dir>/junctions.json (skipped when the core has no junctions).
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


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: write-junctions-manifest.py <core-dir>")
        return 2
    core = os.path.abspath(sys.argv[1])
    entries = []
    stack = [core]
    while stack:
        dirpath = stack.pop()
        try:
            children = list(os.scandir(dirpath))
        except OSError:
            continue
        for entry in children:
            if entry.is_dir(follow_symlinks=False) and not entry.is_symlink():
                full = entry.path
                if is_junction(full):
                    target = junction_target(full)
                    if target and target.lower().startswith(core.lower()):
                        entries.append({
                            "link": os.path.relpath(full, core),
                            "target": os.path.relpath(target, core),
                        })
                else:
                    stack.append(full)
    if not entries:
        print("no junctions found, manifest not written")
        return 0
    manifest = os.path.join(core, "junctions.json")
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=0)
    print(f"wrote {len(entries)} junction(s) to {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
