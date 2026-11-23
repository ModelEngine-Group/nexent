#!/usr/bin/env bash
# Machine-local wrapper: invoke from any scheduler without an interactive shell.
set -euo pipefail
if (( $# < 3 || $# > 4 )); then
  echo "Usage: daily-launch.sh REPO TEST_HOME BRANCH [--execute]" >&2
  exit 2
fi
repo=$(realpath "$1")
test_home=$(realpath "$2")
branch=$3
# Reuse the runtime installed by onboarding; require one unambiguous version.
shopt -s nullglob
node_bins=("$test_home"/runtime/node-v22*-linux-*/bin)
if (( ${#node_bins[@]} == 1 )); then
  export PATH="${node_bins[0]}:$PATH"
fi
cd "$repo"
args=(--test-home "$test_home" --branch "$branch")
if (( $# == 4 )); then
  [[ $4 == --execute ]] || exit 2
  args+=(--execute)
fi
exec "$test_home/runtime/test-venv/bin/python" \
  "$repo/test-e2e/infra/scripts/daily-launch.py" "${args[@]}"
