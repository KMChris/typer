import random
import threading
import time

import pytest

from typer_app.engine.typing import Control, TypingJob, TypingSettings, burst_chance, corrupt, estimate_seconds, typo_for


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


def replay(sender) -> str:
    """The text a target window ends up with after the sender's operations."""
    out: list[str] = []
    for op in sender.ops:
        if op[0] == "char":
            out.append(op[1])
        elif op == ("key", "backspace"):
            out.pop()
        elif op == ("key", "tab"):
            out.append("\t")
        elif op[0] == "key" and op[1].endswith("enter"):
            out.append("\n")
    return "".join(out)


class ScriptedRandom(random.Random):
    """random() returns the scripted rolls (then 0.99); every other draw is deterministic."""

    def __init__(self, rolls):
        super().__init__(0)
        self.rolls = list(rolls)

    def random(self):
        return self.rolls.pop(0) if self.rolls else 0.99

    def choices(self, population, weights=None, *, cum_weights=None, k=1):
        return [population[0]]

    def choice(self, seq):
        return seq[0]

    def randint(self, a, b):
        return b

    def uniform(self, a, b):
        return a


TYPO_TEXT = "Zażółć gęślą jaźń, hello world!\nSecond line."


def test_typos_always_end_with_the_right_text():
    from conftest import FakeSender, InstantControl

    fixed_at_once = fixed_later = False
    for seed in range(60):
        sender, control = FakeSender(), InstantControl()
        job = TypingJob(TYPO_TEXT, settings(char_delay_ms=10, typo_pct=100), sender, control, rng=random.Random(seed))
        assert job.run()
        assert replay(sender) == TYPO_TEXT
        assert len(sender.chars) > len(TYPO_TEXT)
        kinds = sender.kinds
        for i in range(1, len(kinds) - 1):
            if sender.ops[i] != ("key", "backspace"):
                continue
            if kinds[i - 1] == "char" and kinds[i + 1] == "char":
                fixed_at_once = True
            if sender.ops[i + 1] == ("key", "backspace"):
                fixed_later = True
    assert fixed_at_once and fixed_later


def test_typo_noticed_at_the_end_of_the_word_is_fixed_from_the_mistake(sender, control):
    # rolls: slip on "h", not noticed at once, noticed after finishing the word
    rng = ScriptedRandom([0.0, 0.9, 0.0])
    assert TypingJob("hello world", settings(char_delay_ms=10, typo_pct=50), sender, control, rng=rng).run()
    assert sender.kinds == ["char"] * 5 + ["key"] * 5 + ["char"] * 11
    assert sender.chars == "gello" + "hello world"
    assert sender.keys == ["backspace"] * 5
    assert replay(sender) == "hello world"


def test_typo_noticed_at_once_and_repeated_while_correcting(sender, control):
    # rolls: slip on "h", noticed at once, slip again while retyping it
    rng = ScriptedRandom([0.0, 0.1, 0.1])
    assert TypingJob("hello", settings(char_delay_ms=10, typo_pct=50), sender, control, rng=rng).run()
    assert sender.ops[:5] == [("char", "g", "unicode"), ("key", "backspace"), ("char", "g", "unicode"),
                              ("key", "backspace"), ("char", "h", "unicode")]
    assert replay(sender) == "hello"
    # thinking pause before the first Backspace, quick Backspace, then normal typing again
    waits = [w for w in control.waits if w > 0]
    assert waits[1] > waits[0] > waits[2]


def test_corrupt_makes_one_or_several_mistakes():
    for seed in range(40):
        single = corrupt("abcdef", random.Random(seed), burst=0.0)
        assert single != "abcdef" and single.endswith("cdef")
        many = corrupt("abcdef", random.Random(seed), burst=1.0)
        assert len(many) != 6 or sum(a != b for a, b in zip(many, "abcdef")) >= 2
    assert corrupt("h", ScriptedRandom([]), burst=0.0) == "g"
    assert 0.1 <= burst_chance(0.5) < burst_chance(5) <= burst_chance(50) <= 0.4


def test_typo_for_polish_letters_and_unknown_scripts():
    wrong = {typo_for("ą", random.Random(seed)) for seed in range(40)}
    assert "a" in wrong and wrong <= set("aqsz")
    assert {typo_for("Ł", random.Random(seed)) for seed in range(40)} <= set("LKO")
    assert typo_for("ж", random.Random(0)) is None
    assert typo_for("7", random.Random(0)) is None


def test_cancel_during_a_correction(sender):
    from conftest import InstantControl

    class Impatient(InstantControl):
        def wait(self, seconds):
            if len(self.waits) >= 3:
                self.cancel()
            return super().wait(seconds)

    rng = ScriptedRandom([0.0, 0.9, 0.0])
    assert TypingJob("hello world", settings(char_delay_ms=10, typo_pct=50), sender, Impatient(), rng=rng).run() is False
    assert len(sender.ops) <= 5


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
    plain = estimate_seconds("hello world", settings(char_delay_ms=100))
    assert estimate_seconds("hello world", settings(char_delay_ms=100, typo_pct=10)) > plain
