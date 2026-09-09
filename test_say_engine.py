"""Tests for the speak-aloud plugin engine (stdlib-only, no Hermes imports)."""

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from say_engine import core_patch_present, get_mode, handle_say, latest_assistant_texts, resolve_text, set_mode, speaking, start, stop


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


def test_handle_say_empty_history_reports(tmp_path, monkeypatch):
    import say_engine

    monkeypatch.setattr(say_engine, "latest_assistant_texts", lambda *a, **k: [])
    assert handle_say("") == "nothing to speak — start a conversation first"


def _write_tree(root, with_markers=True):
    (root / "tui_gateway").mkdir(parents=True, exist_ok=True)
    (root / "ui-tui" / "src" / "lib").mkdir(parents=True, exist_ok=True)
    (root / "ui-tui" / "src" / "app").mkdir(parents=True, exist_ok=True)
    mark = "present" if with_markers else "absent"
    (root / "tui_gateway" / "methods_voice.py").write_text(
        '@method("speak.say")' if with_markers else "nothing here"
    )
    (root / "ui-tui" / "src" / "lib" / "platform.ts").write_text(
        "isSpeakAloudKey" if with_markers else "nothing here"
    )
    (root / "ui-tui" / "src" / "app" / "useInputHandlers.ts").write_text(
        "toggleSpeakAloud" if with_markers else "nothing here"
    )
    return mark


def test_core_patch_present_true(tmp_path):
    _write_tree(tmp_path, with_markers=True)
    assert core_patch_present(tmp_path) is True


def test_core_patch_present_false_when_marker_missing(tmp_path):
    _write_tree(tmp_path, with_markers=True)
    (tmp_path / "ui-tui" / "src" / "lib" / "platform.ts").write_text("nothing here")
    assert core_patch_present(tmp_path) is False


def test_core_patch_present_none_when_tree_missing(tmp_path):
    assert core_patch_present(tmp_path / "nope") is None


def test_handle_say_adds_restore_tip_when_patch_missing(monkeypatch):
    import say_engine

    monkeypatch.setattr(say_engine, "latest_assistant_texts", lambda *a, **k: ["hi there"])
    monkeypatch.setattr(say_engine, "core_patch_present", lambda *a, **k: False)
    monkeypatch.setattr(say_engine, "start", lambda *a, **k: 1234)
    result = handle_say("hi there")
    assert result.startswith("speaking…")
    assert "hermes speak-patch install" in result


def test_handle_say_no_tip_when_patch_present(monkeypatch):
    import say_engine

    monkeypatch.setattr(say_engine, "latest_assistant_texts", lambda *a, **k: ["hi there"])
    monkeypatch.setattr(say_engine, "core_patch_present", lambda *a, **k: True)
    monkeypatch.setattr(say_engine, "start", lambda *a, **k: 1234)
    assert handle_say("hi there") == "speaking… (/say stop to stop)"


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


def test_handle_say_always_saves_preference(monkeypatch, tmp_path):
    import say_engine

    monkeypatch.setattr(say_engine, "_hermes_home", lambda: tmp_path)
    result = handle_say("always")
    assert get_mode(tmp_path) == "always"
    assert "speak-patch install" in result


def test_handle_say_once_reverts_to_demand(monkeypatch, tmp_path):
    import say_engine

    monkeypatch.setattr(say_engine, "_hermes_home", lambda: tmp_path)
    set_mode("always", tmp_path)
    result = handle_say("once")
    assert get_mode(tmp_path) == "once"
    assert "on-demand" in result
