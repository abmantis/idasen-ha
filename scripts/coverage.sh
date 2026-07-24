#!/usr/bin/env bash

"$(dirname "$0")/run_tests.sh" \
    --cov=idasen_ha --cov-report term-missing --cov-fail-under=95 "$@"
