@echo off
rem PRETTY_RUN_BEGIN
if not defined PRETTY_MODE set "PRETTY_MODE=build"
set "PRETTY_PY=python"
where py >nul 2>&1 && set "PRETTY_PY=py -3"
if not defined PRETTY_RUN if exist "%~dp0tools\pretty_run.py" (
    set "PRETTY_RUN=1"
    %PRETTY_PY% "%~dp0tools\pretty_run.py" --wrap --mode %PRETTY_MODE% -- cmd /d /c "%~f0" %*
    exit /b
)
rem PRETTY_RUN_END
REM HYDRA_UMC_SCRIPT_STANDARD_HEADER_BEGIN
REM *****************************************************************************
REM Project   : HYDRA-UMC-OPS-AGENT
REM Script    : build.bat
REM Purpose   : Incremental project build, verification and packaging workflow.
REM Author    : JuanenRac (Electro Hobby 3D)
REM Email     : electrohobby3d@gmail.com
REM Copyright : (C) 2026 JuanenRac
REM License   : GPL-3.0-or-later - see LICENSE
REM *****************************************************************************
REM HYDRA_UMC_SCRIPT_STANDARD_HEADER_END
REM HYDRA_UMC_SCRIPT_STANDARD_BANNER_BEGIN
echo.
echo *****************************************************************************
echo * HYDRA-UMC-OPS-AGENT - build.bat
echo * Mode      : INCREMENTAL BUILD
echo * Author    : JuanenRac (Electro Hobby 3D)
echo * Email     : electrohobby3d@gmail.com
echo * Copyright : (C) 2026 JuanenRac
echo * License   : GPL-3.0-or-later - see LICENSE
echo * ------------------------------------------------------------------------- *
echo * 1. Read the project version (building never changes it; use the explicit bump command).
echo * 2. Run this project's declared build, verification and packaging commands.
echo * 3. Report the result and keep an interactive terminal open.
echo *****************************************************************************
echo.
REM HYDRA_UMC_SCRIPT_STANDARD_BANNER_END
REM Builds HYDRA-UMC-OPS-AGENT: creates/activates a venv, installs the project
REM (editable, with dev extras), verifies it compiles/imports cleanly, and
REM runs the real test suite. Run this before run.bat.
setlocal enabledelayedexpansion
rem Keep the window open for people, never in automation (CI / HYDRA_UMC_CI).
set "KEEP_OPEN=pause"
if defined CI set "KEEP_OPEN=ver >nul"
if "%HYDRA_UMC_CI%"=="1" set "KEEP_OPEN=ver >nul"
cd /d "%~dp0"
REM HYDRA_UMC_SCRIPT_STANDARD_VERSION_STEP
echo [1/5] Reading the project version (building never changes it)...
for /f "usebackq delims=" %%V in (`python -c "import json; print(json.load(open(r'%~dp0hydra-umc.project.json', encoding='utf-8'))['version'])"`) do set "HYDRA_UMC_VERSION_BUILT=%%V"
if not defined HYDRA_UMC_VERSION_BUILT set "HYDRA_UMC_VERSION_BUILT=unknown"
echo       Building v%HYDRA_UMC_VERSION_BUILT% (building never changes the version)
echo.
echo.
echo       Done.
echo.

echo [2/5] Creating/activating virtual environment...
REM The venv is made with the py launcher when there is one (the python that is first on the PATH may be a stripped one, for example the one of ESP-IDF, whose
REM venv has no activate script), and the scripts use the python of the venv directly instead of activating it.
set "PYMAKE=python"
where py >nul 2>nul && set "PYMAKE=py -3"
if not exist .venv\Scripts\python.exe (
    %PYMAKE% -m venv .venv
    if errorlevel 1 goto :error
)
if not exist .venv\Scripts\python.exe (
    echo ERROR: .venv has no python.exe; delete the .venv folder and run this again.
    goto :error
)
set "VPY=%CD%\.venv\Scripts\python.exe"
echo       Done.
echo.

echo [3/5] Installing project (editable, with dev extras) into the venv...
"%VPY%" -m pip install --upgrade pip >nul
if errorlevel 1 goto :error
"%VPY%" -m pip install -e ".[dev]"
if errorlevel 1 goto :error
echo       Done.
echo.

echo [4/5] Verifying the package compiles/imports without errors...
"%VPY%" -m compileall -q src
if errorlevel 1 goto :error
"%VPY%" -c "import hydra_umc_ops_agent; print('import OK - version', hydra_umc_ops_agent.__version__)"
if errorlevel 1 goto :error
echo       Done.
echo.

echo [5/5] Running the real test suite (pytest)...
"%VPY%" -m pytest tests/ -q
if errorlevel 1 goto :error
echo       Done.
echo.

echo  ===============================================================
echo   Build complete. Run run.bat to see a real edge collect + control show demo.
echo  ===============================================================
echo.
echo Built v%HYDRA_UMC_VERSION_BUILT%. Building never changes the version; to raise it run: python tools\hydra_project_tool.py bump
echo.
%KEEP_OPEN%
exit /b 0

:error
echo.
echo   BUILD FAILED - see the output above.
%KEEP_OPEN%
exit /b 1
