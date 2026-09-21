"""Normalize the encoding of the shipped Windows scripts.

Windows PowerShell 5.1 (and cmd.exe) do not read BOM-less UTF-8 as UTF-8: a
PS1 without a BOM containing Chinese is decoded in the console code page and
fails to parse, and a UTF-8 byte written into an ANSI batch file loses the line
boundary for cmd.exe. Run this after editing any shipped script:

    python scripts\\fix-script-encodings.py [--check]

* ``*.ps1``           -> UTF-8 **with BOM**, CRLF
* ``*.bat`` (post-*)  -> console code page (GBK) without BOM, CRLF

``--check`` reports instead of writing (exit 1 when something needs fixing).
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def shipped_ps1() -> list[str]:
    """Every shipped PowerShell script (root + scripts), discovered, not listed."""
    found = [n for n in os.listdir(ROOT) if n.lower().endswith(".ps1")]
    scripts = os.path.join(ROOT, "scripts")
    found += [os.path.join("scripts", n) for n in os.listdir(scripts)
              if n.lower().endswith(".ps1")]
    return sorted(found)


def shipped_bat() -> list[str]:
    """Every shipped batch file: the post-*.bat payload plus scripts/*.bat."""
    found = [n for n in os.listdir(ROOT)
             if n.lower().endswith(".bat") and n.lower().startswith("post-")]
    scripts = os.path.join(ROOT, "scripts")
    found += [os.path.join("scripts", n) for n in os.listdir(scripts)
              if n.lower().endswith(".bat")]
    return sorted(found)


def crlf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def normalize_ps1(path: str, check: bool) -> str:
    raw = open(path, "rb").read()
    has_non_ascii = any(b > 127 for b in raw)
    text = raw.decode("utf-8-sig")
    data = crlf(text).encode("utf-8")
    if has_non_ascii:
        data = b"\xef\xbb\xbf" + data
    if data == raw:
        return "ok"
    if check:
        return "needs BOM/CRLF normalization"
    open(path, "wb").write(data)
    return "normalized (UTF-8 BOM + CRLF)" if has_non_ascii else "normalized (CRLF)"


def normalize_bat(path: str, check: bool) -> str:
    raw = open(path, "rb").read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SystemExit(f"{path}: has a UTF-8 BOM; cmd.exe would read it as garbage")
    try:
        text = raw.decode("mbcs")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    if "\ufffd" in text:
        raise SystemExit(f"{path}: contains replacement characters (broken encoding)")
    data = crlf(text).encode("mbcs")
    if data == raw:
        return "ok"
    if check:
        return "needs ANSI/CRLF normalization"
    open(path, "wb").write(data)
    return "normalized (console code page + CRLF)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    problems = 0
    for rel in shipped_ps1():
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        state = normalize_ps1(path, args.check)
        print(f"{rel:38s} {state}")
        problems += 1 if state != "ok" else 0
    for rel in shipped_bat():
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        state = normalize_bat(path, args.check)
        print(f"{rel:38s} {state}")
        problems += 1 if state != "ok" else 0
    if args.check and problems:
        print(f"\n{problems} file(s) need normalization: run without --check")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
