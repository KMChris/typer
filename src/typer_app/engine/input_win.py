"""Keyboard and mouse synthesis on Windows through SendInput.

Text is sent as Unicode key events by default (layout independent, works for any
character). The "keys" method presses the physical virtual keys of the active
layout instead, which some applications (VM consoles, games, RDP) require.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from . import clipboard
from .keys import EXTENDED_KEYS, MODIFIER_ORDER, KeyCombo, key_vk

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
WHEEL_DELTA = 120
MAPVK_VK_TO_VSC = 0
MAPVK_VK_TO_CHAR = 2

# Tag placed in dwExtraInfo so our own injected events can be recognised.
INJECTED_TAG = 0x54595045

VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C
_MODIFIER_VK = {"ctrl": VK_CONTROL, "alt": VK_MENU, "shift": VK_SHIFT, "win": VK_LWIN}
_ALL_MODIFIER_VKS = (0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5)

_BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

ULONG_PTR = ctypes.c_size_t


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.VkKeyScanExW.argtypes = (wintypes.WCHAR, wintypes.HKL)
user32.VkKeyScanExW.restype = wintypes.SHORT
user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.GetKeyboardLayout.argtypes = (wintypes.DWORD,)
user32.GetKeyboardLayout.restype = wintypes.HKL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = wintypes.SHORT
user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
user32.SetCursorPos.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
user32.GetCursorPos.restype = wintypes.BOOL


def _send(inputs: list[_INPUT]) -> None:
    if not inputs:
        return
    array = (_INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), array, ctypes.sizeof(_INPUT))
    if sent != len(inputs):
        raise OSError(f"SendInput delivered {sent} of {len(inputs)} events (error {ctypes.get_last_error()})")


def _key_event(vk: int, scan: int, flags: int) -> _INPUT:
    item = _INPUT(type=INPUT_KEYBOARD)
    item.ki = _KEYBDINPUT(vk, scan, flags, 0, INJECTED_TAG)
    return item


def _vk_event(vk: int, down: bool, extended: bool = False) -> _INPUT:
    flags = 0 if down else KEYEVENTF_KEYUP
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    return _key_event(vk, user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC), flags)


def _unicode_events(ch: str) -> list[_INPUT]:
    events = []
    data = ch.encode("utf-16-le")
    for i in range(0, len(data), 2):
        unit = int.from_bytes(data[i:i + 2], "little")
        events.append(_key_event(0, unit, KEYEVENTF_UNICODE))
        events.append(_key_event(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    return events


def _mouse_event(flags: int, data: int = 0) -> _INPUT:
    item = _INPUT(type=INPUT_MOUSE)
    item.mi = _MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, INJECTED_TAG)
    return item


def foreground_layout() -> int:
    """Keyboard layout handle of the thread that owns the foreground window."""
    hwnd = user32.GetForegroundWindow()
    thread_id = user32.GetWindowThreadProcessId(hwnd, None) if hwnd else 0
    return user32.GetKeyboardLayout(thread_id)


def scan_char(ch: str, layout: int | None = None) -> tuple[int, int] | None:
    """(virtual key, modifier state) for a character in a layout; None when the layout cannot produce it."""
    result = user32.VkKeyScanExW(ch, layout if layout is not None else foreground_layout())
    if result == -1:
        return None
    vk, state = result & 0xFF, (result >> 8) & 0xFF
    if vk == 0xFF:
        return None
    return vk, state


def resolve_key(key: str, layout: int | None = None) -> tuple[int, int]:
    """Virtual key and layout modifier state (1 shift, 2 ctrl, 4 alt) for a key name or character."""
    vk = key_vk(key)
    if vk is not None:
        return vk, 0
    if len(key) == 1:
        scanned = scan_char(key, layout)
        if scanned is None:
            raise ValueError(f"the active keyboard layout has no key for {key!r}")
        return scanned
    raise ValueError(f"unknown key: {key}")


def _modifier_names(state: int) -> list[str]:
    names = []
    if state & 1:
        names.append("shift")
    if state & 2:
        names.append("ctrl")
    if state & 4:
        names.append("alt")
    return names


def _wrapped(vk: int, extended: bool, modifiers: list[str]) -> list[_INPUT]:
    """Press modifiers, tap the key, release modifiers in reverse order."""
    ordered = [m for m in MODIFIER_ORDER if m in modifiers]
    events = [_vk_event(_MODIFIER_VK[m], True, m == "win") for m in ordered]
    events.append(_vk_event(vk, True, extended))
    events.append(_vk_event(vk, False, extended))
    events.extend(_vk_event(_MODIFIER_VK[m], False, m == "win") for m in reversed(ordered))
    return events


def combo_events(combo: KeyCombo) -> list[_INPUT]:
    vk, state = resolve_key(combo.key)
    modifiers = set(combo.modifiers) | set(_modifier_names(state))
    return _wrapped(vk, combo.key in EXTENDED_KEYS, list(modifiers))


def vk_char(vk: int) -> str:
    """Character printed on a virtual key in the current layout, or an empty string."""
    value = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_CHAR) & 0xFFFF
    return chr(value) if value else ""


class WindowsSender:
    """Sender implementation backed by SendInput. Every call is a single SendInput batch."""

    def text_char(self, ch: str, method: str = "unicode") -> None:
        if method == "keys":
            scanned = scan_char(ch)
            if scanned is not None:
                vk, state = scanned
                _send(_wrapped(vk, False, _modifier_names(state)))
                return
        _send(_unicode_events(ch))

    def key_tap(self, combo: KeyCombo) -> None:
        _send(combo_events(combo))

    def key_down(self, key: str) -> None:
        vk, _ = resolve_key(key)
        _send([_vk_event(vk, True, key in EXTENDED_KEYS)])

    def key_up(self, key: str) -> None:
        vk, _ = resolve_key(key)
        _send([_vk_event(vk, False, key in EXTENDED_KEYS)])

    def set_clipboard(self, text: str) -> None:
        if not clipboard.set_text(text):
            raise OSError("clipboard is locked by another application")

    def get_clipboard(self) -> str | None:
        return clipboard.get_text()

    def mouse_move(self, x: int, y: int) -> None:
        user32.SetCursorPos(int(x), int(y))

    def mouse_button(self, button: str, down: bool) -> None:
        flags = _BUTTON_FLAGS.get(button)
        if flags is None:
            raise ValueError(f"unknown mouse button: {button}")
        _send([_mouse_event(flags[0] if down else flags[1])])

    def mouse_click(self, button: str = "left", count: int = 1, x: int | None = None, y: int | None = None) -> None:
        if x is not None and y is not None:
            self.mouse_move(x, y)
            time.sleep(0.02)
        flags = _BUTTON_FLAGS.get(button)
        if flags is None:
            raise ValueError(f"unknown mouse button: {button}")
        count = max(1, int(count))
        for i in range(count):
            _send([_mouse_event(flags[0]), _mouse_event(flags[1])])
            if i + 1 < count:
                time.sleep(0.06)

    def mouse_scroll(self, dy: int = 0, dx: int = 0) -> None:
        events = []
        if dy:
            events.append(_mouse_event(MOUSEEVENTF_WHEEL, int(dy) * WHEEL_DELTA))
        if dx:
            events.append(_mouse_event(MOUSEEVENTF_HWHEEL, int(dx) * WHEEL_DELTA))
        _send(events)

    def cursor_position(self) -> tuple[int, int]:
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        return point.x, point.y

    def modifiers_pressed(self) -> bool:
        return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in _ALL_MODIFIER_VKS)

    def wait_modifiers_released(self, timeout: float = 1.5) -> bool:
        """Wait for the user to let go of Ctrl/Alt/Shift/Win (typically after pressing a hotkey)."""
        deadline = time.monotonic() + timeout
        while self.modifiers_pressed():
            if time.monotonic() > deadline:
                return False
            time.sleep(0.02)
        return True

    def release_modifiers(self) -> None:
        """Send key-up for any modifier still reported as pressed so typed text is not read as shortcuts."""
        events = [_vk_event(vk, False, vk in (VK_LWIN, VK_RWIN)) for vk in _ALL_MODIFIER_VKS
                  if user32.GetAsyncKeyState(vk) & 0x8000]
        _send(events)
