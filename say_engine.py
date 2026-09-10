"""Apple-native read-aloud engine (macOS `/usr/bin/say`, no API keys).

Same voices as System Settings → Accessibility → Spoken Content, usable
where the global Option+Esc hotkey can't reach: fullscreen terminal apps
never expose AXSelectedText, so macOS has nothing to speak. One utterance
per process; a new call barges the previous one.

Stdlib-only on purpose: this module must keep working across Hermes
updates and refactor windows without touching internal APIs.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

SAY_BIN = "/usr/bin/say"  # Fixed OS path: immune to sparse launchd PATHs.
MAX_CHARS = 5000

_lock = threading.Lock()
_proc = None  # Optional[subprocess.Popen] for the current utterance.


def resolve_text(arg: str, assistants: list) -> str:
    """'' → last assistant message; 'N' → Nth (1-based, clamped, oldest
    first — same convention as the TUI's built-in /say); else literal text."""
    arg = (arg or "").strip()
    texts = [str(t or "").strip() for t in assistants or []]
    texts = [t for t in texts if t]
    if not arg:
        return texts[-1] if texts else ""
    try:
        idx = int(arg)
    except ValueError:
        return arg
    if not texts:
        return ""
    return texts[min(max(idx, 1), len(texts)) - 1]


def spoken_script(text: str) -> str:
    """TTS-friendly script (markdown/code stripped); raw fallback."""
    try:
        from tools.tts_text_normalize import prepare_spoken_text

        return prepare_spoken_text(text, max_chars=MAX_CHARS) or text[:MAX_CHARS]
    except Exception:
        return text[:MAX_CHARS]


def _stop_locked() -> bool:
    global _proc
    proc, _proc = _proc, None
    if proc is None:
        return False
    try:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    except Exception:
        pass
    return True


def stop() -> bool:
    """Silence the current utterance. True when something was playing."""
    with _lock:
        return _stop_locked()


def speaking() -> bool:
    global _proc
    with _lock:
        proc = _proc
        if proc is None:
            return False
        try:
            alive = proc.poll() is None
        except Exception:
            alive = False
        if not alive:
            _proc = None
        return alive


def start(text: str, voice: str | None = None, rate: str | int | None = None) -> int:
    """Speak `text`; barges any current utterance. Returns pid."""
    global _proc
    if sys.platform != "darwin":
        raise RuntimeError("Apple read-aloud needs macOS (/usr/bin/say)")
    cmd = [SAY_BIN]
    if voice:
        cmd += ["-v", str(voice)]
    if rate:
        cmd += ["-r", str(rate)]
    cmd.append(text)
    with _lock:
        _stop_locked()
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _proc = proc
        return proc.pid


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        return Path.home() / ".hermes"


def latest_assistant_texts(limit: int = 50, home: Path | None = None) -> list:
    """Chronological assistant texts of the most recently started session.

    Best-effort by design (raw read-only SQL, no internal imports): [] on
    any failure — callers fall back to a usage hint, never an exception."""
    try:
        base = Path(home) if home is not None else _hermes_home()
        db = base / "state.db"
        if not db.is_file():
            return []
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT id FROM sessions ORDER BY started_at DESC LIMIT 1").fetchone()
            if not row:
                return []
            rows = con.execute(
                "SELECT content FROM messages WHERE session_id = ? AND role = 'assistant'"
                " AND content IS NOT NULL ORDER BY id DESC LIMIT ?",
                (row[0], limit),
            ).fetchall()
        finally:
            con.close()
        return [c for c in (str(r[0]).strip() for r in rows) if c][::-1]
    except Exception:
        return []


USAGE = "usage: /say [text|number|stop] — bare /say reads the last reply"

RESTORE_TIP = "Tip: TUI patch missing since an update — `hermes speak-patch install`, rebuild, restart to restore Ctrl+S."

MODE_FILE = "speak-aloud.mode"  # Shared with the TUI backend (speak.mode RPC reads/writes the same file).
MODES = ("once", "always")


def _mode_file(home=None) -> Path:
    base = Path(home) if home is not None else _hermes_home()
    return base / MODE_FILE


def get_mode(home=None) -> str:
    try:
        mode = _mode_file(home).read_text().strip().lower()
        return mode if mode in MODES else "once"
    except Exception:
        return "once"


def set_mode(mode: str, home=None) -> tuple:
    """Persist auto-speak mode. Returns (mode, stopped)."""
    mode = str(mode or "").strip().lower()
    if mode not in MODES:
        raise ValueError("mode must be 'always' or 'once'")
    stopped = stop() if mode == "once" else False
    _mode_file(home).write_text(mode + "\n")
    return mode, stopped


def hermes_tree() -> Path | None:
    """Installed Hermes source tree, or None when it can't be located."""
    try:
        import hermes_constants

        return Path(hermes_constants.__file__).resolve().parent
    except Exception:
        pass
    fallback = Path.home() / ".hermes" / "hermes-agent"
    return fallback if (fallback / "tui_gateway").is_dir() else None


_CORE_MARKERS = (
    ("tui_gateway/methods_voice.py", '@method("speak.say")'),
    ("ui-tui/src/lib/platform.ts", "isSpeakAloudKey"),
    ("ui-tui/src/app/useInputHandlers.ts", "toggleSpeakAloud"),
)


def core_patch_present(tree: Path | None = None) -> bool | None:
    """True/False whether the TUI source patch is applied; None if unknown."""
    try:
        root = Path(tree) if tree is not None else hermes_tree()
        if root is None:
            return None
        for rel, marker in _CORE_MARKERS:
            if marker not in (root / rel).read_text():
                return False
        return True
    except Exception:
        return None


def handle_say(raw_args: str | None) -> str:
    """Plugin slash-command body: `/say ...` → human-readable result line."""
    arg = (raw_args or "").strip()
    if arg.lower() == "stop":
        silenced = stop()
        try:
            set_mode("once")
        except Exception:
            pass
        return "stopped." if silenced else "nothing playing."
    if arg.lower() in MODES:
        # Seen only when the TUI tree patch is gone (it intercepts these words
        # while present): save the preference into the shared mode file so auto
        # read-aloud resumes after `hermes speak-patch install` + rebuild.
        try:
            set_mode(arg.lower())
        except Exception as e:
            return f"could not save auto-mode: {e}"
        if arg.lower() == "always":
            return ("auto read-aloud noted — it needs the TUI patch to speak turns by itself: "
                    "`hermes speak-patch install`, rebuild, restart. (Saved; takes effect once restored.)")
        return "auto read-aloud OFF — back to on-demand. (stopped.)"
    if sys.platform != "darwin":
        return "Apple read-aloud needs macOS (/usr/bin/say)."
    text = resolve_text(arg, latest_assistant_texts())
    if not text:
        return "nothing to speak — start a conversation first"
    script = spoken_script(text)
    if not script.strip():
        return "nothing speakable after cleanup"
    try:
        start(script)
    except FileNotFoundError:
        return "Apple 'say' not found — read-aloud needs macOS."
    except Exception as e:
        return f"read-aloud failed: {e}"
    result = "speaking… (/say stop to stop)"
    if core_patch_present() is False:
        result += f"\n{RESTORE_TIP}"
    return result
