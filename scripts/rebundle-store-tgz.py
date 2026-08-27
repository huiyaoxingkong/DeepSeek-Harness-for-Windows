"""Rebundle the published dshmarket tarball for offline install.

The official npm tarball ships built lib/ + client/ but NOT its runtime
dependency closure. This script downloads the official tarball, resolves the
runtime deps (js-yaml -> argparse, undici) from the registry, embeds them
under ``package/node_modules`` and writes ``bundleDependencies`` so the app's
``pnpm add <tarball>`` preseed works with zero registry traffic.

Usage: python scripts\\rebundle-store-tgz.py [--version 1.33.0]
"""
import argparse
import io
import json
import os
import re
import sys
import tarfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "dsh-build"}


def fetch(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def registry_doc(name: str) -> dict:
    return json.loads(fetch(f"https://registry.npmjs.org/{name}"))


def satisfies(version: str, spec: str) -> bool:
    spec = spec.strip().lstrip("^~")
    if not spec:
        return True
    return version.startswith(spec) and version[len(spec):len(spec) + 1] in ("", ".")


def _version_key(version: str):
    nums = [int(x) for x in re.findall(r"\d+", version)][:8]
    return (nums + [0] * (8 - len(nums)), version)


def resolve(name: str, spec: str) -> str:
    doc = registry_doc(name)
    versions = sorted(doc.get("versions", {}).keys(), key=_version_key)
    matches = [v for v in versions if satisfies(v, spec)]
    if not matches:
        raise RuntimeError(f"no {name} version satisfies {spec}")
    return matches[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="1.33.0")
    args = parser.parse_args()
    version = args.version

    out_path = os.path.join(ROOT, "app", "store", f"dshmarket-{version}.tgz")
    if os.path.isfile(out_path):
        print(f"{out_path} already exists, skipping.")
        return 0

    print(f"fetching dshmarket@{version} ...")
    main_data = fetch(f"https://registry.npmjs.org/dshmarket/-/dshmarket-{version}.tgz")
    print(f"  official tarball: {len(main_data) / 1e6:.1f} MB")

    # Resolve the runtime dependency closure (two levels cover the real tree).
    with tarfile.open(fileobj=io.BytesIO(main_data), mode="r:gz") as tf:
        pkg = json.loads(tf.extractfile("package/package.json").read())
    closure: dict[str, str] = {}
    pending = dict(pkg.get("dependencies") or {})
    for name, spec in pending.items():
        closure[name] = resolve(name, spec)
    for name, ver in list(closure.items()):
        dep_doc = registry_doc(name)["versions"][ver]
        for sub, sub_spec in (dep_doc.get("dependencies") or {}).items():
            if sub not in closure:
                closure[sub] = resolve(sub, sub_spec)
    print("  closure:", closure)

    # Assemble: official tarball + embedded node_modules + bundleDependencies.
    with tarfile.open(fileobj=io.BytesIO(main_data), mode="r:gz") as tf:
        entries: dict[str, tuple[tarfile.TarInfo, bytes]] = {
            m.name: (m, tf.extractfile(m).read()) for m in tf.getmembers()
            if m.isfile()
        }
    for name, ver in closure.items():
        print(f"  embedding {name}@{ver} ...")
        dep_tgz = fetch(f"https://registry.npmjs.org/{name}/-/{name}-{ver}.tgz")
        with tarfile.open(fileobj=io.BytesIO(dep_tgz), mode="r:gz") as tf:
            for m in tf.getmembers():
                if not m.isfile() or not m.name.startswith("package/"):
                    continue
                target = f"package/node_modules/{name}/" + m.name[len("package/"):]
                entries[target] = (m, tf.extractfile(m).read())
    pkg["bundleDependencies"] = sorted(closure)
    pkg_bytes = json.dumps(pkg, ensure_ascii=False, indent=2).encode("utf-8")
    pkg_info = tarfile.TarInfo("package/package.json")
    pkg_info.size = len(pkg_bytes)
    pkg_info.mtime = int(os.environ.get("SOURCE_DATE_EPOCH", 0)) or 1700000000
    pkg_info.mode = 0o644
    entries["package/package.json"] = (pkg_info, pkg_bytes)

    with tarfile.open(out_path, "w:gz") as out:
        for target, (info, data) in entries.items():
            info.name = target
            info.mtime = pkg_info.mtime
            out.addfile(info, io.BytesIO(data))
    print(f"written: {out_path} ({os.path.getsize(out_path) / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
