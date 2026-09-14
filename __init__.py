"""Hermes plugin: Apple-native read-aloud (`/say`, `hermes say`).

macOS Speak Selection (Option+Esc) reads AXSelectedText, which fullscreen
terminal apps never expose — so this speaks via /usr/bin/say (same Apple
voices, no API keys) instead. The plugin lives in user state
(`~/.hermes/plugins/`), so `/say` and `hermes say` survive Hermes updates.

`/say always` is plugin-owned and reads completed TUI replies only. Replies
on CLI and messaging platforms remain silent; global selection voices belong
to separate external macOS scripts.
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


def _auto_speak_after_llm_call(*, assistant_response="", platform=None, **_kwargs) -> None:
    if platform != "tui":
        return
    try:
        from say_engine import auto_speak_response

        auto_speak_response(assistant_response, platform=platform)
    except Exception:
        pass


def register(ctx) -> None:
    from say_engine import handle_say

    ctx.register_command(
        name="say",
        handler=handle_say,
        description="Read aloud with the Apple system voice: [text|number|stop|always|once]",
        args_hint="[text|number|stop|always|once]",
    )
    ctx.register_cli_command(
        name="say",
        help="Read aloud with the Apple system voice",
        setup_fn=_setup_argparse,
        handler_fn=_handle_cli,
    )
    ctx.register_hook("post_llm_call", _auto_speak_after_llm_call)
