@echo off
REM HYDRA_UMC_SCRIPT_STANDARD_HEADER_BEGIN
REM *****************************************************************************
REM Project   : HYDRA-UMC-OPS-AGENT
REM Script    : run.bat
REM Purpose   : Runtime workflow for the project entry point.
REM Author    : JuanenRac (Electro Hobby 3D)
REM Email     : electrohobby3d@gmail.com
REM Copyright : (C) 2026 JuanenRac
REM License   : GPL-3.0 - see LICENSE
REM *****************************************************************************
REM HYDRA_UMC_SCRIPT_STANDARD_HEADER_END
REM HYDRA_UMC_SCRIPT_STANDARD_BANNER_BEGIN
echo.
echo *****************************************************************************
echo * HYDRA-UMC-OPS-AGENT - run.bat
echo * Mode      : RUN WORKFLOW
echo * Author    : JuanenRac (Electro Hobby 3D)
echo * Email     : electrohobby3d@gmail.com
echo * Copyright : (C) 2026 JuanenRac
echo * License   : GPL-3.0 - see LICENSE
echo * ------------------------------------------------------------------------- *
echo * 1. Resolve the runtime prerequisites declared by this script.
echo * 2. Start the project entry point and forward user arguments unchanged.
echo * 3. Preserve its result and keep an interactive terminal open.
echo *****************************************************************************
echo.
REM HYDRA_UMC_SCRIPT_STANDARD_BANNER_END
REM Runs HYDRA-UMC-OPS-AGENT. Run build.bat first.
REM
REM Usage:
REM   run.bat                                        - real demo: edge collect
REM                                                     against this GitHub
REM                                                     workspace, then control show
REM   run.bat edge collect --node-name n --projects-root DIR --out FILE
REM   run.bat control show snapshot.json
REM This delivery is CLI-only (no GUI yet) - see cli.py's own header comment.
setlocal enabledelayedexpansion
cd /d "%~dp0"

if exist .venv\Scripts\python.exe (
    set "HYDRA_UMC_PY=.venv\Scripts\python.exe"
) else (
    set "HYDRA_UMC_PY=python"
)

if "%~1"=="" (
    echo No arguments given - running a real demo: edge collect against this GitHub workspace, then control show.
    for %%I in ("%~dp0..") do set "HYDRA_UMC_DEMO_ROOT=%%~fI"
    set "HYDRA_UMC_DEMO_SNAPSHOT=%TEMP%\hydra-umc-ops-agent-demo-snapshot.json"
    "!HYDRA_UMC_PY!" -m hydra_umc_ops_agent.cli edge collect --node-name demo-node --projects-root "!HYDRA_UMC_DEMO_ROOT!" --out "!HYDRA_UMC_DEMO_SNAPSHOT!"
    if errorlevel 1 goto :done
    echo.
    "!HYDRA_UMC_PY!" -m hydra_umc_ops_agent.cli control show "!HYDRA_UMC_DEMO_SNAPSHOT!"
    del /q "!HYDRA_UMC_DEMO_SNAPSHOT!" >nul 2>&1
) else (
    "!HYDRA_UMC_PY!" -m hydra_umc_ops_agent.cli %*
)

:done
pause
