#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TMP_DIR="${TMPDIR:-/tmp}/nexent-offline-package-test-$$"
BIN_DIR="$TMP_DIR/bin"
OUT_DIR="$TMP_DIR/out"

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
  pull)
    exit 0
    ;;
  save)
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
  [ -f "$package_dir/offline-install.sh" ] || fail "offline-install.sh should be packaged"
  [ -f "$package_dir/load-images.sh" ] || fail "load-images.sh should be packaged"
  [ -f "$package_dir/manifest.yaml" ] || fail "manifest.yaml should be packaged"
  [ -f "$package_dir/checksums.txt" ] || fail "checksums.txt should be packaged"
  [ -f "$package_dir/deploy/deploy.sh" ] || fail "deploy/deploy.sh should be packaged"
  [ -f "$package_dir/deploy/uninstall.sh" ] || fail "deploy/uninstall.sh should be packaged"
  [ -f "$package_dir/VERSION" ] || fail "root VERSION should be packaged"
  [ -f "$package_dir/.env.example" ] || fail "root .env.example should be packaged"
  [ -f "$package_dir/deploy/sql/init.sql" ] || fail "deploy/sql/init.sql should be packaged"
  [ -d "$package_dir/deploy/sql/migrations" ] || fail "deploy/sql/migrations should be packaged"
  [ -d "$package_dir/deploy/sql/supabase" ] || fail "deploy/sql/supabase should be packaged"
  [ -f "$package_dir/deploy/sql/supabase/webhooks.sql" ] || fail "deploy/sql/supabase/webhooks.sql should be packaged"
  [ ! -f "$package_dir/.env" ] || fail ".env should not be packaged"
  [ ! -f "$package_dir/deploy/docker/.env" ] || fail "deploy/docker/.env should not be packaged"
  [ ! -f "$package_dir/deploy/docker/.env.generated" ] || fail "deploy/docker/.env.generated should not be packaged"
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
      --output-dir "$package_dir" >/tmp/nexent-offline-package-${target}.log

  assert_common_package_files "$package_dir"
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

echo "All offline package tests passed."
