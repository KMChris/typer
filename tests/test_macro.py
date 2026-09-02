import pytest

from typer_app.engine.macro import Macro, RawEvent, Step, events_to_steps, run_macro
from typer_app.engine.typing import TypingSettings


def test_step_from_dict_validates_and_normalizes():
    assert Step.from_dict({"kind": "key", "key": "Ctrl + C"}).key == "ctrl+c"
    click = Step.from_dict({"kind": "mouse_click", "x": "10", "y": 20, "count": 9})
    assert (click.x, click.y, click.count) == (10, 20, 3)
    assert Step.from_dict({"kind": "mouse_move"}).has_point is False
    with pytest.raises(ValueError):
        Step.from_dict({"kind": "teleport"})
    with pytest.raises(ValueError):
        Step.from_dict({"kind": "key", "key": "hyper+x"})
    with pytest.raises(ValueError):
        Step.from_dict({"kind": "mouse_click", "button": "back"})


def test_step_to_dict_is_compact():
    assert Step("wait", ms=250).to_dict() == {"kind": "wait", "ms": 250}
    assert Step("mouse_click", x=1, y=2, button="right", count=2).to_dict() == {
        "kind": "mouse_click", "x": 1, "y": 2, "button": "right", "count": 2}
    assert Step("text", text="hi").to_dict() == {"kind": "text", "text": "hi"}


def test_macro_roundtrip_and_validation():
    macro = Macro.from_dict({
        "name": " Sign ", "hotkey": "Ctrl+Alt+1", "repeat": 0, "interval_ms": -3,
        "steps": [{"kind": "text", "text": "x"}, {"kind": "wait", "ms": 5}],
    })
    assert macro.name == "Sign"
    assert macro.hotkey == "ctrl+alt+1"
    assert macro.repeat == 1 and macro.interval_ms == 0
    assert len(macro.id) == 32
    assert Macro.from_dict(macro.to_dict()) == macro
    with pytest.raises(ValueError, match="step 2"):
        Macro.from_dict({"name": "bad", "steps": [{"kind": "wait"}, {"kind": "nope"}]})


def test_run_macro_executes_steps(sender, control):
    macro = Macro(id="m", name="demo", repeat=2, interval_ms=100, steps=[
        Step("text", text="ab"),
        Step("key", key="ctrl+s"),
        Step("wait", ms=50),
        Step("mouse_click", x=5, y=6, button="left", count=2),
        Step("mouse_scroll", x=1, y=1, dy=-3),
        Step("mouse_down", x=1, y=1), Step("mouse_up", x=9, y=9),
        Step("focus", title="Notepad"),
    ])
    focused = []
    settings = TypingSettings(char_delay_ms=0, jitter_pct=0, final_key="enter")
    ok = run_macro(macro, settings, sender, control, focus_by_title=lambda t: focused.append(t) or True)
    assert ok
    assert sender.chars == "abab"
    assert sender.keys == ["ctrl+s", "ctrl+s"]  # final_key is not applied inside macros
    assert ("click", "left", 2, 5, 6) in sender.ops
    assert ("move", 1, 1) in sender.ops and ("scroll", -3, 0) in sender.ops
    assert ("button", "left", True) in sender.ops and ("button", "left", False) in sender.ops
    assert focused == ["Notepad", "Notepad"]
    assert 0.05 in control.waits and 0.1 in control.waits


def test_run_macro_stops_when_cancelled(sender, control):
    control.cancel()
    macro = Macro(id="m", name="demo", steps=[Step("key", key="a")])
    assert run_macro(macro, TypingSettings(), sender, control) is False
    assert sender.ops == []


def test_events_to_steps_groups_text_keys_mouse_and_waits():
    events = [
        RawEvent(0.00, "key_down", key="h"),
        RawEvent(0.01, "key_up", key="h"),
        RawEvent(0.05, "key_down", key="shift"),
        RawEvent(0.06, "key_down", key="I"),
        RawEvent(0.07, "key_up", key="I"),
        RawEvent(0.08, "key_up", key="shift"),
        RawEvent(0.10, "key_down", key="space"),
        RawEvent(0.12, "key_down", key="ctrl"),
        RawEvent(0.15, "key_down", key="c"),
        RawEvent(0.16, "key_up", key="c"),
        RawEvent(0.17, "key_up", key="ctrl"),
        RawEvent(0.70, "click", x=100, y=200, button="left", pressed=True),
        RawEvent(0.75, "click", x=101, y=201, button="left", pressed=False),
        RawEvent(0.80, "click", x=100, y=200, button="left", pressed=True),
        RawEvent(0.85, "click", x=100, y=200, button="left", pressed=False),
        RawEvent(1.20, "click", x=10, y=10, button="right", pressed=True),
        RawEvent(1.50, "click", x=300, y=300, button="right", pressed=False),
        RawEvent(1.60, "scroll", x=50, y=50, dy=-1),
        RawEvent(1.65, "scroll", x=50, y=50, dy=-2),
        RawEvent(1.70, "key_down", key="shift"),
        RawEvent(1.72, "key_down", key="enter"),
        RawEvent(1.73, "key_up", key="enter"),
        RawEvent(1.74, "key_up", key="shift"),
        RawEvent(2.00, "key_down", key="ctrl"),
        RawEvent(2.01, "key_down", key="alt"),
        RawEvent(2.02, "key_down", key="x"),
        RawEvent(2.03, "key_up", key="x"),
        RawEvent(2.04, "key_up", key="alt"),
        RawEvent(2.05, "key_up", key="ctrl"),
    ]
    steps = events_to_steps(events, stop_hotkey="ctrl+alt+x")
    assert [s.to_dict() for s in steps] == [
        {"kind": "text", "text": "hI "},
        {"kind": "key", "key": "ctrl+c"},
        {"kind": "wait", "ms": 550},
        {"kind": "mouse_click", "x": 100, "y": 200, "button": "left", "count": 2},
        {"kind": "wait", "ms": 400},
        {"kind": "mouse_down", "x": 10, "y": 10, "button": "right"},
        {"kind": "mouse_up", "x": 300, "y": 300, "button": "right"},
        {"kind": "wait", "ms": 400},
        {"kind": "mouse_scroll", "x": 50, "y": 50, "dx": 0, "dy": -3},
        {"kind": "key", "key": "shift+enter"},
    ]


def test_events_to_steps_drag_uses_right_button():
    events = [
        RawEvent(0.0, "click", x=10, y=10, button="right", pressed=True),
        RawEvent(0.3, "click", x=300, y=300, button="right", pressed=False),
    ]
    steps = events_to_steps(events)
    assert steps[0].to_dict() == {"kind": "mouse_down", "x": 10, "y": 10, "button": "right"}
    assert steps[1].to_dict() == {"kind": "mouse_up", "x": 300, "y": 300, "button": "right"}


def test_events_to_steps_ignores_lonely_releases_and_trailing_waits():
    events = [
        RawEvent(0.0, "key_up", key="t"),
        RawEvent(0.1, "click", x=1, y=1, button="left", pressed=False),
        RawEvent(0.2, "key_down", key="a"),
        RawEvent(5.0, "key_down", key="escape"),
    ]
    steps = events_to_steps(events, stop_hotkey="escape")
    assert [s.to_dict() for s in steps] == [{"kind": "text", "text": "a"}]
