import random
import threading
import time

import pytest

from typer_app.engine.typing import Control, TypingJob, TypingSettings, estimate_seconds


def settings(**overrides) -> TypingSettings:
    base = {"char_delay_ms": 0, "jitter_pct": 0}
    base.update(overrides)
    return TypingSettings(**base)


def test_settings_from_dict_clamps_and_validates():
    parsed = TypingSettings.from_dict({
        "char_delay_ms": -5, "jitter_pct": 500, "newline_mode": "bogus", "input_method": "x",
        "final_key": "not a key", "typo_pct": "abc", "instant": 1,
    })
    assert parsed.char_delay_ms == 0
    assert parsed.jitter_pct == 100
    assert parsed.newline_mode == "enter"
    assert parsed.input_method == "unicode"
    assert parsed.final_key == ""
    assert parsed.typo_pct == 0
    assert parsed.instant is True
    assert TypingSettings.from_dict("garbage") == TypingSettings()
    assert TypingSettings.from_dict({"final_key": "Ctrl+Enter"}).final_key == "Ctrl+Enter"


@pytest.mark.parametrize(
    "mode, expected_key",
    [("enter", "enter"), ("shift_enter", "shift+enter"), ("ctrl_enter", "ctrl+enter")],
)
def test_newline_modes(sender, control, mode, expected_key):
    assert TypingJob("ab\r\ncd", settings(newline_mode=mode), sender, control).run()
    assert sender.chars == "abcd"
    assert sender.keys == [expected_key]
    assert sender.ops[2] == ("key", expected_key)


def test_newline_none_skips_newlines(sender, control):
    TypingJob("a\nb", settings(newline_mode="none"), sender, control).run()
    assert sender.chars == "ab"
    assert sender.keys == []


def test_tab_and_final_key(sender, control):
    progress = []
    job = TypingJob("a\tb", settings(final_key="ctrl+enter"), sender, control, on_progress=lambda d, t: progress.append((d, t)))
    assert job.run()
    assert sender.ops == [("char", "a", "unicode"), ("key", "tab"), ("char", "b", "unicode"), ("key", "ctrl+enter")]
    assert progress[-1] == (3, 3)


def test_input_method_is_passed_to_sender(sender, control):
    TypingJob("x", settings(input_method="keys"), sender, control).run()
    assert sender.ops == [("char", "x", "keys")]


def test_pauses_are_added_after_specific_characters(sender, control):
    conf = settings(char_delay_ms=100, word_pause_ms=500, punct_pause_ms=300, newline_pause_ms=1000)
    TypingJob("a b.\nc", conf, sender, control).run()
    assert [round(w, 3) for w in control.waits if w > 0] == [0.1, 0.6, 0.1, 0.4, 1.1, 0.1]


def test_jitter_stays_within_bounds(sender, control):
    conf = settings(char_delay_ms=100, jitter_pct=50)
    TypingJob("abcdefghij", conf, sender, control, rng=random.Random(3)).run()
    delays = [w for w in control.waits if w > 0]
    assert all(0.05 <= d <= 0.15 for d in delays)
    assert len(set(delays)) > 1


def test_cancel_before_and_during_run(sender, control):
    control.cancel()
    assert TypingJob("abc", settings(final_key="enter"), sender, control).run() is False
    assert sender.ops == []

    fresh = Control()

    class CancellingSender(type(sender)):
        def text_char(self, ch, method="unicode"):
            super().text_char(ch, method)
            if ch == "b":
                fresh.cancel()

    cancelling = CancellingSender()
    assert TypingJob("abc", settings(final_key="enter"), cancelling, fresh).run() is False
    assert cancelling.chars == "ab"
    assert cancelling.keys == []


def test_pause_and_resume(sender):
    control = Control()
    job = TypingJob("abcdefghijklmnopqrstuvwxyz", settings(char_delay_ms=5), sender, control)
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("ok", job.run()))
    thread.start()
    time.sleep(0.03)
    control.pause()
    time.sleep(0.05)
    typed = len(sender.chars)
    assert 0 < typed < 26
    time.sleep(0.1)
    assert len(sender.chars) == typed
    assert control.paused
    control.resume()
    thread.join(3)
    assert result["ok"] is True
    assert sender.chars == "abcdefghijklmnopqrstuvwxyz"


def test_skip_abandons_the_job_without_cancelling(sender):
    control = Control()
    control.skip()
    assert TypingJob("abc", settings(), sender, control).run() is False
    assert control.skipped and not control.cancelled
    control.clear_skip()
    assert TypingJob("abc", settings(), sender, control).run() is True
    assert sender.chars == "abc"


def test_typos_are_corrected(sender, control):
    TypingJob("A", settings(char_delay_ms=10, typo_pct=100), sender, control, rng=random.Random(0)).run()
    assert [op[0] for op in sender.ops] == ["char", "key", "char"]
    assert sender.ops[0][1] != "A" and sender.ops[0][1].isupper()
    assert sender.ops[1] == ("key", "backspace")
    assert sender.ops[2] == ("char", "A", "unicode")


def test_instant_mode_pastes_lines_and_restores_clipboard(control):
    from conftest import FakeSender

    sender = FakeSender(clipboard="original")
    TypingJob("first\n\nthird", settings(instant=True, newline_mode="shift_enter"), sender, control).run()
    assert sender.ops == [
        ("clip", "first"), ("key", "ctrl+v"), ("key", "shift+enter"),
        ("key", "shift+enter"),
        ("clip", "third"), ("key", "ctrl+v"),
        ("clip", "original"),
    ]
    assert sender.clipboard == "original"


def test_estimate_seconds():
    assert estimate_seconds("", settings()) == 0
    assert estimate_seconds("abcde", settings(char_delay_ms=100)) == pytest.approx(0.5)
    assert estimate_seconds("a\nb", settings(char_delay_ms=100, newline_pause_ms=1000)) == pytest.approx(1.3)
    assert estimate_seconds("x", settings(instant=True)) > 0
