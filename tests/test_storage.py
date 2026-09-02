import json

from typer_app import storage
from typer_app.storage import Store


def test_store_roundtrip_and_default(tmp_path):
    store = Store(tmp_path / "nested")
    assert store.read("settings", {"a": 1}) == {"a": 1}
    store.write("settings", {"theme": "dark", "name": "Zażółć"})
    assert store.read("settings", {}) == {"theme": "dark", "name": "Zażółć"}
    assert not list(tmp_path.glob("**/*.tmp"))


def test_corrupt_file_is_set_aside(tmp_path):
    store = Store(tmp_path)
    store.path("presets").write_text("{not json", encoding="utf-8")
    assert store.read("presets", []) == []
    assert not store.path("presets").exists()
    assert list(tmp_path.glob("presets.corrupt-*.json"))


def test_data_dir_portable_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "install_dir", lambda: tmp_path)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    assert storage.data_dir() == tmp_path / "appdata" / "Typer"
    (tmp_path / "portable.txt").write_text("")
    assert storage.data_dir() == tmp_path / "data"
