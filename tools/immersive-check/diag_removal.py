"""Diagnose why a leftover tree resists removal (read-only, locks, ACLs)."""

from __future__ import annotations

import os
import stat
import sys

root = sys.argv[1]
print(f"root={root} exists={os.path.exists(root)}")

for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
    for name in filenames + dirnames:
        full = os.path.join(dirpath, name)
        try:
            st = os.lstat(full)
        except OSError as exc:
            print(f"LSTAT FAIL {full}: {exc}")
            continue
        flags = []
        if stat.S_ISLNK(st.st_mode):
            flags.append("SYMLINK/JUNCTION")
        if not (st.st_mode & stat.S_IWRITE):
            flags.append("READONLY")
        if getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_HIDDEN:
            flags.append("HIDDEN")
        if getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_SYSTEM:
            flags.append("SYSTEM")
        if getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            flags.append("REPARSE")
        if flags:
            print(f"{'/'.join(flags)}: {full}")

print("--- os.walk + rmdir dry run (top-down) ---")
for dirpath, dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
    for name in filenames + dirnames:
        full = os.path.join(dirpath, name)
        try:
            if os.path.isdir(full) and not os.path.islink(full):
                os.rmdir(full)
            else:
                os.remove(full)
        except OSError as exc:
            print(f"REMOVE FAIL [{exc.winerror if hasattr(exc, 'winerror') else exc.errno}] {full}: {exc}")
print(f"root still exists={os.path.exists(root)}")
