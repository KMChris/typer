"""Starts the real app window, inspects the page through evaluate_js and closes it.

Usage: .venv\\Scripts\\python tools\\uicheck.py [seconds]
Prints DOM facts and console errors so the frontend can be verified without a person clicking.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import webview  # noqa: E402

from typer_app.api import Api  # noqa: E402
from typer_app.app import UI_DIR, style_title_bar  # noqa: E402
from typer_app.storage import Store  # noqa: E402

CHECK_JS = """
(() => {
  const q = s => document.querySelector(s);
  return {
    title: document.title,
    lang: document.documentElement.lang,
    theme: document.documentElement.dataset.theme || 'system',
    version: q('#version').textContent,
    target: q('#target-title').textContent,
    targetSub: q('#target-sub').textContent,
    hints: q('#hotkey-hints').textContent,
    status: q('#status-text').textContent,
    startDisabled: q('#btn-start').disabled,
    outDelay: q('#out-delay').textContent,
    estimate: q('#meta-estimate').textContent,
    chips: [...document.querySelectorAll('#chips .chip')].map(c => c.textContent.trim()),
    macroCount: document.querySelectorAll('.macro-item').length,
    presetCount: document.querySelectorAll('.preset').length,
    hotkeyStart: q('.hotkey-input[data-hotkey=start_pause]').value,
    position: q('#position').textContent,
    kbdNext: q('#kbd-next').textContent,
    bodyHeight: document.body.scrollHeight,
    width: innerWidth, height: innerHeight,
    errors: window.__errors || [],
  };
})()
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 4
    store = Store(Path(tempfile.mkdtemp(prefix="typer-uicheck-")))
    api = Api(store)
    window = webview.create_window("Typer (uicheck)", url=str(UI_DIR / "index.html"), js_api=api,
                                   width=1180, height=780, min_size=(900, 600), background_color="#0e1016")
    api.attach(window)
    results: dict = {}

    def on_shown() -> None:
        hwnd = int(window.native.Handle.ToInt64())
        api.set_hwnd(hwnd)
        style_title_bar(hwnd, "dark")
        api.start_services()

    window.events.shown += on_shown

    def driver() -> None:
        time.sleep(seconds)
        try:
            window.evaluate_js("window.__errors = window.__errors || []; window.addEventListener('error', e => window.__errors.push(e.message));")
            window.evaluate_js("document.querySelector('#text').value = 'Hello {name} {n} {date}'; document.querySelector('#text').dispatchEvent(new Event('input'));")
            time.sleep(0.8)
            results["dom"] = window.evaluate_js(CHECK_JS)
            # Exercise the event path Python -> JS and the countdown overlay.
            api.emit("countdown", {"seconds": 3})
            time.sleep(0.3)
            results["countdown_visible"] = window.evaluate_js("!document.querySelector('#countdown').hidden")
            api.emit("countdown", {"seconds": 0})
            # Switch views and language through the UI code paths.
            window.evaluate_js("document.querySelector('.rail-item[data-view=macros]').click(); document.querySelector('#macro-new').click();")
            time.sleep(0.3)
            results["macro_form_visible"] = window.evaluate_js("!document.querySelector('#macro-form').hidden")
            window.evaluate_js("document.querySelector('#step-menu button[data-kind=key]').click();")
            time.sleep(0.3)
            results["steps"] = window.evaluate_js("document.querySelectorAll('#steps .step').length")
            results["plan_from_python"] = window.evaluate_js("window.typer.getPlan()")
        except Exception as exc:  # pragma: no cover - diagnostic script
            results["error"] = repr(exc)
        finally:
            api.shutdown()
            window.destroy()

    threading.Thread(target=driver, daemon=True).start()
    webview.start()
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
