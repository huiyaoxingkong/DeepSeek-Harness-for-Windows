"""Records the upstream GitHub commit for a freshly built core.

Writes core/.dsh-desktop-info.json so the app can tell "same as upstream"
from "outdated". Uses the GitHub API when reachable; falls back to the local
git HEAD of the core checkout.

Usage: python scripts/write-core-info.py <core-dir> [commit] [date] [message]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

UPSTREAM = "https://github.com/deepseek-ai/deepseek-harness"
BRANCH = "master"
API_URL = f"https://api.github.com/repos/deepseek-ai/deepseek-harness/commits/{BRANCH}"
USER_AGENT = "DeepSeek-Harness-Desktop/0.1"


def local_head(core_dir: str) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=core_dir, capture_output=True,
            text=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return out.stdout.strip()[:12] if out.returncode == 0 else ""
    except OSError:
        return ""


def remote_info() -> dict:
    req = urllib.request.Request(API_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return {
        "commit": data["sha"][:12],
        "date": data["commit"]["committer"]["date"],
        "message": data["commit"]["message"].splitlines()[0],
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: write-core-info.py <core-dir>")
        return 2
    core_dir = os.path.abspath(sys.argv[1])
    info: dict = {"commit": "", "date": "", "message": "", "updatedAt": ""}
    try:
        info.update(remote_info())
    except Exception as exc:
        print(f"  (GitHub API unreachable: {exc})")
        info["commit"] = local_head(core_dir)
        info["message"] = "local snapshot"
    info["updatedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    target = os.path.join(core_dir, ".dsh-desktop-info.json")
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=2)
    print(f"core info: {info['commit']} ({info['message']}) -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
