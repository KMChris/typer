@echo off
rem Builds the Microsoft Store package: dist\msix\Typer_<version>_x64.msix.
rem Runs build.bat first (creates .venv, tests, PyInstaller), then tools\make_msix.py.
rem Extra arguments are passed on, e.g. build_msix.bat --test --register
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

call "%ROOT%build.bat" || exit /b 1

echo.
echo Packaging...
"%ROOT%.venv\Scripts\python.exe" "%ROOT%tools\make_msix.py" --skip-build %* || exit /b 1
endlocal
