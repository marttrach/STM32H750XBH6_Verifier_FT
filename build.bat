@echo off
setlocal
pushd "%~dp0"

rem Ensure local venv + required build deps (Nuitka/PyArmor) are available
set "VENV=%~dp0.venv"
set "PYTHON=%VENV%\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [INFO] Creating local virtual environment...
    if exist "%WINDIR%\py.exe" (
        py -3 -m venv "%VENV%"
    ) else (
        python -m venv "%VENV%"
    )
)

if not exist "%PYTHON%" (
    echo [ERROR] Python interpreter not found. Install Python 3.10+ and rerun.>&2
    popd
    exit /b 1
)

set "CONSOLE_MODE=disable"
if not "%~1"=="" echo [INFO] Args: %*
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="cmd" set "CONSOLE_MODE=force"
if /i "%~1"=="cmd=true" set "CONSOLE_MODE=force"
if /i "%~1"=="cmd=1" set "CONSOLE_MODE=force"
if /i "%~1"=="console" set "CONSOLE_MODE=force"
if /i "%~1"=="console=true" set "CONSOLE_MODE=force"
if /i "%~1"=="console=1" set "CONSOLE_MODE=force"
if /i "%~1"=="/console" set "CONSOLE_MODE=force"
if /i "%~1"=="--console" set "CONSOLE_MODE=force"
shift
goto parse_args
:args_done
echo [INFO] Console mode: %CONSOLE_MODE%

echo [INFO] Ensuring pip is available...
"%PYTHON%" -m ensurepip --upgrade >nul 2>nul
"%PYTHON%" -m pip install --upgrade pip

echo [INFO] Installing build dependencies (Nuitka + project deps)...
"%PYTHON%" -m pip install --upgrade ^
  nuitka==2.8.9 ^
  ordered-set==4.1.0 ^
  setuptools==80.9.0 ^
  wheel==0.45.1 ^
  zstandard==0.25.0 ^
  -r "%~dp0requirement.txt"

set "OUTDIR=%~dp0build"
set "SRC=%~dp0main.py"
set "BIN_DIR=%~dp0bin"
set "ICON_DIR=%~dp0icon"
set "ICON_PATH=%ICON_DIR%\IOT.ico"
set "LICENSE_FILE=%~dp0LICENSE"
set "ABOUT_FILE=%~dp0about.md"

if not exist "%ICON_PATH%" (
    echo [ERROR] Icon not found: %ICON_PATH%>&2
    popd
    exit /b 1
)

set "NUITKA_ARGS=--onefile"
set "NUITKA_ARGS=%NUITKA_ARGS% --windows-console-mode=%CONSOLE_MODE%"
set "NUITKA_ARGS=%NUITKA_ARGS% --enable-plugin=pyside6"
set "NUITKA_ARGS=%NUITKA_ARGS% --include-qt-plugins=sensible,styles,platforms"
set "NUITKA_ARGS=%NUITKA_ARGS% --windows-icon-from-ico=%ICON_PATH%"
set "NUITKA_ARGS=%NUITKA_ARGS% --include-data-dir=%BIN_DIR%=bin"
set "NUITKA_ARGS=%NUITKA_ARGS% --include-data-dir=%ICON_DIR%=icon"
set "NUITKA_ARGS=%NUITKA_ARGS% --include-data-file=%LICENSE_FILE%=LICENSE"
set "NUITKA_ARGS=%NUITKA_ARGS% --include-data-file=%ABOUT_FILE%=about.md"
set "NUITKA_ARGS=%NUITKA_ARGS% --windows-uac-admin"
set "NUITKA_ARGS=%NUITKA_ARGS% --output-dir=%OUTDIR%"
set "NUITKA_ARGS=%NUITKA_ARGS% --remove-output"

"%PYTHON%" -m nuitka %NUITKA_ARGS% "%SRC%"

set "ERR=%ERRORLEVEL%"
popd
exit /b %ERR%
