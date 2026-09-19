"""Integration test: the launcher's plugin path against a real dsh core.

Runs the *launcher's own* plugin machinery (``plugins.PluginManager``, i.e. the
``dsh plugin --profile web …`` forwarder plus the profile-store heal) against a
real instance, so plugin install/list/remove is verified on whatever core is
installed — including a freshly upgraded or downgraded one.

The bundled dshmarket tarball is installed and then removed again, so the
instance ends in the state it started in.

Usage::

    python tools/core-update-test/test_plugin_on_core.py --app-dir "dist/DeepSeek Harness"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "app"))

import core_api  # noqa: E402
import homes  # noqa: E402
import plugins  # noqa: E402
import settings  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""),
          flush=True)


def wait_idle(manager: plugins.PluginManager, timeout: float = 900.0) -> dict:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        state = manager.status()
        message = str(state.get("message") or "")
        if str(state.get("phase")) == "idle":
            if message != last:
                print(f"    {message}", flush=True)
            return state
        if message != last:
            print(f"    [{state.get('phase')}] {message}", flush=True)
            last = message
        time.sleep(2)
    return manager.status()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-dir", required=True)
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    app_dir = os.path.abspath(args.app_dir)
    cfg = settings.Settings(os.path.join(app_dir, "config.json"))
    data, home = homes.apply_home_env(app_dir, cfg)
    core = core_api.CoreController(app_dir, cfg)
    heal_done = threading.Event()
    manager = plugins.PluginManager(app_dir, cfg, core, heal_done=heal_done)

    print(json.dumps({"appDir": app_dir, "coreVersion": core.status()["coreVersion"],
                      "entry": core.entry_rel, "dshHome": home},
                     ensure_ascii=False, indent=2), flush=True)

    # The launcher heals the profile store in the background at boot; do it
    # synchronously here so the first plugin op has a consistent store.
    heal = homes.heal_profile_store(home, data, core.node_exe)
    print(f"store heal: {json.dumps(heal, ensure_ascii=False)}", flush=True)
    heal_done.set()

    before = manager.list()
    installed_before = {p.get("name") for p in before.get("plugins", [])}
    check("plugin list works on this core", isinstance(before.get("plugins"), list),
          f"{len(installed_before)} installed")

    tarball = os.path.join(app_dir, "store", "dshmarket-1.33.0.tgz")
    if not os.path.isfile(tarball):
        check("bundled dshmarket tarball present", False, tarball)
        return 2
    check("bundled dshmarket tarball present", True, os.path.basename(tarball))

    already = "dshmarket" in installed_before or "@dsh-market/dshmarket" in installed_before
    if not already:
        ok, message = manager.install(tarball)
        check("install accepted", ok, message[:200])
        state = wait_idle(manager)
        check("install finished without error",
              not state.get("error"), json.dumps(state, ensure_ascii=False)[:300])
    else:
        check("dshmarket already installed; skipping install", True)

    after = manager.list()
    names = {p.get("name") for p in after.get("plugins", [])}
    check("dshmarket visible in the plugin list", bool(names - installed_before) or already,
          ", ".join(sorted(names)))

    if not already:
        ok, message = manager.remove("dshmarket")
        check("remove accepted", ok, message[:200])
        state = wait_idle(manager)
        check("remove finished without error", not state.get("error"),
              json.dumps(state, ensure_ascii=False)[:300])
        final = {p.get("name") for p in manager.list().get("plugins", [])}
        check("plugin list back to the starting state", final == installed_before,
              f"{sorted(final)} vs {sorted(installed_before)}")

    failed = [name for name, ok, _ in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"plugin path on {core.status()['coreVersion']}: "
          f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump({"appDir": app_dir, "coreVersion": core.status()["coreVersion"],
                       "results": RESULTS}, fh, ensure_ascii=False, indent=2)
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        sys.exit(70)
