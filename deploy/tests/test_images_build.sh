#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_SCRIPT="$PROJECT_ROOT/deploy/images/build.sh"
ROOT_BUILD_SCRIPT="$PROJECT_ROOT/build.sh"
LIGHT_SANDBOX_DOCKERFILE="$PROJECT_ROOT/deploy/images/dockerfiles/sandbox/Dockerfile"
FULL_SANDBOX_DOCKERFILE="$PROJECT_ROOT/deploy/images/dockerfiles/sandbox-full/Dockerfile"
MAINLAND_WORKFLOW="$PROJECT_ROOT/.github/workflows/docker-build-push-mainland.yml"
OVERSEAS_WORKFLOW="$PROJECT_ROOT/.github/workflows/docker-build-push-overseas.yml"
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

for dockerfile in "$LIGHT_SANDBOX_DOCKERFILE" "$FULL_SANDBOX_DOCKERFILE"; do
  [ -f "$dockerfile" ] || fail "sandbox Dockerfile should exist: $dockerfile"
  grep -q 'USER sandbox' "$dockerfile" || fail "sandbox variants should run as the sandbox user"
  grep -q '/mnt/nexent/workdir' "$dockerfile" || fail "sandbox variants should share the workspace contract"
  grep -q 'EXPOSE 8888' "$dockerfile" || fail "sandbox variants should expose the kernel gateway port"
  grep -q 'jupyter.*kernelgateway' "$dockerfile" || fail "sandbox variants should share the kernel gateway command"
done

! grep -q 'FROM node:20' "$LIGHT_SANDBOX_DOCKERFILE" || fail "the default sandbox should remain lightweight"
! grep -q 'libreoffice-impress' "$LIGHT_SANDBOX_DOCKERFILE" || fail "the default sandbox should not include office programs"
grep -q 'io.nexent.sandbox.variant="lightweight"' "$LIGHT_SANDBOX_DOCKERFILE" || fail "the default sandbox should identify its variant"
grep -q 'FROM node:20' "$FULL_SANDBOX_DOCKERFILE" || fail "the full sandbox should include Node 20"
grep -q 'libreoffice-impress' "$FULL_SANDBOX_DOCKERFILE" || fail "the full sandbox should include office programs"
! grep -q 'playwright install' "$FULL_SANDBOX_DOCKERFILE" || fail "the focused full sandbox should exclude Playwright Chromium"
grep -q 'io.nexent.sandbox.skills="docx,pdf,pptx,xlsx,canvas-design,frontend-design,slack-gif-creator,mcp-builder,web-artifacts-builder,skill-creator"' "$FULL_SANDBOX_DOCKERFILE" || fail "the full sandbox should declare its supported skills"
grep -q 'io.nexent.sandbox.variant="full"' "$FULL_SANDBOX_DOCKERFILE" || fail "the full sandbox should identify its variant"
for workflow in "$MAINLAND_WORKFLOW" "$OVERSEAS_WORKFLOW"; do
  matrix="$(sed -n 's/^[[:space:]]*image: \[\(.*\)\]$/\1/p' "$workflow" | tr -d ' ')"
  assert_not_contains ",$matrix," ",main," "$workflow should skip the combined backend image"
  for image in management runtime mcp ops sandbox-full; do
    case ",$matrix," in
      *",$image,"*) ;;
      *) fail "$workflow should publish $image" ;;
    esac
  done
done

output="$(bash "$BUILD_SCRIPT" --images management,web,mcp,data-process --version latest --registry general --dry-run)"
assert_contains "$output" "nexent/nexent-management:latest" "image list should build Management with latest tag"
assert_contains "$output" "nexent/nexent-web:latest" "image list should build web image with latest tag"
assert_contains "$output" "nexent/nexent-mcp:latest" "image list should build mcp image with latest tag"
assert_contains "$output" "nexent/nexent-data-process:latest" "image list should build data-process image with latest tag"
assert_not_contains "$output" "nexent/nexent-ubuntu-terminal:latest" "terminal image should not be built when terminal image is absent"
assert_not_contains "$output" "--platform" "default build should use local architecture"

output="$(bash "$BUILD_SCRIPT" --management --version latest --platform linux/amd64 --dry-run)"
assert_contains "$output" "--platform linux/amd64" "explicit platform should be forwarded"
assert_contains "$output" "nexent/nexent-management:latest" "explicit platform build should still build selected image"

output="$(bash "$BUILD_SCRIPT" --sandbox --version v1.2.3 --dry-run)"
assert_contains "$output" "nexent/nexent-sandbox:v1.2.3" "sandbox should build the default lightweight image"
assert_contains "$output" "dockerfiles/sandbox/Dockerfile" "sandbox should use the lightweight Dockerfile"
assert_not_contains "$output" "nexent/nexent-sandbox-full:v1.2.3" "sandbox should not build the full image"

output="$(bash "$BUILD_SCRIPT" --sandbox-full --version v1.2.3 --dry-run)"
assert_contains "$output" "nexent/nexent-sandbox-full:v1.2.3" "sandbox-full should build the optional full image"
assert_contains "$output" "dockerfiles/sandbox-full/Dockerfile" "sandbox-full should use the full Dockerfile"

output="$(bash "$BUILD_SCRIPT" --sandbox-full --version v1.2.3 --registry mainland --push --dry-run)"
assert_contains "$output" "ccr.ccs.tencentyun.com/nexent-hub/nexent-sandbox-full:v1.2.3" "mainland publishing should use the full Sandbox registry tag"
assert_contains "$output" "NPM_MIRROR=https://repo.huaweicloud.com/repository/npm/" "mainland full Sandbox builds should use the npm mirror"
assert_contains "$output" "MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple" "mainland full Sandbox builds should use the Python mirror"

output="$(bash "$BUILD_SCRIPT" --all --version v1.2.3 --dry-run)"
assert_not_contains "$output" "nexent/nexent:v1.2.3" "all should skip the combined backend image"
assert_contains "$output" "nexent/nexent-sandbox:v1.2.3" "all should include the default lightweight sandbox"
assert_not_contains "$output" "nexent/nexent-sandbox-full:v1.2.3" "all should leave the optional full sandbox opt-in"

output="$(bash "$ROOT_BUILD_SCRIPT" --web --version latest --dry-run)"
assert_contains "$output" "nexent/nexent-web:latest" "root image build entrypoint should forward to deploy/images/build.sh"
assert_not_contains "$output" "nexent/nexent:latest" "root image build entrypoint should preserve selected image arguments"

output="$(bash "$ROOT_BUILD_SCRIPT" --mcp --version latest --dry-run)"
assert_contains "$output" "nexent/nexent-management:latest" "--mcp should build the shared backend image"
assert_contains "$output" "--target management" "--mcp should select the Management target for the backend"
assert_contains "$output" "nexent/nexent-mcp:latest" "--mcp should also build the MCP proxy image"
assert_contains "$output" "dockerfiles/mcp/Dockerfile" "--mcp should select the proxy Dockerfile"
assert_not_contains "$output" "nexent/nexent-mcp-service:" "the standalone backend image should not be built"

output="$(bash "$ROOT_BUILD_SCRIPT" --images mcp --version latest --dry-run)"
assert_contains "$output" "dockerfiles/mcp/Dockerfile" "the image list should build the proxy on its own"
assert_not_contains "$output" "nexent/nexent-management:latest" "selecting mcp in the image list should only build the proxy"

output="$(bash "$ROOT_BUILD_SCRIPT" --ops --version latest --registry mainland --dry-run)"
assert_contains "$output" "nexent/nexent-ops:latest" "--ops should build the Ops image"
assert_contains "$output" "dockerfiles/ops/Dockerfile" "Ops should use its own Dockerfile"
assert_contains "$output" "MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple" "Ops should receive the mainland index"
assert_not_contains "$output" "--target ops" "Ops should build independently of main"

for removed_flag in --main --mcp-service --mcp-proxy; do
  if output="$(bash "$ROOT_BUILD_SCRIPT" "$removed_flag" --version latest --dry-run 2>&1)"; then
    fail "removed option $removed_flag should be rejected"
  fi
  assert_contains "$output" "Unknown option: $removed_flag" "the removed flag should report an unknown option"
done

output="$(bash "$BUILD_SCRIPT" --runtime --version latest --no-cache --dry-run)"
assert_contains "$output" "--no-cache" "explicit no-cache option should be forwarded"
assert_contains "$output" "nexent/nexent-runtime:latest" "explicit no-cache build should still build selected image"

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

for image_option in --image --images; do
  if output="$(bash "$ROOT_BUILD_SCRIPT" "$image_option" main --dry-run 2>&1)"; then
    fail "$image_option main should fail"
  fi
  assert_contains "$output" "Unsupported image: main" "$image_option should reject the retired image"
done

output="$(bash "$BUILD_SCRIPT" --components application --version latest --dry-run)"
assert_not_contains "$output" "nexent/nexent:latest" "application should skip the combined backend image"
for image in management runtime ops; do
  assert_contains "$output" "nexent/nexent-$image:latest" "application should build $image"
done

output="$(bash "$BUILD_SCRIPT" --components infrastructure,monitoring --version latest --dry-run)"
assert_contains "$output" "No Nexent images selected for build." "legacy non-application components should produce no Nexent image builds"

if bash "$BUILD_SCRIPT" --images management,unknown --dry-run >/tmp/nexent-image-build-invalid.log 2>&1; then
  fail "unknown image should fail"
fi
assert_contains "$(cat /tmp/nexent-image-build-invalid.log)" "Unsupported image: unknown" "unknown image should explain the error"

if bash "$BUILD_SCRIPT" --data-process --variant slim --dry-run >/tmp/nexent-image-build-variant.log 2>&1; then
  fail "deprecated data-process variant option should fail"
fi
assert_contains "$(cat /tmp/nexent-image-build-variant.log)" "Unknown option: --variant" "deprecated data-process variant option should be rejected"

output="$(
  printf 'management,web,mcp,data-process\n1\n1\n' | \
    bash "$BUILD_SCRIPT" --interactive --dry-run
)"
assert_contains "$output" "Nexent image build configuration" "interactive mode should show configuration prompt"
assert_contains "$output" "nexent/nexent-management:latest" "interactive mode should accept latest version selection"
assert_contains "$output" "nexent/nexent-web:latest" "interactive image selection should include web image"
assert_contains "$output" "nexent/nexent-mcp:latest" "interactive image selection should include mcp image"
assert_contains "$output" "nexent/nexent-data-process:latest" "interactive image selection should include data-process image"
assert_not_contains "$output" "nexent/nexent-ubuntu-terminal:latest" "interactive image selection should exclude unselected terminal image"
assert_not_contains "$output" "--platform" "interactive mode should use local architecture by default"

output="$(
  printf '\n\n1\n' | \
    bash "$BUILD_SCRIPT" --interactive --dry-run
)"
assert_not_contains "$output" "nexent/nexent:latest" "interactive defaults should skip the combined backend image"
assert_contains "$output" "nexent/nexent-management:latest" "interactive defaults should include Management"
assert_contains "$output" "nexent/nexent-web:latest" "interactive default image selection should include web image"
assert_not_contains "$output" "nexent/nexent-mcp:latest" "interactive default image selection should not include mcp image"
assert_not_contains "$output" "nexent/nexent-data-process:latest" "interactive default image selection should not include data-process image"
assert_not_contains "$output" "nexent/nexent-ubuntu-terminal:latest" "interactive default image selection should not include terminal image"

assert_contains "$(cat "$PROJECT_ROOT/deploy/images/dockerfiles/main/Dockerfile")" \
  "COPY deploy/sql/tools/supabase_to_postgres /opt/deploy/sql/tools/supabase_to_postgres" \
  "the backend Dockerfile must package the account migration tools"
[ -f "$PROJECT_ROOT/deploy/sql/tools/supabase_to_postgres/migrate_docker.py" ] || fail "Docker migration entry point is missing"
[ -f "$PROJECT_ROOT/deploy/sql/tools/supabase_to_postgres/migrate.sh" ] || fail "Host Shell migration entry point is missing"
[ -f "$PROJECT_ROOT/deploy/sql/tools/supabase_to_postgres/migrate_kubernetes.sh" ] || fail "Kubernetes Shell transport is missing"
assert_contains "$(cat "$PROJECT_ROOT/deploy/images/dockerfiles/main/Dockerfile")" 'COPY deploy/sql/migrations/v2.9.0_001_local_user_accounts.sql /opt/deploy/sql/migrations/' "backend image must package the worker account SQL"
assert_contains "$(cat "$PROJECT_ROOT/deploy/images/dockerfiles/main/Dockerfile")" 'COPY deploy/sql/migrations/v2.9.0_010_account_and_ops_roles.sql /opt/deploy/sql/migrations/' "backend image must package the canonical account role SQL"

echo "All image build tests passed."
