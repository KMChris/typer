"""Turns text into simulated keystrokes with human-like timing.

The job only talks to a `Sender` and a `Control`, so it runs unchanged against
the real Windows sender and against fakes in tests.
"""

from __future__ import annotations

import random
import threading
import time
import unicodedata
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

# Human typos. A slip is noticed either at once or after a few more characters of the same word;
# then Backspace goes back to the mistake and the rest of the word is typed again.
TYPO_LOOKAHEAD = 8          # at most this many characters of a word are typed before a slip is noticed
TYPO_IMMEDIATE_P = 0.35     # chance that the wrong key is noticed right away
TYPO_WORD_END_P = 0.5       # otherwise: chance that the word is finished first (else noticed inside it)
TYPO_RETRY_P = 0.15         # chance of slipping again while retyping the correction
TYPO_MAX_ATTEMPTS = 3
TYPO_NOTICE_S = 0.08        # thinking time before the first Backspace, on top of the character delay
TYPO_KINDS = (("neighbour", 0.6), ("transpose", 0.15), ("omit", 0.1), ("double", 0.15))
TYPO_COST_STROKES = 8.5     # average extra keystrokes per slip (wrong ones, Backspaces, retyping)

_QWERTY_NEIGHBOURS = {
    "q": "wa", "w": "qes", "e": "wrd", "r": "etf", "t": "ryg", "y": "tuh", "u": "yij", "i": "uok",
    "o": "ipl", "p": "ol", "a": "qsz", "s": "adwx", "d": "sfec", "f": "dgrv", "g": "fhtb", "h": "gjyn",
    "j": "hkum", "k": "jli", "l": "ko", "z": "xa", "x": "zcs", "c": "xvd", "v": "cbf", "b": "vng",
    "n": "bmh", "m": "nj",
}
_BARE_LETTERS = {"ł": "l", "Ł": "L"}  # accented letters that NFD does not decompose


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


def bare_letter(ch: str) -> str:
    """The letter without its accent ("ą" -> "a"): what comes out when AltGr is missed."""
    if ch in _BARE_LETTERS:
        return _BARE_LETTERS[ch]
    decomposed = unicodedata.normalize("NFD", ch)
    return decomposed[0] if decomposed else ch


def typo_for(ch: str, rng: random.Random) -> str | None:
    """A plausible wrong key for a letter, keeping its case: a keyboard neighbour, or the bare
    letter when the right one needs AltGr (Polish diacritics)."""
    bare = bare_letter(ch)
    neighbours = _QWERTY_NEIGHBOURS.get(bare.lower())
    if not neighbours:
        return None
    wrong = bare.lower() if bare != ch and rng.random() < 0.6 else rng.choice(neighbours)
    return wrong.upper() if ch.isupper() else wrong


def burst_chance(typo_pct: float) -> float:
    """Chance that a character typed right after a slip is wrong as well (a run of typos)."""
    return min(0.4, max(0.1, 4 * typo_pct / 100))


def corrupt(text: str, rng: random.Random, burst: float) -> str:
    """`text` as a hurried typist enters it. The first character is always wrong and each later one
    with probability `burst`: a neighbouring key, two characters swapped, one dropped or doubled."""
    out: list[str] = []
    index = 0
    while index < len(text):
        ch = text[index]
        if index and rng.random() >= burst:
            out.append(ch)
            index += 1
            continue
        wrong = typo_for(ch, rng)
        following = text[index + 1] if index + 1 < len(text) else ""
        kinds = [(kind, weight) for kind, weight in TYPO_KINDS
                 if (kind != "neighbour" or wrong is not None)
                 and (kind != "transpose" or (following and following != ch))
                 and (kind != "omit" or following)]
        kind = rng.choices([kind for kind, _ in kinds], [weight for _, weight in kinds])[0]
        if kind == "neighbour":
            out.append(wrong)
        elif kind == "transpose":
            out.extend((following, ch))
            index += 1
        elif kind == "double":
            out.extend((ch, ch))
        index += 1  # "omit" adds nothing
    return "".join(out)


def common_prefix_len(a: str, b: str) -> int:
    length = 0
    for x, y in zip(a, b):
        if x != y:
            break
        length += 1
    return length


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
        total += letters * settings.typo_pct / 100.0 * (base * TYPO_COST_STROKES + TYPO_NOTICE_S)
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
        self._burst = burst_chance(settings.typo_pct)

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
        index = 0
        while index < total:
            if not self.control.checkpoint():
                return False
            ch = self.text[index]
            if ch.isalpha() and self.settings.typo_pct and self.rng.random() * 100 < self.settings.typo_pct:
                typed = self._slip(index, method)
                if typed < 0:
                    return False
                index += typed
            else:
                if ch == "\n":
                    self._newline()
                elif ch == "\t":
                    self.sender.key_tap(TAB)
                elif ch.isprintable():
                    self.sender.text_char(ch, method)
                index += 1
                if not self.control.wait(char_delay(ch, self.settings, self.rng)):
                    return False
            self.on_progress(index, total)
        return True

    def _type_run(self, text: str, method: str) -> bool:
        for ch in text:
            self.sender.text_char(ch, method)
            if not self.control.wait(char_delay(ch, self.settings, self.rng)):
                return False
        return True

    def _slip(self, start: int, method: str) -> int:
        """Type the rest of the word at `start` with a typo in it: notice the slip (at once or a few
        characters later), Backspace to the mistake and retype the ending. Returns how many source
        characters were typed, or -1 when interrupted."""
        end = start
        while (end < len(self.text) and end - start < TYPO_LOOKAHEAD
               and self.text[end].isprintable() and not self.text[end].isspace()):
            end += 1
        word = self.text[start:end]
        if len(word) == 1 or self.rng.random() < TYPO_IMMEDIATE_P:
            noticed = 1
        elif self.rng.random() < TYPO_WORD_END_P:
            noticed = len(word)
        else:
            noticed = self.rng.randint(2, len(word))
        target = word[:noticed]
        base = self.settings.char_delay_ms / 1000.0
        typed = corrupt(target, self.rng, self._burst)
        attempts = 0
        while True:
            if not self._type_run(typed, method):
                return -1
            if not self.control.wait(TYPO_NOTICE_S + base * self.rng.uniform(1.5, 3.0)):
                return -1
            keep = common_prefix_len(typed, target)
            for _ in range(len(typed) - keep):
                self.sender.key_tap(BACKSPACE)
                if not self.control.wait(base * self.rng.uniform(0.4, 0.8)):
                    return -1
            target = target[keep:]
            attempts += 1
            if not target or attempts >= TYPO_MAX_ATTEMPTS or self.rng.random() >= TYPO_RETRY_P:
                break
            typed = corrupt(target, self.rng, self._burst)
        return noticed if self._type_run(target, method) else -1

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
