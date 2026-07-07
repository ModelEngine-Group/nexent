#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TMP_DIR="${TMPDIR:-/tmp}/nexent-offline-package-test-$$"
BIN_DIR="$TMP_DIR/bin"
OUT_DIR="$TMP_DIR/out"
export DEPLOYMENT_LANG=en

mkdir -p "$BIN_DIR" "$OUT_DIR"
trap 'rm -rf "$TMP_DIR"' EXIT

fail() {
  echo "FAIL: $*"
  exit 1
}

create_fake_docker() {
  cat > "$BIN_DIR/docker" <<'SH'
#!/bin/sh
case "$1" in
  image)
    if [ "$2" = "inspect" ]; then
      [ -n "${FAKE_DOCKER_LOG:-}" ] && printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
      old_ifs="$IFS"
      IFS=','
      for local_image in ${FAKE_DOCKER_LOCAL_IMAGES:-}; do
        if [ "$local_image" = "$3" ]; then
          IFS="$old_ifs"
          exit 0
        fi
      done
      IFS="$old_ifs"
      exit 1
    fi
    exit 0
    ;;
  pull)
    [ -n "${FAKE_DOCKER_LOG:-}" ] && printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
    exit 0
    ;;
  save)
    [ -n "${FAKE_DOCKER_LOG:-}" ] && printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
    out=""
    while [ "$#" -gt 0 ]; do
      if [ "$1" = "-o" ]; then
        out="$2"
        shift 2
        continue
      fi
      shift
    done
    [ -n "$out" ] && : > "$out"
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
SH
  chmod +x "$BIN_DIR/docker"
}

assert_common_package_files() {
  local package_dir="$1"
  [ -f "$package_dir/deploy.sh" ] || fail "deploy.sh should be packaged"
  [ -f "$package_dir/uninstall.sh" ] || fail "uninstall.sh should be packaged"
  [ ! -f "$package_dir/install.sh" ] || fail "install.sh should not be packaged"
  [ ! -f "$package_dir/offline-install.sh" ] || fail "offline-install.sh should not be packaged"
  [ -f "$package_dir/load-images.sh" ] || fail "load-images.sh should be packaged"
  [ -f "$package_dir/manifest.yaml" ] || fail "manifest.yaml should be packaged"
  [ -f "$package_dir/checksums.txt" ] || fail "checksums.txt should be packaged"
  [ -f "$package_dir/deploy/deploy.sh" ] || fail "deploy/deploy.sh should be packaged"
  [ -f "$package_dir/deploy/uninstall.sh" ] || fail "deploy/uninstall.sh should be packaged"
  [ -f "$package_dir/VERSION" ] || fail "root VERSION should be packaged"
  [ -f "$package_dir/deploy/env/.env.example" ] || fail "deploy/env/.env.example should be packaged"
  [ -f "$package_dir/deploy/env/monitoring.env.example" ] || fail "deploy/env/monitoring.env.example should be packaged"
  [ -f "$package_dir/deploy/sql/init.sql" ] || fail "deploy/sql/init.sql should be packaged"
  [ -d "$package_dir/deploy/sql/migrations" ] || fail "deploy/sql/migrations should be packaged"
  [ -d "$package_dir/deploy/sql/supabase" ] || fail "deploy/sql/supabase should be packaged"
  [ -f "$package_dir/deploy/sql/supabase/webhooks.sql" ] || fail "deploy/sql/supabase/webhooks.sql should be packaged"
  [ ! -f "$package_dir/.env" ] || fail "root .env should not be packaged"
  [ ! -f "$package_dir/deploy/env/.env" ] || fail "deploy/env/.env should not be packaged"
  [ ! -f "$package_dir/deploy/env/monitoring.env" ] || fail "generated deploy/env/monitoring.env should not be packaged"
  [ ! -f "$package_dir/deploy/docker/.env" ] || fail "deploy/docker/.env should not be packaged"
  [ ! -f "$package_dir/deploy/docker/.env.generated" ] || fail "deploy/docker/.env.generated should not be packaged"
  if [ -d "$package_dir/deploy/docker" ]; then
    [ ! -f "$package_dir/deploy/docker/assets/monitoring/monitoring.env" ] || fail "generated monitoring.env should not be packaged"
    [ ! -f "$package_dir/deploy/docker/assets/monitoring/monitoring.env.example" ] || fail "monitoring.env.example should live under deploy/env"
  fi
  [ ! -f "$package_dir/deploy/docker/deploy.options" ] || fail "deploy/docker/deploy.options should not be packaged"
}

create_fake_docker

for target in docker k8s all; do
  package_dir="$OUT_DIR/$target"
  PATH="$BIN_DIR:$PATH" \
    bash "$PROJECT_ROOT/deploy/offline/build_offline_package.sh" \
      --version v2.2.0 \
      --platform amd64 \
      --components infrastructure,application \
      --image-source general \
      --target "$target" \
      --compress true \
      --output-dir "$package_dir" >/tmp/nexent-offline-package-${target}.log

  assert_common_package_files "$package_dir"
  [ -f "$OUT_DIR/nexent-offline-${target}-amd64-v2.2.0.zip" ] || fail "zip package should be created for target $target"
  grep -q "target: \"$target\"" "$package_dir/manifest.yaml" || fail "manifest should record target $target"
  grep -q "nexent/nexent:v2.2.0" "$package_dir/manifest.yaml" || fail "manifest should include Nexent image"

  case "$target" in
    docker)
      [ -f "$package_dir/deploy/docker/deploy.sh" ] || fail "docker package should include deploy/docker/deploy.sh"
      [ ! -e "$package_dir/deploy/k8s/deploy.sh" ] || fail "docker package should not include k8s deploy script"
      ;;
    k8s)
      [ -f "$package_dir/deploy/k8s/deploy.sh" ] || fail "k8s package should include deploy/k8s/deploy.sh"
      [ ! -e "$package_dir/deploy/docker/deploy.sh" ] || fail "k8s package should not include docker deploy script"
      ;;
    all)
      [ -f "$package_dir/deploy/docker/deploy.sh" ] || fail "all package should include deploy/docker/deploy.sh"
      [ -f "$package_dir/deploy/k8s/deploy.sh" ] || fail "all package should include deploy/k8s/deploy.sh"
      ;;
  esac
done

deploy_wrapper_dir="$OUT_DIR/deploy-wrapper"
mkdir -p "$deploy_wrapper_dir/deploy"
cp "$PROJECT_ROOT/deploy.sh" "$deploy_wrapper_dir/deploy.sh"
cat > "$deploy_wrapper_dir/load-images.sh" <<'SH'
#!/usr/bin/env bash
printf 'load-images\n' >> "$DEPLOY_WRAPPER_LOG"
SH
chmod +x "$deploy_wrapper_dir/load-images.sh"
cat > "$deploy_wrapper_dir/deploy/deploy.sh" <<'SH'
#!/usr/bin/env bash
printf 'deploy:%s\n' "$*" >> "$DEPLOY_WRAPPER_LOG"
SH
chmod +x "$deploy_wrapper_dir/deploy/deploy.sh"

deploy_wrapper_log="$TMP_DIR/deploy-wrapper.log"
DEPLOY_WRAPPER_LOG="$deploy_wrapper_log" bash "$deploy_wrapper_dir/deploy.sh" docker --foo bar
if grep -q '^load-images$' "$deploy_wrapper_log"; then
  fail "deploy.sh should not load images by default"
fi
grep -q '^deploy:docker --foo bar$' "$deploy_wrapper_log" || fail "deploy.sh should forward args without --load-images"

: > "$deploy_wrapper_log"
DEPLOY_WRAPPER_LOG="$deploy_wrapper_log" bash "$deploy_wrapper_dir/deploy.sh" --load-images docker --foo bar
first_line="$(sed -n '1p' "$deploy_wrapper_log")"
second_line="$(sed -n '2p' "$deploy_wrapper_log")"
[ "$first_line" = "load-images" ] || fail "deploy.sh --load-images should load images before deploy"
[ "$second_line" = "deploy:docker --foo bar" ] || fail "deploy.sh --load-images should strip only the wrapper flag"

latest_package_dir="$OUT_DIR/latest"
latest_pull_log="$TMP_DIR/latest-docker.log"
: > "$latest_pull_log"

output="$(bash "$PROJECT_ROOT/build.sh" --package --version v2.2.0 --platform amd64 --components infrastructure,application --image-source general --target docker --dry-run)"
echo "$output" | grep -q "=== DRY RUN MODE ===" || fail "build.sh --package should forward to offline package builder"
echo "$output" | grep -q "Target: docker" || fail "build.sh --package should forward package arguments"
echo "$output" | grep -q "nexent/nexent:v2.2.0" || fail "build.sh --package should render package image plan"

PATH="$BIN_DIR:$PATH" FAKE_DOCKER_LOG="$latest_pull_log" \
  bash "$PROJECT_ROOT/deploy/offline/build_offline_package.sh" \
    --version latest \
    --platform amd64 \
    --components infrastructure,application \
    --image-source general \
    --target docker \
    --compress true \
    --output-dir "$latest_package_dir" >/tmp/nexent-offline-package-latest.log

assert_common_package_files "$latest_package_dir"
grep -q '^DEPLOY_WRAPPER_DEFAULT_CONFIG_MODE="defaults"$' "$latest_package_dir/deploy.sh" || fail "offline deploy.sh should reuse the root entrypoint with defaults mode enabled"
offline_help="$(DEPLOYMENT_LANG=en bash "$latest_package_dir/deploy.sh" --help)"
echo "$offline_help" | grep -q "deploys with saved configuration or built-in defaults" || fail "offline deploy help should explain default non-interactive mode"

cat > "$latest_package_dir/load-images.sh" <<'SH'
#!/usr/bin/env bash
printf 'load-images\n' >> "$DEPLOY_WRAPPER_LOG"
SH
chmod +x "$latest_package_dir/load-images.sh"
cat > "$latest_package_dir/deploy/deploy.sh" <<'SH'
#!/usr/bin/env bash
printf 'deploy:%s:%s\n' "${NEXENT_DEPLOY_CONFIG_MODE:-}" "$*" >> "$DEPLOY_WRAPPER_LOG"
SH
chmod +x "$latest_package_dir/deploy/deploy.sh"

offline_deploy_log="$TMP_DIR/offline-deploy-wrapper.log"
: > "$offline_deploy_log"
DEPLOY_WRAPPER_LOG="$offline_deploy_log" bash "$latest_package_dir/deploy.sh" docker --foo bar
grep -q '^deploy:defaults:docker --foo bar$' "$offline_deploy_log" || fail "offline deploy.sh should default to non-interactive defaults mode"

: > "$offline_deploy_log"
DEPLOY_WRAPPER_LOG="$offline_deploy_log" bash "$latest_package_dir/deploy.sh" docker --config --foo bar
grep -q '^deploy:tui:docker --foo bar$' "$offline_deploy_log" || fail "offline deploy.sh --config should enable TUI mode and consume the flag"

: > "$offline_deploy_log"
DEPLOY_WRAPPER_LOG="$offline_deploy_log" bash "$latest_package_dir/deploy.sh" --load-images docker --foo bar
first_line="$(sed -n '1p' "$offline_deploy_log")"
second_line="$(sed -n '2p' "$offline_deploy_log")"
[ "$first_line" = "load-images" ] || fail "offline deploy.sh --load-images should load images before deploy"
[ "$second_line" = "deploy:defaults:docker --foo bar" ] || fail "offline deploy.sh --load-images should preserve defaults mode"

[ -f "$OUT_DIR/nexent-offline-docker-amd64-latest.zip" ] || fail "zip package should be created for latest package"
grep -q "nexent/nexent:latest" "$latest_package_dir/manifest.yaml" || fail "manifest should include local latest Nexent image"
! grep -q '^pull .*nexent/nexent:latest$' "$latest_pull_log" || fail "latest Nexent image should not be pulled"
! grep -q '^pull .*nexent/nexent-web:latest$' "$latest_pull_log" || fail "latest Nexent web image should not be pulled"
! grep -q '^pull .*nexent/nexent-mcp:latest$' "$latest_pull_log" || fail "latest Nexent MCP image should not be pulled"
grep -q '^pull .*docker.elastic.co/elasticsearch/elasticsearch:8.17.4$' "$latest_pull_log" || fail "non-latest infrastructure images should still be pulled"

local_package_dir="$OUT_DIR/local-existing/package"
local_pull_log="$TMP_DIR/local-existing-docker.log"
: > "$local_pull_log"

PATH="$BIN_DIR:$PATH" \
  FAKE_DOCKER_LOG="$local_pull_log" \
  FAKE_DOCKER_LOCAL_IMAGES="nexent/nexent:v2.2.0,docker.elastic.co/elasticsearch/elasticsearch:8.17.4" \
  bash "$PROJECT_ROOT/deploy/offline/build_offline_package.sh" \
    --version v2.2.0 \
    --platform amd64 \
    --components infrastructure,application \
    --image-source general \
    --target docker \
    --compress true \
    --output-dir "$local_package_dir" >/tmp/nexent-offline-package-local-existing.log

assert_common_package_files "$local_package_dir"
[ -f "$OUT_DIR/local-existing/nexent-offline-docker-amd64-v2.2.0.zip" ] || fail "zip package should be created for local existing package"
! grep -q '^pull .*nexent/nexent:v2.2.0$' "$local_pull_log" || fail "existing local Nexent image should not be pulled"
! grep -q '^pull .*docker.elastic.co/elasticsearch/elasticsearch:8.17.4$' "$local_pull_log" || fail "existing local infrastructure image should not be pulled"
grep -q '^pull .*nexent/nexent-web:v2.2.0$' "$local_pull_log" || fail "missing non-latest Nexent web image should still be pulled"

default_package_dir="$OUT_DIR/default-no-compress/package"
PATH="$BIN_DIR:$PATH" \
  bash "$PROJECT_ROOT/deploy/offline/build_offline_package.sh" \
    --version v2.2.0 \
    --platform amd64 \
    --components infrastructure,application \
    --image-source general \
    --target docker \
    --output-dir "$default_package_dir" >/tmp/nexent-offline-package-default-no-compress.log

assert_common_package_files "$default_package_dir"
[ ! -f "$OUT_DIR/default-no-compress/nexent-offline-docker-amd64-v2.2.0.zip" ] || fail "zip package should not be created by default"

echo "All offline package tests passed."
