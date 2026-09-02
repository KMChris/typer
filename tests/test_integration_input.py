"""Sends real keystrokes into a Tk window. Run with: pytest -m integration"""

import ctypes
import threading
import tkinter as tk

import pytest

from typer_app.engine import windows
from typer_app.engine.input_win import WindowsSender
from typer_app.engine.typing import Control, TypingJob, TypingSettings

pytestmark = pytest.mark.integration

SAMPLE = "Zażółć gęślą jaźń! (x+y)\tok\nsecond line"


def type_into_tk(text: str, settings: TypingSettings):
    root = tk.Tk()
    root.title("Typer integration target")
    root.geometry("500x300+200+200")
    widget = tk.Text(root, font=("Segoe UI", 12))
    widget.pack(fill="both", expand=True)
    seen: list[str] = []
    widget.bind("<Shift-Return>", lambda e: seen.append("shift_enter"))
    widget.bind("<Control-Return>", lambda e: seen.append("ctrl_enter"))
    result = {}

    def work():
        hwnd = ctypes.windll.user32.GetParent(widget.winfo_id())
        result["focused"] = windows.focus(hwnd)
        job = TypingJob(text, settings, WindowsSender(), Control())
        result["ok"] = job.run()
        root.after(200, root.quit)

    def begin():
        widget.focus_force()
        threading.Thread(target=work, daemon=True).start()

    root.after(400, begin)
    root.mainloop()
    result["text"] = widget.get("1.0", "end-1c")
    result["events"] = seen
    root.destroy()
    return result


@pytest.mark.parametrize("method", ["unicode", "keys"])
def test_shift_enter_and_unicode_text(method):
    settings = TypingSettings(char_delay_ms=8, jitter_pct=0, newline_mode="shift_enter", input_method=method)
    result = type_into_tk(SAMPLE, settings)
    assert result["focused"]
    assert result["ok"]
    assert result["text"] == SAMPLE
    assert result["events"] == ["shift_enter"]


def test_ctrl_enter_and_instant_mode():
    settings = TypingSettings(newline_mode="ctrl_enter", instant=True)
    result = type_into_tk("alpha\nbeta", settings)
    assert result["events"] == ["ctrl_enter"]
    assert result["text"].startswith("alpha")
