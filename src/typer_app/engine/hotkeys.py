"""Global hotkeys through RegisterHotKey, served by a dedicated message loop thread."""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
from ctypes import wintypes
from typing import Callable

from .input_win import resolve_key
from .keys import KeyCombo, parse_combo

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP_REBIND = 0x8000 + 1
PM_NOREMOVE = 0x0000
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x0008, 0x4000
_MOD_FLAGS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "shift": MOD_SHIFT, "win": MOD_WIN}

user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
user32.PeekMessageW.argtypes = (
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT)
user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def hotkey_params(combo: KeyCombo) -> tuple[int, int]:
    """(modifier flags, virtual key) for RegisterHotKey."""
    vk, state = resolve_key(combo.key)
    flags = MOD_NOREPEAT
    for name in combo.modifiers:
        flags |= _MOD_FLAGS[name]
    if state & 1:
        flags |= MOD_SHIFT
    if state & 2:
        flags |= MOD_CONTROL
    if state & 4:
        flags |= MOD_ALT
    return flags, vk


class HotkeyManager:
    """Registers named hotkeys and calls `on_hotkey(name)` from the message loop thread.

    The callback must return quickly (start a thread for real work).
    """

    def __init__(self, on_hotkey: Callable[[str], None]) -> None:
        self._on_hotkey = on_hotkey
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._requests: queue.Queue = queue.Queue()
        self._ids: dict[int, str] = {}

    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(2)
            self._thread = None

    def set_bindings(self, bindings: dict[str, str]) -> dict[str, str]:
        """Replace all bindings. Returns {name: error} for combos that could not be registered."""
        if not self._thread_id:
            return {name: "hotkey service not running" for name, spec in bindings.items() if spec}
        result: queue.Queue = queue.Queue()
        self._requests.put((dict(bindings), result))
        user32.PostThreadMessageW(self._thread_id, WM_APP_REBIND, 0, 0)
        try:
            return result.get(timeout=3)
        except queue.Empty:
            return {name: "hotkey service did not respond" for name, spec in bindings.items() if spec}

    def _loop(self) -> None:
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)  # creates the thread message queue
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    name = self._ids.get(int(msg.wParam))
                    if name:
                        try:
                            self._on_hotkey(name)
                        except Exception:
                            log.exception("hotkey handler failed for %s", name)
                elif msg.message == WM_APP_REBIND:
                    self._apply_pending()
        finally:
            self._unregister_all()
            self._thread_id = 0

    def _unregister_all(self) -> None:
        for hotkey_id in list(self._ids):
            user32.UnregisterHotKey(None, hotkey_id)
        self._ids.clear()

    def _apply_pending(self) -> None:
        while True:
            try:
                bindings, result = self._requests.get_nowait()
            except queue.Empty:
                return
            self._unregister_all()
            errors: dict[str, str] = {}
            next_id = 1
            for name, spec in bindings.items():
                if not spec:
                    continue
                try:
                    flags, vk = hotkey_params(parse_combo(spec))
                except ValueError as exc:
                    errors[name] = str(exc)
                    continue
                if user32.RegisterHotKey(None, next_id, flags, vk):
                    self._ids[next_id] = name
                    next_id += 1
                else:
                    errors[name] = "in use by another application"
            result.put(errors)
