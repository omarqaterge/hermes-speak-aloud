"""Hermes plugin: Apple-native read-aloud (`/say`, `hermes say`).

macOS Speak Selection (Option+Esc) reads AXSelectedText, which fullscreen
terminal apps never expose — so this speaks via /usr/bin/say (same Apple
voices, no API keys) instead. Lives in user state (`~/.hermes/plugins/`),
so Hermes updates can't wipe it: after an update removes any source-tree
patch, `/say` keeps working through this plugin automatically (the TUI's
built-in handler takes precedence while present; both share conventions).

A global hotkey (Ctrl+S) is NOT possible from a plugin — the framework
exposes no hotkey surface — so that part stays a source-tree patch (or an
upstream merge). Everything else survives here.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _setup_argparse(subparser) -> None:
    subparser.add_argument("text", nargs="?", default="", help="Text to speak (empty = last reply)")
    subparser.add_argument("--stop", action="store_true", help="Stop playback instead of speaking")


def _handle_cli(args) -> int:
    from say_engine import handle_say

    if getattr(args, "stop", False):
        print(handle_say("stop"))
        return 0
    print(handle_say(getattr(args, "text", "") or ""))
    return 0


_PATCH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "speak-tui.patch")


def _patch_setup(subparser) -> None:
    subs = subparser.add_subparsers(dest="speak_patch_command")
    subs.add_parser("status", help="Check whether the TUI source patch is applied")
    subs.add_parser("install", help="Re-apply the TUI source patch after an update wiped it")


def _patch_cli(args) -> int:
    import subprocess

    from say_engine import core_patch_present, hermes_tree

    cmd = getattr(args, "speak_patch_command", None) or "status"
    tree = hermes_tree()
    if tree is None:
        print("can't locate the Hermes source tree.")
        return 1
    if cmd == "status":
        state = core_patch_present(tree)
        print(f"TUI source patch: {'applied' if state else 'MISSING' if state is False else 'unknown'}")
        print(f"tree: {tree}")
        return 0 if state else 1
    if core_patch_present(tree) is True:
        print("TUI source patch already applied — nothing to do.")
        return 0
    if not os.path.isfile(_PATCH_FILE):
        print("patch file missing from the plugin — can't restore.")
        return 1
    probe = subprocess.run(
        ["patch", "-p1", "--dry-run", "-i", _PATCH_FILE],
        cwd=str(tree), capture_output=True, text=True,
    )
    if probe.returncode != 0:
        print("patch no longer applies cleanly to this Hermes version (the tree moved on).")
        print("tell me and I'll re-cut it — /say itself keeps working through this plugin meanwhile.")
        return 1
    applied = subprocess.run(["patch", "-p1", "-i", _PATCH_FILE], cwd=str(tree), capture_output=True, text=True)
    if applied.returncode != 0:
        print("apply failed:")
        print(applied.stdout[-2000:] or applied.stderr[-2000:])
        return 1
    print("patch applied. Finish with:")
    print(f"  cd {tree}/ui-tui && npm run build")
    print("  then restart Hermes (relaunch `hermes --tui`).")
    print("Python side needs no extra step — the gateway reloads on relaunch.")
    return 0


def register(ctx) -> None:
    from say_engine import handle_say

    ctx.register_command(
        name="say",
        handler=handle_say,
        description="Read aloud with the Apple system voice: [text|number|stop]",
        args_hint="[text|number|stop]",
    )
    ctx.register_cli_command(
        name="say",
        help="Read aloud with the Apple system voice",
        setup_fn=_setup_argparse,
        handler_fn=_handle_cli,
    )
    ctx.register_cli_command(
        name="speak-patch",
        help="Check / restore the TUI source patch (Ctrl+S, instant /say)",
        setup_fn=_patch_setup,
        handler_fn=_patch_cli,
    )
