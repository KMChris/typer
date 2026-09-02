"""Application bootstrap: window, native styling and wiring of engine services."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes
from pathlib import Path

import webview

from . import APP_NAME, __version__
from .api import Api
from .storage import Store, data_dir

log = logging.getLogger(__name__)

UI_DIR = Path(__file__).resolve().parent / "ui"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36

# Title bar colours matching the CSS tokens in ui/app.css.
CAPTION_COLORS = {
    "dark": ("#0e1016", "#e8eaf2"),
    "light": ("#f3f4f8", "#1a1d29"),
}


def _colorref(hex_color: str) -> int:
    value = hex_color.lstrip("#")
    r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return (b << 16) | (g << 8) | r


def style_title_bar(hwnd: int, theme: str) -> None:
    """Paint the native title bar with the app colours so the window reads as one surface."""
    if not hwnd:
        return
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
        background, text = CAPTION_COLORS["dark" if theme == "dark" else "light"]
        dark = wintypes.BOOL(theme == "dark")
        dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(dark), 4)
        caption = wintypes.DWORD(_colorref(background))
        dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CAPTION_COLOR, ctypes.byref(caption), 4)
        text_color = wintypes.DWORD(_colorref(text))
        dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), DWMWA_TEXT_COLOR, ctypes.byref(text_color), 4)
    except Exception:  # older Windows builds do not support these attributes
        log.debug("title bar styling unavailable", exc_info=True)


def system_prefers_dark() -> bool:
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except OSError:
        return True


def configure_logging(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(directory / "typer.log", encoding="utf-8")]
    if not getattr(sys, "frozen", False):
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)


def main() -> None:
    directory = data_dir()
    configure_logging(directory)
    log.info("%s %s starting, data in %s", APP_NAME, __version__, directory)

    store = Store(directory)
    api = Api(store)
    theme = api.effective_theme(system_prefers_dark())
    background = CAPTION_COLORS["dark" if theme == "dark" else "light"][0]

    window = webview.create_window(
        APP_NAME,
        url=str(UI_DIR / "index.html"),
        js_api=api,
        width=1180,
        height=780,
        min_size=(900, 600),
        background_color=background,
        text_select=True,
    )
    api.attach(window)

    def on_shown() -> None:
        handle = getattr(getattr(window, "native", None), "Handle", None)
        hwnd = int(handle.ToInt64()) if handle is not None else 0
        api.set_hwnd(hwnd)
        style_title_bar(hwnd, theme)
        api.start_services()

    window.events.shown += on_shown
    window.events.closed += api.shutdown

    icon = ASSETS_DIR / "typer.ico"
    debug = os.environ.get("TYPER_DEBUG") == "1"
    webview.start(debug=debug, icon=str(icon) if icon.exists() else None)
