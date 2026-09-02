import pytest

from typer_app.engine.keys import KeyCombo, combo_id, format_combo, key_vk, parse_combo


@pytest.mark.parametrize(
    "text, key, modifiers",
    [
        ("ctrl+shift+enter", "enter", {"ctrl", "shift"}),
        ("Ctrl + Alt + T", "t", {"ctrl", "alt"}),
        ("enter", "enter", set()),
        ("Return", "enter", set()),
        ("ctrl++", "+", {"ctrl"}),
        ("+", "+", set()),
        ("shift+plus", "+", {"shift"}),
        ("win+d", "d", {"win"}),
        ("control+esc", "escape", {"ctrl"}),
        ("Page Down", "pagedown", set()),
        ("F12", "f12", set()),
        ("ctrl+ą", "ą", {"ctrl"}),
    ],
)
def test_parse_combo(text, key, modifiers):
    combo = parse_combo(text)
    assert combo.key == key
    assert set(combo.modifiers) == modifiers


@pytest.mark.parametrize("text", ["", "ctrl+", "hyper+a", "ctrl+bogus", "+ctrl"])
def test_parse_combo_rejects_invalid(text):
    with pytest.raises(ValueError):
        parse_combo(text)


def test_format_and_id_are_canonical():
    combo = parse_combo("shift+ctrl+pgup")
    assert format_combo(combo) == "Ctrl+Shift+Page Up"
    assert combo_id(combo) == "ctrl+shift+pageup"
    assert str(parse_combo("alt+f4")) == "Alt+F4"
    assert format_combo(KeyCombo("+", frozenset({"ctrl"}))) == "Ctrl++"


def test_key_vk_layout_independent_keys_only():
    assert key_vk("enter") == 0x0D
    assert key_vk("a") == 0x41
    assert key_vk("7") == 0x37
    assert key_vk("+") is None
    assert key_vk("ą") is None
