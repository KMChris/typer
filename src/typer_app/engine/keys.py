"""Key names, virtual-key codes and key combination parsing.

Pure Python (no Windows calls) so it can be unit tested anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

MODIFIER_ORDER = ("ctrl", "alt", "shift", "win")

_MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "ctl": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
    "win": "win",
    "windows": "win",
    "super": "win",
    "meta": "win",
    "cmd": "win",
}

_KEY_ALIASES = {
    "return": "enter",
    "esc": "escape",
    "del": "delete",
    "ins": "insert",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "pgdown": "pagedown",
    "spacebar": "space",
    "bksp": "backspace",
    "back": "backspace",
    "plus": "+",
    "minus": "-",
    "comma": ",",
    "period": ".",
    "dot": ".",
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "prtsc": "printscreen",
    "printscr": "printscreen",
    "caps": "capslock",
    "contextmenu": "apps",
    "menu": "apps",
}

# Virtual-key codes for keys that do not depend on the keyboard layout.
NAMED_VK: dict[str, int] = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "pause": 0x13,
    "capslock": 0x14,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "printscreen": 0x2C,
    "insert": 0x2D,
    "delete": 0x2E,
    "apps": 0x5D,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "multiply": 0x6A,
    "add": 0x6B,
    "subtract": 0x6D,
    "decimal": 0x6E,
    "divide": 0x6F,
    "volumemute": 0xAD,
    "volumedown": 0xAE,
    "volumeup": 0xAF,
    "medianext": 0xB0,
    "mediaprev": 0xB1,
    "mediastop": 0xB2,
    "mediaplay": 0xB3,
    "browserback": 0xA6,
    "browserforward": 0xA7,
    "shift": 0x10,
    "ctrl": 0x11,
    "alt": 0x12,
    "win": 0x5B,
}
NAMED_VK.update({f"f{i}": 0x6F + i for i in range(1, 25)})
NAMED_VK.update({f"num{i}": 0x60 + i for i in range(10)})

# Reverse map used when recording (first name wins for duplicate codes).
VK_TO_NAME: dict[int, str] = {}
for _name, _vk in NAMED_VK.items():
    VK_TO_NAME.setdefault(_vk, _name)
VK_TO_NAME.update({0xA0: "shift", 0xA1: "shift", 0xA2: "ctrl", 0xA3: "ctrl", 0xA4: "alt", 0xA5: "alt", 0x5C: "win"})

# Keys that need KEYEVENTF_EXTENDEDKEY so applications see the right scan code.
EXTENDED_KEYS = frozenset(
    {
        "insert", "delete", "home", "end", "pageup", "pagedown",
        "left", "up", "right", "down", "numlock", "divide", "printscreen", "apps", "win",
    }
)

_KEY_LABELS = {
    "pageup": "Page Up",
    "pagedown": "Page Down",
    "printscreen": "Print Screen",
    "capslock": "Caps Lock",
    "numlock": "Num Lock",
    "scrolllock": "Scroll Lock",
    "escape": "Esc",
    "apps": "Menu",
    "+": "+",
}
_MODIFIER_LABELS = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}


@dataclass(frozen=True)
class KeyCombo:
    """A key with optional modifiers, e.g. Ctrl+Shift+Enter."""

    key: str
    modifiers: frozenset[str] = frozenset()

    def __str__(self) -> str:
        return format_combo(self)


def is_modifier(name: str) -> bool:
    return name in _MODIFIER_LABELS


def key_vk(key: str) -> int | None:
    """Layout independent virtual-key code, or None for layout dependent characters."""
    if key in NAMED_VK:
        return NAMED_VK[key]
    if len(key) == 1 and key.isascii() and key.isalnum():
        return ord(key.upper())
    return None


def normalize_key(name: str) -> str:
    """Canonical key name: single characters are lowercased, names resolved through aliases."""
    key = name.strip()
    if not key:
        raise ValueError("missing key")
    if len(key) == 1:
        return key.lower()
    lowered = key.lower().replace(" ", "").replace("_", "")
    lowered = _KEY_ALIASES.get(lowered, lowered)
    if lowered in NAMED_VK or len(lowered) == 1:
        return lowered
    raise ValueError(f"unknown key: {name.strip()}")


def parse_combo(text: str) -> KeyCombo:
    """Parse "ctrl+shift+t", "Ctrl + Enter", "ctrl++" (the plus key) into a KeyCombo."""
    raw = text.strip()
    if not raw:
        raise ValueError("empty key combination")
    if raw == "+":
        mods, key_text = [], "+"
    elif raw.endswith("++"):
        mods, key_text = (raw[:-2].split("+") if raw[:-2] else []), "+"
    else:
        parts = raw.split("+")
        mods, key_text = parts[:-1], parts[-1]
    modifiers: set[str] = set()
    for part in mods:
        token = part.strip().lower()
        if not token:
            raise ValueError("malformed key combination")
        if token not in _MODIFIER_ALIASES:
            raise ValueError(f"unknown modifier: {part.strip()}")
        modifiers.add(_MODIFIER_ALIASES[token])
    return KeyCombo(key=normalize_key(key_text), modifiers=frozenset(modifiers))


def format_combo(combo: KeyCombo) -> str:
    parts = [_MODIFIER_LABELS[m] for m in MODIFIER_ORDER if m in combo.modifiers]
    key = combo.key
    if len(key) == 1:
        label = key.upper()
    elif key in _KEY_LABELS:
        label = _KEY_LABELS[key]
    elif key.startswith("f") and key[1:].isdigit():
        label = key.upper()
    elif key.startswith("num") and key[3:].isdigit():
        label = "Num " + key[3:]
    else:
        label = _MODIFIER_LABELS.get(key, key.capitalize())
    parts.append(label)
    return "+".join(parts)


def combo_id(combo: KeyCombo) -> str:
    """Canonical machine form, e.g. "ctrl+alt+t"."""
    return "+".join([m for m in MODIFIER_ORDER if m in combo.modifiers] + [combo.key])
