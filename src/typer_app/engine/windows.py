"""Enumerating, inspecting and activating top-level windows (ctypes only)."""

from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
DWMWA_CLOAKED = 14
SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
KEYEVENTF_KEYUP = 0x0002
VK_MENU = 0x12
GA_ROOT = 2

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = (WNDENUMPROC, wintypes.LPARAM)
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.IsWindow.argtypes = (wintypes.HWND,)
user32.IsIconic.argtypes = (wintypes.HWND,)
user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
user32.GetWindowLongW.restype = wintypes.LONG
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
user32.BringWindowToTop.argtypes = (wintypes.HWND,)
user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
user32.GetAncestor.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = (wintypes.POINT,)
user32.WindowFromPoint.restype = wintypes.HWND
user32.keybd_event.argtypes = (wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t)
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
dwmapi.DwmGetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)

OWN_PID = os.getpid()


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    process: str

    def to_dict(self) -> dict:
        return asdict(self)


def window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


_process_cache: dict[int, str] = {}


def process_name(pid: int) -> str:
    if pid in _process_cache:
        return _process_cache[pid]
    name = ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                name = os.path.basename(buffer.value)
        finally:
            kernel32.CloseHandle(handle)
    if len(_process_cache) > 512:
        _process_cache.clear()
    _process_cache[pid] = name
    return name


def _is_cloaked(hwnd: int) -> bool:
    cloaked = wintypes.DWORD(0)
    dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return bool(cloaked.value)


def is_own_window(hwnd: int) -> bool:
    return bool(hwnd) and window_pid(hwnd) == OWN_PID


def window_info(hwnd: int) -> WindowInfo | None:
    if not hwnd or not user32.IsWindow(hwnd):
        return None
    return WindowInfo(hwnd=int(hwnd), title=window_title(hwnd), process=process_name(window_pid(hwnd)))


def list_windows(include_own: bool = False) -> list[WindowInfo]:
    """Visible top-level windows that a user could type into, in z-order."""
    found: list[WindowInfo] = []

    @WNDENUMPROC
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) or _is_cloaked(hwnd):
            return True
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if style & WS_EX_TOOLWINDOW or style & WS_EX_NOACTIVATE:
            return True
        title = window_title(hwnd)
        if not title:
            return True
        pid = window_pid(hwnd)
        if pid == OWN_PID and not include_own:
            return True
        found.append(WindowInfo(hwnd=int(hwnd), title=title, process=process_name(pid)))
        return True

    user32.EnumWindows(callback, 0)
    return found


def foreground() -> WindowInfo | None:
    return window_info(user32.GetForegroundWindow())


def foreground_is_own() -> bool:
    return is_own_window(user32.GetForegroundWindow())


def window_at_point(x: int, y: int) -> int:
    hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    return int(user32.GetAncestor(hwnd, GA_ROOT)) if hwnd else 0


def focus(hwnd: int, timeout: float = 1.0) -> bool:
    """Bring a window to the foreground, escalating through the usual Windows workarounds."""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.15)
    if _try_focus(hwnd, timeout / 3):
        return True
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    own_thread = kernel32.GetCurrentThreadId()
    attached = bool(user32.AttachThreadInput(own_thread, target_thread, True))
    try:
        user32.BringWindowToTop(hwnd)
        if _try_focus(hwnd, timeout / 3):
            return True
    finally:
        if attached:
            user32.AttachThreadInput(own_thread, target_thread, False)
    # Last resort: a synthetic Alt tap lifts the foreground lock for the next SetForegroundWindow.
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    return _try_focus(hwnd, timeout / 3)


def _try_focus(hwnd: int, timeout: float) -> bool:
    user32.SetForegroundWindow(hwnd)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.02)
    return False


def find_by_title(fragment: str) -> WindowInfo | None:
    """First visible window whose title contains the fragment or whose process name equals it."""
    needle = fragment.strip().lower()
    if not needle:
        return None
    for info in list_windows():
        if needle in info.title.lower() or needle == info.process.lower():
            return info
    return None


class ForegroundTracker:
    """Polls the foreground window and remembers the last one that is not ours.

    That window is the natural typing target: it is where the user came from
    before clicking into Typer.
    """

    def __init__(self, on_change: Callable[[WindowInfo], None], interval: float = 0.25):
        self._on_change = on_change
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: WindowInfo | None = None

    @property
    def last_external(self) -> WindowInfo | None:
        return self._last

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="foreground-tracker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            hwnd = user32.GetForegroundWindow()
            if not hwnd or is_own_window(hwnd):
                continue
            info = window_info(hwnd)
            if info is None or not info.title:
                continue
            if info != self._last:
                self._last = info
                try:
                    self._on_change(info)
                except Exception:  # a UI failure must not kill the tracker
                    pass
