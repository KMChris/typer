"""Bridge behaviour that does not need a window."""

from typer_app.api import Api
from typer_app.storage import Store


def test_hotkey_start_keeps_the_countdown_and_targets_the_foreground(tmp_path, monkeypatch):
    api = Api(Store(tmp_path))
    api._settings["draft"] = {"text": "hello", "countdown_s": 4, "split": "lines"}
    started = {}
    monkeypatch.setattr(api._session, "start_typing",
                        lambda plan, rows, mode: started.update(plan=plan, rows=rows, mode=mode))
    api._start_from_hotkey("next")
    plan = started["plan"]
    assert plan.countdown_s == 4
    assert plan.target.mode == "foreground"
    assert plan.split == "lines"
    assert started["mode"] == "next"
