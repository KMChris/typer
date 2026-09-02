@echo off
rem Builds dist\Typer\Typer.exe (PyInstaller onedir). Creates .venv on first run.
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  py -3 -m venv .venv || exit /b 1
)

echo Installing dependencies...
.venv\Scripts\python -m pip install --disable-pip-version-check -q -r requirements-dev.txt || exit /b 1

echo Rendering icon...
.venv\Scripts\python tools\make_icon.py || exit /b 1

echo Running tests...
.venv\Scripts\python -m pytest -q || exit /b 1

echo Building...
.venv\Scripts\python -m PyInstaller --noconfirm --clean typer.spec || exit /b 1

echo.
echo Done: dist\Typer\Typer.exe
endlocal
