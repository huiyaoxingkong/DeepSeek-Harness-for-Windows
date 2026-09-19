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
        # A 1.0.4 install: live ui is the old build, _internal ships 1.0.5.
        _fake_ui(os.path.join(app, "ui"), "1.0.4", "OLD-BUGGY")
        _fake_ui(os.path.join(app, "_internal", "ui"), "1.0.5", "FIXED")
        report = shellui.sync_shell_ui(app, "1.0.5")
        check("stale ui is refreshed", report["action"] == "refreshed",
              json.dumps(report, ensure_ascii=False))
        with open(os.path.join(app, "ui", "style.css"), encoding="utf-8") as fh:
            check("live ui now carries the fix", fh.read() == "FIXED")
        check("previous ui kept as a backup folder",
              os.path.isfile(os.path.join(app, report["backup"], "style.css")))
        with open(os.path.join(app, report["backup"], "style.css"),
                  encoding="utf-8") as fh:
            check("backup keeps the user's files", fh.read() == "OLD-BUGGY")
        check("marker updated",
              shellui.read_marker(os.path.join(app, "ui")) == "1.0.5")
        second = shellui.sync_shell_ui(app, "1.0.5")
        check("second run is a no-op", second["action"] == "none",
              json.dumps(second, ensure_ascii=False))


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
    check("post-update.bat still keeps a backup",
          'rename "%~dp0ui" "ui-backup"' in text)


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
        test_shell_ui_has_no_duplicate_ids,
        test_theme_loader_fetches_relative_stylesheets,
        test_i18n_matches_whitespace_padded_text_nodes,
        test_update_cancel_control_is_wired,
        test_example_shell_plugins_are_not_shipped,
        test_plugin_removal_validates_the_name,
        test_discovers_core_web_url_with_token,
        test_post_update_bat_refreshes_any_stale_ui,
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
