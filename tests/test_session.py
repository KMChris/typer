import time

import pytest

from conftest import FakeSender, InstantControl
from typer_app.engine.macro import Macro, Step
from typer_app.engine.session import Item, RunPlan, Session, SessionError, Target, build_items, split_text
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

    def positions(self):
        return [p["last"] for n, p in self.events if n == "position"]

    def run(self, plan, rows=None, mode="all"):
        self.session.start_typing(plan, rows, mode)
        self.session.join(5)
        assert self.session.state == "idle"


def plan(**overrides) -> RunPlan:
    data = {"text": "hi", "settings": {"char_delay_ms": 0, "jitter_pct": 0}, "countdown_s": 2}
    data.update(overrides)
    return RunPlan.from_dict(data)


def test_plan_from_dict_clamps():
    parsed = RunPlan.from_dict({"repeat_count": 0, "repeat_interval_ms": -1, "countdown_s": 999,
                                "split": "words", "target": {"mode": "x", "hwnd": "7"}})
    assert parsed.repeat_count == 1 and parsed.repeat_interval_ms == 0 and parsed.countdown_s == 120
    assert parsed.split == "whole"
    assert parsed.target == Target(mode="auto", hwnd=7)
    assert RunPlan.from_dict(parsed.to_dict()).split == "whole"


def test_split_text_modes():
    text = "one\ntwo\r\n\n  \nthree\nfour\n"
    assert split_text(text, "whole") == ["one\ntwo\n\n  \nthree\nfour\n"]
    assert split_text(text, "lines") == ["one", "two", "three", "four"]
    assert split_text(text, "paragraphs") == ["one\ntwo", "three\nfour"]
    assert split_text("", "lines") == [""]


def test_build_items():
    rows = [{"name": "A"}, {"name": "B"}]
    whole = build_items(plan(text="x", repeat_count=3), rows)
    assert whole == [Item("x", rows[0], 0), Item("x", rows[1], 1), Item("x", rows[0], 0)]
    per_row = build_items(plan(text="a\nb", split="lines", use_csv_rows=True), rows)
    assert per_row == [Item("a", rows[0], 0), Item("b", rows[0], 0), Item("a", rows[1], 1), Item("b", rows[1], 1)]
    assert build_items(plan(text="a\nb", split="lines", repeat_count=2), None) == [
        Item("a"), Item("b"), Item("a"), Item("b")]


def test_typing_flow_emits_countdown_progress_position_and_finish():
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
    assert h.positions() == [-1, 0]  # before the run, after the only item
    assert h.session.position() == {"last": 0, "total": 1}


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


def test_lines_split_types_each_fragment_with_final_key():
    h = Harness()
    h.run(plan(text="a\nb\nc", split="lines", repeat_interval_ms=10, settings={"char_delay_ms": 0, "final_key": "enter"}))
    assert h.sender.chars == "abc"
    assert h.sender.keys == ["enter"] * 3
    assert h.session._control.waits.count(0.01) == 2
    assert h.positions() == [-1, 0, 1, 2]


def test_next_and_prev_type_single_items_and_move_the_playhead():
    h = Harness()
    lines = plan(text="a\nb\nc", split="lines", countdown_s=0)
    h.run(lines, mode="next")
    assert h.sender.chars == "a" and h.session.position()["last"] == 0
    h.run(lines, mode="next")
    assert h.sender.chars == "ab" and h.session.position()["last"] == 1
    h.run(lines, mode="prev")
    assert h.sender.chars == "aba" and h.session.position()["last"] == 0
    h.run(lines, mode="prev")  # at the first item prev types it again
    assert h.sender.chars == "abaa" and h.session.position()["last"] == 0
    h.run(lines, mode="next")
    h.run(lines, mode="next")
    assert h.sender.chars == "abaabc" and h.session.position()["last"] == 2
    h.run(lines, mode="next")  # after the last item "next" wraps to the first one
    assert h.sender.chars == "abaabca" and h.session.position()["last"] == 0
    h.run(lines, mode="all")  # "start" continues after the playhead
    assert h.sender.chars == "abaabcabc" and h.session.position()["last"] == 2
    h.run(lines, mode="all")  # and wraps once the list is exhausted
    assert h.sender.chars == "abaabcabcabc" and h.session.position()["last"] == 2
    h.session.reset()
    h.run(lines, mode="prev")  # from the start "prev" wraps to the last item
    assert h.sender.chars == "abaabcabcabcc" and h.session.position()["last"] == 2


def test_reset_moves_playhead_to_start_and_shrunken_plan_is_clamped():
    h = Harness()
    lines = plan(text="a\nb\nc", split="lines", countdown_s=0)
    h.run(lines, mode="next")
    h.run(lines, mode="next")
    assert h.session.position()["last"] == 1
    h.session.reset()
    assert h.session.position() == {"last": -1, "total": 3}
    h.run(lines, mode="next")
    h.run(lines, mode="next")
    h.run(plan(text="z", countdown_s=0), mode="next")  # plan shrank below the playhead: start over
    assert h.sender.chars == "ababz"


def test_next_and_prev_are_ignored_when_idle_and_for_macros():
    h = Harness()
    assert h.session.next() is False and h.session.prev() is False


def test_next_during_run_skips_the_current_item():
    h = Harness(control=Control())
    text = "x" * 400 + "\n" + "y" * 5
    h.session.start_typing(plan(text=text, split="lines", settings={"char_delay_ms": 5, "jitter_pct": 0}, countdown_s=0))
    time.sleep(0.08)
    assert h.session.next()
    h.session.join(5)
    typed = h.sender.chars
    assert 0 < typed.count("x") < 400
    assert typed.endswith("yyyyy")
    assert h.finished()["reason"] == "done"
    assert h.session.position()["last"] == 1


def test_prev_during_run_restarts_the_previous_item():
    h = Harness(control=Control())
    text = "ab\n" + "x" * 400
    h.session.start_typing(plan(text=text, split="lines", settings={"char_delay_ms": 5, "jitter_pct": 0}, countdown_s=0,
                                repeat_interval_ms=0))
    time.sleep(0.1)  # "ab" is done, the x item is being typed
    assert h.session.prev()
    time.sleep(0.05)
    h.session.stop()
    h.session.join(5)
    assert h.sender.chars.startswith("ab")
    assert h.sender.chars.count("ab") == 2
    assert h.finished()["reason"] == "cancelled"


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


def test_rejects_empty_text_bad_mode_and_concurrent_starts():
    h = Harness(control=Control())
    with pytest.raises(SessionError, match="empty_text"):
        h.session.start_typing(plan(text="   "))
    with pytest.raises(SessionError, match="invalid_mode"):
        h.session.start_typing(plan(), mode="sideways")
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
