"""The JS bridge. Every public method is callable from the page as `window.pywebview.api.<name>`.

Methods return plain dicts: `{"ok": True, ...}` or `{"ok": False, "error": code, "message": text}`.
Python pushes events to the page through `window.typer.emit(name, payload)`.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

import webview

from . import __version__
from .engine import windows
from .engine.hotkeys import HotkeyManager
from .engine.input_win import WindowsSender
from .engine.keys import combo_id, format_combo, parse_combo
from .engine.macro import Macro, MacroRecorder
from .engine.session import RunPlan, Session, SessionError, Target, split_text
from .engine.template import CsvData, find_placeholders, is_builtin, load_csv, render
from .engine.typing import TypingSettings, estimate_seconds
from .storage import Store

log = logging.getLogger(__name__)

DEFAULT_SETTINGS = {
    "language": "pl",
    "theme": "system",
    # Plain function keys: modifier chords (Ctrl+Alt+..., Alt+...) collide with overlays such as the NVIDIA App.
    "hotkeys": {"start_pause": "f7", "stop_reset": "f5", "prev": "f6", "next": "f8", "record": "f9"},
    "escape_stops": True,
    "draft": None,
}
HOTKEY_NAMES = ("start_pause", "stop_reset", "prev", "next", "record")
MAX_PRESETS = 500


def _ok(**payload) -> dict:
    payload["ok"] = True
    return payload


def _fail(error: str, message: str = "") -> dict:
    return {"ok": False, "error": error, "message": message}


class Api:
    def __init__(self, store: Store) -> None:
        self._store = store
        self._lock = threading.RLock()
        self._window = None
        self._hwnd = 0
        self._settings = self._load_settings()
        self._presets: list[dict] = [p for p in self._store.read("presets", []) if isinstance(p, dict)]
        self._macros: list[Macro] = self._load_macros()
        self._csv: CsvData | None = None
        self._sender = WindowsSender()
        self._session = Session(
            self._sender,
            self.emit,
            focus_window=windows.focus,
            resolve_auto_target=self._auto_target_hwnd,
            foreground_is_own=windows.foreground_is_own,
            focus_by_title=self._focus_by_title,
        )
        self._hotkeys = HotkeyManager(self._on_hotkey)
        self._tracker = windows.ForegroundTracker(self._on_foreground_change)
        self._recorder = MacroRecorder(ignore_point=self._is_own_point, ignore_keys=windows.foreground_is_own)
        self._last_title_update = 0.0
        self._hotkey_errors: dict[str, str] = {}

    # -- lifecycle ---------------------------------------------------------------

    def attach(self, window) -> None:
        self._window = window

    def set_hwnd(self, hwnd: int) -> None:
        self._hwnd = hwnd

    def start_services(self) -> None:
        self._hotkeys.start()
        self._apply_hotkeys()
        self._tracker.start()

    def shutdown(self) -> None:
        try:
            self._session.stop()
            self._tracker.stop()
            if self._recorder.recording:
                self._recorder.stop()
            self._hotkeys.stop()
        except Exception:
            log.exception("shutdown failed")

    def effective_theme(self, system_dark: bool) -> str:
        theme = self._settings.get("theme", "system")
        if theme in ("light", "dark"):
            return theme
        return "dark" if system_dark else "light"

    # -- events to the page ------------------------------------------------------

    def emit(self, name: str, payload: dict) -> None:
        if name == "progress":
            self._update_title(payload)
        elif name == "state":
            self._on_state(payload)
        if self._window is None:
            return
        script = f"window.typer && window.typer.emit({json.dumps(name)}, {json.dumps(payload, ensure_ascii=False)})"
        try:
            self._window.run_js(script)
        except Exception:
            log.debug("run_js failed", exc_info=True)

    def _update_title(self, payload: dict) -> None:
        now = time.monotonic()
        if now - self._last_title_update < 0.5 and payload.get("done") != payload.get("total"):
            return
        self._last_title_update = now
        self._set_title(f"Typer · {payload.get('percent', 0):.0f}%")

    def _set_title(self, title: str) -> None:
        if self._window is not None:
            try:
                self._window.set_title(title)
            except Exception:
                pass

    def _on_state(self, payload: dict) -> None:
        state = payload.get("state")
        if state == "idle":
            self._set_title("Typer")
        # Esc is only a global hotkey while something is running.
        self._apply_hotkeys(active=state in ("countdown", "running", "paused"))

    def _on_foreground_change(self, info: windows.WindowInfo) -> None:
        self.emit("target", info.to_dict())

    # -- init and settings -------------------------------------------------------

    def init(self) -> dict:
        target = self._tracker.last_external
        return _ok(
            version=__version__,
            settings=self._public_settings(),
            presets=self._presets,
            macros=[m.to_dict() for m in self._macros],
            csv=self._csv.to_dict() if self._csv else None,
            target=target.to_dict() if target else None,
            session=self._session.snapshot(),
            position=self._session.position(),
            hotkey_errors=self._hotkey_errors,
            data_dir=str(self._store.directory),
            recording=self._recorder.recording,
        )

    def save_settings(self, settings: dict) -> dict:
        if not isinstance(settings, dict):
            return _fail("invalid", "settings must be an object")
        with self._lock:
            language = str(settings.get("language", self._settings["language"]))
            theme = str(settings.get("theme", self._settings["theme"]))
            self._settings["language"] = language if language in ("pl", "en") else "pl"
            self._settings["theme"] = theme if theme in ("system", "light", "dark") else "system"
            self._settings["escape_stops"] = bool(settings.get("escape_stops", True))
            hotkeys = settings.get("hotkeys")
            if isinstance(hotkeys, dict):
                cleaned = {}
                for name in HOTKEY_NAMES:
                    spec = str(hotkeys.get(name, "") or "").strip()
                    if spec:
                        try:
                            spec = combo_id(parse_combo(spec))
                        except ValueError:
                            return _fail("invalid_hotkey", name)
                    cleaned[name] = spec
                self._settings["hotkeys"] = cleaned
            self._store.write("settings", self._settings)
        errors = self._apply_hotkeys()
        self._restyle_title_bar()
        return _ok(settings=self._public_settings(), hotkey_errors=errors)

    def save_draft(self, draft: dict) -> dict:
        if not isinstance(draft, dict):
            return _fail("invalid")
        with self._lock:
            self._settings["draft"] = draft
            self._store.write("settings", self._settings)
        return _ok()

    def _public_settings(self) -> dict:
        data = dict(self._settings)
        data["hotkey_labels"] = {name: self._label(spec) for name, spec in data.get("hotkeys", {}).items()}
        return data

    @staticmethod
    def _label(spec: str) -> str:
        try:
            return format_combo(parse_combo(spec)) if spec else ""
        except ValueError:
            return spec

    def _load_settings(self) -> dict:
        data = self._store.read("settings", {})
        settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        if isinstance(data, dict):
            for key in ("language", "theme", "escape_stops", "draft"):
                if key in data:
                    settings[key] = data[key]
            hotkeys = data.get("hotkeys")
            if isinstance(hotkeys, dict):
                settings["hotkeys"].update({k: str(v or "") for k, v in hotkeys.items() if k in HOTKEY_NAMES})
        return settings

    def _restyle_title_bar(self) -> None:
        from .app import style_title_bar, system_prefers_dark

        style_title_bar(self._hwnd, self.effective_theme(system_prefers_dark()))

    # -- hotkeys -----------------------------------------------------------------

    def _apply_hotkeys(self, active: bool | None = None) -> dict[str, str]:
        if active is None:
            active = self._session.busy
        bindings = {name: spec for name, spec in self._settings.get("hotkeys", {}).items() if spec}
        for macro in self._macros:
            if macro.hotkey:
                bindings[f"macro:{macro.id}"] = macro.hotkey
        if active and self._settings.get("escape_stops", True):
            bindings["escape"] = "escape"
        errors = self._hotkeys.set_bindings(bindings)
        errors = {name: message for name, message in errors.items() if name != "escape"}
        self._hotkey_errors = errors
        return errors

    def _on_hotkey(self, name: str) -> None:
        log.info("hotkey %s", name)
        if name in ("escape", "stop_reset"):
            if self._recorder.recording:
                self._finish_recording()
            self._session.stop()
            if name == "stop_reset":
                self._session.reset()
        elif name == "start_pause":
            if self._session.busy:
                self._session.toggle_pause()
            else:
                threading.Thread(target=self._start_from_hotkey, args=("all",), daemon=True).start()
        elif name in ("prev", "next"):
            if self._session.busy:
                getattr(self._session, name)()
            else:
                threading.Thread(target=self._start_from_hotkey, args=(name,), daemon=True).start()
        elif name == "record":
            threading.Thread(target=self._toggle_recording, daemon=True).start()
        elif name.startswith("macro:"):
            macro = next((m for m in self._macros if m.id == name[6:]), None)
            if macro is not None:
                threading.Thread(target=self._run_macro_from_hotkey, args=(macro,), daemon=True).start()

    def _current_plan(self) -> RunPlan:
        """Ask the page for its live plan; fall back to the last saved draft."""
        data = None
        if self._window is not None:
            try:
                data = self._window.evaluate_js("window.typer ? window.typer.getPlan() : null")
            except Exception:
                log.debug("evaluate_js failed", exc_info=True)
        if not isinstance(data, dict):
            data = self._settings.get("draft") or {}
        return RunPlan.from_dict(data)

    def _start_from_hotkey(self, mode: str) -> None:
        plan = self._current_plan()
        plan.countdown_s = 0
        plan.target = Target(mode="foreground")
        try:
            self._session.start_typing(plan, self._rows(), mode)
        except SessionError as exc:
            self.emit("notice", {"level": "warn", "code": str(exc)})

    def _run_macro_from_hotkey(self, macro: Macro) -> None:
        plan = self._current_plan()
        try:
            self._session.start_macro(macro, plan.settings, Target(mode="foreground"), 0)
        except SessionError as exc:
            self.emit("notice", {"level": "warn", "code": str(exc)})

    # -- typing ------------------------------------------------------------------

    def _rows(self) -> list[dict] | None:
        return self._csv.rows if self._csv and self._csv.rows else None

    def _auto_target_hwnd(self) -> int:
        info = self._tracker.last_external
        return info.hwnd if info else 0

    def _focus_by_title(self, title: str) -> bool:
        info = windows.find_by_title(title)
        return bool(info) and windows.focus(info.hwnd)

    def start(self, plan: dict) -> dict:
        """Type every item from the playhead to the end."""
        try:
            self._session.start_typing(RunPlan.from_dict(plan), self._rows(), "all")
        except SessionError as exc:
            return _fail(str(exc))
        return _ok()

    def step(self, plan: dict, direction: str) -> dict:
        """Type a single item (next or prev); while running, jump to that item instead."""
        if direction not in ("next", "prev"):
            return _fail("invalid")
        if self._session.busy:
            return _ok() if getattr(self._session, direction)() else _fail("busy")
        try:
            self._session.start_typing(RunPlan.from_dict(plan), self._rows(), direction)
        except SessionError as exc:
            return _fail(str(exc))
        return _ok()

    def pause(self) -> dict:
        self._session.pause()
        return _ok()

    def resume(self) -> dict:
        self._session.resume()
        return _ok()

    def toggle_pause(self) -> dict:
        self._session.toggle_pause()
        return _ok()

    def stop(self) -> dict:
        """Stop and move the playhead back to the first item."""
        self._session.stop()
        self._session.reset()
        return _ok()

    def estimate(self, plan: dict) -> dict:
        parsed = RunPlan.from_dict(plan)
        text = parsed.text
        columns = {c.lower() for c in self._csv.columns} if self._csv else set()
        placeholders = []
        for name in find_placeholders(text):
            if name.lower() in columns:
                kind = "csv"
            elif is_builtin(name):
                kind = "builtin"
            else:
                kind = "missing"
            placeholders.append({"name": name, "kind": kind})
        rows = self._rows()
        fragments = split_text(text, parsed.split) if text.strip() else []
        copies = len(rows) if (parsed.use_csv_rows and rows) else parsed.repeat_count
        items = len(fragments) * copies
        per_copy = sum(estimate_seconds(fragment, parsed.settings) for fragment in fragments)
        seconds = per_copy * copies + max(0, items - 1) * parsed.repeat_interval_ms / 1000
        return _ok(seconds=seconds, chars=len(text), items=items, placeholders=placeholders)

    def preview(self, text: str, row_index: int = 0) -> dict:
        rows = self._rows() or [{}]
        index = max(0, min(len(rows) - 1, int(row_index or 0)))
        rendered = render(str(text or ""), rows[index], n=index + 1, total=len(rows),
                          clipboard=self._sender.get_clipboard)
        return _ok(text=rendered, row=index, total=len(rows))

    # -- windows -----------------------------------------------------------------

    def list_windows(self) -> dict:
        return _ok(windows=[w.to_dict() for w in windows.list_windows()])

    # -- CSV ---------------------------------------------------------------------

    def load_csv(self) -> dict:
        if self._window is None:
            return _fail("no_window")
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=("CSV (*.csv;*.txt;*.tsv)", "All files (*.*)"))
        if not result:
            return _fail("cancelled")
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            data = load_csv(path)
        except OSError as exc:
            return _fail("read_error", str(exc))
        if not data.columns:
            return _fail("empty_csv")
        with self._lock:
            self._csv = data
        return _ok(csv=data.to_dict())

    def clear_csv(self) -> dict:
        with self._lock:
            self._csv = None
        return _ok()

    # -- presets -----------------------------------------------------------------

    def save_preset(self, preset: dict) -> dict:
        if not isinstance(preset, dict):
            return _fail("invalid")
        name = str(preset.get("name", "") or "").strip()[:80]
        if not name:
            return _fail("invalid", "name required")
        with self._lock:
            preset_id = str(preset.get("id") or uuid.uuid4().hex)
            plan = RunPlan.from_dict(preset.get("plan")).to_dict()
            plan.pop("text", None)
            stored = {
                "id": preset_id,
                "name": name,
                "text": str(preset.get("text", "") or ""),
                "plan": plan,
                "updated": time.time(),
            }
            self._presets = [p for p in self._presets if p.get("id") != preset_id]
            self._presets.insert(0, stored)
            del self._presets[MAX_PRESETS:]
            self._store.write("presets", self._presets)
        return _ok(presets=self._presets, preset=stored)

    def delete_preset(self, preset_id: str) -> dict:
        with self._lock:
            self._presets = [p for p in self._presets if p.get("id") != preset_id]
            self._store.write("presets", self._presets)
        return _ok(presets=self._presets)

    def export_presets(self) -> dict:
        if self._window is None:
            return _fail("no_window")
        result = self._window.create_file_dialog(
            webview.FileDialog.SAVE, save_filename="typer-presets.json", file_types=("JSON (*.json)",))
        if not result:
            return _fail("cancelled")
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            Path(path).write_text(json.dumps({"typer_presets": self._presets}, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            return _fail("write_error", str(exc))
        return _ok(path=str(path))

    def import_presets(self) -> dict:
        if self._window is None:
            return _fail("no_window")
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("JSON (*.json)",))
        if not result:
            return _fail("cancelled")
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return _fail("read_error", str(exc))
        items = data.get("typer_presets") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return _fail("invalid", "not a Typer preset file")
        imported = 0
        with self._lock:
            known = {p.get("id") for p in self._presets}
            for item in items:
                if not isinstance(item, dict) or not str(item.get("name", "")).strip():
                    continue
                if item.get("id") in known:
                    item = dict(item, id=uuid.uuid4().hex)
                self._presets.append(item)
                imported += 1
            self._store.write("presets", self._presets)
        return _ok(presets=self._presets, imported=imported)

    # -- macros ------------------------------------------------------------------

    def _load_macros(self) -> list[Macro]:
        macros = []
        for raw in self._store.read("macros", []):
            try:
                macros.append(Macro.from_dict(raw))
            except ValueError:
                log.warning("skipping invalid macro: %r", raw)
        return macros

    def save_macro(self, macro: dict) -> dict:
        try:
            parsed = Macro.from_dict(macro)
        except ValueError as exc:
            return _fail("invalid_macro", str(exc))
        with self._lock:
            self._macros = [m for m in self._macros if m.id != parsed.id]
            self._macros.append(parsed)
            self._store.write("macros", [m.to_dict() for m in self._macros])
        errors = self._apply_hotkeys()
        return _ok(macros=[m.to_dict() for m in self._macros], macro=parsed.to_dict(), hotkey_errors=errors)

    def delete_macro(self, macro_id: str) -> dict:
        with self._lock:
            self._macros = [m for m in self._macros if m.id != macro_id]
            self._store.write("macros", [m.to_dict() for m in self._macros])
        self._apply_hotkeys()
        return _ok(macros=[m.to_dict() for m in self._macros])

    def run_macro(self, macro: dict, settings: dict, target: dict, countdown_s: float = 2) -> dict:
        try:
            parsed = Macro.from_dict(macro)
        except ValueError as exc:
            return _fail("invalid_macro", str(exc))
        try:
            self._session.start_macro(parsed, TypingSettings.from_dict(settings), Target.from_dict(target),
                                      max(0.0, min(60.0, float(countdown_s or 0))))
        except SessionError as exc:
            return _fail(str(exc))
        return _ok()

    def record_start(self) -> dict:
        if self._session.busy:
            return _fail("busy")
        if self._recorder.recording:
            return _ok()
        try:
            self._recorder.start()
        except Exception as exc:
            log.exception("recorder failed to start")
            return _fail("recorder", str(exc))
        self.emit("recording", {"active": True})
        return _ok()

    def record_stop(self) -> dict:
        steps = self._finish_recording()
        return _ok(steps=steps)

    def _toggle_recording(self) -> None:
        if self._recorder.recording:
            self._finish_recording()
        else:
            self.record_start()

    def _finish_recording(self) -> list[dict]:
        if not self._recorder.recording:
            return []
        stop_spec = self._settings.get("hotkeys", {}).get("record", "")
        steps = [s.to_dict() for s in self._recorder.stop(stop_hotkey=stop_spec)]
        self.emit("recording", {"active": False, "steps": steps})
        return steps

    def _is_own_point(self, x: int, y: int) -> bool:
        return windows.is_own_window(windows.window_at_point(x, y))

    def pick_point(self, delay_s: float = 3) -> dict:
        time.sleep(max(0.0, min(10.0, float(delay_s or 0))))
        x, y = self._sender.cursor_position()
        return _ok(x=x, y=y)

    # -- misc --------------------------------------------------------------------

    def open_data_folder(self) -> dict:
        try:
            os.startfile(str(self._store.directory))  # type: ignore[attr-defined]
        except OSError as exc:
            return _fail("open_failed", str(exc))
        return _ok()
