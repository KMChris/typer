# MSIX package for the Microsoft Store

## Contents

- `AppxManifest.xml`: manifest template. `tools\make_msix.py` substitutes `$identity_name`, `$publisher`,
  `$publisher_display_name`, `$display_name` and `$version`; the result is placed next to `Typer.exe` in the package
  layout.
- `identity.json`: package identity from Partner Center (see below).
- Package icons are generated, not stored: `tools\make_store_assets.py` renders 84 PNG files (every scale and target
  size) from the code that draws `typer.ico`, on every build.

Store listing texts, screenshot captions and the privacy policy: `tools\store\`.

## Requirements

- Windows 10/11 SDK with `makeappx.exe`, `makepri.exe` and `signtool.exe` (the "Windows 11 SDK" component of the
  Visual Studio Installer or the standalone SDK installer). The script uses the newest version under
  `C:\Program Files (x86)\Windows Kits\10\bin`; the `WINDOWS_SDK_BIN` environment variable overrides the location.
- `.venv` as created by `build.bat`.

## Package identity

Values from Partner Center (app → Product management → Product identity), copied verbatim into `identity.json`:

| Partner Center | `identity.json` |
| --- | --- |
| Package/Identity/Name | `name` |
| Package/Identity/Publisher (`CN=…`) | `publisher` |
| Package/Properties/PublisherDisplayName | `publisher_display_name` |
| reserved app name, shown in the Start menu | `display_name` |

`display_name` has to be one of the names reserved for the app in Partner Center; a package with any other name is
rejected at upload. The Store name is **Typer Macro** ("Typer" alone was already reserved). The name inside the app
(`APP_NAME` in `src\typer_app\__init__.py`) is independent and remains "Typer".

The package version is derived from `__version__` in `src\typer_app\__init__.py`: `1.0.0` becomes `1.0.0.0`. The
Store requires a zero in the fourth part and a higher version for every new submission, so an update starts with a
bump of `__version__`.

## Build

```bat
build_msix.bat
```

Output: `dist\msix\Typer_1.0.0.0_x64.msix`, unsigned. Partner Center accepts it as is; the Store signs the package
with its own certificate after certification. Steps of the script:

1. `build.bat` (tests, PyInstaller into `dist\Typer\`); `--skip-build` reuses an existing `dist\Typer\`.
2. Copy of `dist\Typer\` to `build\msix\layout\`, icons and the manifest.
3. `makepri` in `build\msix\pri\` (manifest and `Assets` only, so the PyInstaller files are not indexed) →
   `resources.pri`, copied into the layout.
4. `makeappx pack` with manifest validation.
5. Store listing images to `dist\store\listing\`.

Options of `tools\make_msix.py`:

| Option | Effect |
| --- | --- |
| `--skip-build` | skips `build.bat` |
| `--test` | throwaway identity `Typer.Dev` instead of `identity.json`; output `Typer_…_x64_test.msix` |
| `--sign CERT.pfx [--password PASSWORD]` | signs the package (sideloading only, not for the Store) |
| `--register` | registers the unpacked layout `build\msix\layout` as an installed app (local test) |
| `--install` | installs the built `.msix` |
| `--remove` | uninstalls the package with that identity |

## Local test

Without a certificate, with Developer Mode enabled (Settings → System → For developers):

```bat
.venv\Scripts\python tools\make_msix.py --skip-build --register
```

The app then appears in the Start menu like an installed app while its files are read from `build\msix\layout`.
`.venv\Scripts\python tools\make_msix.py --remove` uninstalls it. With `--test` the same works under the throwaway
identity.

Installation of the `.msix` file itself (`--test --install`): the package then carries the unsigned-package OID in
its Publisher (`CN=Typer Dev, OID.2.25.311729368913984317654407730594956997722=1`), which Windows 11 accepts with
`Add-AppxPackage -AllowUnsigned`, but packages with executable files install for all users and therefore need an
elevated PowerShell (error 0x80073D2B otherwise). The script prints the exact command for an elevated window; removal
is elevated as well: `Get-AppxPackage Typer.Dev -AllUsers | Remove-AppxPackage -AllUsers`. A package with that OID
cannot be registered through `--register`, so the OID is added only for `--install`.

A signed package for sideloading on other computers needs a certificate whose Subject equals `publisher` in
`identity.json`, passed with `--sign`. Test certificate (elevated PowerShell; the `.cer` is imported into the
"Trusted People" store of the target computer):

```powershell
$cert = New-SelfSignedCertificate -Type Custom -Subject "CN=Typer Dev" -KeyUsage DigitalSignature `
  -FriendlyName "Typer test" -CertStoreLocation "Cert:\CurrentUser\My" `
  -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")
$password = ConvertTo-SecureString -String "typer" -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath build\typer-test.pfx -Password $password
Export-Certificate -Cert $cert -FilePath build\typer-test.cer
```

## Windows App Certification Kit

`C:\Program Files (x86)\Windows Kits\10\App Certification Kit\appcert.exe` runs the checks of Store certification.
The registered layout (see above) can be tested without a certificate, by package full name
(`Get-AppxPackage -Name KrzysztofMizgaa.TyperMacro`):

```powershell
appcert.exe test -packagefullname <PackageFullName> -reportoutputpath build\wack\report.xml
```

A package file is tested with `appcert.exe test -appxpackagepath <file.msix> -reportoutputpath <report.xml>`; that
requires an installable package, i.e. one signed with a trusted certificate.

Expected report for this package: "App resources" and "Debug configuration" pass (the unqualified icon files have
exactly the base size; the .NET Standard facade assemblies bundled by pythonnet are dropped in `typer.spec`).
"Blocked executables" reports references to process-launching APIs in `python314.dll` and `Typer.exe` and string
matches such as "reG" or "cDB" in the PyInstaller bootloader; these come from the Python runtime, not from the app,
which only opens the data folder through the shell. "DPI awareness" warns that the executable declares no
per-monitor DPI awareness; pywebview sets system DPI awareness at start-up instead.

## App data in the Store version

The app writes its data under `%APPDATA%\Typer`, but Windows virtualizes AppData writes of an installed MSIX
package: the files physically land in `%LOCALAPPDATA%\Packages\<package name>\LocalCache\Roaming\Typer` and are
removed on uninstall. Consequences:

- The Store version and `Typer.exe` keep separate presets and macros; the preset export and import (JSON) or a copy
  of `presets.json` and `macros.json` moves them.
- The "Open folder" button opens the plain `%APPDATA%\Typer` in Explorer, not the package folder.
- A registered loose layout (`--register`) is not virtualized: in a test the app wrote to the plain `%APPDATA%\Typer`.

Disabling the virtualization (`desktop6:FileSystemWriteVirtualization` in the manifest) requires the restricted
capability `unvirtualizedResources`, which the Store grants only after a justification in the submission, so the
manifest keeps the default. Portable mode (`portable.txt`) does not apply to the package, because the installation
folder is read-only.

## Store submission

1. Partner Center → Apps and games → New product → MSIX or PWA app → name reservation ("Typer Macro").
2. Product identity → `identity.json` → `build_msix.bat`.
3. Submission: Pricing and availability (Free), Properties, Age ratings, Packages
   (`dist\msix\Typer_1.0.0.0_x64.msix`), Store listings for pl-PL and en-US (texts, screenshots and images from
   `tools\store\` and `dist\store\`), Submission options (notes for certification from `tools\store\listing-pl.md`).
4. Submit to the Store; certification usually takes 1–3 business days.
