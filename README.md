# hermes-speak-aloud

Apple-native read-aloud for the Hermes agent terminal UI, on macOS, with no API keys. It speaks through `/usr/bin/say`, so you hear the same system voices as macOS Spoken Content.

## Why this exists

macOS Speak Selection (Option+Esc) reads the selected text through the accessibility API, which fullscreen terminal apps never expose. Highlighting a Hermes reply and pressing Option+Esc therefore does nothing. This plugin speaks through the Apple voice engine directly instead, so read-aloud works where the system hotkey cannot reach.

## Install

Copy this directory to `~/.hermes/plugins/speak-aloud` and enable it:

```sh
cp -r hermes-speak-aloud ~/.hermes/plugins/speak-aloud
hermes plugins enable speak-aloud
```

## Use

In the Hermes TUI:

- `/say` reads the last reply aloud, `/say <text>` speaks your own words, `/say 2` the second-to-last reply, `/say stop` stops playback.
- `/say always` speaks every future reply automatically until `/say once` switches back to on-demand. The choice is remembered across restarts.
- `Ctrl+S` reads the highlighted text (or the last reply when nothing is highlighted); pressing it again stops.

On the command line, `hermes say "some text"` speaks and `hermes say --stop` stops.

For a system-wide hotkey that works in every app, bind `~/.local/bin/speak-selection` (companion script, not included here) to a key in skhd; inside Hermes the options above are enough.

## How it works

The plugin registers a `/say` slash command, which Hermes reaches directly without spending an agent turn, plus the `hermes say` command. Speech itself is one `/usr/bin/say` process at a time; starting a new utterance stops the previous one. The auto mode lives in a small `speak-aloud.mode` file in your Hermes home, shared with the optional TUI source patch.

`speak-tui.patch` holds the matching Hermes source changes (instant `/say`, `Ctrl+S`, turn-completion hook) for the NousResearch/hermes-agent tree. If a Hermes update wipes an applied patch, `/say` keeps working through this plugin and tells you the one command that restores the rest: `hermes speak-patch install`, followed by a rebuild and restart. Check the state anytime with `hermes speak-patch status`.

## Tests

```sh
python -m pytest test_say_engine.py -q
```

Nineteen tests cover text resolution, the speech process lifecycle, mode persistence, patch detection, and the restore hint. They run without Hermes installed and make no sound (process spawning is mocked).

## License

MIT. The `speak-tui.patch` file applies against the NousResearch/hermes-agent source tree.
