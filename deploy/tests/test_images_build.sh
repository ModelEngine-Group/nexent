#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_SCRIPT="$PROJECT_ROOT/deploy/images/build.sh"

fail() {
  echo "FAIL: $*"
  exit 1
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local message="$3"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "FAIL: $message"
    echo "  missing: $needle"
    echo "  in: $haystack"
    exit 1
  fi
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  local message="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    echo "FAIL: $message"
    echo "  unexpected: $needle"
    echo "  in: $haystack"
    exit 1
  fi
}

output="$(bash "$BUILD_SCRIPT" --components application,data-process --version latest --registry general --dry-run)"
assert_contains "$output" "nexent/nexent:latest" "application component should build main image with latest tag"
assert_contains "$output" "nexent/nexent-web:latest" "application component should build web image with latest tag"
assert_contains "$output" "nexent/nexent-mcp:latest" "application component should build mcp image with latest tag"
assert_contains "$output" "nexent/nexent-data-process:latest" "data-process component should build data-process image with latest tag"
assert_not_contains "$output" "nexent/nexent-ubuntu-terminal:latest" "terminal image should not be built when terminal component is absent"

output="$(bash "$BUILD_SCRIPT" --components terminal --version v9.9.9 --registry mainland --dry-run)"
assert_contains "$output" "ccr.ccs.tencentyun.com/nexent-hub/nexent-ubuntu-terminal:v9.9.9" "terminal component should build terminal image with selected version"
assert_not_contains "$output" "ccr.ccs.tencentyun.com/nexent-hub/nexent:v9.9.9" "application image should not be built for terminal-only component"

output="$(bash "$BUILD_SCRIPT" --image web --version v1.2.3 --registry general --dry-run)"
assert_contains "$output" "nexent/nexent-web:v1.2.3" "explicit image build should keep supporting selected versions"
assert_not_contains "$output" "nexent/nexent:v1.2.3" "single image build should not build main image"

output="$(bash "$BUILD_SCRIPT" --components infrastructure,supabase,monitoring --version latest --dry-run)"
assert_contains "$output" "No Nexent images selected for build." "non-application components should produce no Nexent image builds"

if bash "$BUILD_SCRIPT" --components infrastructure,unknown --dry-run >/tmp/nexent-image-build-invalid.log 2>&1; then
  fail "unknown component should fail"
fi
assert_contains "$(cat /tmp/nexent-image-build-invalid.log)" "Unsupported component for image build: unknown" "unknown component should explain the error"

echo "All image build tests passed."
