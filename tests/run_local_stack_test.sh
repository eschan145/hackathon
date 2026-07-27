#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
export ORCHESTRATR_RUN_LOCAL_STACK=1
exec .venv/bin/python -m unittest tests.test_local_openclaw_email_stack -v
