"""Count pnpm junctions under a core tree (long-path safe, links not followed)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
import homes  # noqa: E402

PROBE_REL = os.path.join("apps", "cli", "node_modules", "@deepseek-ai", "dsh-app-boot")


def count_junctions(root: str) -> tuple[int, bool, str]:
    total = 0
    stack = [homes.long_path(root)]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                if homes._is_reparse_point(entry.path):
                    total += 1
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
            except OSError:
                continue
    probe = os.path.join(root, PROBE_REL)
    is_link = homes._is_reparse_point(homes.long_path(probe))
    try:
        target = os.readlink(homes.long_path(probe))
    except OSError:
        target = ""
    return total, is_link, target


for path in sys.argv[1:]:
    if not os.path.isdir(path):
        print(f"{path}: MISSING")
        continue
    total, is_link, target = count_junctions(path)
    print(f"{path}\n  junctions: {total}\n  probe is a link: {is_link}\n  probe target: {target}")
