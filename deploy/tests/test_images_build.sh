#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_SCRIPT="$PROJECT_ROOT/deploy/images/build.sh"
ROOT_BUILD_SCRIPT="$PROJECT_ROOT/build.sh"
export DEPLOYMENT_LANG=en

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

output="$(bash "$BUILD_SCRIPT" --images main,web,mcp,data-process --version latest --registry general --dry-run)"
assert_contains "$output" "nexent/nexent:latest" "image list should build main image with latest tag"
assert_contains "$output" "nexent/nexent-web:latest" "image list should build web image with latest tag"
assert_contains "$output" "nexent/nexent-mcp:latest" "image list should build mcp image with latest tag"
assert_contains "$output" "nexent/nexent-data-process:latest" "image list should build data-process image with latest tag"
assert_not_contains "$output" "nexent/nexent-ubuntu-terminal:latest" "terminal image should not be built when terminal image is absent"
assert_not_contains "$output" "--platform" "default build should use local architecture"

output="$(bash "$BUILD_SCRIPT" --main --version latest --platform linux/amd64 --dry-run)"
assert_contains "$output" "--platform linux/amd64" "explicit platform should be forwarded"
assert_contains "$output" "nexent/nexent:latest" "explicit platform build should still build selected image"

output="$(bash "$ROOT_BUILD_SCRIPT" --web --version latest --dry-run)"
assert_contains "$output" "nexent/nexent-web:latest" "root image build entrypoint should forward to deploy/images/build.sh"
assert_not_contains "$output" "nexent/nexent:latest" "root image build entrypoint should preserve selected image arguments"

output="$(bash "$BUILD_SCRIPT" --main --version latest --no-cache --dry-run)"
assert_contains "$output" "--no-cache" "explicit no-cache option should be forwarded"
assert_contains "$output" "nexent/nexent:latest" "explicit no-cache build should still build selected image"

output="$(bash "$BUILD_SCRIPT" --web --version v9.9.9 --registry mainland --dry-run)"
assert_contains "$output" "--no-cache" "mainland web build should avoid stale Docker cache"
assert_contains "$output" "nexent/nexent-web:v9.9.9" "mainland web build without push should keep local Nexent tag"

output="$(bash "$BUILD_SCRIPT" --web --version v9.9.9 --registry mainland --push --dry-run)"
assert_contains "$output" "--no-cache" "mainland web push should avoid stale Docker cache"
assert_contains "$output" "ccr.ccs.tencentyun.com/nexent-hub/nexent-web:v9.9.9" "mainland web push should use CCS tag"

output="$(bash "$BUILD_SCRIPT" --terminal --version v9.9.9 --registry mainland --dry-run)"
assert_contains "$output" "nexent/nexent-ubuntu-terminal:v9.9.9" "mainland build without push should keep local Nexent tag"
assert_not_contains "$output" "ccr.ccs.tencentyun.com/nexent-hub/nexent-ubuntu-terminal:v9.9.9" "mainland build without push should not use CCS tag"
assert_not_contains "$output" "ccr.ccs.tencentyun.com/nexent-hub/nexent:v9.9.9" "main image should not be built for terminal-only option"

output="$(bash "$BUILD_SCRIPT" --terminal --version v9.9.9 --registry mainland --push --dry-run)"
assert_contains "$output" "ccr.ccs.tencentyun.com/nexent-hub/nexent-ubuntu-terminal:v9.9.9" "mainland push should use CCS tag"
assert_not_contains "$output" "nexent/nexent-ubuntu-terminal:v9.9.9" "mainland push should not use local Nexent tag"

output="$(bash "$BUILD_SCRIPT" --web --docs --version v8.8.8 --registry general --dry-run)"
assert_contains "$output" "nexent/nexent-web:v8.8.8" "web option should build web image"
assert_contains "$output" "nexent/nexent-docs:v8.8.8" "docs option should build docs image"
assert_not_contains "$output" "nexent/nexent-data-process:v8.8.8" "data-process image should not be built when option is absent"

output="$(bash "$BUILD_SCRIPT" --image web --version v1.2.3 --registry general --dry-run)"
assert_contains "$output" "nexent/nexent-web:v1.2.3" "explicit image build should keep supporting selected versions"
assert_not_contains "$output" "nexent/nexent:v1.2.3" "single image build should not build main image"

output="$(bash "$BUILD_SCRIPT" --components infrastructure,supabase,monitoring --version latest --dry-run)"
assert_contains "$output" "No Nexent images selected for build." "legacy non-application components should produce no Nexent image builds"

if bash "$BUILD_SCRIPT" --images main,unknown --dry-run >/tmp/nexent-image-build-invalid.log 2>&1; then
  fail "unknown image should fail"
fi
assert_contains "$(cat /tmp/nexent-image-build-invalid.log)" "Unsupported image: unknown" "unknown image should explain the error"

if bash "$BUILD_SCRIPT" --data-process --variant slim --dry-run >/tmp/nexent-image-build-variant.log 2>&1; then
  fail "deprecated data-process variant option should fail"
fi
assert_contains "$(cat /tmp/nexent-image-build-variant.log)" "Unknown option: --variant" "deprecated data-process variant option should be rejected"

output="$(
  printf 'main,web,mcp,data-process\n1\n1\n' | \
    bash "$BUILD_SCRIPT" --interactive --dry-run
)"
assert_contains "$output" "Nexent image build configuration" "interactive mode should show configuration prompt"
assert_contains "$output" "nexent/nexent:latest" "interactive mode should accept latest version selection"
assert_contains "$output" "nexent/nexent-web:latest" "interactive image selection should include web image"
assert_contains "$output" "nexent/nexent-mcp:latest" "interactive image selection should include mcp image"
assert_contains "$output" "nexent/nexent-data-process:latest" "interactive image selection should include data-process image"
assert_not_contains "$output" "nexent/nexent-ubuntu-terminal:latest" "interactive image selection should exclude unselected terminal image"
assert_not_contains "$output" "--platform" "interactive mode should use local architecture by default"

output="$(
  printf '\n\n1\n' | \
    bash "$BUILD_SCRIPT" --interactive --dry-run
)"
assert_contains "$output" "nexent/nexent:latest" "interactive default image selection should include main image"
assert_contains "$output" "nexent/nexent-web:latest" "interactive default image selection should include web image"
assert_not_contains "$output" "nexent/nexent-mcp:latest" "interactive default image selection should not include mcp image"
assert_not_contains "$output" "nexent/nexent-data-process:latest" "interactive default image selection should not include data-process image"
assert_not_contains "$output" "nexent/nexent-ubuntu-terminal:latest" "interactive default image selection should not include terminal image"

echo "All image build tests passed."
