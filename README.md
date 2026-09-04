# Typer

Windows desktop app that types text into any window through simulated keyboard input: with human-like timing,
Shift+Enter newlines, macros, presets and placeholders filled from a CSV file. Python backend, HTML/CSS/JS
frontend rendered by pywebview (Edge WebView2). Published in the Microsoft Store as **Typer Macro**.

![Typer: text with placeholders, CSV data and typing speed in one view](https://github.com/user-attachments/assets/9b24ac5d-70e1-4144-bb07-054d0b9ba4b7)

## Features

- **Target window**: Typer remembers the last active window (the one that was in front before) or uses a window
  chosen from a list. Before it starts, it activates that window and counts down (3 s by default).
- **Timing**: delay between characters with randomness, extra pauses after a word, punctuation and a new line,
  optional "human" typos (neighbouring key, swapped letters, missing AltGr; noticed at once or a few characters
  later and corrected with Backspace, sometimes several in a row), instant mode (lines pasted through the clipboard).
- **Keys**: new line as Enter, Shift+Enter, Ctrl+Enter or skipped; a key at the end (e.g. Enter to send a
  message); key-code compatibility mode for games, VM consoles and remote desktop.
- **Fragments and position**: the text can be split into fragments (whole text, lines or paragraphs). Typer keeps
  the position like a media player: "next" types the next fragment, "previous" types the previous one again,
  "start" types everything from the current position, "stop" aborts and rewinds to the start.
- **Repeat and CSV**: N repetitions with a pause, or one repetition per CSV row. `{column}` placeholders from the
  file plus built-in ones: `{n}`, `{total}`, `{date}`, `{time}`, `{datetime}`, `{clipboard}`, `{rand:1-100}`,
  `{rand:a|b|c}`, `{uuid}`. `{{` and `}}` produce literal braces.
- **Macros**: sequences of text, key combinations, pauses, mouse moves, clicks, drags and scrolling, and window
  activation. Recording from the keyboard and mouse, step-by-step editing, a global hotkey for every macro.
- **Presets**: text together with its settings, full-window preview on click, JSON import and export.
- **Global hotkeys** (function keys by default): `F7` start in the active window / pause, `F5` stop and rewind,
  `F6` previous fragment, `F8` next fragment, `F9` record a macro. While a job runs, `Esc` stops it too. Everything
  can be changed in the settings.
- Light and dark theme, Polish and English, the window title bar painted in the app colours.

![Macro editor: steps such as window activation, clicks, text and key combinations](https://github.com/user-attachments/assets/886bbc38-96a7-4eab-bde0-60c63f7fda5b)

## Running from source

```bat
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m typer_app
```

Requires Windows 10/11 with the WebView2 Runtime (built into Windows 11).

## Tests

```bat
.venv\Scripts\python -m pytest
```

Integration tests send real keystrokes to a Tk window and are skipped by default:

```bat
.venv\Scripts\python -m pytest -m integration
```

## Building the exe

```bat
build.bat
```

The script creates `.venv`, installs the dependencies, renders the icon, runs the tests and builds the
`dist\Typer\` folder (PyInstaller `--onedir`). The executable is `dist\Typer\Typer.exe`.

## Microsoft Store package (MSIX)

```bat
build_msix.bat
```

Builds the app like `build.bat`, renders the package assets (icons in every size), fills `tools\msix\AppxManifest.xml`
with the identity from `tools\msix\identity.json` (values from Partner Center) and packs
`dist\msix\Typer_1.0.0.0_x64.msix` with the Windows SDK tools. The Store screenshots and listing images come from
`.venv\Scripts\python tools\store_screenshots.py` (output in `dist\store\`). The Partner Center texts are in
`tools\store\`, the packaging and local test details in `tools\msix\README.md`.

## Data

Settings, presets and macros are stored as JSON in `%APPDATA%\Typer`. If a `portable.txt` file exists next to
`Typer.exe`, the data goes to a `data\` subfolder instead (portable mode).

## Layout

- `src/typer_app/engine/`: the engine (SendInput, hotkeys, windows, templates, macros, session).
- `src/typer_app/api.py`: the JS-Python bridge; `app.py`: the window and service start-up.
- `src/typer_app/ui/`: the frontend (`index.html`, `app.css`, `app.js`, `i18n.js`).
- `tools/`: `make_icon.py` (icon), `uicheck.py` (automated window check), `make_msix.py` (MSIX package),
  `make_store_assets.py` (package icons and Store images), `store_screenshots.py` (Store screenshots);
  `tools/msix/`: manifest template and package identity; `tools/store/`: Store listing texts and the privacy policy.
