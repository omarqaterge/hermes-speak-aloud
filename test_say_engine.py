"""Tests for the speak-aloud plugin engine (stdlib-only, no Hermes imports)."""

import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from say_engine import get_mode, handle_say, latest_assistant_texts, resolve_text, set_mode, speaking, start, stop


def test_resolve_last_assistant_on_empty_arg():
    assert resolve_text("", ["first", "second"]) == "second"


def test_resolve_nth_assistant_message():
    assert resolve_text("1", ["first", "second"]) == "first"
    assert resolve_text("99", ["first", "second"]) == "second"


def test_resolve_literal_text():
    assert resolve_text("hello there", ["first"]) == "hello there"


def test_resolve_empty_history():
    assert resolve_text("", []) == ""
    assert resolve_text("2", []) == ""


class _FakePopen:
    instances = []

    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.pid = 2000 + len(_FakePopen.instances)
        self.terminated = False
        _FakePopen.instances.append(self)

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return None if not self.terminated else 0


@pytest.mark.skipif(sys.platform != "darwin", reason="Apple say engine")
def test_start_stop_lifecycle(monkeypatch):
    import say_engine

    _FakePopen.instances.clear()
    monkeypatch.setattr(say_engine.subprocess, "Popen", _FakePopen)
    stop()
    assert speaking() is False
    pid = start("hello")
    assert isinstance(pid, int)
    assert _FakePopen.instances[-1].cmd[0] == "/usr/bin/say"
    assert _FakePopen.instances[-1].cmd[-1] == "hello"
    assert speaking() is True
    assert stop() is True
    assert speaking() is False


@pytest.mark.skipif(sys.platform != "darwin", reason="Apple say engine")
def test_start_barges_previous(monkeypatch):
    import say_engine

    _FakePopen.instances.clear()
    monkeypatch.setattr(say_engine.subprocess, "Popen", _FakePopen)
    stop()
    start("first")
    start("second")
    assert _FakePopen.instances[0].terminated is True
    assert _FakePopen.instances[-1].cmd[-1] == "second"
    stop()


def test_latest_assistant_texts_reads_newest_session(tmp_path):
    db = tmp_path / "state.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at REAL NOT NULL)")
    con.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT)"
    )
    con.execute("INSERT INTO sessions VALUES ('old', 1.0)")
    con.execute("INSERT INTO sessions VALUES ('new', 2.0)")
    con.execute("INSERT INTO messages (session_id, role, content) VALUES ('old', 'assistant', 'stale')")
    con.execute("INSERT INTO messages (session_id, role, content) VALUES ('new', 'user', 'q')")
    con.execute("INSERT INTO messages (session_id, role, content) VALUES ('new', 'assistant', 'fresh reply')")
    con.commit()
    con.close()
    assert latest_assistant_texts(home=tmp_path) == ["fresh reply"]


def test_latest_assistant_texts_missing_db(tmp_path):
    assert latest_assistant_texts(home=tmp_path / "nope") == []


def test_handle_say_stop_idle():
    stop()
    assert handle_say("stop") == "nothing playing."


def test_handle_say_stop_disarms_always(monkeypatch, tmp_path):
    import say_engine

    monkeypatch.setattr(say_engine, "_hermes_home", lambda: tmp_path)
    set_mode("always", tmp_path)
    stop()
    assert handle_say("stop") == "nothing playing."
    assert get_mode(tmp_path) == "once"


def test_handle_say_empty_history_reports(tmp_path, monkeypatch):
    import say_engine

    monkeypatch.setattr(say_engine, "latest_assistant_texts", lambda *a, **k: [])
    assert handle_say("") == "nothing to speak — start a conversation first"


def test_mode_round_trips_to_file(tmp_path):
    assert get_mode(tmp_path) == "once"
    assert set_mode("always", tmp_path) == ("always", False)
    assert get_mode(tmp_path) == "always"
    assert (tmp_path / "speak-aloud.mode").read_text() == "always\n"
    mode, _ = set_mode("once", tmp_path)
    assert mode == "once"
    assert get_mode(tmp_path) == "once"


def test_mode_rejects_garbage(tmp_path):
    with pytest.raises(ValueError):
        set_mode("sometimes", tmp_path)


def test_handle_say_always_enables_plugin_owned_tui_auto_reading(monkeypatch, tmp_path):
    import say_engine

    monkeypatch.setattr(say_engine, "_hermes_home", lambda: tmp_path)
    result = handle_say("always")
    assert get_mode(tmp_path) == "always"
    assert result == "auto read-aloud ON — this plugin will speak future TUI replies. /say once to stop."


def test_handle_say_once_reverts_to_on_demand_and_stops_active_utterance(monkeypatch, tmp_path):
    import say_engine

    monkeypatch.setattr(say_engine, "_hermes_home", lambda: tmp_path)
    set_mode("always", tmp_path)
    stops = []
    monkeypatch.setattr(say_engine, "stop", lambda: stops.append(True) or True)
    result = handle_say("once")
    assert stops == [True]
    assert get_mode(tmp_path) == "once"
    assert result == "auto read-aloud OFF — back to on-demand. (stopped.)"


def test_auto_speak_starts_for_tui_final_response_when_mode_is_always(monkeypatch, tmp_path):
    import say_engine

    spoken = []
    set_mode("always", tmp_path)
    monkeypatch.setattr(say_engine, "spoken_script", lambda text: f"spoken: {text}")
    monkeypatch.setattr(say_engine, "start", lambda text: spoken.append(text) or 1234)

    assert say_engine.auto_speak_response("finished reply", home=tmp_path, platform="tui") is True
    assert spoken == ["spoken: finished reply"]


def test_auto_speak_stays_silent_when_mode_is_once(monkeypatch, tmp_path):
    import say_engine

    set_mode("once", tmp_path)
    monkeypatch.setattr(
        say_engine,
        "start",
        lambda text: (_ for _ in ()).throw(AssertionError("start must not be called")),
    )

    assert say_engine.auto_speak_response("finished reply", home=tmp_path, platform="tui") is False


def test_auto_speak_stays_silent_for_blank_response(monkeypatch, tmp_path):
    import say_engine

    set_mode("always", tmp_path)
    monkeypatch.setattr(
        say_engine,
        "start",
        lambda text: (_ for _ in ()).throw(AssertionError("start must not be called")),
    )

    assert say_engine.auto_speak_response(" \n\t ", home=tmp_path, platform="tui") is False


def test_auto_speak_swallows_audio_errors(monkeypatch, tmp_path):
    import say_engine

    set_mode("always", tmp_path)

    def unavailable(_text):
        raise OSError("say is unavailable")

    monkeypatch.setattr(say_engine, "start", unavailable)

    assert say_engine.auto_speak_response("finished reply", home=tmp_path, platform="tui") is False


def test_auto_speak_stays_silent_outside_tui_when_mode_is_always(monkeypatch, tmp_path):
    import say_engine

    set_mode("always", tmp_path)
    monkeypatch.setattr(
        say_engine,
        "start",
        lambda text: (_ for _ in ()).throw(AssertionError("start must not be called")),
    )

    assert say_engine.auto_speak_response("finished reply", home=tmp_path, platform="cli") is False


def _load_plugin_module():
    spec = importlib.util.spec_from_file_location(
        "speak_aloud_plugin_test", Path(__file__).with_name("__init__.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingContext:
    def __init__(self):
        self.commands = []
        self.cli_commands = []
        self.hooks = {}

    def register_command(self, **kwargs):
        self.commands.append(kwargs)

    def register_cli_command(self, **kwargs):
        self.cli_commands.append(kwargs)

    def register_hook(self, name, callback):
        self.hooks[name] = callback


def test_registers_only_say_slash_and_cli_commands():
    context = _RecordingContext()

    _load_plugin_module().register(context)

    assert [command["name"] for command in context.commands] == ["say"]
    assert [command["name"] for command in context.cli_commands] == ["say"]
    assert set(context.hooks) == {"post_llm_call"}


def test_post_llm_hook_forwards_tui_platform_to_auto_speech(monkeypatch):
    import say_engine

    calls = []

    def record(response, *, platform):
        calls.append((response, platform))

    monkeypatch.setattr(say_engine, "auto_speak_response", record, raising=False)

    context = _RecordingContext()
    _load_plugin_module().register(context)

    context.hooks["post_llm_call"](assistant_response="finished reply", platform="tui")

    assert calls == [("finished reply", "tui")]


@pytest.mark.parametrize(
    "hook_kwargs",
    [
        {"platform": "cli"},
        {"platform": "telegram"},
        {"platform": "unknown"},
        {"platform": None},
        {},
    ],
    ids=["cli", "telegram", "unknown", "none", "absent"],
)
def test_post_llm_hook_stays_silent_outside_tui(monkeypatch, hook_kwargs):
    import say_engine

    calls = []
    monkeypatch.setattr(say_engine, "auto_speak_response", lambda *args, **kwargs: calls.append((args, kwargs)), raising=False)

    context = _RecordingContext()
    _load_plugin_module().register(context)

    context.hooks["post_llm_call"](assistant_response="finished reply", **hook_kwargs)

    assert calls == []
