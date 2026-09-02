"""Turns text into simulated keystrokes with human-like timing.

The job only talks to a `Sender` and a `Control`, so it runs unchanged against
the real Windows sender and against fakes in tests.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable, Protocol

from .keys import KeyCombo, parse_combo

NEWLINE_MODES: dict[str, str] = {
    "enter": "enter",
    "shift_enter": "shift+enter",
    "ctrl_enter": "ctrl+enter",
    "none": "",
}
INPUT_METHODS = ("unicode", "keys")
PUNCTUATION = ".,;:!?"
BACKSPACE = KeyCombo("backspace")
TAB = KeyCombo("tab")
PASTE = KeyCombo("v", frozenset({"ctrl"}))

_QWERTY_NEIGHBOURS = {
    "q": "wa", "w": "qes", "e": "wrd", "r": "etf", "t": "ryg", "y": "tuh", "u": "yij", "i": "uok",
    "o": "ipl", "p": "ol", "a": "qsz", "s": "adwx", "d": "sfec", "f": "dgrv", "g": "fhtb", "h": "gjyn",
    "j": "hkum", "k": "jli", "l": "ko", "z": "xa", "x": "zcs", "c": "xvd", "v": "cbf", "b": "vng",
    "n": "bmh", "m": "nj",
}


class Sender(Protocol):
    def text_char(self, ch: str, method: str = "unicode") -> None: ...
    def key_tap(self, combo: KeyCombo) -> None: ...
    def set_clipboard(self, text: str) -> None: ...
    def get_clipboard(self) -> str | None: ...


@dataclass
class TypingSettings:
    char_delay_ms: float = 30.0
    jitter_pct: int = 25
    newline_mode: str = "enter"
    word_pause_ms: int = 0
    punct_pause_ms: int = 0
    newline_pause_ms: int = 0
    input_method: str = "unicode"
    instant: bool = False
    final_key: str = ""
    typo_pct: float = 0.0

    @classmethod
    def from_dict(cls, data: object) -> "TypingSettings":
        """Build settings from untrusted JSON, clamping every value into its valid range."""
        base = cls()
        if not isinstance(data, dict):
            return base

        def number(key: str, low: float, high: float, cast=float):
            try:
                value = cast(data.get(key, getattr(base, key)))
            except (TypeError, ValueError):
                value = getattr(base, key)
            return max(low, min(high, value))

        newline_mode = str(data.get("newline_mode", base.newline_mode))
        input_method = str(data.get("input_method", base.input_method))
        final_key = str(data.get("final_key", "") or "").strip()
        if final_key:
            try:
                parse_combo(final_key)
            except ValueError:
                final_key = ""
        return cls(
            char_delay_ms=number("char_delay_ms", 0, 5000),
            jitter_pct=number("jitter_pct", 0, 100, int),
            newline_mode=newline_mode if newline_mode in NEWLINE_MODES else base.newline_mode,
            word_pause_ms=number("word_pause_ms", 0, 60000, int),
            punct_pause_ms=number("punct_pause_ms", 0, 60000, int),
            newline_pause_ms=number("newline_pause_ms", 0, 60000, int),
            input_method=input_method if input_method in INPUT_METHODS else base.input_method,
            instant=bool(data.get("instant", base.instant)),
            final_key=final_key,
            typo_pct=number("typo_pct", 0, 50),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def newline_combo(self) -> KeyCombo | None:
        spec = NEWLINE_MODES[self.newline_mode]
        return parse_combo(spec) if spec else None


class Control:
    """Cancellation, skipping and pause shared by everything that runs in a session.

    `cancel()` ends the whole job; `skip()` only abandons the current piece of work
    (the runner decides what comes next and calls `clear_skip()`).
    """

    def __init__(self) -> None:
        self._cancel = threading.Event()
        self._skip = threading.Event()
        self._resume = threading.Event()
        self._resume.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def skipped(self) -> bool:
        return self._skip.is_set()

    @property
    def paused(self) -> bool:
        return not self._resume.is_set() and not self._cancel.is_set()

    def reset(self) -> None:
        self._cancel.clear()
        self._skip.clear()
        self._resume.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._resume.set()

    def skip(self) -> None:
        self._skip.set()

    def clear_skip(self) -> None:
        self._skip.clear()

    def pause(self) -> None:
        if not self._cancel.is_set():
            self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    def wait(self, seconds: float) -> bool:
        """Sleep, blocking while paused. Returns False as soon as the work is cancelled or skipped."""
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            if self._cancel.is_set() or self._skip.is_set():
                return False
            if not self._resume.is_set():
                self._resume.wait(0.05)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            if self._cancel.wait(min(remaining, 0.05)):
                return False

    def checkpoint(self) -> bool:
        return self.wait(0)


ProgressFn = Callable[[int, int], None]


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def char_delay(ch: str, settings: TypingSettings, rng: random.Random) -> float:
    """Seconds to wait after typing `ch`: base delay with jitter plus the extra pause for that character."""
    base = settings.char_delay_ms / 1000.0
    if settings.jitter_pct and base > 0:
        spread = settings.jitter_pct / 100.0
        base *= 1 + rng.uniform(-spread, spread)
    extra = 0
    if ch == "\n":
        extra = settings.newline_pause_ms
    elif ch == " ":
        extra = settings.word_pause_ms
    elif ch in PUNCTUATION:
        extra = settings.punct_pause_ms
    return base + extra / 1000.0


def typo_for(ch: str, rng: random.Random) -> str | None:
    """A plausible neighbouring key for a letter, keeping its case."""
    neighbours = _QWERTY_NEIGHBOURS.get(ch.lower())
    if not neighbours:
        return None
    wrong = rng.choice(neighbours)
    return wrong.upper() if ch.isupper() else wrong


def estimate_seconds(text: str, settings: TypingSettings) -> float:
    """Expected duration of typing `text` once (no jitter, average typo cost)."""
    text = normalize_text(text)
    if not text:
        return 0.0
    if settings.instant:
        lines = text.split("\n")
        pastes = sum(0.08 + min(0.4, len(line) / 50000) for line in lines if line)
        return pastes + (len(lines) - 1) * (0.05 + settings.newline_pause_ms / 1000.0) + 0.15
    base = settings.char_delay_ms / 1000.0
    total = len(text) * base
    total += text.count("\n") * settings.newline_pause_ms / 1000.0
    total += text.count(" ") * settings.word_pause_ms / 1000.0
    total += sum(text.count(p) for p in PUNCTUATION) * settings.punct_pause_ms / 1000.0
    if settings.typo_pct:
        letters = sum(1 for c in text if c.isalpha())
        total += letters * settings.typo_pct / 100.0 * base * 2.6
    return total


class TypingJob:
    """Types one piece of text. `run()` returns True when finished, False when cancelled."""

    def __init__(
        self,
        text: str,
        settings: TypingSettings,
        sender: Sender,
        control: Control,
        on_progress: ProgressFn | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.text = normalize_text(text)
        self.settings = settings
        self.sender = sender
        self.control = control
        self.on_progress = on_progress or (lambda done, total: None)
        self.rng = rng or random.Random()

    def run(self) -> bool:
        if not self.control.checkpoint():
            return False
        finished = self._run_instant() if self.settings.instant else self._run_keystrokes()
        if not finished:
            return False
        if self.settings.final_key:
            self.sender.key_tap(parse_combo(self.settings.final_key))
        return True

    def _newline(self) -> None:
        combo = self.settings.newline_combo()
        if combo is not None:
            self.sender.key_tap(combo)

    def _run_keystrokes(self) -> bool:
        total = len(self.text)
        method = self.settings.input_method
        for index, ch in enumerate(self.text):
            if not self.control.checkpoint():
                return False
            if ch == "\n":
                self._newline()
            elif ch == "\t":
                self.sender.key_tap(TAB)
            elif ch.isprintable():
                if self.settings.typo_pct and self.rng.random() * 100 < self.settings.typo_pct:
                    if not self._type_with_typo(ch, method):
                        return False
                else:
                    self.sender.text_char(ch, method)
            self.on_progress(index + 1, total)
            if not self.control.wait(char_delay(ch, self.settings, self.rng)):
                return False
        return True

    def _type_with_typo(self, ch: str, method: str) -> bool:
        wrong = typo_for(ch, self.rng)
        if wrong is None:
            self.sender.text_char(ch, method)
            return True
        base = self.settings.char_delay_ms / 1000.0
        self.sender.text_char(wrong, method)
        if not self.control.wait(base * 2):
            return False
        self.sender.key_tap(BACKSPACE)
        if not self.control.wait(base):
            return False
        self.sender.text_char(ch, method)
        return True

    def _run_instant(self) -> bool:
        """Paste line by line through the clipboard, keeping the configured Enter behaviour."""
        lines = self.text.split("\n")
        total = len(self.text)
        done = 0
        original = self.sender.get_clipboard()
        try:
            for index, line in enumerate(lines):
                if not self.control.checkpoint():
                    return False
                if line:
                    self.sender.set_clipboard(line)
                    self.sender.key_tap(PASTE)
                    # Give the target time to consume the clipboard before it changes again.
                    if not self.control.wait(0.08 + min(0.4, len(line) / 50000)):
                        return False
                done += len(line)
                if index < len(lines) - 1:
                    self._newline()
                    done += 1
                    if not self.control.wait(0.05 + self.settings.newline_pause_ms / 1000.0):
                        return False
                self.on_progress(done, total)
            return True
        finally:
            if original is not None:
                time.sleep(0.15)
                try:
                    self.sender.set_clipboard(original)
                except OSError:
                    pass
