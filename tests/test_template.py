import random
from datetime import datetime

from typer_app.engine.template import find_placeholders, is_builtin, load_csv, parse_csv_text, render


def test_render_uses_csv_values_case_insensitively():
    assert render("Hi {Name}, {city}!", {"name": "Ada", "City": "Kraków"}) == "Hi Ada, Kraków!"


def test_render_builtins():
    now = datetime(2026, 9, 2, 14, 5)
    rng = random.Random(1)
    out = render("{n}/{total} {n:3} {date} {time} {date:%d.%m.%Y}", n=7, total=12, now=now, rng=rng)
    assert out == "7/12 007 2026-09-02 14:05 02.09.2026"


def test_render_random_and_uuid_are_deterministic_with_seed():
    a = render("{rand:1-6} {rand:x|y|z} {uuid}", rng=random.Random(42))
    b = render("{rand:1-6} {rand:x|y|z} {uuid}", rng=random.Random(42))
    assert a == b
    value, choice, uid = a.split(" ")
    assert 1 <= int(value) <= 6
    assert choice in {"x", "y", "z"}
    assert len(uid) == 36


def test_render_leaves_unknown_and_escapes():
    assert render("{{literal}} {unknown} {n}", n=2) == "{literal} {unknown} 2"


def test_csv_values_win_over_builtins():
    assert render("{date}", {"date": "custom"}) == "custom"


def test_render_clipboard_placeholder():
    assert render("[{clipboard}]", clipboard=lambda: "copied") == "[copied]"
    assert render("[{clipboard}]", clipboard=lambda: None) == "[]"


def test_find_placeholders_unique_in_order():
    assert find_placeholders("{a} {{x}} {b:1-2} {a} {C}") == ["a", "b", "C"]
    assert is_builtin("Rand") and not is_builtin("name")


def test_parse_csv_semicolon_with_bom_and_blank_rows():
    text = "\ufeffimię;miasto\nAda;Kraków\n;\nBob;\n"
    data = parse_csv_text(text)
    assert data.columns == ["imię", "miasto"]
    assert data.rows == [{"imię": "Ada", "miasto": "Kraków"}, {"imię": "Bob", "miasto": ""}]
    assert data.to_dict()["count"] == 2


def test_load_csv_falls_back_to_cp1250(tmp_path):
    path = tmp_path / "people.csv"
    path.write_bytes("name,city\r\nZbigniew,Łódź\r\n".encode("cp1250"))
    data = load_csv(path)
    assert data.rows == [{"name": "Zbigniew", "city": "Łódź"}]
    assert data.to_dict()["name"] == "people.csv"


def test_parse_csv_empty():
    assert parse_csv_text("").rows == []
    assert parse_csv_text("only,header\n").rows == []
