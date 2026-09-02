"""Placeholder rendering and CSV loading for repeated typing.

Placeholders look like `{name}`. CSV columns win over the built-ins
(`{n}`, `{total}`, `{date}`, `{time}`, `{datetime}`, `{clipboard}`, `{rand:1-100}`,
`{rand:a|b|c}`, `{uuid}`). Unknown placeholders are left untouched and `{{`/`}}`
produce literal braces.
"""

from __future__ import annotations

import csv
import io
import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

PLACEHOLDER_RE = re.compile(r"\{\{|\}\}|\{([^{}:]+?)(?::([^{}]*))?\}")
BUILTIN_NAMES = ("n", "total", "date", "time", "datetime", "clipboard", "rand", "uuid")
_RANGE_RE = re.compile(r"^\s*(-?\d+)\s*-\s*(-?\d+)\s*$")
_DEFAULT_FORMATS = {"date": "%Y-%m-%d", "time": "%H:%M", "datetime": "%Y-%m-%d %H:%M"}
_ENCODINGS = ("utf-8-sig", "utf-8", "cp1250", "cp1252", "latin-1")


def _lookup(values: dict[str, str] | None, name: str) -> str | None:
    if not values:
        return None
    if name in values:
        return values[name]
    wanted = name.strip().lower()
    for key, value in values.items():
        if str(key).strip().lower() == wanted:
            return value
    return None


def _random_value(arg: str | None, rng: random.Random) -> str:
    if not arg:
        return str(rng.randint(0, 99))
    match = _RANGE_RE.match(arg)
    if match:
        low, high = sorted((int(match.group(1)), int(match.group(2))))
        return str(rng.randint(low, high))
    options = [item.strip() for item in arg.split("|") if item.strip()]
    return rng.choice(options) if options else ""


def render(
    template: str,
    values: dict[str, str] | None = None,
    *,
    n: int = 1,
    total: int = 1,
    rng: random.Random | None = None,
    now: datetime | None = None,
    clipboard: Callable[[], str | None] | None = None,
) -> str:
    rng = rng or random.Random()
    moment = now or datetime.now()

    def replace(match: re.Match) -> str:
        token = match.group(0)
        if token == "{{":
            return "{"
        if token == "}}":
            return "}"
        name = match.group(1).strip()
        arg = match.group(2)
        value = _lookup(values, name)
        if value is not None:
            return str(value)
        lowered = name.lower()
        if lowered == "n":
            return str(n).zfill(int(arg)) if arg and arg.strip().isdigit() else str(n)
        if lowered == "total":
            return str(total)
        if lowered in _DEFAULT_FORMATS:
            try:
                return moment.strftime(arg if arg else _DEFAULT_FORMATS[lowered])
            except ValueError:
                return token
        if lowered == "clipboard":
            text = clipboard() if clipboard else None
            return text or ""
        if lowered == "rand":
            return _random_value(arg, rng)
        if lowered == "uuid":
            return str(uuid.UUID(int=rng.getrandbits(128), version=4))
        return token

    return PLACEHOLDER_RE.sub(replace, template)


def find_placeholders(template: str) -> list[str]:
    """Unique placeholder names in order of first appearance (escapes excluded)."""
    names: list[str] = []
    for match in PLACEHOLDER_RE.finditer(template):
        if match.group(1) is None:
            continue
        name = match.group(1).strip()
        if name and name not in names:
            names.append(name)
    return names


def is_builtin(name: str) -> bool:
    return name.strip().lower() in BUILTIN_NAMES


@dataclass
class CsvData:
    path: str
    columns: list[str]
    rows: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self, preview: int = 5) -> dict:
        return {
            "path": self.path,
            "name": Path(self.path).name if self.path else "",
            "columns": self.columns,
            "count": len(self.rows),
            "preview": self.rows[:preview],
        }


def _decode(data: bytes) -> str:
    for encoding in _ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _guess_delimiter(header: str) -> str:
    candidates = {sep: header.count(sep) for sep in (";", ",", "\t", "|")}
    best = max(candidates, key=candidates.get)
    return best if candidates[best] > 0 else ","


def parse_csv_text(text: str, path: str = "") -> CsvData:
    text = text.lstrip("\ufeff")
    first_line = text.split("\n", 1)[0]
    reader = csv.reader(io.StringIO(text), delimiter=_guess_delimiter(first_line))
    rows_raw = list(reader)
    if not rows_raw:
        return CsvData(path=path, columns=[])
    columns = [name.strip() for name in rows_raw[0]]
    rows: list[dict[str, str]] = []
    for raw in rows_raw[1:]:
        if not any(cell.strip() for cell in raw):
            continue
        rows.append({columns[i]: (raw[i] if i < len(raw) else "") for i in range(len(columns)) if columns[i]})
    return CsvData(path=path, columns=[c for c in columns if c], rows=rows)


def load_csv(path: str | Path) -> CsvData:
    data = Path(path).read_bytes()
    return parse_csv_text(_decode(data), str(path))
