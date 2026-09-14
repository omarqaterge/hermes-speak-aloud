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
- `/say always` speaks every future TUI reply automatically until `/say once` switches back to on-demand. The choice is remembered across restarts.

On the command line, `hermes say "some text"` speaks and `hermes say --stop` stops.

Global selection voices are separate macOS tooling, not Hermes functionality. The existing `~/.local/bin/speak-selection` and `~/.local/bin/speak-selection-andrew` scripts are invoked by the user's skhd bindings and work independently of this plugin.

## How it works

The plugin registers a `/say` slash command, which Hermes reaches directly without spending an agent turn, plus the `hermes say` command and a `post_llm_call` hook. The hook speaks finalized TUI replies only when `/say always` is enabled. Speech itself is one `/usr/bin/say` process at a time; starting a new utterance stops the previous one. The auto mode lives in the plugin's `speak-aloud.mode` file in your Hermes home.

There is no Hermes source patch, TUI hotkey handler, or rebuild step. Hermes updates leave this user-state plugin in place.

## Tests

```sh
python -m pytest test_say_engine.py -q
```

Twenty-seven tests cover text resolution, the speech process lifecycle, mode persistence, TUI-only automatic reply speech, plugin registration, and failure handling. They run without Hermes installed and make no sound (process spawning is mocked).

## License

MIT.
