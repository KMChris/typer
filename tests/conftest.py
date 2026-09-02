from __future__ import annotations

import pytest

from typer_app.engine.keys import combo_id
from typer_app.engine.typing import Control


class FakeSender:
    """Records every call instead of touching the OS."""

    def __init__(self, clipboard: str = "") -> None:
        self.ops: list[tuple] = []
        self.clipboard = clipboard

    def text_char(self, ch: str, method: str = "unicode") -> None:
        self.ops.append(("char", ch, method))

    def key_tap(self, combo) -> None:
        self.ops.append(("key", combo_id(combo)))

    def key_down(self, key: str) -> None:
        self.ops.append(("down", key))

    def key_up(self, key: str) -> None:
        self.ops.append(("up", key))

    def set_clipboard(self, text: str) -> None:
        self.clipboard = text
        self.ops.append(("clip", text))

    def get_clipboard(self):
        return self.clipboard

    def mouse_move(self, x, y) -> None:
        self.ops.append(("move", x, y))

    def mouse_click(self, button="left", count=1, x=None, y=None) -> None:
        self.ops.append(("click", button, count, x, y))

    def mouse_button(self, button, down) -> None:
        self.ops.append(("button", button, down))

    def mouse_scroll(self, dy=0, dx=0) -> None:
        self.ops.append(("scroll", dy, dx))

    def wait_modifiers_released(self, timeout=1.5) -> bool:
        return True

    def release_modifiers(self) -> None:
        self.ops.append(("release_modifiers",))

    @property
    def chars(self) -> str:
        return "".join(op[1] for op in self.ops if op[0] == "char")

    @property
    def keys(self) -> list[str]:
        return [op[1] for op in self.ops if op[0] == "key"]

    @property
    def kinds(self) -> list[str]:
        return [op[0] for op in self.ops]


class InstantControl(Control):
    """Records requested waits and returns immediately (still honours cancellation)."""

    def __init__(self) -> None:
        super().__init__()
        self.waits: list[float] = []

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        return not self.cancelled


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


@pytest.fixture
def control() -> InstantControl:
    return InstantControl()
