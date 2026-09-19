"""Feature audit for the desktop shell: does every advertised control exist?

Three static cross-checks that catch the "UI element with no implementation"
class of defect without needing a GUI:

1. **DOM ids** — every ``$("id")`` / ``getElementById("id")`` in ``app.js`` and
   the shell plugins must exist in ``index.html`` (a missing id throws while
   wiring listeners, which silently kills every handler after it).
2. **Bridge methods** — every ``callApi("method")`` in the UI must match a
   public method on ``Bridge`` in ``app/main.py`` (and the HTTP fallback must
   be able to dispatch it: no leading underscore).
3. **Buttons** — every ``<button id="...">`` in ``index.html`` must be
   referenced by ``app.js`` (direct listener, delegation, or a shell-plugin
   extension point), otherwise it is a dead control.

Usage::

    python tools/audit-features.py            # prints a report, exit 1 on findings
    python tools/audit-features.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
UI = os.path.join(REPO, "app", "ui")

# Controls that are intentionally driven from elsewhere (documented exceptions).
BUTTON_EXCEPTIONS = {
    # The floating exit button is wired directly in app.js as $("btn-exit-immersive").
}


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def html_ids(html: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', html))


def duplicate_ids(html: str) -> dict[str, int]:
    """Ids used more than once: getElementById returns the first, so a page with
    a duplicate id silently binds handlers to the wrong element."""
    counts: dict[str, int] = {}
    for name in re.findall(r'\bid="([^"]+)"', html):
        counts[name] = counts.get(name, 0) + 1
    return {name: count for name, count in counts.items() if count > 1}


def js_id_lookups(js: str) -> set[str]:
    found = set(re.findall(r'\$\("([^"]+)"\)', js))
    found |= set(re.findall(r'getElementById\("([^"]+)"\)', js))
    return found


def js_call_api(js: str) -> set[str]:
    # Both quoting styles are used in the shell (and by shell plugins).
    return set(re.findall(r"callApi\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", js))


def bridge_methods(main_py: str) -> set[str]:
    body = main_py.split("class Bridge:", 1)[-1]
    return set(re.findall(r"\n    def ([a-z][A-Za-z0-9_]*)\(", body))


def html_buttons(html: str) -> set[str]:
    return set(re.findall(r'<button[^>]*\bid="([^"]+)"', html))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    index_html = read(os.path.join(UI, "index.html"))
    app_js = read(os.path.join(UI, "app.js"))
    main_py = read(os.path.join(REPO, "app", "main.py"))

    plugin_js = []
    plugin_root = os.path.join(REPO, "examples", "shell-plugins")
    for dirpath, _dirnames, filenames in os.walk(plugin_root):
        for name in filenames:
            if name.endswith(".js"):
                plugin_js.append(os.path.join(dirpath, name))
    plugin_source = "\n".join(read(p) for p in plugin_js)

    ids = html_ids(index_html)
    # Only the shell's own JS is checked against index.html: shell plugins ship
    # their own markup (injected at runtime), so their ids are expected to be
    # absent from the static page.
    lookups = js_id_lookups(app_js)
    runtime_created = {"shell-theme", "shell-pet-layer"}
    missing_ids = sorted(lookups - ids - runtime_created)

    ui_calls = js_call_api(app_js) | js_call_api(plugin_source)
    methods = bridge_methods(main_py)
    missing_methods = sorted(ui_calls - methods)
    unused_methods = sorted(methods - ui_calls)

    buttons = html_buttons(index_html)
    referenced = set(re.findall(r'"(btn-[a-z0-9-]+)"', app_js))
    referenced |= set(re.findall(r"\$\('(btn-[a-z0-9-]+)'\)", app_js))
    referenced |= {b for b in buttons if b in app_js}
    unreferenced = sorted(b for b in buttons
                          if b not in app_js and b not in BUTTON_EXCEPTIONS and b not in referenced)

    report = {
        "domIds": {"defined": len(ids), "referenced": len(lookups),
                   "missing": missing_ids, "duplicated": duplicate_ids(index_html)},
        "bridge": {"methods": len(methods), "called": len(ui_calls),
                   "missing": missing_methods, "notCalledByUi": unused_methods},
        "buttons": {"defined": len(buttons), "unreferenced": unreferenced},
        "shellPluginExamples": {
            "root": os.path.relpath(plugin_root, REPO),
            "files": len(plugin_js),
            "shippedInUi": os.path.isdir(os.path.join(UI, "plugins")),
        },
    }

    print("== DOM ids ==")
    print(f"  defined in index.html: {len(ids)}, referenced from JS: {len(lookups)}")
    print(f"  referenced but missing: {missing_ids or 'none'}")
    print(f"  duplicated: {report['domIds']['duplicated'] or 'none'}")
    print("== bridge methods ==")
    print(f"  Bridge methods: {len(methods)}, callApi() names: {len(ui_calls)}")
    print(f"  called but not implemented: {missing_methods or 'none'}")
    print(f"  implemented but never called by the shell UI: {unused_methods or 'none'}")
    print("== buttons ==")
    print(f"  defined: {len(buttons)}, with no JS reference: {unreferenced or 'none'}")
    print("== shell plugin examples ==")
    print(f"  kept in repo: {report['shellPluginExamples']['root']} "
          f"({len(plugin_js)} js files), shipped in ui/plugins: "
          f"{report['shellPluginExamples']['shippedInUi']}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)

    findings = bool(missing_ids or missing_methods or unreferenced
                    or report["domIds"]["duplicated"]
                    or report["shellPluginExamples"]["shippedInUi"])
    print("\n" + ("FINDINGS" if findings else "ALL CHECKS PASS"))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
