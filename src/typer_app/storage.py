"""JSON persistence for settings, presets and macros."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

APP_DIR_NAME = "Typer"


def install_dir() -> Path:
    """Folder of the executable (frozen) or the project root (source checkout)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    """`data/` next to the app when `portable.txt` exists there, otherwise %APPDATA%/Typer."""
    base = install_dir()
    if (base / "portable.txt").exists():
        return base / "data"
    appdata = os.environ.get("APPDATA")
    return (Path(appdata) if appdata else Path.home()) / APP_DIR_NAME


class Store:
    """Reads and writes named JSON documents atomically; corrupt files are set aside, not lost."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self.directory / f"{name}.json"

    def read(self, name: str, default):
        path = self.path(name)
        if not path.exists():
            return default
        try:
            with path.open(encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            backup = path.with_name(f"{name}.corrupt-{int(time.time())}.json")
            try:
                path.replace(backup)
            except OSError:
                pass
            return default

    def write(self, name: str, data) -> None:
        path = self.path(name)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
