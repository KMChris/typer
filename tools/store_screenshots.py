"""Takes the Microsoft Store screenshots of the real app window filled with sample data.

  python tools\\store_screenshots.py [--lang pl,en] [--out DIR] [--size 1920x1080]

Starts Typer with a temporary data folder seeded with sample presets, macros, a CSV file and a
draft text, drives the page through the same buttons a user clicks and captures it with the
WebView2 DevTools protocol at exactly the requested size, whatever the real window size is.
Each language runs in its own process because pywebview can start only once per process.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import webview  # noqa: E402

from typer_app.api import Api  # noqa: E402
from typer_app.app import UI_DIR, style_title_bar  # noqa: E402
from typer_app.storage import Store  # noqa: E402

HOTKEYS = {"start_pause": "f7", "stop_reset": "f5", "prev": "f6", "next": "f8", "record": "f9"}
PLAN = {
    "settings": {"char_delay_ms": 35, "jitter_pct": 30, "newline_mode": "enter", "word_pause_ms": 40,
                 "punct_pause_ms": 120, "newline_pause_ms": 250, "input_method": "unicode", "instant": False,
                 "final_key": "", "typo_pct": 1.5},
    "split": "whole", "repeat_count": 1, "repeat_interval_ms": 800, "use_csv_rows": False, "countdown_s": 3,
}
ASCII = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")

# ------------------------------------------------------------------ sample data


def text(value: str) -> dict:
    return {"kind": "text", "text": value}


def key(combo: str) -> dict:
    return {"kind": "key", "key": combo}


def wait(ms: int) -> dict:
    return {"kind": "wait", "ms": ms}


def focus(title: str) -> dict:
    return {"kind": "focus", "title": title}


def click(x: int, y: int) -> dict:
    return {"kind": "mouse_click", "x": x, "y": y, "button": "left", "count": 1}


def mouse(kind: str, x: int, y: int, **extra) -> dict:
    return {"kind": kind, "x": x, "y": y, **extra}


def rows(first_names: list[str], surnames: list[str], order_prefix: str, shipping: list[str], columns: list[str]) -> list[dict]:
    result = []
    for index, (first, last) in enumerate(zip(first_names, surnames)):
        email = f"{first}.{last}@example.com".translate(ASCII).lower()
        values = [first, last, email, f"{order_prefix}-{4810 + index * 7}", shipping[index % len(shipping)]]
        result.append(dict(zip(columns, values)))
    return result


PL_FIRST = ["Anna", "Michał", "Zofia", "Łukasz", "Katarzyna", "Paweł", "Małgorzata", "Tomasz", "Agnieszka", "Jakub",
            "Ewa", "Piotr", "Magdalena", "Krzysztof", "Joanna", "Marcin", "Aleksandra", "Bartosz", "Natalia",
            "Grzegorz", "Karolina", "Wojciech", "Julia", "Mateusz"]
PL_LAST = ["Nowak", "Kowalska", "Wiśniewski", "Wójcik", "Kamińska", "Lewandowski", "Zielińska", "Szymański",
           "Woźniak", "Dąbrowska", "Kozłowski", "Jankowska", "Mazur", "Krawczyk", "Piotrowska", "Grabowski",
           "Pawłowska", "Michalski", "Nowicka", "Adamczyk", "Dudek", "Zając", "Wieczorek", "Jabłońska"]
EN_FIRST = ["Emma", "Liam", "Olivia", "Noah", "Ava", "Oliver", "Sophia", "Elijah", "Isabella", "James", "Mia",
            "William", "Charlotte", "Benjamin", "Amelia", "Lucas", "Harper", "Henry", "Evelyn", "Alexander",
            "Abigail", "Mason", "Emily", "Ethan"]
EN_LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
           "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee",
           "Perez", "Thompson", "White", "Harris"]

PL_TEXT = """Dzień dobry {imie},

dziękujemy za zamówienie nr {zamowienie} w sklepie Papierowo. Paczka wyjedzie z magazynu {wysylka}, a numer do śledzenia prześlemy tego samego dnia na adres {email}.

Jeśli chcesz coś zmienić w zamówieniu, odpisz na tę wiadomość do godziny 14:00. Zamówienia złożone do południa wysyłamy tego samego dnia.

Pozdrawiam serdecznie
Anna Kowalska
Papierowo, obsługa klienta · {date}"""

EN_TEXT = """Hello {name},

thank you for order no. {order} at Paper & Co. It leaves our warehouse {shipping}, and we will email the tracking number to {email} the same day.

If you would like to change anything, reply to this message before 2 pm. Orders placed before noon ship the same day.

Kind regards
Anna Kowalski
Paper & Co, customer care · {date}"""

SAMPLES = {
    "pl": {
        "csv_name": "klienci.csv",
        "columns": ["imie", "nazwisko", "email", "zamowienie", "wysylka"],
        "rows": rows(PL_FIRST, PL_LAST, "PA", ["w poniedziałek 7 września", "we wtorek 8 września", "w środę 9 września",
                                              "w czwartek 10 września", "w piątek 11 września"],
                     ["imie", "nazwisko", "email", "zamowienie", "wysylka"]),
        "text": PL_TEXT,
        "target": {"hwnd": 1, "title": "Panel klienta – Papierowo – Google Chrome", "process": "chrome.exe"},
        "data_dir": r"C:\Users\Anna\AppData\Roaming\Typer",
        "presets": [
            ("Potwierdzenie zamówienia", PL_TEXT, {"use_csv_rows": True}),
            ("Raport dzienny na czacie",
             "Raport dzienny, {date}\nZamknięte zgłoszenia: 14\nW toku: 3\nWymaga uwagi: #4821 (opóźniona dostawa)\nNastępna aktualizacja jutro o 9:00.",
             {"settings": {"instant": True, "newline_mode": "shift_enter", "final_key": "enter"}, "countdown_s": 2}),
            ("Odpowiedź na reklamację",
             "Dzień dobry,\n\nprzykro nam, że przesyłka dotarła uszkodzona. Jeszcze dziś wysyłamy nowy egzemplarz na nasz koszt, "
             "a kurier odbierze uszkodzony towar przy doręczeniu. Nie trzeba niczego odsyłać samodzielnie.\n\n"
             "Jeśli wolisz zwrot pieniędzy zamiast wymiany, wystarczy jedno zdanie w odpowiedzi.\n\nPozdrawiam\nAnna Kowalska",
             {"settings": {"char_delay_ms": 45, "jitter_pct": 35, "typo_pct": 2}}),
            ("Komendy serwera (SSH)", "cd /var/www/sklep\ngit pull --ff-only\nsudo systemctl restart sklep\njournalctl -u sklep -n 20",
             {"settings": {"char_delay_ms": 5, "jitter_pct": 0, "input_method": "keys"}, "split": "lines",
              "repeat_interval_ms": 1500, "countdown_s": 5}),
            ("Formularz CRM: nowy klient", "{imie} {nazwisko}\n{email}\n{zamowienie}",
             {"settings": {"char_delay_ms": 20, "jitter_pct": 10, "newline_mode": "none", "final_key": "tab"},
              "split": "lines", "use_csv_rows": True}),
            ("Notatka ze spotkania",
             "Spotkanie zespołu, {date}\n\nUstalenia:\n- nowy cennik od 1 października\n- na reklamacje odpowiadamy w 24 godziny\n"
             "- Michał przygotuje szablony odpowiedzi\n\nNastępne spotkanie: piątek, 10:00.",
             {"settings": {"char_delay_ms": 25, "jitter_pct": 20}, "split": "paragraphs"}),
            ("Powitanie na czacie wsparcia",
             "Dzień dobry, tu Anna z Papierowo. Widzę Twoje zgłoszenie i już je sprawdzam. Daj mi dwie minuty.",
             {"settings": {"char_delay_ms": 40, "jitter_pct": 40, "typo_pct": 1, "newline_mode": "shift_enter", "final_key": "enter"}}),
            ("Status zamówienia",
             "Zamówienie {zamowienie} jest już w drodze. Kurier dostarczy paczkę {wysylka}. Numer do śledzenia wysłaliśmy na {email}.",
             {"settings": {"instant": True}, "use_csv_rows": True}),
            ("Przypomnienie o płatności",
             "Dzień dobry {imie},\n\nprzypominamy o płatności za zamówienie {zamowienie}. Jeśli przelew już wyszedł, prosimy zignorować tę wiadomość.\n\nPozdrawiamy\nPapierowo",
             {"settings": {"char_delay_ms": 30, "jitter_pct": 25}, "use_csv_rows": True, "countdown_s": 5}),
            ("Podziękowanie po spotkaniu",
             "Dziękuję za dzisiejsze spotkanie. Podsumowanie i kolejne kroki wyślę do końca dnia. W razie pytań jestem pod telefonem.",
             {"settings": {"char_delay_ms": 50, "jitter_pct": 30, "typo_pct": 2.5, "word_pause_ms": 80}}),
        ],
        "macros": [
            ("Raport na czacie zespołu", "ctrl+shift+r",
             [focus("Teams"), wait(400), text("Raport dzienny: 14 zgłoszeń zamkniętych, 3 w toku, #4821 wymaga uwagi."), key("enter")]),
            ("Nowe zgłoszenie w CRM", "ctrl+shift+n",
             [focus("Panel klienta"), wait(300), click(412, 188), wait(500), text("Reklamacja: uszkodzona przesyłka"), key("tab"),
              text("Priorytet: wysoki"), key("tab"), text("Kurier odbierze towar przy doręczeniu nowego egzemplarza."), key("ctrl+enter")]),
            ("Zapisz i zamknij kartę", "ctrl+shift+q", [key("ctrl+s"), wait(300), key("ctrl+w")]),
            ("Przewiń i zaznacz tabelę", "",
             [mouse("mouse_move", 640, 420), mouse("mouse_scroll", 640, 420, dx=0, dy=-10), wait(200),
              mouse("mouse_down", 300, 300, button="left"), mouse("mouse_up", 900, 640, button="left")]),
        ],
    },
    "en": {
        "csv_name": "customers.csv",
        "columns": ["name", "surname", "email", "order", "shipping"],
        "rows": rows(EN_FIRST, EN_LAST, "PC", ["on Monday 7 September", "on Tuesday 8 September", "on Wednesday 9 September",
                                              "on Thursday 10 September", "on Friday 11 September"],
                     ["name", "surname", "email", "order", "shipping"]),
        "text": EN_TEXT,
        "target": {"hwnd": 1, "title": "Customer panel – Paper & Co – Google Chrome", "process": "chrome.exe"},
        "data_dir": r"C:\Users\Anna\AppData\Roaming\Typer",
        "presets": [
            ("Order confirmation", EN_TEXT, {"use_csv_rows": True}),
            ("Daily report on the chat",
             "Daily report, {date}\nTickets closed: 14\nIn progress: 3\nNeeds attention: #4821 (delayed delivery)\nNext update tomorrow at 9:00.",
             {"settings": {"instant": True, "newline_mode": "shift_enter", "final_key": "enter"}, "countdown_s": 2}),
            ("Reply to a complaint",
             "Hello,\n\nwe are sorry the parcel arrived damaged. A replacement ships today at our expense and the courier will "
             "collect the damaged item on delivery. There is nothing you need to send back yourself.\n\n"
             "If you would prefer a refund instead of a replacement, one sentence in your reply is enough.\n\nKind regards\nAnna Kowalski",
             {"settings": {"char_delay_ms": 45, "jitter_pct": 35, "typo_pct": 2}}),
            ("Server commands (SSH)", "cd /var/www/shop\ngit pull --ff-only\nsudo systemctl restart shop\njournalctl -u shop -n 20",
             {"settings": {"char_delay_ms": 5, "jitter_pct": 0, "input_method": "keys"}, "split": "lines",
              "repeat_interval_ms": 1500, "countdown_s": 5}),
            ("CRM form: new customer", "{name} {surname}\n{email}\n{order}",
             {"settings": {"char_delay_ms": 20, "jitter_pct": 10, "newline_mode": "none", "final_key": "tab"},
              "split": "lines", "use_csv_rows": True}),
            ("Meeting notes",
             "Team meeting, {date}\n\nDecisions:\n- new price list from 1 October\n- complaints get an answer within 24 hours\n"
             "- Michael prepares the reply templates\n\nNext meeting: Friday, 10:00.",
             {"settings": {"char_delay_ms": 25, "jitter_pct": 20}, "split": "paragraphs"}),
            ("Support chat greeting",
             "Hi, this is Anna from Paper & Co. I can see your ticket and I am looking into it now. Give me two minutes.",
             {"settings": {"char_delay_ms": 40, "jitter_pct": 40, "typo_pct": 1, "newline_mode": "shift_enter", "final_key": "enter"}}),
            ("Order status",
             "Order {order} is on its way. The courier delivers it {shipping}. We sent the tracking number to {email}.",
             {"settings": {"instant": True}, "use_csv_rows": True}),
            ("Payment reminder",
             "Hello {name},\n\nthis is a reminder about the payment for order {order}. If the transfer is already on its way, please ignore this message.\n\nKind regards\nPaper & Co",
             {"settings": {"char_delay_ms": 30, "jitter_pct": 25}, "use_csv_rows": True, "countdown_s": 5}),
            ("Thank you after a meeting",
             "Thank you for today's meeting. I will send the summary and next steps by the end of the day. Call me if anything is unclear.",
             {"settings": {"char_delay_ms": 50, "jitter_pct": 30, "typo_pct": 2.5, "word_pause_ms": 80}}),
        ],
        "macros": [
            ("Daily report on the team chat", "ctrl+shift+r",
             [focus("Teams"), wait(400), text("Daily report: 14 tickets closed, 3 in progress, #4821 needs attention."), key("enter")]),
            ("New ticket in the CRM", "ctrl+shift+n",
             [focus("Customer panel"), wait(300), click(412, 188), wait(500), text("Complaint: damaged parcel"), key("tab"),
              text("Priority: high"), key("tab"), text("The courier collects the damaged item when delivering the replacement."), key("ctrl+enter")]),
            ("Save and close the tab", "ctrl+shift+q", [key("ctrl+s"), wait(300), key("ctrl+w")]),
            ("Scroll and select the table", "",
             [mouse("mouse_move", 640, 420), mouse("mouse_scroll", 640, 420, dx=0, dy=-10), wait(200),
              mouse("mouse_down", 300, 300, button="left"), mouse("mouse_up", 900, 640, button="left")]),
        ],
    },
}


def merged_plan(overrides: dict) -> dict:
    plan = json.loads(json.dumps(PLAN))
    plan["settings"].update(overrides.get("settings", {}))
    plan.update({k: v for k, v in overrides.items() if k != "settings"})
    return plan


def seed(directory: Path, lang: str) -> Path:
    """Writes the JSON files Typer reads on start plus the sample CSV; returns the CSV path."""
    sample = SAMPLES[lang]
    store = Store(directory)
    store.write("settings", {"language": lang, "theme": "dark", "hotkeys": HOTKEYS, "escape_stops": True,
                             "draft": {"text": sample["text"], **PLAN}})
    now = time.time()
    store.write("presets", [
        {"id": f"sample-preset-{index}", "name": name, "text": body, "plan": merged_plan(overrides), "updated": now - index * 86400}
        for index, (name, body, overrides) in enumerate(sample["presets"])
    ])
    store.write("macros", [
        {"id": f"sample-macro-{index}", "name": name, "hotkey": hotkey, "repeat": 1, "interval_ms": 0, "steps": steps}
        for index, (name, hotkey, steps) in enumerate(sample["macros"])
    ])
    csv_path = directory / sample["csv_name"]
    lines = [",".join(sample["columns"])] + [",".join(row[c] for c in sample["columns"]) for row in sample["rows"]]
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path


# ------------------------------------------------------------------ capture


class Shooter:
    def __init__(self, window, out_dir: Path, width: int, height: int) -> None:
        self.window = window
        self.out_dir = out_dir
        self.width, self.height = width, height
        self.files: list[Path] = []

    def js(self, code: str):
        return self.window.evaluate_js(code)

    def emit(self, name: str, payload: dict) -> None:
        self.js(f"window.typer.emit({json.dumps(name)}, {json.dumps(payload, ensure_ascii=False)})")

    def click(self, selector: str, index: int = 0) -> None:
        self.js(f"document.querySelectorAll({json.dumps(selector)})[{index}].click()")
        time.sleep(0.35)

    def cdp(self, method: str, params: dict) -> dict:
        """Calls a DevTools protocol method; CoreWebView2 must be touched on the UI thread."""
        from System import Action

        form = self.window.native
        box: dict = {}

        def call() -> None:
            core = form.browser.webview.CoreWebView2
            box["task"] = core.CallDevToolsProtocolMethodAsync(method, json.dumps(params))

        form.Invoke(Action(call))
        task = box["task"]
        while not task.IsCompleted:
            time.sleep(0.02)
        if task.IsFaulted:
            raise RuntimeError(f"{method}: {task.Exception}")
        return json.loads(task.Result) if task.Result else {}

    def wait_ready(self, timeout: float = 20) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.js("Boolean(window.typer) && document.querySelector('#version').textContent !== ''"):
                    return
            except Exception:
                pass
            time.sleep(0.25)
        raise RuntimeError("the page did not initialise")

    def emulate(self) -> None:
        self.cdp("Emulation.setDeviceMetricsOverride",
                 {"width": self.width, "height": self.height, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(0.6)

    def shot(self, name: str) -> None:
        self.js("document.querySelectorAll('.toast').forEach(t => t.remove())")
        time.sleep(0.3)
        result = self.cdp("Page.captureScreenshot", {
            "format": "png", "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": self.width, "height": self.height, "scale": 1},
        })
        path = self.out_dir / f"{name}.png"
        path.write_bytes(base64.b64decode(result["data"]))
        self.files.append(path)
        print(f"wrote {path}")


def scenes(shooter: Shooter, sample: dict) -> None:
    total = len(sample["rows"])
    shooter.wait_ready()
    shooter.emulate()
    shooter.emit("target", sample["target"])

    # 1. Typer view: text with placeholders, CSV loaded, preview of the first row.
    shooter.click("#csv-load")
    time.sleep(1.0)
    if shooter.js("document.querySelector('#csv-loaded').hidden"):
        raise RuntimeError("the CSV file was not loaded")
    shooter.click("#csv-preview-toggle")
    time.sleep(0.8)
    shooter.shot("01-typer")

    # 3. Countdown overlay before typing starts.
    shooter.emit("state", {"state": "countdown", "kind": "typing"})
    shooter.emit("position", {"last": -1, "total": total})
    shooter.emit("countdown", {"seconds": 3})
    time.sleep(0.9)
    shooter.shot("03-countdown")

    # 2. Typing in progress: row 10 of the CSV, progress bar, pause and stop enabled.
    iteration, done, chars = 10, 57, 143
    shooter.emit("countdown", {"seconds": 0})
    shooter.emit("state", {"state": "running", "kind": "typing"})
    shooter.emit("position", {"last": iteration - 2, "total": total})
    shooter.js(f"for (let i = 1; i < {iteration}; i++) document.querySelector('#csv-next').click()")
    time.sleep(0.8)
    percent = round((iteration - 1 + done / chars) / total * 100, 1)
    shooter.emit("progress", {"done": done, "total": chars, "iteration": iteration, "iterations": total, "percent": percent})
    time.sleep(0.5)
    shooter.shot("02-typing")
    shooter.emit("state", {"state": "idle", "kind": ""})
    shooter.emit("position", {"last": -1, "total": total})

    # 4. Macros: the second sample macro open in the editor.
    shooter.click(".rail-item[data-view=macros]")
    shooter.click(".macro-item", 1)
    time.sleep(0.4)
    shooter.shot("04-macros")

    # 5. Presets grid and 6. the full-window preview of the first preset.
    shooter.click(".rail-item[data-view=presets]")
    shooter.shot("05-presets")
    shooter.click(".preset", 0)
    shooter.shot("06-preset-preview")
    shooter.click("#preset-back")

    # 7. Settings with the hotkeys; the data folder shows a typical path instead of the temp one.
    shooter.click(".rail-item[data-view=settings]")
    shooter.js(f"document.querySelector('#data-dir').textContent = {json.dumps(sample['data_dir'])}")
    time.sleep(0.4)
    shooter.shot("07-settings")

    # 8. Light theme (applied on the page only, the native title bar is not in the capture).
    shooter.js("document.documentElement.dataset.theme = 'light';"
               "document.querySelector('meta[name=\"color-scheme\"]').content = 'light';"
               "document.querySelector('#theme-toggle use').setAttribute('href', '#i-moon');")
    shooter.click(".rail-item[data-view=typer]")
    time.sleep(0.6)
    shooter.shot("08-light-theme")


def run(lang: str, out_dir: Path, width: int, height: int) -> None:
    out_dir = out_dir / lang
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path(tempfile.mkdtemp(prefix=f"typer-shots-{lang}-"))
    csv_path = seed(data_dir, lang)
    api = Api(Store(data_dir))
    window = webview.create_window("Typer", url=str(UI_DIR / "index.html"), js_api=api, width=1180, height=780,
                                   min_size=(900, 600), background_color="#0e1016", text_select=True)
    api.attach(window)
    # The CSV button opens a file dialog; here it "picks" the sample file straight away.
    window.create_file_dialog = lambda *args, **kwargs: [str(csv_path)]
    shooter = Shooter(window, out_dir, width, height)
    outcome: dict = {}

    def on_shown() -> None:
        hwnd = int(window.native.Handle.ToInt64())
        api.set_hwnd(hwnd)
        style_title_bar(hwnd, "dark")

    window.events.shown += on_shown

    def driver() -> None:
        try:
            scenes(shooter, SAMPLES[lang])
        except Exception as exc:  # pragma: no cover - diagnostic tool
            outcome["error"] = repr(exc)
        finally:
            api.shutdown()
            window.destroy()

    threading.Thread(target=driver, daemon=True).start()
    webview.start()
    if "error" in outcome:
        sys.exit(f"{lang}: {outcome['error']}")
    print(f"{lang}: {len(shooter.files)} screenshots in {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lang", default="pl,en", help="comma separated: pl, en")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "store" / "screenshots")
    parser.add_argument("--size", default="1920x1080", help="WIDTHxHEIGHT, at least 1366x768 for the Store")
    args = parser.parse_args()
    width, height = (int(v) for v in args.size.lower().split("x"))
    languages = [lang.strip() for lang in args.lang.split(",") if lang.strip()]
    unknown = [lang for lang in languages if lang not in SAMPLES]
    if unknown:
        sys.exit(f"no sample data for: {', '.join(unknown)}")
    if len(languages) > 1:
        for lang in languages:
            subprocess.run([sys.executable, __file__, "--lang", lang, "--out", str(args.out), "--size", args.size], check=True)
        return
    run(languages[0], args.out, width, height)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
