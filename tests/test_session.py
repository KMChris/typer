import time

import pytest

from conftest import FakeSender, InstantControl
from typer_app.engine.macro import Macro, Step
from typer_app.engine.session import RunPlan, Session, SessionError, Target
from typer_app.engine.typing import Control, TypingSettings


class Harness:
    def __init__(self, control=None, focus_ok=True, own_foreground=False, auto_hwnd=42):
        self.sender = FakeSender()
        self.events: list[tuple[str, dict]] = []
        self.focused: list[int] = []
        self.session = Session(
            self.sender,
            lambda name, payload: self.events.append((name, payload)),
            focus_window=lambda hwnd: self.focused.append(hwnd) or focus_ok,
            resolve_auto_target=lambda: auto_hwnd,
            foreground_is_own=lambda: own_foreground,
            focus_by_title=lambda title: True,
            control=control or InstantControl(),
        )

    def names(self):
        return [name for name, _ in self.events]

    def finished(self):
        return next(payload for name, payload in self.events if name == "finished")

    def run(self, plan, rows=None):
        self.session.start_typing(plan, rows)
        self.session.join(5)
        assert self.session.state == "idle"


def plan(**overrides) -> RunPlan:
    data = {"text": "hi", "settings": {"char_delay_ms": 0, "jitter_pct": 0}, "countdown_s": 2}
    data.update(overrides)
    return RunPlan.from_dict(data)


def test_plan_from_dict_clamps():
    parsed = RunPlan.from_dict({"repeat_count": 0, "repeat_interval_ms": -1, "countdown_s": 999, "target": {"mode": "x", "hwnd": "7"}})
    assert parsed.repeat_count == 1 and parsed.repeat_interval_ms == 0 and parsed.countdown_s == 120
    assert parsed.target == Target(mode="auto", hwnd=7)


def test_typing_flow_emits_countdown_progress_and_finish():
    h = Harness()
    h.run(plan(text="ab"))
    assert h.focused == [42]
    assert h.sender.chars == "ab"
    countdowns = [p["seconds"] for n, p in h.events if n == "countdown"]
    assert countdowns == [2, 1, 0]
    states = [p["state"] for n, p in h.events if n == "state"]
    assert states == ["countdown", "running", "idle"]
    assert h.finished()["reason"] == "done"
    progress = [p for n, p in h.events if n == "progress"]
    assert progress[-1]["percent"] == 100


def test_csv_rows_drive_repetitions():
    h = Harness()
    rows = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    h.run(plan(text="Hi {name} {n}/{total}\n", use_csv_rows=True, repeat_interval_ms=10), rows)
    assert h.sender.chars == "Hi A 1/3Hi B 2/3Hi C 3/3"
    assert h.sender.keys == ["enter"] * 3
    assert 0.01 in h.session._control.waits


def test_repeat_count_cycles_rows_when_not_bound_to_csv():
    h = Harness()
    h.run(plan(text="{name}", repeat_count=3), [{"name": "x"}, {"name": "y"}])
    assert h.sender.chars == "xyx"


def test_target_modes():
    h = Harness()
    h.run(plan(target={"mode": "window", "hwnd": 7}))
    assert h.focused == [7]
    h = Harness()
    h.run(plan(target={"mode": "foreground"}))
    assert h.focused == []


def test_blocked_when_focus_fails_or_own_window_active():
    h = Harness(focus_ok=False)
    h.run(plan())
    assert h.sender.ops == []
    assert h.finished()["reason"] == "blocked"
    assert ("notice", {"level": "error", "code": "focus_failed"}) in h.events

    h = Harness(own_foreground=True)
    h.run(plan())
    assert h.finished()["reason"] == "blocked"
    assert any(p.get("code") == "own_window" for n, p in h.events if n == "notice")


def test_rejects_empty_text_and_concurrent_starts():
    h = Harness(control=Control())
    with pytest.raises(SessionError, match="empty_text"):
        h.session.start_typing(plan(text="   "))
    h.session.start_typing(plan(text="x" * 200, settings={"char_delay_ms": 20}, countdown_s=0))
    with pytest.raises(SessionError, match="busy"):
        h.session.start_typing(plan())
    h.session.stop()
    h.session.join(5)
    assert h.finished()["reason"] == "cancelled"
    assert len(h.sender.chars) < 200


def test_pause_resume_and_stop_with_real_control():
    h = Harness(control=Control())
    h.session.start_typing(plan(text="x" * 500, settings={"char_delay_ms": 5, "jitter_pct": 0}, countdown_s=0))
    time.sleep(0.05)
    h.session.pause()
    assert h.session.state == "paused"
    typed = len(h.sender.chars)
    time.sleep(0.1)
    assert len(h.sender.chars) == typed
    h.session.toggle_pause()
    assert h.session.state == "running"
    time.sleep(0.05)
    assert len(h.sender.chars) > typed
    h.session.stop()
    h.session.join(5)
    assert h.finished()["reason"] == "cancelled"


def test_macro_runs_through_session():
    h = Harness()
    macro = Macro(id="m", name="demo", steps=[Step("text", text="ok"), Step("key", key="enter")])
    h.session.start_macro(macro, TypingSettings(char_delay_ms=0, jitter_pct=0), Target(mode="foreground"), 0)
    h.session.join(5)
    assert h.sender.chars == "ok"
    assert h.sender.keys == ["enter"]
    assert h.finished() == {"reason": "done", "message": "", "kind": "macro"}
    with pytest.raises(SessionError, match="empty_macro"):
        h.session.start_macro(Macro(id="e", name="empty"), TypingSettings(), Target(), 0)
