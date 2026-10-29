#!/usr/bin/env bash
# HYDRA-UMC-OPS-AGENT test launcher: the tests and the checks of build-test, shown in a live panel; the version is never changed. GPL-3.0-or-later.
PRETTY_MODE=test exec bash "$(dirname "$0")/build-test.sh" "$@"
