"""Download portable Git for Windows into runtime\\git (lazy package).

Mirrors scripts/install-node.ps1 for the Git runtime: fetches the latest
Git for Windows release, picks the PortableGit 64-bit self-extracting 7z,
extracts it with the bundled 7z.exe and normalises the layout so that
``runtime\\git\\cmd\\git.exe`` and ``runtime\\git\\bin\\bash.exe`` exist.

Usage: python scripts\\download-portable-git.py [--version <tag>]
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "dsh-desktop-build"}


def fetch(url: str, timeout: int = 60):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                  timeout=timeout)


def main() -> int:
    version = None
    if "--version" in sys.argv:
        version = sys.argv[sys.argv.index("--version") + 1]

    target = os.path.join(ROOT, "runtime", "git")
    git_exe = os.path.join(target, "cmd", "git.exe")
    if os.path.isfile(git_exe) and not version:
        print("runtime\\git\\cmd\\git.exe already present, skipping download.")
        return 0

    if version:
        rel = json.load(fetch(
            f"https://api.github.com/repos/git-for-windows/git/releases/tags/{version}"))
    else:
        rel = json.load(fetch(
            "https://api.github.com/repos/git-for-windows/git/releases/latest"))
    print("release:", rel.get("tag_name"))
    asset = next((a for a in rel.get("assets", [])
                  if a["name"].startswith("PortableGit-")
                  and a["name"].endswith("64-bit.7z.exe")), None)
    if not asset:
        print("no PortableGit-*-64-bit.7z.exe asset found", file=sys.stderr)
        return 1

    dst = os.path.join(ROOT, "tools", "PortableGit.7z.exe")
    tmp = dst + ".part"
    print("downloading", asset["name"], f'{asset["size"] / 1e6:.1f} MB ...')
    with fetch(asset["browser_download_url"], timeout=120) as r, \
            open(tmp, "wb") as fh:
        total = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            total += len(chunk)
            if total % (20 << 20) < (1 << 20):
                print(f"  {total / 1e6:.0f} MB", flush=True)
    os.replace(tmp, dst)
    print(f"downloaded {total / 1e6:.1f} MB")

    # PortableGit extracts into a top-level PortableGit/ folder; move its
    # contents one level up into runtime\git.
    staging = os.path.join(ROOT, "runtime", ".git-staging")
    if os.path.isdir(staging):
        shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    seven = os.path.join(ROOT, "tools", "7zip", "7z.exe")
    res = subprocess.run(
        [seven, "x", dst, f"-o{staging}", "-y", "-bso0", "-bsp0"],
        capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        print(f"extract failed: {res.returncode}\n{res.stderr[-500:]}",
              file=sys.stderr)
        return 1
    inner = None
    # The PortableGit SFX payload is FLAT (bin/, cmd/, mingw64/, usr/, ...)
    # with no wrapper folder. A wrapper exists only when a single top-level
    # directory is present and it is not one of the payload's own folders.
    flat_markers = {"bin", "cmd", "mingw64", "usr", "etc", "tmp"}
    dirs = [d for d in os.listdir(staging)
            if os.path.isdir(os.path.join(staging, d))]
    if len(dirs) == 1 and dirs[0].lower() not in flat_markers:
        inner = os.path.join(staging, dirs[0])
    src = inner or staging
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.move(src, target)
    if inner:
        shutil.rmtree(staging, ignore_errors=True)
    os.remove(dst)

    missing = []
    for probe in ("cmd\\git.exe", "bin\\bash.exe"):
        ok = os.path.isfile(os.path.join(target, probe))
        print(f"{probe}: {'ok' if ok else 'MISSING'}")
        if not ok:
            missing.append(probe)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
