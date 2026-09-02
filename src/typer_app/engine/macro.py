"""Macros: editable step sequences that can be recorded from real input and replayed."""

from __future__ import annotations

import dataclasses
import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from .keys import MODIFIER_ORDER, VK_TO_NAME, combo_id, is_modifier, parse_combo
from .typing import Control, TypingJob, TypingSettings

log = logging.getLogger(__name__)

STEP_KINDS = ("text", "key", "wait", "mouse_move", "mouse_click", "mouse_down", "mouse_up", "mouse_scroll", "focus")
MOUSE_BUTTONS = ("left", "right", "middle")
MAX_WAIT_MS = 600_000
STEP_GAP_S = 0.02  # small breather after key and mouse steps so applications keep up


def _int(value: object, default: int = 0, low: int | None = None, high: int | None = None) -> int:
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        result = default
    if low is not None:
        result = max(low, result)
    if high is not None:
        result = min(high, result)
    return result


@dataclass
class Step:
    kind: str
    text: str = ""
    key: str = ""
    ms: int = 0
    x: int | None = None
    y: int | None = None
    button: str = "left"
    count: int = 1
    dx: int = 0
    dy: int = 0
    title: str = ""

    @property
    def has_point(self) -> bool:
        return self.x is not None and self.y is not None

    def to_dict(self) -> dict:
        data: dict = {"kind": self.kind}
        if self.kind == "text":
            data["text"] = self.text
        elif self.kind == "key":
            data["key"] = self.key
        elif self.kind == "wait":
            data["ms"] = self.ms
        elif self.kind == "focus":
            data["title"] = self.title
        else:
            if self.has_point:
                data["x"], data["y"] = self.x, self.y
            if self.kind in ("mouse_click", "mouse_down", "mouse_up"):
                data["button"] = self.button
            if self.kind == "mouse_click":
                data["count"] = self.count
            if self.kind == "mouse_scroll":
                data["dx"], data["dy"] = self.dx, self.dy
        return data

    @classmethod
    def from_dict(cls, data: object) -> "Step":
        if not isinstance(data, dict):
            raise ValueError("step must be an object")
        kind = str(data.get("kind", ""))
        if kind not in STEP_KINDS:
            raise ValueError(f"unknown step kind: {kind}")
        key = str(data.get("key", "") or "").strip()
        if kind == "key":
            key = combo_id(parse_combo(key))
        button = str(data.get("button", "left") or "left")
        if button not in MOUSE_BUTTONS:
            raise ValueError(f"unknown mouse button: {button}")
        x, y = data.get("x"), data.get("y")
        if x is None or y is None or x == "" or y == "":
            point = (None, None)
        else:
            point = (_int(x), _int(y))
        return cls(
            kind=kind,
            text=str(data.get("text", "") or ""),
            key=key,
            ms=_int(data.get("ms", 0), 0, 0, MAX_WAIT_MS),
            x=point[0],
            y=point[1],
            button=button,
            count=_int(data.get("count", 1), 1, 1, 3),
            dx=_int(data.get("dx", 0), 0, -100, 100),
            dy=_int(data.get("dy", 0), 0, -100, 100),
            title=str(data.get("title", "") or "").strip(),
        )


@dataclass
class Macro:
    id: str
    name: str
    steps: list[Step] = field(default_factory=list)
    hotkey: str = ""
    repeat: int = 1
    interval_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "hotkey": self.hotkey,
            "repeat": self.repeat,
            "interval_ms": self.interval_ms,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: object) -> "Macro":
        if not isinstance(data, dict):
            raise ValueError("macro must be an object")
        hotkey = str(data.get("hotkey", "") or "").strip()
        if hotkey:
            hotkey = combo_id(parse_combo(hotkey))
        steps = []
        for index, raw in enumerate(data.get("steps", []) or []):
            try:
                steps.append(Step.from_dict(raw))
            except ValueError as exc:
                raise ValueError(f"step {index + 1}: {exc}") from exc
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex),
            name=str(data.get("name", "") or "").strip() or "Macro",
            steps=steps,
            hotkey=hotkey,
            repeat=_int(data.get("repeat", 1), 1, 1, 10_000),
            interval_ms=_int(data.get("interval_ms", 0), 0, 0, MAX_WAIT_MS),
        )


StepProgressFn = Callable[[int, int, int, int], None]


def run_macro(
    macro: Macro,
    settings: TypingSettings,
    sender,
    control: Control,
    *,
    focus_by_title: Callable[[str], bool] | None = None,
    on_progress: StepProgressFn | None = None,
    rng: random.Random | None = None,
) -> bool:
    """Replay a macro. Returns False when cancelled."""
    # The final key belongs to the main typer flow, not to text steps inside a macro.
    text_settings = dataclasses.replace(settings, final_key="")
    total = len(macro.steps)
    for repetition in range(macro.repeat):
        for index, step in enumerate(macro.steps):
            if not control.checkpoint():
                return False
            if on_progress:
                on_progress(index, total, repetition + 1, macro.repeat)
            if not _run_step(step, text_settings, sender, control, focus_by_title, rng):
                return False
        if repetition < macro.repeat - 1 and macro.interval_ms:
            if not control.wait(macro.interval_ms / 1000):
                return False
    return True


def _run_step(step: Step, settings, sender, control, focus_by_title, rng) -> bool:
    kind = step.kind
    if kind == "text":
        return TypingJob(step.text, settings, sender, control, rng=rng).run()
    if kind == "wait":
        return control.wait(step.ms / 1000)
    if kind == "key":
        sender.key_tap(parse_combo(step.key))
    elif kind == "mouse_move":
        if step.has_point:
            sender.mouse_move(step.x, step.y)
    elif kind == "mouse_click":
        sender.mouse_click(step.button, step.count, step.x, step.y)
    elif kind in ("mouse_down", "mouse_up"):
        if step.has_point:
            sender.mouse_move(step.x, step.y)
        sender.mouse_button(step.button, kind == "mouse_down")
    elif kind == "mouse_scroll":
        if step.has_point:
            sender.mouse_move(step.x, step.y)
        sender.mouse_scroll(step.dy, step.dx)
    elif kind == "focus":
        if focus_by_title and not focus_by_title(step.title):
            log.warning("macro focus step: no window matching %r", step.title)
    return control.wait(STEP_GAP_S)


@dataclass
class RawEvent:
    """One captured input event; `key` is a normalized key name or the typed character."""

    t: float
    type: str  # key_down, key_up, click, scroll
    key: str = ""
    x: int = 0
    y: int = 0
    button: str = "left"
    pressed: bool = False
    dx: int = 0
    dy: int = 0


def events_to_steps(
    events: list[RawEvent],
    *,
    min_gap_ms: int = 120,
    stop_hotkey: str = "",
    double_click_ms: int = 400,
) -> list[Step]:
    """Collapse raw events into editable steps: text runs, key combos, clicks, drags, scrolls and waits."""
    steps: list[Step] = []
    modifiers: set[str] = set()
    text: list[str] = []
    pending: dict[str, tuple[int, int, float]] = {}
    last_t: float | None = None
    last_click_t = -1.0

    def flush_text() -> None:
        if text:
            steps.append(Step("text", text="".join(text)))
            text.clear()

    def gap(t: float) -> None:
        nonlocal last_t
        if last_t is not None:
            ms = round((t - last_t) * 1000)
            if ms >= min_gap_ms:
                flush_text()
                steps.append(Step("wait", ms=min(MAX_WAIT_MS, round(ms / 10) * 10)))
        last_t = t

    for event in events:
        if event.type == "key_down":
            if is_modifier(event.key):
                modifiers.add(event.key)
                continue
            gap(event.t)
            plain = not (modifiers - {"shift"})
            if plain and len(event.key) == 1:
                text.append(event.key)
            elif plain and event.key == "space":
                text.append(" ")
            else:
                flush_text()
                combo = "+".join([m for m in MODIFIER_ORDER if m in modifiers] + [event.key])
                steps.append(Step("key", key=combo_id(parse_combo(combo))))
        elif event.type == "key_up":
            modifiers.discard(event.key)
        elif event.type == "click":
            if event.pressed:
                gap(event.t)
                flush_text()
                pending[event.button] = (event.x, event.y, event.t)
                continue
            start = pending.pop(event.button, None)
            if start is None:
                continue
            x0, y0, t0 = start
            if abs(event.x - x0) > 4 or abs(event.y - y0) > 4:
                steps.append(Step("mouse_down", x=x0, y=y0, button=event.button))
                steps.append(Step("mouse_up", x=event.x, y=event.y, button=event.button))
                continue
            # Merge quick repeated clicks at the same spot into a double or triple click.
            recent = steps[-2:] if len(steps) >= 2 and steps[-1].kind == "wait" else steps[-1:]
            previous = recent[0] if recent else None
            if (previous is not None and previous.kind == "mouse_click" and previous.button == event.button
                    and previous.x == x0 and previous.y == y0 and previous.count < 3
                    and (t0 - last_click_t) * 1000 <= double_click_ms):
                if len(recent) == 2:
                    steps.pop()
                previous.count += 1
            else:
                steps.append(Step("mouse_click", x=x0, y=y0, button=event.button))
            last_click_t = t0
        elif event.type == "scroll":
            gap(event.t)
            flush_text()
            previous = steps[-1] if steps else None
            if previous is not None and previous.kind == "mouse_scroll" and previous.x == event.x and previous.y == event.y:
                previous.dx = max(-100, min(100, previous.dx + event.dx))
                previous.dy = max(-100, min(100, previous.dy + event.dy))
            else:
                steps.append(Step("mouse_scroll", x=event.x, y=event.y, dx=event.dx, dy=event.dy))
    flush_text()

    # Trailing waits, the stop hotkey and the window switch back to Typer are not part of the macro.
    trailing_keys = {"alt+tab", "alt+escape"}
    if stop_hotkey:
        trailing_keys.add(combo_id(parse_combo(stop_hotkey)))
    while steps and (steps[-1].kind == "wait" or (steps[-1].kind == "key" and steps[-1].key in trailing_keys)):
        steps.pop()
    return steps


class MacroRecorder:
    """Captures keyboard and mouse input through pynput hooks while recording."""

    def __init__(
        self,
        ignore_point: Callable[[int, int], bool] | None = None,
        ignore_keys: Callable[[], bool] | None = None,
    ) -> None:
        # ignore_point: clicks and scrolls at that screen position are dropped (used for Typer's own window).
        # ignore_keys: while it returns True, non-modifier keys are dropped (typing inside Typer itself).
        self._ignore_point = ignore_point
        self._ignore_keys = ignore_keys
        self._events: list[RawEvent] = []
        self._modifiers: set[str] = set()
        self._t0 = 0.0
        self._keyboard = None
        self._mouse = None
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._keyboard is not None

    def start(self) -> None:
        from pynput import keyboard, mouse  # hooks are only installed while recording

        with self._lock:
            if self._keyboard is not None:
                return
            self._events = []
            self._modifiers = set()
            self._t0 = time.monotonic()
            self._keyboard = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self._mouse = mouse.Listener(on_click=self._on_click, on_scroll=self._on_scroll)
            self._keyboard.start()
            self._mouse.start()

    def stop(self, stop_hotkey: str = "") -> list[Step]:
        with self._lock:
            for listener in (self._keyboard, self._mouse):
                if listener is not None:
                    listener.stop()
            self._keyboard = None
            self._mouse = None
            events = list(self._events)
        return events_to_steps(events, stop_hotkey=stop_hotkey)

    def _now(self) -> float:
        return time.monotonic() - self._t0

    def _key_name(self, key) -> str:
        code = getattr(key, "value", key)  # pynput.Key members wrap a KeyCode
        vk = getattr(code, "vk", None)
        char = getattr(code, "char", None)
        if vk in VK_TO_NAME:
            return VK_TO_NAME[vk]
        held = self._modifiers - {"shift"}
        if vk is not None and held and (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A):
            return chr(vk).lower()  # with Ctrl/Alt held pynput reports control characters
        if char and char.isprintable():
            return char
        if vk is not None:
            from .input_win import vk_char

            printed = vk_char(vk)
            return printed.lower() if printed else ""
        return ""

    def _on_press(self, key) -> None:
        name = self._key_name(key)
        if not name:
            return
        if is_modifier(name):
            self._modifiers.add(name)
        elif self._ignore_keys and self._ignore_keys():
            return
        self._events.append(RawEvent(self._now(), "key_down", key=name))

    def _on_release(self, key) -> None:
        name = self._key_name(key)
        if not name:
            return
        if is_modifier(name):
            self._modifiers.discard(name)
        elif self._ignore_keys and self._ignore_keys():
            return
        self._events.append(RawEvent(self._now(), "key_up", key=name))

    def _on_click(self, x, y, button, pressed) -> None:
        name = getattr(button, "name", "")
        if name not in MOUSE_BUTTONS:
            return
        if self._ignore_point and self._ignore_point(int(x), int(y)):
            return
        self._events.append(RawEvent(self._now(), "click", x=int(x), y=int(y), button=name, pressed=bool(pressed)))

    def _on_scroll(self, x, y, dx, dy) -> None:
        if self._ignore_point and self._ignore_point(int(x), int(y)):
            return
        self._events.append(RawEvent(self._now(), "scroll", x=int(x), y=int(y), dx=int(dx), dy=int(dy)))
