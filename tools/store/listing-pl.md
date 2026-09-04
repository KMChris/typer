# Typer Macro in the Microsoft Store: Polish listing (pl-PL)

Partner Center texts for the pl-PL Store listing; the en-US listing is in `listing-en.md`. Field limits follow the
Partner Center documentation as of September 2026. Required fields are marked; the others are optional.

## Product name

`Typer Macro`, reserved in Partner Center ("Typer" alone was taken by an unpublished reservation). The same value is
`display_name` in `tools\msix\identity.json`: the manifest `DisplayName` has to be one of the reserved names and appears in
the Start menu. The in-app name remains "Typer". Several names can be reserved for one app; unused reservations expire
after three months.

## Properties

| Field | Value |
| --- | --- |
| Category | Productivity |
| Secondary category | Utilities & tools |
| Privacy: does the app access, collect or transmit personal information? | **No** |
| Privacy policy URL | optional; text in `privacy-policy.md` (a GitHub Pages page or the file in the repository) |
| Website | repository or project page URL |
| Support contact info | e-mail address or the repository's issue tracker |
| Display mode | unchecked |
| Product declarations | unchecked |
| System requirements: minimum | OS: Windows 10 version 1809 (build 17763) or later, 64-bit · Keyboard: required · Memory: 4 GB |
| System requirements: recommended | Windows 11 |

## Age ratings

IARC questionnaire: **No** to every question about violence, adult content, gambling, purchases, user interaction and
location sharing; no user-generated content, no communication. Expected result: PEGI 3 / ESRB Everyone / 3+.

## Pricing and availability

Free · all markets · visibility: Public · release: as soon as it passes certification (or a manual date).

## Packages

`dist\msix\Typer_1.0.0.0_x64.msix`, built by `build_msix.bat` with the identity from `tools\msix\identity.json` (see
`tools\msix\README.md`). x64, Windows 10 build 17763 and later (desktop). Unsigned: the Store signs it after certification.

## Store listing, Polish (pl-PL)

### Description · required · up to 10,000 characters

```
Typer wpisuje dowolny tekst w każdym oknie Windows tak, jakby pisał go człowiek: znak po znaku, w naturalnym tempie, z opcjonalnymi literówkami, które sam poprawia. Działa wszędzie tam, gdzie zwykłe wklejanie zawodzi: w komunikatorach, formularzach w przeglądarce, konsolach maszyn wirtualnych, na pulpicie zdalnym i w grach.

Jak to działa
Wklej tekst do Typera, kliknij w okno, do którego ma trafić, i naciśnij F7. Po krótkim odliczaniu Typer aktywuje wybrane okno i zaczyna pisać. F5 albo Esc przerywa w każdej chwili. Możesz też wskazać konkretne okno z listy, a Typer sam wysunie je na wierzch przed startem.

Tempo jak u człowieka
Ustaw opóźnienie między znakami i jego losowość oraz dodatkowe pauzy po słowie, po interpunkcji i po nowej linii. Włącz ludzkie literówki: Typer trafi w sąsiedni klawisz albo zamieni litery miejscami, zauważy błąd od razu lub po kilku znakach i poprawi go klawiszem Backspace. Gdy liczy się czas, tryb błyskawiczny wkleja całe linie przez schowek.

Klawisze pod kontrolą
Nowa linia jako Enter, Shift+Enter, Ctrl+Enter albo pominięta, więc wiadomość na czacie nie wyśle się w połowie. Na końcu Typer może nacisnąć Enter lub Tab, żeby wysłać wiadomość albo przejść do następnego pola. Tryb zgodności wysyła kody klawiszy zamiast znaków Unicode, co pomaga w grach, konsolach maszyn wirtualnych i na pulpicie zdalnym.

Fragmenty i pozycja
Podziel tekst na linie albo akapity. Typer pamięta, gdzie skończył, jak odtwarzacz: F8 wpisuje następny fragment, F6 powtarza poprzedni, F7 wpisuje wszystko od bieżącej pozycji, a F5 zatrzymuje i wraca na początek. Przydaje się do dyktowania kwestii, odpowiadania w ankietach czy wydawania komend krok po kroku.

Dane z pliku CSV
Wczytaj plik CSV, a placeholdery takie jak {imie} czy {zamowienie} wypełnią się danymi z kolejnych wierszy: jedno powtórzenie na wiersz albo N powtórzeń z przerwą. Do tego wbudowane placeholdery: {n}, {total}, {date}, {time}, {datetime}, {clipboard}, {uuid}, {rand:1-100} i {rand:a|b|c}. Podgląd pokazuje gotowy tekst dla każdego wiersza jeszcze przed startem.

Makra
Nagraj sekwencję z klawiatury i myszy albo złóż ją z kroków: tekst, kombinacja klawiszy, pauza, ruch, kliknięcie, przeciągnięcie, przewijanie i aktywacja okna. Edytuj kroki, ustaw liczbę powtórzeń i przypisz makru własny skrót globalny, żeby uruchamiać je z dowolnej aplikacji.

Presety
Zapisz tekst razem z ustawieniami i wracaj do niego jednym kliknięciem. Podgląd na całym oknie oraz import i eksport do pliku JSON, żeby przenieść presety na inny komputer.

Wygląd i prywatność
Jasny i ciemny motyw, interfejs po polsku i angielsku. Typer działa w całości lokalnie: nie łączy się z internetem, nie zbiera żadnych danych i nie wymaga konta. Ustawienia, presety i makra to zwykłe pliki JSON na Twoim dysku.

Wymagania: Windows 10 w wersji 1809 lub nowszy, 64-bit, oraz Microsoft Edge WebView2 Runtime (wbudowany w Windows 11).
```

### Short description · recommended · best under 270 characters

```
Wpisuje dowolny tekst w każdym oknie tak, jakby pisał go człowiek: naturalne tempo, poprawiane literówki, makra, presety i dane z pliku CSV. Sterowanie klawiszami funkcyjnymi z dowolnej aplikacji.
```

### What's new in this version · up to 1,500 characters

Empty for the first submission.

### Product features · up to 20 items, 200 characters each, no bullets

```
Wpisuje tekst symulowaną klawiaturą w dowolnym oknie: komunikatory, formularze w przeglądarce, konsole maszyn wirtualnych, pulpit zdalny, gry
Ludzkie tempo: opóźnienie między znakami z losowością oraz pauzy po słowie, po interpunkcji i po nowej linii
Opcjonalne literówki poprawiane jak przez człowieka: sąsiedni klawisz, zamiana liter, poprawka od razu albo po kilku znakach
Tryb błyskawiczny: całe linie wklejane przez schowek
Nowa linia jako Enter, Shift+Enter, Ctrl+Enter albo pominięta; na końcu Enter lub Tab, np. żeby wysłać wiadomość
Tryb zgodności z kodami klawiszy dla gier, maszyn wirtualnych i pulpitu zdalnego
Podział tekstu na linie lub akapity i pozycja jak w odtwarzaczu: następny, poprzedni, start od bieżącego miejsca
Placeholdery z pliku CSV: jedno powtórzenie na wiersz albo N powtórzeń z przerwą, podgląd gotowego tekstu
Wbudowane placeholdery: {n}, {total}, {date}, {time}, {datetime}, {clipboard}, {uuid}, {rand:1-100}, {rand:a|b|c}
Makra: nagrywanie klawiatury i myszy, edycja krok po kroku, powtórzenia i własny skrót globalny dla każdego makra
Presety: tekst i ustawienia w jednym miejscu, podgląd na całym oknie, import i eksport do JSON
Skróty globalne na klawiszach funkcyjnych: F7 start i pauza, F5 stop, F6 i F8 fragmenty, F9 nagrywanie; każdy do zmiany
Okno docelowe z listy albo automatycznie ostatnie aktywne okno, z odliczaniem przed startem
Jasny i ciemny motyw, język polski i angielski
Działa w pełni lokalnie: bez internetu, bez konta, bez zbierania danych
```

### Screenshots · at least 1, up to 10 for Desktop · PNG, at least 1366 × 768

Files in `dist\store\screenshots\pl\` (1920 × 1080). Captions (up to 200 characters):

| File | Caption |
| --- | --- |
| `01-typer.png` | Tekst z placeholderami, plik CSV i tempo pisania w jednym widoku. Podgląd pokazuje gotową wiadomość dla każdego wiersza. |
| `02-typing.png` | Wpisywanie w toku: pasek postępu, bieżący fragment oraz pauza i stop w każdej chwili. F5 lub Esc przerywa z dowolnej aplikacji. |
| `03-countdown.png` | Odliczanie przed startem daje czas, żeby upewnić się, że aktywne jest właściwe okno. |
| `04-macros.png` | Makra: nagrane albo złożone z kroków, takich jak tekst, klawisze, pauzy, kliknięcia i aktywacja okna, z własnymi skrótami globalnymi. |
| `05-presets.png` | Presety trzymają tekst razem z ustawieniami, gotowe do wczytania jednym kliknięciem. |
| `06-preset-preview.png` | Podgląd presetu na całym oknie ze wszystkimi ustawieniami. |
| `07-settings.png` | Skróty globalne na klawiszach funkcyjnych, motyw i język w Ustawieniach. |
| `08-light-theme.png` | Jasny motyw. |

### Store logos

| Field | File |
| --- | --- |
| 1:1 App tile icon (300 × 300) · recommended | `dist\store\listing\store-tile-icon-300x300.png` |
| 16:9 Super hero art (1920 × 1080) · optional, no text | `dist\store\listing\store-hero-1920x1080.png` |

Poster art 2:3 and box art 1:1 apply to games only. The Store uses the uploaded icon instead of the package logo when
the corresponding option is enabled.

### Additional information

| Field | Value |
| --- | --- |
| Search terms (if the field is shown; up to 7, 30 characters each) | auto typer · autotyper · wpisywanie tekstu · symulacja klawiatury · makra klawiatury · automatyzacja · CSV |
| Copyright and trademark info | © 2026 Krzysztof Mizgała |
| Additional license terms | empty (or the project licence, if the repository has one) |
| Developed by | Krzysztof Mizgała |
| Additional system requirements: minimum hardware | Microsoft Edge WebView2 Runtime (wbudowany w Windows 11, w Windows 10 zwykle obecny; darmowy do pobrania) |

## Submission options

### Notes for certification (English)

```
Typer Macro is a Win32 desktop app (Python + WebView2) packaged as MSIX with the runFullTrust capability. It sends simulated keystrokes and mouse actions to the window the user chooses, like an auto-typer or macro tool. It never sends input on its own: typing starts only after the user presses Start or a global hotkey (F7 by default), after a visible 3-second countdown, and F5 or Esc stops it at any time.

How to test: open Notepad, switch to Typer, paste any text into the editor, click into Notepad and press F7 (or click Start in Typer). After the countdown the text is typed into Notepad. Macros: Macros > New macro > Record captures keystrokes and mouse actions, Run plays them back. Presets: Save preset stores the text with its settings.

The app works fully offline: no network access, no account, no telemetry. Settings, presets and macros are JSON files in the user's AppData folder. Requires the Microsoft Edge WebView2 Runtime (included in Windows 11).
```

## Partner Center steps

1. Name reservation ("Typer Macro"); Product management → Product identity → `Package/Identity/Name`,
   `Package/Identity/Publisher` and `Package/Properties/PublisherDisplayName` into `tools\msix\identity.json`.
2. `build_msix.bat` → `dist\msix\Typer_1.0.0.0_x64.msix`.
3. Submission: Pricing and availability, Properties, Age ratings (questionnaire), Packages (the .msix), Store
   listings (pl-PL and en-US; both languages appear automatically because the manifest declares them), Submission
   options.
4. Submit to the Store. Certification usually takes 1–3 days; remarks arrive by e-mail to the account.
