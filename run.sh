#!/usr/bin/env bash
# HYDRA_UMC_SCRIPT_STANDARD_HEADER_BEGIN
# *****************************************************************************
# Project   : HYDRA-UMC-OPS-AGENT
# Script    : run.sh
# Purpose   : Runtime workflow for the project entry point.
# Author    : JuanenRac (Electro Hobby 3D)
# Email     : electrohobby3d@gmail.com
# Copyright : (C) 2026 JuanenRac
# License   : GPL-3.0 - see LICENSE
# *****************************************************************************
# HYDRA_UMC_SCRIPT_STANDARD_HEADER_END
# HYDRA_UMC_SCRIPT_STANDARD_BANNER_BEGIN
printf '\n*******************************************************************************\n'
printf '%s\n' "* HYDRA-UMC-OPS-AGENT - run.sh"
printf '%s\n' "* Mode      : RUN WORKFLOW"
printf '%s\n' "* Author    : JuanenRac (Electro Hobby 3D)"
printf '%s\n' "* Email     : electrohobby3d@gmail.com"
printf '%s\n' "* Copyright : (C) 2026 JuanenRac"
printf '%s\n' "* License   : GPL-3.0 - see LICENSE"
printf '%s\n' "* ------------------------------------------------------------------------- *"
printf '%s\n' "* 1. Resolve the runtime prerequisites declared by this script."
printf '%s\n' "* 2. Start the project entry point and forward user arguments unchanged."
printf '%s\n' "* 3. Preserve its result and keep an interactive terminal open."
printf '%s\n' "*******************************************************************************"
printf '\n'
# HYDRA_UMC_SCRIPT_STANDARD_BANNER_END
# Runs HYDRA-UMC-OPS-AGENT. Run ./build.sh first.
#
# Usage:
#   ./run.sh                                          - real demo: edge collect
#                                                        against this GitHub
#                                                        workspace, then control show
#   ./run.sh edge collect --node-name n --projects-root DIR --out FILE
#   ./run.sh control show snapshot.json
# This delivery is CLI-only (no GUI yet) - see cli.py's own header comment.
set -uo pipefail  # no -e: we need to reach the trap below even if the process exits non-zero
cd "$(dirname "$0")"

# Keep the window open if this was double-clicked instead of run from an
# already-open terminal - real output would otherwise flash-close before
# it's readable. Only prompts when stdin is actually a terminal (never in
# CI/piped/non-interactive runs).
trap '[ -t 0 ] && read -r -p "Press Enter to close..." _' EXIT

if [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
elif [ -f .venv/Scripts/activate ]; then
    # shellcheck disable=SC1091
    source .venv/Scripts/activate
fi

if [ "$#" -eq 0 ]; then
    printf '%s\n' "No arguments given - running a real demo: edge collect against this GitHub workspace, then control show."
    demo_root="$(cd "$(pwd)/.." && pwd)"
    demo_dir="$(mktemp -d)"
    demo_snapshot="$demo_dir/snapshot.json"
    python -m hydra_umc_ops_agent.cli edge collect --node-name demo-node --projects-root "$demo_root" --out "$demo_snapshot"
    status=$?
    if [ "$status" -eq 0 ]; then
        echo
        python -m hydra_umc_ops_agent.cli control show "$demo_snapshot"
        status=$?
    fi
    rm -rf "$demo_dir"
else
    python -m hydra_umc_ops_agent.cli "$@"
    status=$?
fi
exit "$status"
