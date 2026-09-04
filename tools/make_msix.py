"""Builds the MSIX package of Typer for the Microsoft Store (or a test package for sideloading).

  python tools\\make_msix.py [--skip-build] [--test] [--sign CERT.pfx [--password PW]] [--install | --register | --remove]

Steps: build.bat (PyInstaller onedir), package assets, AppxManifest.xml with the identity from
tools\\msix\\identity.json, resources.pri (makepri) and makeappx pack. Needs the Windows 10/11 SDK.

The Store signs the package itself, so the Store build stays unsigned; --sign is for sideloading.
--test uses a throwaway identity (CN=Typer Dev) instead of the Partner Center one. --register
installs the unpacked layout for a local run (Developer Mode, no certificate). --install installs
the .msix instead: unsigned, that works only for a --test build, whose Publisher then also carries
the "unsigned package" OID, through Add-AppxPackage -AllowUnsigned in an elevated PowerShell.
--remove uninstalls whichever of the two is present.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import string
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_store_assets import write_listing_images, write_package_assets  # noqa: E402
from typer_app import __version__  # noqa: E402

DIST_APP = ROOT / "dist" / "Typer"
BUILD_DIR = ROOT / "build" / "msix"
LAYOUT = BUILD_DIR / "layout"
PRI_ROOT = BUILD_DIR / "pri"
OUT_DIR = ROOT / "dist" / "msix"
TEMPLATE = Path(__file__).resolve().parent / "msix" / "AppxManifest.xml"
IDENTITY_FILE = Path(__file__).resolve().parent / "msix" / "identity.json"
TEST_IDENTITY = {"name": "Typer.Dev", "publisher": "CN=Typer Dev", "publisher_display_name": "Typer Dev",
                 "display_name": "Typer"}
# Marks a package that is meant to stay unsigned: Add-AppxPackage -AllowUnsigned accepts only such a Publisher
# (Windows 11 22H2+, Developer Mode), while -Register of a loose layout rejects it.
UNSIGNED_OID = "OID.2.25.311729368913984317654407730594956997722=1"
SDK_BIN = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"


def sdk_tool(name: str) -> Path:
    override = os.environ.get("WINDOWS_SDK_BIN")
    candidates = [Path(override) / name] if override else []
    if SDK_BIN.exists():
        versions = sorted((d for d in SDK_BIN.iterdir() if d.name.startswith("10.")),
                          key=lambda d: [int(p) for p in d.name.split(".") if p.isdigit()], reverse=True)
        candidates += [d / "x64" / name for d in versions]
    for path in candidates:
        if path.exists():
            return path
    sys.exit(f"{name} not found: install the Windows 10/11 SDK or set WINDOWS_SDK_BIN")


def run(command: list[str | Path], check: bool = True, **kwargs) -> int:
    print("+", " ".join(str(part) for part in command))
    return subprocess.run([str(part) for part in command], check=check, **kwargs).returncode


def package_version() -> str:
    parts = [p for p in __version__.split(".") if p.isdigit()]
    while len(parts) < 3:
        parts.append("0")
    return ".".join(parts[:3]) + ".0"  # the Store reserves the fourth part and requires 0


def load_identity(test: bool, unsigned_install: bool = False) -> dict:
    if test:
        identity = dict(TEST_IDENTITY)
        if unsigned_install:
            identity["publisher"] += f", {UNSIGNED_OID}"
        return identity
    data = json.loads(IDENTITY_FILE.read_text(encoding="utf-8"))
    data.setdefault("display_name", TEST_IDENTITY["display_name"])
    identity = {key: str(data.get(key, "")).strip() for key in TEST_IDENTITY}
    bad = [key for key, value in identity.items() if not value or "REPLACE" in value]
    if bad or not identity["publisher"].startswith("CN="):
        sys.exit(f"fill in {IDENTITY_FILE} with the values from Partner Center (Product identity), "
                 "or build a throwaway package with --test")
    return identity


def build_app() -> None:
    run(["cmd", "/c", ROOT / "build.bat"], cwd=ROOT)


def stage_layout(identity: dict, version: str) -> None:
    if not (DIST_APP / "Typer.exe").exists():
        sys.exit(f"{DIST_APP} is missing: run build.bat or drop --skip-build")
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    shutil.copytree(DIST_APP, LAYOUT)
    manifest = string.Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        identity_name=identity["name"], publisher=identity["publisher"],
        publisher_display_name=identity["publisher_display_name"], display_name=identity["display_name"],
        version=version)
    # The resource index is built in a folder with only the manifest and the assets, so makepri
    # never has to look at the thousands of files PyInstaller puts next to the executable.
    PRI_ROOT.mkdir(parents=True)
    (PRI_ROOT / "AppxManifest.xml").write_text(manifest, encoding="utf-8")
    count = write_package_assets(PRI_ROOT / "Assets")
    print(f"rendered {count} package assets")


def make_pri() -> None:
    makepri = sdk_tool("makepri.exe")
    config = BUILD_DIR / "priconfig.xml"
    run([makepri, "createconfig", "/cf", config, "/dq", "en-US", "/pv", "10.0.0", "/o"])
    run([makepri, "new", "/pr", PRI_ROOT, "/cf", config, "/mn", PRI_ROOT / "AppxManifest.xml",
         "/of", PRI_ROOT / "resources.pri", "/o"])
    for name in ("AppxManifest.xml", "resources.pri"):
        shutil.copy2(PRI_ROOT / name, LAYOUT / name)
    shutil.copytree(PRI_ROOT / "Assets", LAYOUT / "Assets")


def pack(version: str, test: bool) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    package = OUT_DIR / f"Typer_{version}_x64{'_test' if test else ''}.msix"
    run([sdk_tool("makeappx.exe"), "pack", "/d", LAYOUT, "/p", package, "/o"])
    return package


def sign(package: Path, pfx: Path, password: str | None) -> None:
    command = [sdk_tool("signtool.exe"), "sign", "/fd", "SHA256", "/f", pfx]
    if password:
        command += ["/p", password]
    run(command + [package])


def powershell(script: str, check: bool = True) -> int:
    return run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], check=check)


def remove(identity: dict) -> None:
    powershell(f"Get-AppxPackage -Name '{identity['name']}' | Remove-AppxPackage")


def register(identity: dict) -> None:
    remove(identity)
    powershell(f"Add-AppxPackage -Register '{LAYOUT / 'AppxManifest.xml'}'")
    print(f"registered {identity['name']} from {LAYOUT}; start Typer from the Start menu")


def install(package: Path, identity: dict, signed: bool) -> None:
    if not signed and UNSIGNED_OID not in identity["publisher"]:
        sys.exit("an unsigned Store package cannot be installed locally: use --test or --sign")
    remove(identity)
    command = f"Add-AppxPackage -Path '{package}'" + ("" if signed else " -AllowUnsigned")
    if powershell(command, check=False) == 0:
        print(f"installed {identity['name']} from {package}; start Typer from the Start menu")
    elif signed:
        sys.exit("install failed: the signing certificate must be trusted on this machine (Trusted People)")
    else:
        # Windows installs unsigned packages with executable content for all users (error 0x80073D2B otherwise).
        sys.exit("install failed: unsigned packages need an elevated PowerShell. Run as administrator:\n  " + command)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-build", action="store_true", help="reuse dist\\Typer instead of running build.bat")
    parser.add_argument("--test", action="store_true", help="throwaway identity (CN=Typer Dev) instead of tools\\msix\\identity.json")
    parser.add_argument("--sign", type=Path, metavar="CERT.pfx", help="sign with this certificate (sideloading only)")
    parser.add_argument("--password", help="password of the .pfx file")
    local = parser.add_mutually_exclusive_group()
    local.add_argument("--install", action="store_true", help="install the built .msix for a local test (Developer Mode)")
    local.add_argument("--register", action="store_true", help="install the unpacked layout instead of the .msix")
    local.add_argument("--remove", action="store_true", help="uninstall the locally installed package and exit")
    args = parser.parse_args()

    identity = load_identity(args.test, unsigned_install=args.install and not args.sign)
    if args.remove:
        remove(identity)
        return
    version = package_version()
    if not args.skip_build:
        build_app()
    stage_layout(identity, version)
    make_pri()
    package = pack(version, args.test)
    if args.sign:
        sign(package, args.sign, args.password)
    listing = write_listing_images(ROOT / "dist" / "store" / "listing")
    if args.register:
        register(identity)
    elif args.install:
        install(package, identity, signed=bool(args.sign))
    print()
    print(f"Package: {package} ({package.stat().st_size / 1_048_576:.1f} MB)")
    print(f"Identity: {identity['name']} / {identity['publisher']} / {version}, shown as {identity['display_name']!r}")
    print("Listing images:", ", ".join(str(path) for path in listing))
    if not args.sign:
        print("Unsigned: fine for Partner Center (the Store signs it); use --sign for sideloading.")


if __name__ == "__main__":
    main()
