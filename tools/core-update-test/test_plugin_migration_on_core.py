"""Integration test: retired dsh-web plugins and the replacement on a real core.

Runs the *dev instance's* core (``--app-dir``, e.g. ``dist\\DeepSeek Harness``)
against a throwaway instance home and verifies the 1.0.5 plugin migration end
to end:

1. an updated install's config (a pre-1.0.5 ``store/dshmarket-<old>.tgz`` spec) is
   repointed at the bundled tarball;
2. a profile that still carries the retired dsh-web packages is migrated —
   manifest first, then a real ``dsh plugin --profile web remove`` prune —
   and the launcher's own plugin path can still install the author's
   replacement afterwards;
3. the core boots and serves the Web UI both before and after, and the log of
   the post-migration boot names none of the retired packages.

Everything is written under ``--work-dir`` (the core, node and pnpm come from
the dev instance / repo runtime), so the dev instance's own ``data\\`` is
never touched.

Usage::

    python tools/core-update-test/test_plugin_migration_on_core.py \
        --app-dir "dist/DeepSeek Harness"
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "app"))

import core_api  # noqa: E402
import homes  # noqa: E402
import migrate  # noqa: E402
import plugins  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []
REPLACEMENT = f"{migrate.NEW_AGGREGATE}@0.3.23"
OLD_AGGREGATE_NAME = "@linxin666/dsh-web-ui-all"
OLD_AGGREGATE_VERSION = "0.3.6"
OLD_AGGREGATE = f"{OLD_AGGREGATE_NAME}@{OLD_AGGREGATE_VERSION}"
# Which retired packages the integration run actually installs. The deprecated
# aggregate is skipped on purpose: its 0.3.6 closure is ~225 packages (~10 MB,
# tens of minutes on a slow registry) and it is covered by the offline
# regression tests plus the registry evidence in docs. These three have no (or
# one tiny) dependency, so the profile state they build is realistic and fast.
RETIRED_INSTALLED = (
    "@linxin666/dsh-chat-recovery",
    "@linxin666/dsh-desktop-launcher",
    "@linxin666/dsh-perf",
)
ERROR_RE = re.compile(r"(?i)\b(error|failed|failure|exception|fatal|not found|-1)\b")
STORE_TGZ_RE = re.compile(r"^dshmarket-(?P<version>\d+(?:\.\d+)+)\.tgz$", re.IGNORECASE)


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""),
          flush=True)


def wait_idle(manager: plugins.PluginManager, timeout: float = 1800.0) -> dict:
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


def http_status(url: str, timeout: float = 25.0):
    """GET *url* with a cookie jar.

    dsh >= 0.1.6 answers the token URL with a 303 that sets the session
    cookie and then requires it; a plain urlopen sends no cookie and gets 401
    even though a browser (and the WebView) loads the UI fine.
    """
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        with opener.open(url, timeout=timeout) as resp:  # noqa: S310
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:  # noqa: BLE001 - the status string is the evidence
        return f"ERR {type(exc).__name__}: {exc}"


def _newest_pnpm_log(profile: str) -> str:
    """Tail of dsh's most recent pnpm diagnostics for a failed plugin op."""
    root = os.path.join(profile, ".plugin-manager", "logs")
    newest, stamp = "", -1.0
    try:
        for name in os.listdir(root):
            path = os.path.join(root, name, "pnpm.log")
            if os.path.isfile(path) and os.path.getmtime(path) > stamp:
                newest, stamp = path, os.path.getmtime(path)
    except OSError:
        return "(no pnpm diagnostics)"
    if not newest:
        return "(no pnpm diagnostics)"
    try:
        with open(newest, "r", encoding="utf-8", errors="replace") as fh:
            return f"--- {os.path.basename(os.path.dirname(newest))}\n" + fh.read()[-4000:]
    except OSError as exc:
        return f"(unreadable: {exc})"


def _reset_work_dir(work: str, keep_store: bool = True) -> None:
    """Clear the scratch instance, optionally keeping the pnpm content store."""
    for name in sorted(os.listdir(work)):
        path = os.path.join(work, name)
        if keep_store and name == "data":
            for entry in sorted(os.listdir(path)):
                if entry == "store":
                    continue
                child = os.path.join(path, entry)
                if os.path.isdir(child):
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    try:
                        os.remove(child)
                    except OSError:
                        pass
            continue
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass


def _old_store_tarball(dev_app: str, scratch_app: str, bundled_ver: str) -> str:
    """A pre-1.0.5 ``dshmarket-*.tgz`` for the "upgraded install" state.

    Prefers a tarball the already-installed dev instance still carries (the
    real upgrade leftover), falls back to fetching the retired 1.33.0 build
    from npm, and finally to any other bundled build that is not the current
    one. Returns the path inside the scratch instance, or "".
    """
    store_dir = os.path.join(scratch_app, "store")
    for src in (os.path.join(dev_app, "store"), os.path.join(REPO, ".tmp-old-store"),
                os.path.join(scratch_app, "store"),
                os.path.join(REPO, "app", "store")):
        if not os.path.isdir(src):
            continue
        for name in sorted(os.listdir(src)):
            match = STORE_TGZ_RE.match(name)
            if not match or match.group("version") == bundled_ver:
                continue
            dst = os.path.join(store_dir, name)
            if os.path.normcase(os.path.abspath(src)) != os.path.normcase(
                    os.path.abspath(store_dir)):
                shutil.copy2(os.path.join(src, name), dst)
            return dst
    dst = os.path.join(store_dir, "dshmarket-1.33.0.tgz")
    try:
        url = "https://registry.npmjs.org/dshmarket/-/dshmarket-1.33.0.tgz"
        print(f"    (fetching the retired store build from {url})", flush=True)
        with urllib.request.urlopen(url, timeout=180) as resp, open(dst, "wb") as fh:  # noqa: S310
            shutil.copyfileobj(resp, fh)
        return dst
    except Exception as exc:  # noqa: BLE001 - a missing tarball is reported upstream
        print(f"    (could not fetch the retired store build: {exc})", flush=True)
        return ""


def boot(app_dir: str, cfg) -> dict:
    """Start the core, read the token URL's status and the log, then stop."""
    core = core_api.CoreController(app_dir, cfg)
    ok, message = core.start()
    info = {"ok": ok, "message": message[:400], "url": core.web_url(),
            "tokenUrl": "token=" in core.web_url(),
            "status": "", "bareStatus": "", "log": "", "errors": []}
    if ok:
        info["status"] = http_status(core.web_url())
        port = int(cfg.get("port", 3080))
        info["bareStatus"] = http_status(f"http://127.0.0.1:{port}/")
    info["log"] = core.read_log(tail=400)
    info["errors"] = [line for line in info["log"].splitlines() if ERROR_RE.search(line)][-25:]
    core.stop()
    return info


def seed_old_profile(manager: plugins.PluginManager, old_store_tgz: str) -> str:
    """Build a pre-1.0.5 web profile the way an install really would.

    The profile is created by the dsh CLI itself (which writes the core's own
    bundles — ``@deepseek-ai/dsh-base`` / ``-web-app`` — into
    ``dsh.profile.bundles``); hand-writing the manifest would drop those and
    make the core fail to boot for unrelated reasons. The old store tarball is
    installed first, then the retired packages.
    """
    okay, _ = manager.install(old_store_tgz)
    if not okay:
        raise RuntimeError("could not install the old store tarball")
    state = wait_idle(manager)
    if state.get("error"):
        raise RuntimeError(f"old store install failed: {json.dumps(state)[:300]}")
    ok, _ = manager.install_many(list(RETIRED_INSTALLED))
    if not ok:
        raise RuntimeError("could not install the retired plugins")
    state = wait_idle(manager)
    if state.get("error"):
        raise RuntimeError(f"retired plugin install failed: {json.dumps(state)[:300]}")
    profile = manager.profile_dir
    with open(os.path.join(profile, "package.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    missing = [name for name in RETIRED_INSTALLED
               if name not in (manifest.get("dependencies") or {})]
    if missing:
        raise RuntimeError(f"the installed profile does not record {missing}")
    return profile


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-dir", required=True,
                    help="dev instance whose core is exercised")
    ap.add_argument("--work-dir", default=os.path.join(REPO, ".tmp-plugin-migration"))
    ap.add_argument("--keep", action="store_true", help="keep the scratch instance")
    ap.add_argument("--fresh-store", action="store_true",
                    help="also drop the cached pnpm store (forces a full download)")
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    dev_app = os.path.abspath(args.app_dir)
    work = os.path.abspath(args.work_dir)
    app_dir = os.path.join(work, "app")
    dev_core = os.path.join(dev_app, "core")
    replacement = None

    print(json.dumps({"devApp": dev_app, "work": work, "replacement": REPLACEMENT},
                     ensure_ascii=False, indent=2), flush=True)

    check("the dev instance core is present",
          os.path.isfile(os.path.join(dev_core, "apps", "cli", "lib", "bin.js")),
          dev_core)

    if os.path.isdir(work):
        # Keep the pnpm content cache (data\store, hundreds of MB) so a rerun
        # is minutes instead of tens of minutes on a slow registry; everything
        # else — the scratch app dir and the harness home — is rebuilt.
        _reset_work_dir(work, keep_store=not args.fresh_store)
    os.makedirs(os.path.join(app_dir, "store"), exist_ok=True)

    # ---- scratch instance: the dev core, a bundled node/pnpm, scratch data
    runtime = os.path.join(REPO, "runtime")
    bundled_tgz, bundled_ver = migrate.bundled_store(os.path.join(REPO, "app"))
    check("the new build ships a dshmarket tarball", bool(bundled_tgz), bundled_ver)
    if bundled_tgz:
        shutil.copy2(bundled_tgz, os.path.join(app_dir, "store",
                                               os.path.basename(bundled_tgz)))
    # The upgrade state needs a *pre-1.0.5* store tarball: take the one the
    # already-installed dev instance still carries, else fetch it from npm.
    old_store = _old_store_tarball(dev_app, app_dir, bundled_ver)
    check("a pre-1.0.5 store tarball is available for the upgrade state",
          bool(old_store), old_store or "not found")
    if not old_store:
        return 2
    old_spec = "store/" + os.path.basename(old_store)

    cfg_path = os.path.join(app_dir, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump({
            "core_dir": dev_core,          # absolute: the dev instance's core
            "runtime_dir": runtime,        # absolute: the repo's node + pnpm
            "data_dir": os.path.join(work, "data"),
            "app_version": settings.VERSION,
            "store_sources": [{
                "name": "dshmarket", "label": "dshmarket 插件商店",
                "spec": old_spec,
                "homepage": "https://github.com/dsh-market/dsh-market",
                "catalog": "https://awesome-dsh-plugin.com/plugins.json",
                "builtin": True,
            }],
        }, fh, ensure_ascii=False, indent=2)

    cfg = settings.Settings(cfg_path)
    data, home = homes.apply_home_env(app_dir, cfg)
    core = core_api.CoreController(app_dir, cfg)
    print(json.dumps({"coreVersion": core.status()["coreVersion"], "entry": core.entry_rel,
                      "dshHome": home, "node": core.node_exe}, ensure_ascii=False),
          flush=True)
    check("the dev instance core resolves from the scratch instance",
          os.path.normcase(os.path.abspath(core.core_dir)) == os.path.normcase(dev_core),
          core.core_dir)
    check("a node runtime is available for pnpm", os.path.isfile(core.node_exe),
          core.node_exe)

    # ---- 1. the store heal repoints the stale config spec
    changed = store.heal_store_sources(cfg, app_dir)
    spec = cfg.get("store_sources")[0]["spec"].replace("\\", "/")
    expected_spec = "store/" + os.path.basename(bundled_tgz)
    check("the stale store spec is repointed at the bundled tarball",
          spec == expected_spec and changed, f"{spec} (expected {expected_spec})")
    check("the store config was persisted",
          json.load(open(cfg_path, encoding="utf-8"))["store_sources"][0]["spec"]
          .replace("\\", "/") == expected_spec)

    # ---- 2. the pre-1.0.5 profile state
    # The profile-store heal is a different code path (tested elsewhere); mark
    # it done so the plugin manager never waits on it here.
    heal_done = threading.Event()
    heal_done.set()
    manager = plugins.PluginManager(app_dir, cfg, core, heal_done=heal_done)
    old_tgz = os.path.join(app_dir, "store", os.path.basename(old_store))
    try:
        profile = seed_old_profile(manager, old_tgz)
    except RuntimeError as exc:
        check("the pre-1.0.5 profile could be built", False, str(exc))
        return 1
    check("the pre-1.0.5 profile could be built", True, profile)
    with open(os.path.join(profile, "package.json"), encoding="utf-8") as fh:
        seeded = json.load(fh)
    core_bundles = {"@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app"}
    check("the profile carries the core's own bundles",
          core_bundles <= set(seeded["dsh"]["profile"]["bundles"]),
          json.dumps(seeded["dsh"]["profile"]["bundles"]))
    before = {p.get("name") for p in manager.list().get("plugins", [])}
    check("the retired packages are visible to the plugin list before migration",
          set(RETIRED_INSTALLED) <= before,
          f"missing {sorted(set(RETIRED_INSTALLED) - before)}")
    materialized = [name for name in RETIRED_INSTALLED
                    if os.path.isdir(os.path.join(profile, "node_modules",
                                                  *name.split("/")))]
    check("the retired packages are materialized in node_modules",
          len(materialized) == len(RETIRED_INSTALLED),
          f"{len(materialized)}/{len(RETIRED_INSTALLED)}: {materialized}")
    old_boot = boot(app_dir, cfg)
    print(f"    pre-migration boot: ok={old_boot['ok']} status={old_boot['status']} "
          f"bare={old_boot['bareStatus']}", flush=True)
    if not old_boot["ok"]:
        print("    pre-migration boot log:\n      "
              + "\n      ".join(old_boot["log"].splitlines()[-20:]), flush=True)
    # The pre-migration boot is *measured*, not asserted: the retired set may
    # fail to boot (the incompatibility users reported) or start while logging
    # plugin errors. Either outcome motivates the removal; the post-migration
    # boot below is the one that must be clean.
    check("pre-migration boot measured", True,
          f"ok={old_boot['ok']} status={old_boot['status']} bare={old_boot['bareStatus']}")

    # ---- 3. the migration itself, against the real core CLI
    res = migrate.migrate_profile(app_dir, core.node_exe, core.bin_js, home)
    print(f"    migration: {json.dumps(res, ensure_ascii=False)[:500]}", flush=True)
    check("the migration reports success", res["ok"], json.dumps(res)[:200])
    check("every retired package was recorded for removal",
          set(res["removed"]) == set(RETIRED_INSTALLED),
          json.dumps(res["removed"]))
    check("the store dependency was repointed at the bundled tarball",
          bool(res["storeFrom"]), json.dumps(res)[:250])
    check("the real dsh CLI pruned the retired packages", res["pruned"],
          json.dumps(res)[:250])
    if not res["pruned"]:
        # dsh points at its pnpm diagnostics file; surface the reason so a
        # failure here is diagnosable instead of just "pnpm failed".
        print("    prune diagnostics:\n      " + "\n      ".join(
            _newest_pnpm_log(profile).splitlines()[-20:]), flush=True)
    check("upstream's migration target is reported when the deprecated package is run",
          bool(res["migrateTo"]) if OLD_AGGREGATE_NAME in RETIRED_INSTALLED
          else res["migrateTo"] == [],
          json.dumps(res["migrateTo"]))
    with open(os.path.join(profile, "package.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    check("the retired packages are gone from the manifest",
          not (set(manifest.get("dependencies", {})) & set(migrate.OBSOLETE_PLUGINS)),
          json.dumps(manifest.get("dependencies", {}))[:200])
    check("the retired packages are gone from the bundle list",
          not (set(manifest["dsh"]["profile"]["bundles"])
               & set(migrate.OBSOLETE_PLUGINS)),
          json.dumps(manifest["dsh"]["profile"]["bundles"])[:200])
    check("the core's own bundles survive the migration",
          core_bundles <= set(manifest["dsh"]["profile"]["bundles"]),
          json.dumps(manifest["dsh"]["profile"]["bundles"]))
    check("dshmarket now points at the bundled tarball",
          bundled_ver in str(manifest.get("dependencies", {}).get("dshmarket")),
          str(manifest.get("dependencies", {}).get("dshmarket")))
    left = [name for name in RETIRED_INSTALLED
            if os.path.isdir(os.path.join(profile, "node_modules", *name.split("/")))]
    check("the retired packages were pruned from node_modules", not left,
          json.dumps(left))
    after = {p.get("name") for p in manager.list().get("plugins", [])}
    check("the plugin list no longer shows the retired packages",
          not (set(RETIRED_INSTALLED) & after), ", ".join(sorted(after)))
    again = migrate.migrate_profile(app_dir, core.node_exe, core.bin_js, home)
    check("running the migration again is a no-op",
          again["skipped"] == "up-to-date" and not again["removed"], json.dumps(again)[:200])

    # ---- 4. the replacement works on the same core
    ok, message = manager.install(REPLACEMENT)
    check("the launcher accepts the replacement spec", ok, message[:200])
    state = wait_idle(manager)
    check("the replacement installs without error", not state.get("error"),
          json.dumps(state, ensure_ascii=False)[:400])
    installed = {p.get("name") for p in manager.list().get("plugins", [])}
    check("the replacement is installed", migrate.NEW_AGGREGATE in installed,
          ", ".join(sorted(installed)))
    new_boot = boot(app_dir, cfg)
    print(f"    post-migration boot: ok={new_boot['ok']} status={new_boot['status']}", flush=True)
    check("the core still boots after the migration", new_boot["ok"], new_boot["message"])
    check("the core still serves the Web UI", new_boot["status"] == 200,
          f"{new_boot['status']} {new_boot['url']}")
    named = [line for line in new_boot["log"].splitlines()
             if any(name.split("/")[-1] in line for name in migrate.OBSOLETE_PLUGINS)]
    check("no retired package appears in the post-migration core log", not named,
          " | ".join(named[:3])[:300])
    replacement_errors = [line for line in new_boot["errors"]
                          if "dsh-web-all" in line or "web-all" in line]
    check("the replacement loads without an error line", not replacement_errors,
          " | ".join(replacement_errors[:3])[:300])
    check("the replacement is not removed by a later migration",
          migrate.migrate_profile(app_dir, core.node_exe, core.bin_js, home)["skipped"]
          == "up-to-date")

    report = {
        "devApp": dev_app, "coreVersion": core.status()["coreVersion"],
        "dshHome": home, "replacement": REPLACEMENT, "oldAggregate": OLD_AGGREGATE,
        "migration": res, "preBoot": old_boot, "postBoot": new_boot,
        "results": RESULTS,
    }
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    if not args.keep:
        _reset_work_dir(work, keep_store=True)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print("\n" + "=" * 62)
    print(f"plugin migration on core {core.status()['coreVersion']}: "
          f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
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
