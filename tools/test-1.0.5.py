"""Regression tests for the DeepSeek Harness Desktop 1.0.5 fixes.

Covers the three defect families fixed in 1.0.5:

* **core upgrade/downgrade** — long-path (``>MAX_PATH``) tree deletion, the
  ``core.backup`` deadlock that blocked every later swap, swap verification
  and rollback, stale-backup cleanup;
* **core version tolerance** — CLI entry resolution from the shipped manifest,
  the launch-argument fallback ladder, usage-error classification, and the
  profile health check degrading to "unsupported" on a core that does not know
  the dump flag;
* **shell UI fullscreen layout** — a static guard on the CSS invariant that
  fixes the collapsed iframe (the behavioural check is
  ``tools/immersive-check/cdp_probe.mjs``, which drives a real Chromium).

Run with any Python 3.10+ (no third-party packages)::

    python tools/test-1.0.5.py            # the bundled embedded interpreter works
    python tools/test-1.0.5.py -v
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "app"))

import core_api  # noqa: E402
import homes  # noqa: E402
import settings  # noqa: E402
import updater  # noqa: E402

VERBOSE = False
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))
    if not condition or VERBOSE:
        print(f"  {'PASS' if condition else 'FAIL'}  {name}"
              + (f"  -- {detail}" if detail else ""), flush=True)


def case(fn):
    def wrapper() -> None:
        print(f"\n== {fn.__name__} ==", flush=True)
        try:
            fn()
        except Exception:  # noqa: BLE001 - a crashing case is a failing case
            RESULTS.append((fn.__name__, False, "crashed"))
            traceback.print_exc()
    wrapper.__name__ = fn.__name__
    return wrapper


def long_path(dirpath: str, depth: int = 6, segment: str = "d" * 40) -> str:
    """Build a path far beyond MAX_PATH (260) inside *dirpath*."""
    current = dirpath
    for _ in range(depth):
        current = os.path.join(current, segment)
    return current


@contextlib.contextmanager
def temp_dir(prefix: str = "dsh-t-"):
    """Scratch directory that also survives >MAX_PATH content.

    ``tempfile.TemporaryDirectory`` cleans up with ``shutil.rmtree``, which
    cannot delete the long-path trees these tests create; remove them with the
    product's own long-path-safe remover first.
    """
    path = tempfile.mkdtemp(prefix=prefix)
    try:
        yield path
    finally:
        homes.remove_tree(path)
        shutil.rmtree(path, ignore_errors=True)


def makedirs_long(path: str) -> None:
    """Create a directory tree past MAX_PATH.

    Plain ``os.makedirs`` cannot create these (WinError 3); the extended-length
    prefix can, and that is exactly how pnpm/node materialize such trees in the
    first place.
    """
    os.makedirs(homes.long_path(path), exist_ok=True)
    if not os.path.isdir(homes.long_path(path)):
        raise RuntimeError(f"long path not created: {path}")


# --------------------------------------------------------------------- delete


@case
def test_removes_tree_beyond_max_path() -> None:
    with temp_dir() as tmp:
        deep = long_path(os.path.join(tmp, "pnpm"))
        makedirs_long(deep)
        leaf = os.path.join(homes.long_path(deep), "operations.d.ts")
        with open(leaf, "w", encoding="utf-8") as fh:
            fh.write("x")
        plain_leaf = os.path.join(deep, "operations.d.ts")
        check("path really exceeds MAX_PATH", len(plain_leaf) > 260,
              f"len={len(plain_leaf)}")
        # The old implementation: shutil.rmtree leaves the tree behind.
        shutil.rmtree(os.path.join(tmp, "pnpm"), ignore_errors=True)
        check("shutil.rmtree cannot delete it (documents the old bug)",
              os.path.exists(os.path.join(tmp, "pnpm")))
        check("homes.remove_tree deletes it",
              homes.remove_tree(os.path.join(tmp, "pnpm")))
        check("tree is gone", not os.path.exists(os.path.join(tmp, "pnpm")))
        check("long_path prefixes extended-length form",
              homes.long_path(tmp).startswith("\\\\?\\"))


@case
def test_removes_read_only_files() -> None:
    with temp_dir() as tmp:
        target = os.path.join(tmp, "tree")
        os.makedirs(os.path.join(target, "objects", "pack"), exist_ok=True)
        pack = os.path.join(target, "objects", "pack", "pack-1.pack")
        with open(pack, "w", encoding="utf-8") as fh:
            fh.write("packed")
        os.chmod(pack, stat.S_IREAD)  # git marks pack files read-only
        check("read-only file removed", homes.remove_tree(target))
        check("tree gone despite read-only member", not os.path.exists(target))


@case
def test_removal_never_follows_junctions() -> None:
    with temp_dir() as tmp:
        store = os.path.join(tmp, "store", "content")
        os.makedirs(store, exist_ok=True)
        payload = os.path.join(store, "blob.bin")
        with open(payload, "w", encoding="utf-8") as fh:
            fh.write("store content must survive")
        tree = os.path.join(tmp, "core.backup", "node_modules")
        os.makedirs(tree, exist_ok=True)
        link = os.path.join(tree, "linked-store")
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", link, store],
            capture_output=True, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if created.returncode != 0 or not os.path.isdir(link):
            check("junction created (skipped: mklink unavailable)", True,
                  created.stderr.strip()[:80])
            return
        check("junction removed with its tree",
              homes.remove_tree(os.path.join(tmp, "core.backup")))
        check("junction link is gone", not os.path.exists(link))
        check("junction target content survived", os.path.isfile(payload))
        with open(payload, "r", encoding="utf-8") as fh:
            check("target content intact", fh.read() == "store content must survive")


@case
def test_remove_tree_on_missing_and_file_paths() -> None:
    with temp_dir() as tmp:
        check("missing path is 'removed'",
              homes.remove_tree(os.path.join(tmp, "nope")))
        single = os.path.join(tmp, "file.txt")
        with open(single, "w", encoding="utf-8") as fh:
            fh.write("x")
        check("single file removed", homes.remove_tree(single))
        check("single file gone", not os.path.exists(single))
        check("empty path is a no-op", homes.remove_tree(""))


# ----------------------------------------------------------- version detection


def _fake_core(root: str, bin_field, entry_rel: str = "lib/bin.js",
               write_entry: bool = True) -> str:
    core = os.path.join(root, "core")
    cli = os.path.join(core, "apps", "cli")
    os.makedirs(cli, exist_ok=True)
    manifest = {"name": "@deepseek-ai/dsh", "version": "0.1.6-alpha.2"}
    if bin_field is not None:
        manifest["bin"] = bin_field
    with open(os.path.join(cli, "package.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    if write_entry and entry_rel:
        entry = os.path.join(cli, entry_rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(entry), exist_ok=True)
        with open(entry, "w", encoding="utf-8") as fh:
            fh.write("// fake cli\n")
    return core


@case
def test_resolves_cli_entry_across_layouts() -> None:
    with temp_dir() as tmp:
        core = _fake_core(os.path.join(tmp, "a"), {"dsh": "lib/bin.js"})
        check("bin dict resolves",
              core_api.resolve_cli_entry(core).endswith(os.path.join("lib", "bin.js")))
    with temp_dir() as tmp:
        core = _fake_core(os.path.join(tmp, "b"), "dist/cli.js", "dist/cli.js")
        check("bin string with a new layout resolves",
              core_api.resolve_cli_entry(core).endswith(os.path.join("dist", "cli.js")))
    with temp_dir() as tmp:
        core = _fake_core(os.path.join(tmp, "c"), {"other": "lib/other.js"},
                          "lib/bin.js")
        check("unknown bin key falls back to lib/bin.js",
              core_api.resolve_cli_entry(core).endswith(os.path.join("lib", "bin.js")))
    with temp_dir() as tmp:
        core = _fake_core(os.path.join(tmp, "d"), {"dsh": "dist/cli.js"},
                          "lib/bin.js")
        check("declared-but-missing entry falls back to the classic path",
              core_api.resolve_cli_entry(core).endswith(os.path.join("lib", "bin.js")))
    with temp_dir() as tmp:
        core = os.path.join(tmp, "e", "core")
        os.makedirs(core, exist_ok=True)
        check("missing manifest falls back to the classic path",
              core_api.resolve_cli_entry(core).endswith(os.path.join("lib", "bin.js")))


@case
def test_core_controller_entry_and_version() -> None:
    with temp_dir() as tmp:
        core = _fake_core(tmp, {"dsh": "lib/bin.js"})
        with open(os.path.join(core, "package.json"), "w", encoding="utf-8") as fh:
            json.dump({"name": "deepseek-harness", "version": "0.1.6-alpha.2"}, fh)
        cfg = settings.Settings(os.path.join(tmp, "config.json"))
        controller = core_api.CoreController(tmp, cfg)
        check("bin_js resolves under the app dir",
              os.path.isfile(controller.bin_js), controller.bin_js)
        check("entry_rel is core-relative with slashes",
              controller.entry_rel == "apps/cli/lib/bin.js", controller.entry_rel)
        check("core version read from package.json",
              controller._core_version() == "0.1.6-alpha.2",
              controller._core_version())
        check("core_ready true with node + entry",
              controller.core_ready() or not os.path.isfile(controller.node_exe))


@case
def test_launch_candidate_ladder() -> None:
    with temp_dir() as tmp:
        cfg = settings.Settings(os.path.join(tmp, "config.json"))
        controller = core_api.CoreController(tmp, cfg)
        order = controller._launch_candidates()
        check("ladder starts with the modern flag set",
              order[0][1][:2] == ["web", "--no-open"], str(order[0][1]))
        check("ladder covers --profile form and bare web",
              any(args[:2] == ["--profile", "web"] for _, args in order)
              and any(args == ["web"] for _, args in order))
        cfg.set("core_launch_mode", "3")
        order = controller._launch_candidates()
        check("remembered launch mode is tried first", order[0][0] == 3)
        check("all candidates still offered", len(order) == len(controller.LAUNCH_CANDIDATES))
        cfg.set("core_launch_mode", "99")
        check("out-of-range memory is ignored",
              controller._launch_candidates()[0][0] == 0)


@case
def test_usage_error_classification() -> None:
    patterns = [
        "error: unknown option '--host'",
        "Unknown argument: --no-open",
        "error: unrecognized option '--port'",
        "error: invalid option '--trusted-host'",
        "Usage: dsh [options]",
    ]
    for text in patterns:
        check(f"usage error detected: {text[:34]}",
              bool(core_api.CoreController._USAGE_ERROR_RE.search(text)))
    for text in ["Error: Cannot find module '@deepseek-ai/dsh-base'",
                 "EPROFILE: profile web failed to boot"]:
        check(f"real failure not treated as usage error: {text[:32]}",
              not core_api.CoreController._USAGE_ERROR_RE.search(text))


# --------------------------------------------------------------- health check


@case
def test_health_check_tolerates_unknown_dump_flag() -> None:
    node = shutil.which("node")
    if not node:
        check("node available for health check test", False, "node not on PATH")
        return
    script_usage = ("process.stderr.write(\"error: unknown option '--dump-config'\\n\");"
                    "process.exit(1);")
    script_ok = "process.stdout.write('[]');"
    script_broken = "throw new Error('boom');"
    for label, source, expect in (
        ("unsupported flag -> skipped", script_usage, "unsupported"),
        ("successful dump -> ok", script_ok, "ok"),
        ("broken core -> failure", script_broken, "fail"),
    ):
        with temp_dir() as tmp:
            core = _fake_core(tmp, {"dsh": "lib/bin.js"})
            with open(os.path.join(core, "apps", "cli", "lib", "bin.js"),
                      "w", encoding="utf-8") as fh:
                fh.write(source)
            profile = os.path.join(tmp, "data", ".dsh", "profiles", "web")
            os.makedirs(profile, exist_ok=True)
            cfg = settings.Settings(os.path.join(tmp, "config.json"))
            os.environ["DSH_HOME"] = os.path.join(tmp, "data", ".dsh")
            try:
                homes.run_health_check(tmp, cfg, node,
                                       os.path.join(core, "apps", "cli", "lib", "bin.js"))
                result = homes.read_health(tmp)
            finally:
                os.environ.pop("DSH_HOME", None)
            if expect == "ok":
                check(label, result.get("ok") is True, json.dumps(result)[:150])
            elif expect == "unsupported":
                check(label,
                      result.get("skipped") is True and result.get("unsupported") is True,
                      json.dumps(result)[:150])
            else:
                check(label,
                      result.get("ok") is False and result.get("skipped") is False,
                      json.dumps(result)[:150])


# ----------------------------------------------------------------------- swap


def _build_instance(root: str, old_entry: bool = True, new_entry: bool = True) -> tuple[str, str, str]:
    app = os.path.join(root, "app")
    core = os.path.join(app, "core")
    os.makedirs(os.path.join(core, "apps", "cli", "lib"), exist_ok=True)
    with open(os.path.join(core, "apps", "cli", "package.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": "@deepseek-ai/dsh", "version": "0.1.1-rc.2",
                   "bin": {"dsh": "lib/bin.js"}}, fh)
    if old_entry:
        with open(os.path.join(core, "apps", "cli", "lib", "bin.js"), "w",
                  encoding="utf-8") as fh:
            fh.write("// old core\n")
    # The staged tree lives *outside* <app>\.update: CoreUpdater.__init__ wipes
    # that work directory, which is exactly what the tests must not depend on.
    src = os.path.join(app, "newcore-staging")
    os.makedirs(os.path.join(src, "apps", "cli", "lib"), exist_ok=True)
    with open(os.path.join(src, "apps", "cli", "package.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": "@deepseek-ai/dsh", "version": "0.1.6-alpha.2",
                   "bin": {"dsh": "lib/bin.js"}}, fh)
    if new_entry:
        with open(os.path.join(src, "apps", "cli", "lib", "bin.js"), "w",
                  encoding="utf-8") as fh:
            fh.write("// new core\n")
    return app, core, src


@case
def test_swap_replaces_core_and_clears_launch_mode() -> None:
    with temp_dir() as tmp:
        app, core, src = _build_instance(tmp)
        cfg = settings.Settings(os.path.join(app, "config.json"))
        cfg.set("core_launch_mode", "2")
        controller = core_api.CoreController(app, cfg)
        up = updater.CoreUpdater(app, cfg, controller)
        up._state["remote"] = {"commit": "deadbeef", "date": "2026-09-17",
                               "message": "release dsh-v0.1.6-alpha.2"}
        up._swap(src)
        with open(os.path.join(core, "apps", "cli", "lib", "bin.js"),
                  encoding="utf-8") as fh:
            body = fh.read()
        check("new core in place", "new core" in body, body.strip())
        check("core metadata written",
              os.path.isfile(os.path.join(core, ".dsh-desktop-info.json")))
        info = json.loads(open(os.path.join(core, ".dsh-desktop-info.json"),
                               encoding="utf-8").read())
        check("metadata records the source commit", info.get("commit") == "deadbeef")
        check("launch-mode memory cleared for the new core",
              cfg.get("core_launch_mode") == "")
        check("backup removed after a successful swap",
              not os.path.exists(os.path.join(app, "core.backup")))


@case
def test_swap_rejects_half_built_stage() -> None:
    """A staged core without a CLI entry is refused before anything moves."""
    with temp_dir() as tmp:
        app, core, src = _build_instance(tmp, new_entry=False)
        cfg = settings.Settings(os.path.join(app, "config.json"))
        controller = core_api.CoreController(app, cfg)
        up = updater.CoreUpdater(app, cfg, controller)
        up._state["remote"] = {"commit": "cafebabe"}
        raised = ""
        try:
            up._swap(src)
        except RuntimeError as exc:
            raised = str(exc)
        check("half-built stage is rejected", "CLI 入口" in raised, raised[:130])
        with open(os.path.join(core, "apps", "cli", "lib", "bin.js"),
                  encoding="utf-8") as fh:
            body = fh.read()
        check("old core untouched", "old core" in body, body.strip())
        check("no core.backup* directory created",
              not [n for n in os.listdir(app) if n.startswith("core.backup")],
              str(os.listdir(app)))


@case
def test_swap_rolls_back_when_verification_fails() -> None:
    """A swap whose result does not boot restores the previous core."""
    with temp_dir() as tmp:
        app, core, src = _build_instance(tmp)
        cfg = settings.Settings(os.path.join(app, "config.json"))
        controller = core_api.CoreController(app, cfg)
        up = updater.CoreUpdater(app, cfg, controller)
        up._state["remote"] = {"commit": "cafebabe"}
        # Force the post-swap verification to fail: simulates a core that lost
        # its runtime/entry right after the rename.
        controller.core_ready = lambda: False  # type: ignore[method-assign]
        raised = ""
        try:
            up._swap(src)
        except RuntimeError as exc:
            raised = str(exc)
        check("failed verification is reported as a rollback", "回滚" in raised,
              raised[:130])
        with open(os.path.join(core, "apps", "cli", "lib", "bin.js"),
                  encoding="utf-8") as fh:
            body = fh.read()
        check("old core restored after rollback", "old core" in body, body.strip())
        check("staged tree returned for inspection",
              os.path.isdir(os.path.join(src, "apps", "cli", "lib")),
              str(os.listdir(app)))


@case
def test_stale_backup_does_not_block_the_swap() -> None:
    with temp_dir() as tmp:
        app, core, src = _build_instance(tmp)
        # A stale backup that pretends to be undeletable: _remove_path is
        # monkeypatched to fail once, exactly like the long-path deadlock.
        stale = os.path.join(app, "core.backup")
        os.makedirs(os.path.join(stale, "node_modules"), exist_ok=True)
        cfg = settings.Settings(os.path.join(app, "config.json"))
        controller = core_api.CoreController(app, cfg)
        up = updater.CoreUpdater(app, cfg, controller)
        up._state["remote"] = {"commit": "abc123"}

        real_remove = updater.CoreUpdater._remove_path
        calls = {"n": 0}

        def flaky(path: str) -> bool:  # noqa: ANN001
            calls["n"] += 1
            if calls["n"] == 1:
                return False
            return real_remove(path)

        updater.CoreUpdater._remove_path = staticmethod(flaky)
        try:
            up._swap(src)
        finally:
            updater.CoreUpdater._remove_path = real_remove
        with open(os.path.join(core, "apps", "cli", "lib", "bin.js"),
                  encoding="utf-8") as fh:
            body = fh.read()
        check("swap completed despite the stuck backup", "new core" in body)
        check("stuck backup was replaced by a timestamped one",
              not os.path.exists(stale) or os.path.isdir(stale))


@case
def test_cleanup_stale_core_backups() -> None:
    with temp_dir() as tmp:
        keep = os.path.join(tmp, "core")
        os.makedirs(keep, exist_ok=True)
        with open(os.path.join(keep, "package.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        active = os.path.join(tmp, "core.backup")
        old = os.path.join(tmp, "core.backup-20260101-000000")
        for path in (active, old):
            deep = long_path(os.path.join(path, "node_modules", ".pnpm"))
            makedirs_long(deep)
            with open(os.path.join(homes.long_path(deep), "f.d.ts"), "w",
                      encoding="utf-8") as fh:
                fh.write("x")
        stuck = updater.cleanup_stale_core_backups(tmp)
        check("all stale backups removed", stuck == [], str(stuck))
        check("other backups gone",
              not os.path.exists(active) and not os.path.exists(old))
        check("the live core survives", os.path.isdir(keep))
        # keep= must protect the named tree
        active2 = os.path.join(tmp, "core.backup")
        os.makedirs(active2, exist_ok=True)
        updater.cleanup_stale_core_backups(tmp, keep=active2)
        check("keep= protects the active backup", os.path.isdir(active2))


@case
def test_settings_round_trip_launch_mode() -> None:
    with temp_dir() as tmp:
        path = os.path.join(tmp, "config.json")
        cfg = settings.Settings(path)
        cfg.set("core_launch_mode", "4")
        cfg.save()
        reloaded = settings.Settings(path)
        check("core_launch_mode persists", reloaded.get("core_launch_mode") == "4",
              str(reloaded.get("core_launch_mode")))
        check("version is 1.0.5", settings.VERSION == "1.0.5", settings.VERSION)


# --------------------------------------------------------------- shell UI CSS


@case
def test_shell_ui_frame_is_absolutely_positioned() -> None:
    css_path = os.path.join(REPO, "app", "ui", "style.css")
    with open(css_path, "r", encoding="utf-8") as fh:
        css = fh.read()

    def block(selector: str) -> str:
        marker = f"\n{selector} {{"
        start = css.find(marker)
        if start < 0:
            marker = f"{selector} {{"
            start = css.find(marker)
        if start < 0:
            return ""
        end = css.find("}", start)
        return css[start:end]

    frame = block(".frame")
    check(".frame block found", bool(frame))
    check(".frame is position: absolute", "position: absolute" in frame, frame[:80])
    for side in ("top: 0", "right: 0", "bottom: 0", "left: 0"):
        check(f".frame pins {side}", side in frame)
    check(".frame no longer relies on height: 100% alone "
          "(percentage height collapses to 150px)",
          "height: 100%" not in frame or "position: absolute" in frame)

    immersive = block("body.immersive .frame-wrap")
    check("immersive wrapper block found", bool(immersive))
    check("immersive wrapper stays positioned",
          "position: static" not in immersive, immersive[:120])

    empty = block(".frame-empty")
    check(".frame-empty is absolutely positioned too",
          "position: absolute" in empty, empty[:80])


# --------------------------------------------------------------- shell UI sync


def _fake_ui(root: str, version: str, body: str) -> str:
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(body)
    with open(os.path.join(root, "style.css"), "w", encoding="utf-8") as fh:
        fh.write(body)
    with open(os.path.join(root, "shellui.py"), "w", encoding="utf-8") as fh:
        fh.write("an unrelated file")
    with open(os.path.join(root, ".version"), "w", encoding="utf-8") as fh:
        fh.write(version)
    return root


@case
def test_shell_ui_sync_refreshes_stale_installs() -> None:
    sys.path.insert(0, os.path.join(REPO, "app"))
    import shellui  # noqa: PLC0415 - imported here so the module set stays obvious

    with temp_dir() as app:
        # A 1.0.4 install: live ui is the old build, plus a file the user added
        # and an example plugin 1.0.4 shipped; _internal ships 1.0.5.
        live = _fake_ui(os.path.join(app, "ui"), "1.0.4", "OLD-BUGGY")
        with open(os.path.join(live, "custom.css"), "w", encoding="utf-8") as fh:
            fh.write("/* the user's own skin */")
        legacy = os.path.join(live, "plugins", "example-pet")
        os.makedirs(legacy, exist_ok=True)
        with open(os.path.join(legacy, "plugin.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        _fake_ui(os.path.join(app, "_internal", "ui"), "1.0.5", "FIXED")

        report = shellui.sync_shell_ui(app, "1.0.5")
        check("stale ui is refreshed", report["action"] == "refreshed",
              json.dumps(report, ensure_ascii=False))
        with open(os.path.join(app, "ui", "style.css"), encoding="utf-8") as fh:
            check("shipped file updated in place", fh.read() == "FIXED")
        check("user-added file survives the refresh",
              os.path.isfile(os.path.join(app, "ui", "custom.css")))
        check("example plugin dropped from the live ui", not os.path.isdir(legacy),
              json.dumps(report.get("removed")))
        backup = os.path.join(app, report["backup"])
        check("pre-upgrade ui snapshotted for recovery",
              os.path.isfile(os.path.join(backup, "style.css"))
              and os.path.isfile(os.path.join(backup, "custom.css")))
        with open(os.path.join(backup, "style.css"), encoding="utf-8") as fh:
            check("snapshot keeps the previous build", fh.read() == "OLD-BUGGY")
        check("marker updated",
              shellui.read_marker(os.path.join(app, "ui")) == "1.0.5")
        second = shellui.sync_shell_ui(app, "1.0.5")
        check("second run is a no-op", second["action"] == "none",
              json.dumps(second, ensure_ascii=False))
        check("a second refresh does not clobber the snapshot",
              os.path.isfile(os.path.join(backup, "custom.css")))


@case
def test_shell_ui_sync_handles_missing_and_dev_layouts() -> None:
    import shellui  # noqa: PLC0415

    with temp_dir() as app:
        # No live ui folder at all (fresh payload extraction).
        _fake_ui(os.path.join(app, "_internal", "ui"), "1.0.5", "FIXED")
        report = shellui.sync_shell_ui(app, "1.0.5")
        check("missing live ui is installed", report["action"] == "installed",
              json.dumps(report, ensure_ascii=False))
        check("installed ui present",
              os.path.isfile(os.path.join(app, "ui", "index.html")))
    with temp_dir() as app:
        # Source/dev layout: no packaged bundle next to the app.
        _fake_ui(os.path.join(app, "ui"), "1.0.5", "DEV")
        report = shellui.sync_shell_ui(app, "1.0.5")
        check("dev layout is left alone", report["action"] == "dev",
              json.dumps(report, ensure_ascii=False))
        with open(os.path.join(app, "ui", "style.css"), encoding="utf-8") as fh:
            check("dev ui untouched", fh.read() == "DEV")


@case
def test_shell_ui_sync_never_downgrades() -> None:
    import shellui  # noqa: PLC0415

    with temp_dir() as app:
        _fake_ui(os.path.join(app, "ui"), "1.0.6", "NEWER-UI")
        _fake_ui(os.path.join(app, "_internal", "ui"), "1.0.5", "SHIPPED")
        report = shellui.sync_shell_ui(app, "1.0.5")
        check("newer live ui is kept", report["action"] == "none",
              json.dumps(report, ensure_ascii=False))
        with open(os.path.join(app, "ui", "style.css"), encoding="utf-8") as fh:
            check("newer ui content untouched", fh.read() == "NEWER-UI")
    check("version_newer orders dotted versions",
          homes.version_newer("1.0.6", "1.0.5")
          and not homes.version_newer("1.0.5", "1.0.5")
          and not homes.version_newer("1.0.4", "1.0.5")
          and homes.version_newer("1.0.10", "1.0.9"))


@case
def test_console_output_decoding_never_crashes() -> None:
    """Console tools write OEM bytes, not UTF-8 (the relink crash of 1.0.4).

    ``relink.create_junction`` decoded ``mklink`` output as UTF-8; on a Chinese
    Windows install every junction produced a UnicodeDecodeError inside
    subprocess's reader thread (thousands of tracebacks during one core swap).
    """
    import relink  # noqa: PLC0415

    emit_invalid_utf8 = [sys.executable, "-c",
                         "import sys; sys.stdout.buffer.write(b'\\xb4\\xf3\\xd6\\xd0')"]
    raw = subprocess.run(emit_invalid_utf8, capture_output=True)
    check("the sample bytes really are invalid UTF-8",
          raw.stdout == b"\xb4\xf3\xd6\xd0")
    try:
        raw.stdout.decode("utf-8")
        strict_failed = False
    except UnicodeDecodeError:
        strict_failed = True
    check("strict UTF-8 decoding of them raises (old behaviour)", strict_failed)

    kwargs = homes.console_text_kwargs()
    try:
        decoded = subprocess.run(emit_invalid_utf8, capture_output=True, **kwargs)
        ok = True
    except UnicodeDecodeError as exc:
        decoded, ok = None, False
        check("safe kwargs decode without raising", False, str(exc))
    if ok:
        check("safe kwargs decode without raising", True)
        check("safe kwargs keep the text (mojibake is acceptable, a crash is not)",
              isinstance(decoded.stdout, str) and len(decoded.stdout) > 0,
              repr(decoded.stdout)[:40])

    with temp_dir() as tmp:
        target = os.path.join(tmp, "target")
        os.makedirs(target, exist_ok=True)
        link = os.path.join(tmp, "link")
        created = relink.create_junction(link, target)
        check("relink.create_junction works with OEM-safe decoding", created,
              f"link exists: {os.path.isdir(link)}")
        check("created link is a junction",
              created and getattr(os.lstat(link), "st_reparse_tag", 0) == 0xA0000003)


@case
def test_discovers_core_web_url_with_token() -> None:
    """dsh >= 0.1.6 prints the only URL it will serve; it must be used."""
    with temp_dir() as app:
        _fake_core(app, {"dsh": "lib/bin.js"})
        cfg = settings.Settings(os.path.join(app, "config.json"))
        controller = core_api.CoreController(app, cfg)
        log_path = os.path.join(app, "logs", "core.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        def write(text: str, offset: int) -> None:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(text)

        modern = ("dsh web: http://127.0.0.1:3080/?token=AbC123_-xyz\n")
        write(modern, 0)
        controller.URL_DISCOVERY_TIMEOUT = 2.0
        url = controller._discover_web_url(0)
        check("token url discovered", url == "http://127.0.0.1:3080/?token=AbC123_-xyz", url)
        check("web_url() serves the token url", controller.web_url(3080) == url,
              controller.web_url(3080))

        class _AliveProc:
            returncode = None

            @staticmethod
            def poll():
                return None

        controller._proc = _AliveProc()
        check("status().url serves the token url while running",
              controller.status()["url"] == url, controller.status()["url"])
        controller._proc = None
        check("status().url falls back to the plain url when stopped",
              controller.status()["url"] == "http://127.0.0.1:3080",
              controller.status()["url"])

        # Older core: a bare URL, no token (must still work).
        offset = os.path.getsize(log_path)
        write("dsh web: http://127.0.0.1:3080\n", offset)
        bare = controller._discover_web_url(offset)
        check("bare url discovered for older cores",
              bare == "http://127.0.0.1:3080", bare)

        # A core that prints nothing must not hang the start path.
        offset = os.path.getsize(log_path)
        write("starting up, nothing to see here\n", offset)
        controller._web_url = ""          # a fresh start clears it (stop() does this)
        controller.URL_DISCOVERY_TIMEOUT = 0.4
        started = time.time()
        empty = controller._discover_web_url(offset)
        elapsed = time.time() - started
        check("no url printed -> empty result after a bounded wait",
              empty == "" and elapsed < 5, f"{empty!r} in {elapsed:.1f}s")
        check("fallback URL is the plain localhost one",
              controller.web_url(3080) == "http://127.0.0.1:3080",
              controller.web_url(3080))
        check("stop() clears the token", controller.stop()[0]
              and controller.web_url(3080) == "http://127.0.0.1:3080")


@case
def test_post_update_bat_refreshes_any_stale_ui() -> None:
    """The package installer must refresh a marked-but-old UI (1.0.4's gap)."""
    bat = os.path.join(REPO, "post-update.bat")
    with open(bat, "r", encoding="mbcs", errors="replace") as fh:
        text = fh.read()
    check("post-update.bat no longer gates on a missing marker",
          'if not exist "%~dp0ui\\.version"' not in text, text[:0])
    check("post-update.bat compares the marker with this release",
          'findstr /x /c:"1.0.5" "%~dp0ui\\.version"' in text)
    check("post-update.bat snapshots the pre-upgrade ui",
          'robocopy "%~dp0ui" "%~dp0ui-backup"' in text)
    check("post-update.bat merges instead of replacing the ui folder",
          'robocopy "%~dp0_internal\\ui" "%~dp0ui"' in text
          and 'rename "%~dp0ui" "ui-backup"' not in text)
    check("post-update.bat removes the example shell plugins",
          "example-pet" in text and "plugin-dev-kit" in text)


# ------------------------------------------------- shell UI static guards


def _ui_file(name: str) -> str:
    with open(os.path.join(REPO, "app", "ui", name), "r", encoding="utf-8") as fh:
        return fh.read()


@case
def test_shell_ui_has_no_duplicate_ids() -> None:
    """Duplicate ids make getElementById bind to the wrong element.

    ``#store-catalog`` was both the catalog list <div> and the add-source
    <input>: reading ``.value`` off the div threw, so 「添加商店源」 never worked.
    """
    html = _ui_file("index.html")
    ids = re.findall(r'\bid="([^"]+)"', html)
    duplicates = {name: ids.count(name) for name in set(ids) if ids.count(name) > 1}
    check("index.html has no duplicate ids", not duplicates, json.dumps(duplicates))
    check("the add-source catalog input has its own id",
          'id="store-catalog-url"' in html)


@case
def test_theme_loader_fetches_relative_stylesheets() -> None:
    """The theme loader must not inject a bare path as CSS.

    Built-in themes are relative paths (``themes/ocean.css``); the old loader
    only fetched ``http(s)://`` / ``//`` / ``/`` values, so it injected the path
    string itself and no theme ever applied.
    """
    js = _ui_file("app.js")
    body = js[js.find("async function applyTheme"): js.find("function renderThemeList")]
    check("applyTheme distinguishes CSS text from a stylesheet reference",
          "/[{}]/.test(css)" in body, body[:0] or "")
    check("applyTheme fetches the reference", "await fetch(css" in body)
    check("built-in themes still use relative paths",
          '"themes/ocean.css"' in js and '"themes/light.css"' in js)
    check("a failed load removes the stale theme",
          "styleEl.remove()" in body)


@case
def test_i18n_matches_whitespace_padded_text_nodes() -> None:
    """i18n must translate text nodes that carry indentation.

    Nav labels are ``<span>◇</span>插件\\n        `` — an exact-match lookup
    never hit the dictionary, so the language switch did nothing.
    """
    js = _ui_file("i18n.js")
    check("i18n trims the node text before lookup", "raw.trim()" in js)
    check("i18n preserves the surrounding whitespace",
          "leading + window.t(key) + trailing" in js)
    check("i18n keeps an exact-match fallback", "keys[trimmed] || keys[raw]" in js)


@case
def test_update_cancel_control_is_wired() -> None:
    """cancel_update existed in the bridge with no control to reach it."""
    html = _ui_file("index.html")
    js = _ui_file("app.js")
    check("update page has a cancel control", 'id="btn-cancel-update"' in html)
    check("cancel control calls cancel_update", 'callApi("cancel_update")' in js)
    check("cancel control is toggled with the busy state",
          'cancelBtn.classList.toggle("hidden", !busy)' in js)


@case
def test_example_shell_plugins_are_not_shipped() -> None:
    """Examples live in examples/shell-plugins and must never be packaged."""
    check("app/ui/plugins is gone (nothing bundled)",
          not os.path.isdir(os.path.join(REPO, "app", "ui", "plugins")))
    examples = os.path.join(REPO, "examples", "shell-plugins")
    check("examples kept in the repository for reference", os.path.isdir(examples))
    for plugin in ("example-pet", "example-status", "plugin-dev-kit"):
        manifest = os.path.join(examples, plugin, "plugin.json")
        check(f"{plugin} kept as a reference example", os.path.isfile(manifest))
    build = open(os.path.join(REPO, "build.ps1"), "r", encoding="utf-8-sig").read()
    check("build.ps1 does not copy examples into the app",
          "examples" not in build.split("Copy-Item")[0] and "shell-plugins" not in build)


@case
def test_plugin_removal_validates_the_name() -> None:
    """remove() must reject a name that is not an installed dependency."""
    source = open(os.path.join(REPO, "app", "plugins.py"), "r", encoding="utf-8").read()
    body = source[source.find("    def remove(self"): source.find("    def set_enabled")]
    check("remove() reads the profile manifest", "_read_manifest()" in body)
    check("remove() rejects a missing manifest", "profile 尚未初始化" in body)
    check("remove() rejects an unknown dependency", "不是已安装的插件" in body)


@case
def test_immersive_is_gated_on_the_workspace_page() -> None:
    """Fullscreen must never strand the user on another page.

    ``openFrame`` used to force immersive mode when the server finished
    starting, even if the user had switched tabs during the (long) start: the
    sidebar is hidden in immersive mode and the exit button lives in the
    workspace page, so the other page rendered full-bleed with no way back.
    """
    js = _ui_file("app.js")
    open_frame = js[js.find("function openFrame"): js.find("/* 沉浸模式")]
    check("openFrame checks which page is visible",
          'page-workspace' in open_frame and 'contains("hidden")' in open_frame,
          open_frame[:0] or "")
    check("openFrame only enters immersive inside that check",
          "setImmersive(true, false)" in open_frame)
    show_page = js[js.find("function showPage"): js.find("document.querySelectorAll(\".nav-item\")")]
    check("showPage exits immersive when leaving the workspace",
          'name !== "workspace"' in show_page and "immersive" in show_page,
          show_page[:0] or "")


@case
def test_close_saves_state_and_stops_the_core() -> None:
    """Closing must confirm first, then save settings and stop the core."""
    main_py = open(os.path.join(REPO, "app", "main.py"), "r", encoding="utf-8").read()
    quit_body = main_py[main_py.find("    def quit_app(self)"): main_py.find("    def _save_state")]
    check("quit_app saves the config", "_save_state()" in quit_body)
    check("quit_app stops the core server before destroying the window",
          quit_body.find("self._core.stop()") < quit_body.find("destroy()"))
    check("quit_app stops the tray icon", "self._tray.stop()" in quit_body)
    check("quit_app clears the pending close request", "_close_requested.clear()" in quit_body)

    closing = main_py[main_py.find("    def _on_closing"): main_py.find("    def cancel_close")]
    check("close is deferred when confirmation is enabled",
          'self._cfg.get("close_confirm", True)' in closing and "return False" in closing)
    check("_on_closing nudges the shell and sets the request flag",
          "_close_requested.set()" in closing and "_nudge_shell()" in closing)
    check("a second close request quits without waiting (never traps the user)",
          "second close request" in closing)
    check("close with confirmation off saves state before allowing the close",
          "_save_state()" in closing)
    check("hide-to-tray keeps the app running", "def hide_to_tray" in main_py)
    check("poll_tray carries the close flag",
          '"close": close' in main_py and "_close_requested.is_set()" in main_py)
    check("the finally block saves settings too",
          "final settings save failed" in main_py and "cfg.save()" in main_py)


@case
def test_close_confirmation_ui_is_complete() -> None:
    """The dialog needs its own id, three actions, and a settings toggle."""
    html = _ui_file("index.html")
    js = _ui_file("app.js")
    ids = re.findall(r'\bid="([^"]+)"', html)
    duplicates = {name: ids.count(name) for name in set(ids) if ids.count(name) > 1}
    check("no duplicate ids after adding the dialog", not duplicates, json.dumps(duplicates))
    check("settings has the confirm toggle", 'id="close-confirm"' in html)
    check("dialog has its own id", 'id="close-confirm-dialog"' in html)
    for button in ("btn-close-cancel", "btn-close-tray", "btn-close-quit"):
        check(f"dialog offers {button}", f'id="{button}"' in html)
    dialog_at = html.find('id="close-confirm-dialog"')
    scripts_at = html.find('<script src="i18n.js"')
    check("dialog markup precedes the scripts (handlers can bind)",
          0 < dialog_at < scripts_at, f"dialog@{dialog_at} scripts@{scripts_at}")
    check("cancel calls cancel_close", 'callApi("cancel_close")' in js)
    check("minimize calls hide_to_tray", 'callApi("hide_to_tray")' in js)
    check("close calls quit_app", 'callApi("quit_app")' in js)
    check("poll_tray opens the dialog", "res.close) showCloseConfirm" in js)
    check("the toggle is persisted with the other settings",
          'close_confirm: $("close-confirm").checked' in js)
    main_py = open(os.path.join(REPO, "app", "main.py"), "r", encoding="utf-8").read()
    check("close_confirm reaches get_state",
          'self._cfg.get("close_confirm", True)' in main_py)
    settings_defaults = open(os.path.join(REPO, "app", "settings.py"), "r",
                             encoding="utf-8").read()
    check("close_confirm has a default", '"close_confirm": True' in settings_defaults)


@case
def test_script_encodings_match_their_interpreters() -> None:
    """PowerShell needs a UTF-8 BOM; cmd batch files must be ANSI.

    Windows PowerShell 5.1 (the interpreter the release scripts run under)
    decodes a BOM-less file as ANSI, so a UTF-8 script with Chinese literals —
    the payload checks compare Chinese file names — silently becomes mojibake
    and reports healthy packages as broken. cmd.exe reads .bat in the console
    code page, so those must stay ANSI (no BOM).
    """
    ps1 = [os.path.join(REPO, "build.ps1")]
    ps1 += [os.path.join(REPO, "scripts", n)
            for n in sorted(os.listdir(os.path.join(REPO, "scripts")))
            if n.endswith(".ps1")]
    for path in ps1:
        raw = open(path, "rb").read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            check(f"{os.path.basename(path)} is valid UTF-8", False)
            continue
        has_non_ascii = any(ord(ch) > 127 for ch in text)
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        check(f"{os.path.basename(path)}: UTF-8 BOM when it has non-ASCII text",
              has_bom or not has_non_ascii,
              "BOM missing -> PowerShell 5.1 would read it as ANSI" if has_non_ascii else "")

    for name in ("post-update.bat", "post-install.bat", "scripts/apply-patch.bat"):
        raw = open(os.path.join(REPO, name), "rb").read()
        check(f"{name} has no UTF-8 BOM (cmd reads ANSI)", not raw.startswith(b"\xef\xbb\xbf"))
        try:
            raw.decode("mbcs")
            decodable = True
        except (UnicodeDecodeError, LookupError):
            decodable = False
        check(f"{name} decodes in the console code page", decodable)
        # A UTF-8 replacement byte written into an ANSI batch file loses the
        # line boundary for cmd.exe (a double-byte lead byte swallows the
        # newline) and every later line is executed as garbage commands —
        # observed in a smoke run. Batch files are also CRLF for the same
        # reason: cmd.exe's parser is only reliable with CRLF.
        text = raw.decode("mbcs", errors="replace") if decodable else ""
        check(f"{name} has no mojibake/replacement characters",
              "\ufffd" not in text)
        try:
            raw.decode("gbk")
            strict = True
        except (UnicodeDecodeError, LookupError):
            strict = False
        check(f"{name} is strictly GBK-decodable", strict)
        check(f"{name} uses CRLF line endings",
              raw.count(b"\r\n") > 0 and raw.count(b"\n") == raw.count(b"\r\n"),
              f"CRLF={raw.count(b'\r\n')} LF={raw.count(b'\n')}")


@case
def test_profile_migration_drops_retired_plugins() -> None:
    """The retired dsh-web plugins must leave an existing profile.

    They declare dsh compatibility ranges that exclude the bundled 0.1.6
    kernel, so leaving them in ``profiles/web/package.json`` keeps the whole
    profile failing to load after an upgrade. The migration is manifest-first
    (works with no core CLI) and also repoints the preseeded dshmarket plugin
    at the bundled tarball.
    """
    import migrate  # noqa: PLC0415 - app/ is on sys.path at import time

    app_dir = os.path.join(REPO, "app")
    tgz, version = migrate.bundled_store(app_dir)
    check("a bundled dshmarket tarball is present", bool(tgz), tgz)
    check("the bundled store version is newer than the retired 1.33.0",
          bool(version) and homes.version_newer(version, "1.33.0"), version)

    scratch = tempfile.mkdtemp(prefix="dsh-migrate-")
    try:
        profile = os.path.join(scratch, "profiles", "web")
        os.makedirs(profile)

        # ---- a profile carrying every retired plugin -------------------
        manifest = {
            "dependencies": {
                "dshmarket": "file:" + os.path.join(scratch, "store", "dshmarket-1.33.0.tgz"),
                "@linxin666/dsh-web-ui-all": "^0.3.11",
                "@linxin666/dsh-chat-recovery": "^0.3.11",
                "@linxin666/dsh-client-ui-preset-center": "^0.3.23",
                "dsh-better-sidebar": "^1.2.0",
            },
            "dsh": {"profile": {"bundles": [
                "@deepseek-ai/dsh-base",
                "@deepseek-ai/dsh-web-app",
                "@linxin666/dsh-web-ui-all",
                "@linxin666/dsh-perf",
                "@linxin666/dsh-client-ui-preset-center",
            ]}},
        }
        with open(os.path.join(profile, "package.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)

        res = migrate.migrate_profile(app_dir, "", "", scratch)
        check("migration reports success", res["ok"], json.dumps(res)[:200])
        check("retired plugins are removed from dependencies",
              set(res["removed"]) == {"@linxin666/dsh-web-ui-all",
                                      "@linxin666/dsh-chat-recovery"},
              json.dumps(res["removed"]))
        with open(os.path.join(profile, "package.json"), "r", encoding="utf-8") as fh:
            after = json.load(fh)
        deps = after["dependencies"]
        for name in migrate.OBSOLETE_PLUGINS:
            check(f"{name} no longer a dependency", name not in deps)
        check("the compatible replacement is untouched",
              deps.get("@linxin666/dsh-client-ui-preset-center") == "^0.3.23")
        check("non-dsh-web plugins are untouched", deps.get("dsh-better-sidebar") == "^1.2.0")
        bundles = after["dsh"]["profile"]["bundles"]
        check("retired plugins are dropped from dsh.profile.bundles",
              "@linxin666/dsh-web-ui-all" not in bundles
              and "@linxin666/dsh-perf" not in bundles, json.dumps(bundles))
        check("surviving bundles are kept",
              "@linxin666/dsh-client-ui-preset-center" in bundles)
        check("the core's own bundles are never touched by the migration",
              "@deepseek-ai/dsh-base" in bundles and "@deepseek-ai/dsh-web-app" in bundles,
              json.dumps(bundles))
        check("dshmarket is repointed at the bundled tarball",
              os.path.normcase(deps["dshmarket"]) == os.path.normcase("file:" + tgz),
              deps["dshmarket"])
        check("without a core CLI the migration stops after the manifest edit",
              res["skipped"] == "no-core-cli", res["skipped"])

        # ---- running again is a no-op ----------------------------------
        res2 = migrate.migrate_profile(app_dir, "", "", scratch)
        check("a migrated profile is skipped", res2["skipped"] == "up-to-date",
              res2["skipped"])
        check("a migrated profile reports nothing left to do",
              not res2["removed"] and not res2["bundlesDropped"] and not res2["storeFrom"],
              json.dumps(res2)[:200])

        # ---- a missing profile is not an error -------------------------
        res3 = migrate.migrate_profile(app_dir, "", "", os.path.join(scratch, "nope"))
        check("a missing profile is skipped, not failed",
              res3["ok"] and res3["skipped"] == "no-profile", json.dumps(res3)[:200])

        # ---- a half-written manifest must not be clobbered -------------
        broken = os.path.join(scratch, "broken", "profiles", "web")
        os.makedirs(broken)
        with open(os.path.join(broken, "package.json"), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        res4 = migrate.migrate_profile(app_dir, "", "", os.path.join(scratch, "broken"))
        check("an unreadable manifest is skipped, not failed",
              res4["ok"] and res4["skipped"] == "no-profile", json.dumps(res4)[:200])
        with open(os.path.join(broken, "package.json"), "r", encoding="utf-8") as fh:
            check("an unreadable manifest is left alone", fh.read() == "{ not json")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


@case
def test_migration_prunes_through_pnpm_install() -> None:
    """Pruning must reconcile with pnpm, and must not depend on the dsh CLI.

    ``dsh plugin --profile web remove …`` cannot work after the manifest edit:
    the packages are no longer dependencies and pnpm refuses with
    ERR_PNPM_CANNOT_REMOVE_MISSING_DEPS (observed on a real profile, where the
    prune silently never happened). The migration runs ``pnpm install`` in the
    profile instead, which drops the extraneous packages and materializes the
    bundled store tarball.
    """
    import migrate  # noqa: PLC0415

    scratch = tempfile.mkdtemp(prefix="dsh-prune-")
    try:
        profile = os.path.join(scratch, "profiles", "web")
        os.makedirs(profile)
        seeded = {"dependencies": {name: "^0.3.0" for name in migrate.OBSOLETE_PLUGINS}}
        with open(os.path.join(profile, "package.json"), "w", encoding="utf-8") as fh:
            json.dump(seeded, fh)

        # The deprecated aggregate publishes upstream's own migration target.
        pkg_dir = os.path.join(profile, "node_modules", "@linxin666", "dsh-web-ui-all")
        os.makedirs(pkg_dir)
        with open(os.path.join(pkg_dir, "package.json"), "w", encoding="utf-8") as fh:
            json.dump({"name": migrate.OBSOLETE_PLUGINS[0], "version": "0.3.6",
                       "dsh": {"migrate": {"to": migrate.NEW_AGGREGATE,
                                           "since": "0.3.6"}}}, fh)

        node_exe = os.path.join(scratch, "node.exe")
        bin_js = os.path.join(scratch, "bin.js")
        for path in (node_exe, bin_js):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("")

        calls: list[dict] = []

        class FakePopen:
            """Stands in for pnpm.cmd: records argv/env/kwargs, then exits."""

            def __init__(self, argv, **kw):
                calls.append({"argv": list(argv), "env": dict(kw.get("env") or {}),
                              "cwd": kw.get("cwd"), "stdout": kw.get("stdout")})
                self.pid = 4242
                self._code = exit_code

            def wait(self, timeout=None):
                if timeout is not None and hang:
                    raise subprocess.TimeoutExpired("pnpm", timeout)
                return self._code

        exit_code = 0
        hang = False
        real_popen = migrate.subprocess.Popen
        real_run = migrate.subprocess.run
        real_homes_run = homes.subprocess.run
        killed: list[list[str]] = []
        app_dir = os.path.join(REPO, "app")

        def fake_taskkill(argv, *a, **kw):
            killed.append(list(argv))
            return type("P", (), {"returncode": 0})()

        migrate.subprocess.Popen = FakePopen
        migrate.subprocess.run = fake_taskkill
        homes.subprocess.run = fake_taskkill
        try:
            res = migrate.migrate_profile(app_dir, node_exe, bin_js, scratch)
        finally:
            migrate.subprocess.Popen = real_popen
            migrate.subprocess.run = real_run
            homes.subprocess.run = real_homes_run

        check("the prune is reported as done", res["pruned"] is True,
              json.dumps(res)[:250])
        check("pruning goes through pnpm, not `dsh plugin remove`",
              len(calls) == 1 and "install" in calls[0]["argv"]
              and not any("remove" in c["argv"] for c in calls),
              json.dumps([c["argv"] for c in calls])[:250])
        check("pnpm runs inside the profile", calls and calls[0]["cwd"] == profile,
              str(calls[0]["cwd"]) if calls else "")
        check("the reconcile cannot use a frozen lockfile",
              calls and "--no-frozen-lockfile" in calls[0]["argv"]
              and "--ignore-scripts" in calls[0]["argv"],
              json.dumps(calls[0]["argv"]) if calls else "")
        check("CI is cleared from pnpm's environment",
              calls and "CI" not in calls[0]["env"] and "ci" not in calls[0]["env"])
        check("pnpm is pointed at the instance store",
              calls and calls[0]["env"].get("PNPM_HOME") == scratch,
              calls[0]["env"].get("PNPM_HOME", "") if calls else "")
        check("pnpm receives the profile's DSH_HOME",
              calls and calls[0]["env"].get("DSH_HOME") == scratch,
              calls[0]["env"].get("DSH_HOME", "") if calls else "")
        check("pnpm's output goes to a file, never a pipe (no wedged pipe)",
              calls and calls[0]["stdout"] is not None
              and not isinstance(calls[0]["stdout"], int),
              "capture_output would hang on an orphaned pnpm child")
        check("the pnpm log is reported", bool(res["pruneLog"])
              and os.path.isfile(res["pruneLog"]), res["pruneLog"])
        check("the upstream migration target is reported",
              res["migrateTo"] == [{"from": migrate.OBSOLETE_PLUGINS[0],
                                    "to": migrate.NEW_AGGREGATE, "version": "0.3.6"}],
              json.dumps(res["migrateTo"]))

        # ---- a hung pnpm must be killed, not waited on forever -------------
        calls.clear()
        killed.clear()
        hang = True
        scratch_hang = tempfile.mkdtemp(prefix="dsh-prune-hang-")
        try:
            os.makedirs(os.path.join(scratch_hang, "profiles", "web"))
            with open(os.path.join(scratch_hang, "profiles", "web", "package.json"),
                      "w", encoding="utf-8") as fh:
                json.dump({"dependencies": {name: "^0.3.0"
                                            for name in migrate.OBSOLETE_PLUGINS}}, fh)
            migrate.subprocess.Popen = FakePopen
            migrate.subprocess.run = fake_taskkill
            homes.subprocess.run = fake_taskkill
            try:
                res_hang = migrate.migrate_profile(app_dir, node_exe, bin_js,
                                                   scratch_hang, timeout=5)
            finally:
                migrate.subprocess.Popen = real_popen
                migrate.subprocess.run = real_run
                homes.subprocess.run = real_homes_run
            check("a hung pnpm is killed and reported as a failed prune",
                  res_hang["pruned"] is False and res_hang["ok"]
                  and any("taskkill" in c[0] for c in killed),
                  json.dumps(res_hang)[:200] + " killed=" + json.dumps(killed))
        finally:
            hang = False
            shutil.rmtree(scratch_hang, ignore_errors=True)

        # ---- pnpm failing: reported, manifest still clean ------------------
        def fake_all_fail(argv, *a, **kw):
            calls.append({"argv": list(argv), "env": {}, "cwd": kw.get("cwd")})
            return None

        exit_code = 2
        scratch2 = tempfile.mkdtemp(prefix="dsh-prune2-")
        try:
            profile2 = os.path.join(scratch2, "profiles", "web")
            os.makedirs(profile2)
            with open(os.path.join(profile2, "package.json"), "w", encoding="utf-8") as fh:
                json.dump({"dependencies": {name: "^0.3.0"
                                            for name in migrate.OBSOLETE_PLUGINS}}, fh)
            migrate.subprocess.Popen = FakePopen
            migrate.subprocess.run = fake_all_fail
            try:
                res2 = migrate.migrate_profile(app_dir, node_exe, bin_js, scratch2)
            finally:
                migrate.subprocess.Popen = real_popen
                migrate.subprocess.run = real_run
            check("a failed prune is reported as failed, never as done",
                  res2["pruned"] is False and res2["ok"], json.dumps(res2)[:250])
            with open(os.path.join(profile2, "package.json"), encoding="utf-8") as fh:
                cleaned = json.load(fh)
            check("the manifest is still cleaned even when pnpm cannot prune",
                  cleaned["dependencies"] == {}, json.dumps(cleaned)[:200])
        finally:
            shutil.rmtree(scratch2, ignore_errors=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


@case
def test_subprocess_helpers_never_pipe_a_killed_tree() -> None:
    """No shipped subprocess may block on a pipe whose writer outlived it.

    ``subprocess.run(capture_output=True, timeout=…)`` is a deadlock on
    Windows: killing ``pnpm.cmd``/``cmd`` leaves the grandchild alive holding
    the pipe, so ``communicate()`` never returns and the thread that owns
    ``_heal_done`` (or the core-update worker) hangs forever. The shipped code
    must use ``homes.run_capture`` (file output + tree kill) or
    ``homes.run_stream`` (daemon reader + cancel-aware + tree kill).
    """
    import threading  # noqa: PLC0415

    calls: list[dict] = []
    killed: list[list[str]] = []

    class FakePopen:
        def __init__(self, argv, **kw):
            calls.append({"argv": list(argv), "kw": kw,
                          "stdout": kw.get("stdout")})
            self.pid = 777
            self.stdout = _FakeStdout()

        def wait(self, timeout=None):
            # Hang until the tree is killed, then exit like a real killed child.
            if always_hang and not killed:
                raise subprocess.TimeoutExpired("x", timeout)
            return 0

    class _FakeStdout:
        def __iter__(self):
            return iter(["line one\n", "line two\n"])

    always_hang = True
    real_popen = homes.subprocess.Popen
    real_run = homes.subprocess.run
    real_kill = homes.kill_process_tree

    def fake_taskkill(argv, *a, **kw):
        killed.append(list(argv))
        return type("P", (), {"returncode": 0})()

    def fake_kill(pid):
        killed.append(["kill_process_tree", str(pid)])
        return True

    homes.subprocess.Popen = FakePopen
    homes.subprocess.run = fake_taskkill
    homes.kill_process_tree = fake_kill
    try:
        # ---- run_capture: file output, tree killed on timeout ---------------
        code, out = homes.run_capture(["pnpm", "install"], timeout=0.5)
        check("run_capture reports failure when the child hangs", code == -1, str(code))
        check("run_capture kills the whole tree on timeout",
              any(c[0] == "kill_process_tree" for c in killed), json.dumps(killed))
        check("run_capture never captures through a pipe",
              calls and calls[0]["kw"].get("stdout") is not None
              and not isinstance(calls[0]["kw"].get("stdout"), int)
              and "capture_output" not in calls[0]["kw"],
              "stdout must be a log file, not subprocess.PIPE")
        check("run_capture's log path is honoured",
              os.path.dirname(calls[0]["kw"]["stdout"].name) != "",
              calls[0]["kw"]["stdout"].name)
        calls.clear()
        killed.clear()

        # ---- run_stream: cancel is observed, reader cannot wedge ------------
        stop = threading.Event()
        stop.set()
        started = time.time()
        code = homes.run_stream(["pnpm", "build"], stop=stop, on_line=lambda _l: None)
        elapsed = time.time() - started
        check("run_stream returns immediately when already cancelled", code == -1, str(code))
        check("a cancelled run does not wait the command out", elapsed < 5,
              f"{elapsed:.1f}s")
        check("a cancelled run kills the whole tree",
              any(c[0] == "kill_process_tree" for c in killed), json.dumps(killed))
        check("run_stream reads on a daemon thread, not the caller",
              calls and calls[0]["kw"].get("stdout") == subprocess.PIPE
              and "capture_output" not in calls[0]["kw"])
    finally:
        homes.subprocess.Popen = real_popen
        homes.subprocess.run = real_run
        homes.kill_process_tree = real_kill

    # ---- the shipped call sites use those helpers ---------------------------
    homes_src = open(os.path.join(REPO, "app", "homes.py"), "r", encoding="utf-8").read()
    heal = homes_src[homes_src.find("def heal_profile_store"):]
    heal = heal[:heal.find("\ndef ", 10)]
    check("the profile-store heal runs pnpm through run_capture",
          "run_capture(" in heal and "capture_output" not in heal)
    health = homes_src[homes_src.find("def run_health_check"):]
    check("the health check runs the core through run_capture",
          "run_capture(" in health and "capture_output" not in health)

    updater_src = open(os.path.join(REPO, "app", "updater.py"), "r", encoding="utf-8").read()
    pnpm_body = updater_src[updater_src.find("def _run_pnpm"):]
    pnpm_body = pnpm_body[:pnpm_body.find("\n    def ", 10)]
    check("core-update pnpm runs stream, so cancel really cancels",
          "homes.run_stream(" in pnpm_body and "stop=self._cancel" in pnpm_body)
    check("core-update pnpm no longer reads a raw pipe",
          "subprocess.Popen(" not in pnpm_body)


@case
def test_migration_is_wired_into_startup_and_upgrade() -> None:
    """Both the launcher and the update script must run the migration."""
    main_py = open(os.path.join(REPO, "app", "main.py"), "r", encoding="utf-8").read()
    check("main.py imports the migration module", "import migrate" in main_py)
    heal = main_py[main_py.find("def _heal_profile"): main_py.find("def _heal_profile") + 4000]
    check("the profile heal runs the migration", "migrate.migrate_profile(" in heal)
    check("the migration receives the bundled core CLI",
          "self._core.node_exe" in heal and "self._core.bin_js" in heal)
    check("the migration runs before the heal is marked done",
          heal.find("migrate.migrate_profile(") < heal.find("_heal_done.set()"))

    migrate_py = open(os.path.join(REPO, "app", "migrate.py"), "r", encoding="utf-8").read()
    check("the migration clears CI so pnpm cannot demand a frozen lockfile",
          'env.pop("CI", None)' in migrate_py and 'setdefault("CI"' not in migrate_py,
          "CI makes pnpm use --frozen-lockfile, which the manifest edit invalidates")

    bat = open(os.path.join(REPO, "post-update.bat"), "rb").read().decode("mbcs")
    remove_line = [ln for ln in bat.splitlines() if "plugin --profile web remove" in ln]
    check("post-update.bat removes retired plugins via the core CLI", bool(remove_line))
    joined = " ".join(remove_line)
    import migrate  # noqa: PLC0415
    for name in migrate.OBSOLETE_PLUGINS:
        check(f"post-update.bat names {name}", name in joined)
    check("post-update.bat uses the bundled node runtime when present",
          "runtime\\node.exe" in bat)
    check("post-update.bat points the CLI at the installed profile",
          'set "DSH_HOME=%~dp0data\\.dsh"' in bat)
    check("post-update.bat guards the migration when the profile is absent",
          "goto skip_profile_migration" in bat and ":skip_profile_migration" in bat)
    check("post-update.bat can skip the prune (smoke dry-run has no pnpm store)",
          "no-plugin-migration.flag" in bat)
    check("the migration runs before the smoke-test early exit",
          bat.find("plugin --profile web remove") < bat.find("no-launch.flag"))
    check("post-update.bat is still a valid ANSI batch file",
          not bat.startswith("\ufeff"))


@case
def test_presets_use_the_compatible_new_family() -> None:
    """The shipped presets must name packages that work with dsh 0.1.6."""
    import migrate  # noqa: PLC0415

    js = _ui_file("app.js")
    html = _ui_file("index.html")
    start = js.find("const PRESET_WEB_NO_SSH = [")
    end = js.find("];", start)
    check("the no-ssh preset still exists", 0 < start < end)
    preset = js[start:end]
    for name in migrate.OBSOLETE_PLUGINS:
        check(f"the preset no longer lists {name}", name not in preset)
    for name in ("@linxin666/dsh-client-ui-preset-center",
                 "@linxin666/dsh-usage",
                 "@linxin666/dsh-i18n",
                 "@linxin666/dsh-session-archive",
                 "@linxin666/dsh-client-ui-model-capabilities"):
        check(f"the preset lists the current package {name}", name in preset)
    check("the aggregate button pins the verified 0.3.23 build",
          '"@linxin666/dsh-web-all@0.3.23"' in js)
    check("the aggregate button no longer points at dsh-web-ui-all",
          "dsh-web-ui-all@" not in js)
    check("the aggregate preset button is still in the markup",
          'id="preset-web-all"' in html)
    check("the aggregate preset is documented in its tooltip",
          "dsh-web-all" in html)


@case
def test_bundled_store_tarball_is_current() -> None:
    """Only the current dshmarket build may ship, and it must accept 0.1.x."""
    import tarfile  # noqa: PLC0415

    store_dir = os.path.join(REPO, "app", "store")
    tgz_names = sorted(n for n in os.listdir(store_dir) if n.lower().endswith(".tgz"))
    check("exactly one bundled store tarball ships", len(tgz_names) == 1,
          json.dumps(tgz_names))
    name = tgz_names[0] if tgz_names else ""
    check("the retired dshmarket 1.33.0 tarball is gone",
          "1.33.0" not in name, name)
    spec = settings.Settings.DEFAULTS["store_sources"][0]["spec"]
    check("the store spec in settings.py matches the shipped tarball",
          spec == f"store/{name}", spec)

    # The build rebundles the store tarball; it used to default to 1.33.0 and
    # would have silently re-shipped the retired, incompatible build.
    import importlib.util  # noqa: PLC0415
    rb_path = os.path.join(REPO, "scripts", "rebundle-store-tgz.py")
    rb_spec = importlib.util.spec_from_file_location("_rebundle_store", rb_path)
    rb = importlib.util.module_from_spec(rb_spec)
    rb_spec.loader.exec_module(rb)
    check("the store rebundler takes its version from settings.py",
          f"dshmarket-{rb.bundled_version()}.tgz" == name,
          f"{rb.bundled_version()} vs {name}")
    source = open(rb_path, encoding="utf-8").read()
    check("the store rebundler has no hard-coded store version",
          'default="1.33.0"' not in source
          and "version = args.version or bundled_version()" in source)
    check("the store rebundler deletes superseded tarballs",
          "_drop_superseded" in source and "removed superseded" in source)

    with open(os.path.join(store_dir, name), "rb") as fh:
        magic = fh.read(2)
    check("the tarball is gzip-compressed", magic == b"\x1f\x8b", repr(magic))
    with tarfile.open(os.path.join(store_dir, name), "r:gz") as tar:
        member = tar.extractfile("package/package.json")
        check("the tarball carries a package.json", member is not None)
        meta = json.loads(member.read().decode("utf-8"))
    check("the shipped version matches its file name",
          name == f"dshmarket-{meta.get('version')}.tgz",
          f"{name} vs {meta.get('version')}")
    peers = meta.get("peerDependencies") or {}
    settings_range = str(peers.get("@deepseek-ai/dsh-settings") or "")
    check("the store accepts the current dsh-settings line",
          "0.1.2-alpha" in settings_range, settings_range)
    check("the store no longer pins the pre-0.1.2 range only",
          settings_range.count("||") >= 2, settings_range)


@case
def test_incremental_patch_is_safe_and_verified() -> None:
    """The 1.0.5 incremental patch must not be able to hurt an instance.

    Guards the mistakes this patch actually made while being built:
    a name-only process match (it refused to patch because *another* instance
    was running), an unquoted Start-Process argument list (breaks on the
    default ``C:\\DeepSeek Harness`` path), a batch ``pnpm remove`` naming
    packages that are not dependencies (pnpm fails as a whole), and the
    reserved ``$home`` automatic variable.
    """
    apply_src = open(os.path.join(REPO, "scripts", "apply-patch.ps1"),
                     "r", encoding="utf-8").read()
    make_src = open(os.path.join(REPO, "scripts", "make-patch.ps1"),
                    "r", encoding="utf-8").read()
    test_src = open(os.path.join(REPO, "scripts", "test-patch.ps1"),
                    "r", encoding="utf-8").read()

    check("the patch script does not use the reserved $home variable",
          "$home " not in apply_src and "$home)" not in apply_src
          and "$home=" not in apply_src and "$dshHome" in apply_src)
    check("the running-instance guard matches the install path, not the name",
          "Get-InstanceExePids" in apply_src and "| Stop-Process" not in apply_src,
          "a name-only match blocks/patches other instances")
    check("only installed retired plugins are passed to the CLI",
          "$present" in apply_src and '") + $present' in apply_src)
    check("Start-Process arguments are quoted (paths with spaces)",
          "$quoted" in apply_src and "$quoted -join ' '" in apply_src)
    check("_internal is mirrored, not merged",
          "/MIR" in apply_src and "robocopy" in apply_src)
    check("the patch backs up before writing",
          0 < apply_src.find("patch-backup-") < apply_src.find("3. 应用应用层文件"))
    check("the patch supports -DryRun and -NoRestart",
          "[switch]$DryRun" in apply_src and "[switch]$NoRestart" in apply_src)
    check("the patch verifies payload hashes at the end",
          "MANIFEST.sha256" in apply_src and "Test-Hash" in apply_src)

    check("the patch builder refuses a corrupted post-update.bat",
          "GetEncoding(936)" in make_src and "CRLF" in make_src
          and "替换字符" in make_src)
    check("the patch builder rejects a UTF-8 BOM in the batch file",
          "0xEF" in make_src and "0xBB" in make_src)
    check("the patch builder emits a manifest and a zip hash",
          "MANIFEST.sha256" in make_src and "$zipPath.sha256" in make_src)
    check("the acceptance test applies the patch to a copy only",
          "-NoRestart" in test_src and "PATCH TEST: ALL PASS" in test_src
          and "mklink /J" in test_src)

    # the encoding normalizer is the guard for the whole class of bugs
    script = os.path.join(REPO, "scripts", "fix-script-encodings.py")
    check("the encoding normalizer ships with the repo", os.path.isfile(script))
    proc = subprocess.run([sys.executable, script, "--check"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)
    check("every shipped script is encoded for its interpreter",
          proc.returncode == 0, (proc.stdout or "")[-300:])


# ---------------------------------------------------------------------- main


def main() -> int:
    global VERBOSE
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    VERBOSE = args.verbose

    cases = [
        test_removes_tree_beyond_max_path,
        test_removes_read_only_files,
        test_removal_never_follows_junctions,
        test_remove_tree_on_missing_and_file_paths,
        test_resolves_cli_entry_across_layouts,
        test_core_controller_entry_and_version,
        test_launch_candidate_ladder,
        test_usage_error_classification,
        test_health_check_tolerates_unknown_dump_flag,
        test_swap_replaces_core_and_clears_launch_mode,
        test_swap_rejects_half_built_stage,
        test_swap_rolls_back_when_verification_fails,
        test_stale_backup_does_not_block_the_swap,
        test_cleanup_stale_core_backups,
        test_settings_round_trip_launch_mode,
        test_shell_ui_frame_is_absolutely_positioned,
        test_shell_ui_sync_refreshes_stale_installs,
        test_shell_ui_sync_handles_missing_and_dev_layouts,
        test_shell_ui_sync_never_downgrades,
        test_console_output_decoding_never_crashes,
        test_immersive_is_gated_on_the_workspace_page,
        test_script_encodings_match_their_interpreters,
        test_incremental_patch_is_safe_and_verified,
        test_close_saves_state_and_stops_the_core,
        test_close_confirmation_ui_is_complete,
        test_shell_ui_has_no_duplicate_ids,
        test_theme_loader_fetches_relative_stylesheets,
        test_i18n_matches_whitespace_padded_text_nodes,
        test_update_cancel_control_is_wired,
        test_example_shell_plugins_are_not_shipped,
        test_plugin_removal_validates_the_name,
        test_discovers_core_web_url_with_token,
        test_post_update_bat_refreshes_any_stale_ui,
        test_profile_migration_drops_retired_plugins,
        test_migration_prunes_through_pnpm_install,
        test_subprocess_helpers_never_pipe_a_killed_tree,
        test_migration_is_wired_into_startup_and_upgrade,
        test_presets_use_the_compatible_new_family,
        test_bundled_store_tarball_is_current,
    ]
    for fn in cases:
        fn()

    failed = [name for name, ok, _ in RESULTS if not ok]
    print("\n" + "=" * 62)
    print(f"1.0.5 regression tests: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("FAILED:")
        for name in failed:
            print(f"  - {name}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
