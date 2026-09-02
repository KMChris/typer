"""Runs typing jobs and macros on a worker thread with countdown, targeting and progress events."""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .macro import Macro, run_macro
from .template import render
from .typing import Control, TypingJob, TypingSettings

log = logging.getLogger(__name__)

EmitFn = Callable[[str, dict], None]
TARGET_MODES = ("auto", "window", "foreground")
PROGRESS_INTERVAL_S = 1 / 15


class SessionError(Exception):
    """Raised when a job cannot be started (e.g. another one is running)."""


@dataclass
class Target:
    """Where to type: the last external window, a chosen window, or whatever is in front."""

    mode: str = "auto"
    hwnd: int = 0

    @classmethod
    def from_dict(cls, data: object) -> "Target":
        if not isinstance(data, dict):
            return cls()
        mode = str(data.get("mode", "auto"))
        try:
            hwnd = int(data.get("hwnd", 0) or 0)
        except (TypeError, ValueError):
            hwnd = 0
        return cls(mode=mode if mode in TARGET_MODES else "auto", hwnd=hwnd)


@dataclass
class RunPlan:
    text: str = ""
    settings: TypingSettings = field(default_factory=TypingSettings)
    repeat_count: int = 1
    repeat_interval_ms: int = 500
    use_csv_rows: bool = False
    countdown_s: float = 3.0
    target: Target = field(default_factory=Target)

    @classmethod
    def from_dict(cls, data: object) -> "RunPlan":
        if not isinstance(data, dict):
            return cls()

        def number(key: str, default, low, high, cast):
            try:
                value = cast(data.get(key, default))
            except (TypeError, ValueError):
                value = default
            return max(low, min(high, value))

        return cls(
            text=str(data.get("text", "") or ""),
            settings=TypingSettings.from_dict(data.get("settings")),
            repeat_count=number("repeat_count", 1, 1, 100_000, int),
            repeat_interval_ms=number("repeat_interval_ms", 500, 0, 3_600_000, int),
            use_csv_rows=bool(data.get("use_csv_rows", False)),
            countdown_s=number("countdown_s", 3.0, 0.0, 120.0, float),
            target=Target.from_dict(data.get("target")),
        )


class Session:
    """Owns the worker thread and the shared Control. Only one job runs at a time."""

    def __init__(
        self,
        sender,
        emit: EmitFn,
        *,
        focus_window: Callable[[int], bool],
        resolve_auto_target: Callable[[], int],
        foreground_is_own: Callable[[], bool],
        focus_by_title: Callable[[str], bool] | None = None,
        control: Control | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._sender = sender
        self._emit = emit
        self._focus_window = focus_window
        self._resolve_auto_target = resolve_auto_target
        self._foreground_is_own = foreground_is_own
        self._focus_by_title = focus_by_title
        self._control = control or Control()
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last_progress = 0.0
        self.state = "idle"
        self.kind = ""

    @property
    def busy(self) -> bool:
        return self.state != "idle"

    def snapshot(self) -> dict:
        return {"state": self.state, "kind": self.kind}

    # -- commands -----------------------------------------------------------------

    def start_typing(self, plan: RunPlan, rows: list[dict] | None = None) -> None:
        if not plan.text.strip():
            raise SessionError("empty_text")
        self._launch("typing", lambda: self._run_typing(plan, rows))

    def start_macro(self, macro: Macro, settings: TypingSettings, target: Target, countdown_s: float = 0.0) -> None:
        if not macro.steps:
            raise SessionError("empty_macro")
        self._launch("macro", lambda: self._run_macro(macro, settings, target, countdown_s))

    def pause(self) -> None:
        if self.state == "running":
            self._control.pause()
            self._set_state("paused")

    def resume(self) -> None:
        if self.state == "paused":
            self._control.resume()
            self._set_state("running")

    def toggle_pause(self) -> None:
        if self.state == "paused":
            self.resume()
        else:
            self.pause()

    def stop(self) -> None:
        if self.busy:
            self._control.cancel()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # -- internals ----------------------------------------------------------------

    def _launch(self, kind: str, work: Callable[[], None]) -> None:
        with self._lock:
            if self.busy:
                raise SessionError("busy")
            self._control.reset()
            self.kind = kind
            self.state = "countdown"
            self._thread = threading.Thread(target=work, name=f"session-{kind}", daemon=True)
            self._thread.start()

    def _set_state(self, state: str) -> None:
        self.state = state
        self._emit("state", self.snapshot())

    def _finish(self, reason: str, message: str = "") -> None:
        kind = self.kind
        self.state = "idle"
        self.kind = ""
        self._emit("finished", {"reason": reason, "message": message, "kind": kind})
        self._emit("state", self.snapshot())

    def _prepare(self, countdown_s: float, target: Target) -> bool:
        self._set_state("countdown")
        remaining = float(countdown_s)
        while remaining > 0:
            self._emit("countdown", {"seconds": math.ceil(remaining)})
            step = min(1.0, remaining)
            if not self._control.wait(step):
                return False
            remaining -= step
        self._emit("countdown", {"seconds": 0})
        hwnd = 0
        if target.mode == "window":
            hwnd = target.hwnd
        elif target.mode == "auto":
            hwnd = self._resolve_auto_target()
        if hwnd and not self._focus_window(hwnd):
            self._emit("notice", {"level": "error", "code": "focus_failed"})
            return False
        if self._foreground_is_own():
            self._emit("notice", {"level": "error", "code": "own_window"})
            return False
        wait_released = getattr(self._sender, "wait_modifiers_released", None)
        if wait_released is not None and not wait_released(1.5):
            release = getattr(self._sender, "release_modifiers", None)
            if release is not None:
                release()
        self._set_state("running")
        return True

    def _blocked_reason(self) -> str:
        return "cancelled" if self._control.cancelled else "blocked"

    def _progress(self, iteration: int, iterations: int, done: int, total: int) -> None:
        now = time.monotonic()
        if done < total and now - self._last_progress < PROGRESS_INTERVAL_S:
            return
        self._last_progress = now
        fraction = (iteration + (done / total if total else 1.0)) / max(1, iterations)
        self._emit("progress", {
            "done": done,
            "total": total,
            "iteration": iteration + 1,
            "iterations": iterations,
            "percent": round(fraction * 100, 1),
        })

    def _run_typing(self, plan: RunPlan, rows: list[dict] | None) -> None:
        try:
            if not self._prepare(plan.countdown_s, plan.target):
                self._finish(self._blocked_reason())
                return
            iterations = len(rows) if (plan.use_csv_rows and rows) else plan.repeat_count
            for iteration in range(iterations):
                values = rows[iteration % len(rows)] if rows else None
                text = render(plan.text, values, n=iteration + 1, total=iterations, rng=self._rng,
                              clipboard=self._sender.get_clipboard)
                job = TypingJob(
                    text, plan.settings, self._sender, self._control,
                    on_progress=lambda done, total, it=iteration: self._progress(it, iterations, done, total),
                    rng=self._rng,
                )
                if not job.run():
                    self._finish("cancelled")
                    return
                if iteration < iterations - 1 and plan.repeat_interval_ms > 0:
                    if not self._control.wait(plan.repeat_interval_ms / 1000):
                        self._finish("cancelled")
                        return
            self._finish("done")
        except Exception as exc:
            log.exception("typing job failed")
            self._finish("error", str(exc))

    def _run_macro(self, macro: Macro, settings: TypingSettings, target: Target, countdown_s: float) -> None:
        try:
            if not self._prepare(countdown_s, target):
                self._finish(self._blocked_reason())
                return
            total_steps = len(macro.steps) * macro.repeat

            def progress(index: int, total: int, repetition: int, repetitions: int) -> None:
                done = (repetition - 1) * total + index
                self._emit("progress", {
                    "done": done, "total": total_steps, "iteration": repetition,
                    "iterations": repetitions, "percent": round(done / max(1, total_steps) * 100, 1),
                })

            finished = run_macro(macro, settings, self._sender, self._control,
                                 focus_by_title=self._focus_by_title, on_progress=progress, rng=self._rng)
            self._finish("done" if finished else "cancelled")
        except Exception as exc:
            log.exception("macro failed")
            self._finish("error", str(exc))
