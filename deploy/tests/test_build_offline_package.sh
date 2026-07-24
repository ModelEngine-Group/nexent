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
  login)
    password="$(cat)"
    [ -n "${FAKE_DOCKER_LOG:-}" ] && printf '%s password=%s\n' "$*" "$password" >> "$FAKE_DOCKER_LOG"
    exit 0
    ;;
  load|tag|push)
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
  [ -f "$package_dir/push-images.sh" ] || fail "push-images.sh should be packaged"
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

WORKFLOW_CONTENT="$(cat "$PROJECT_ROOT/.github/workflows/build-offline-package.yml")"
echo "$WORKFLOW_CONTENT" | grep -q 'SOURCE_SUFFIX="-with-source"' || fail "offline package workflow should append with-source when source is included"
echo "$WORKFLOW_CONTENT" | grep -q 'package-name=nexent-${VERSION}-${PLATFORM}${SOURCE_SUFFIX}' || fail "offline package workflow package name should include source suffix"
echo "$WORKFLOW_CONTENT" | grep -q -- '--compress false' || fail "offline package workflow should let GitHub create the final artifact zip"
echo "$WORKFLOW_CONTENT" | grep -q 'path: ./offline-output' || fail "offline package workflow should upload package contents, not an inner zip"
! echo "$WORKFLOW_CONTENT" | grep -q 'path: .*package-name.*\\.zip' || fail "offline package workflow should not upload a pre-compressed zip"

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
  [ "$(cat "$package_dir/VERSION")" = "v2.2.0" ] || fail "root VERSION should match requested package version for target $target"
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
mkdir -p "$deploy_wrapper_dir/deploy/common" "$deploy_wrapper_dir/deploy/env"
cp "$PROJECT_ROOT/deploy.sh" "$deploy_wrapper_dir/deploy.sh"
cp "$PROJECT_ROOT/deploy/common/common.sh" "$deploy_wrapper_dir/deploy/common/common.sh"
printf 'WRAPPER_OLD_VALUE=preserved\n' > "$deploy_wrapper_dir/deploy/env/.env"
printf 'WRAPPER_NEW_DEFAULT=merged-before-actions\n' > "$deploy_wrapper_dir/deploy/env/.env.example"
cat > "$deploy_wrapper_dir/load-images.sh" <<'SH'
#!/usr/bin/env bash
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "${DEPLOY_WRAPPER_EXPECT_ENV:-}" ]; then
  grep -Fqx "$DEPLOY_WRAPPER_EXPECT_ENV" "$script_dir/deploy/env/.env" || exit 1
fi
printf 'load-images\n' >> "$DEPLOY_WRAPPER_LOG"
SH
chmod +x "$deploy_wrapper_dir/load-images.sh"
cat > "$deploy_wrapper_dir/push-images.sh" <<'SH'
#!/usr/bin/env bash
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "${DEPLOY_WRAPPER_EXPECT_ENV:-}" ]; then
  grep -Fqx "$DEPLOY_WRAPPER_EXPECT_ENV" "$script_dir/deploy/env/.env" || exit 1
fi
args=("$@")
printf 'push:%s:%s\n' "${REGISTRY_PASSWORD:-}" "${args[*]}" >> "$DEPLOY_WRAPPER_LOG"
SH
chmod +x "$deploy_wrapper_dir/push-images.sh"
cat > "$deploy_wrapper_dir/deploy/deploy.sh" <<'SH'
#!/usr/bin/env bash
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "${DEPLOY_WRAPPER_EXPECT_ENV:-}" ]; then
  grep -Fqx "$DEPLOY_WRAPPER_EXPECT_ENV" "$script_dir/env/.env" || exit 1
fi
printf 'deploy:%s:%s:%s\n' "${NEXENT_DEPLOY_CONFIG_MODE:-}" "${NEXENT_DEPLOYMENT_OFFLINE:-}" "$*" >> "$DEPLOY_WRAPPER_LOG"
SH
chmod +x "$deploy_wrapper_dir/deploy/deploy.sh"

deploy_wrapper_log="$TMP_DIR/deploy-wrapper.log"
DEPLOY_WRAPPER_LOG="$deploy_wrapper_log" \
  DEPLOY_WRAPPER_EXPECT_ENV='WRAPPER_NEW_DEFAULT=merged-before-actions' \
  bash "$deploy_wrapper_dir/deploy.sh" docker --foo bar
if grep -q '^load-images$' "$deploy_wrapper_log"; then
  fail "deploy.sh should not load images by default"
fi
grep -q '^deploy::false:docker --foo bar$' "$deploy_wrapper_log" || fail "deploy.sh should forward args and mark an online deployment"
grep -q '^WRAPPER_OLD_VALUE=preserved$' "$deploy_wrapper_dir/deploy/env/.env" || fail "online deployment should preserve existing environment values"
grep -q '^WRAPPER_NEW_DEFAULT=merged-before-actions$' "$deploy_wrapper_dir/deploy/env/.env" || fail "online deployment should merge current template variables"

: > "$deploy_wrapper_log"
DEPLOY_WRAPPER_LOG="$deploy_wrapper_log" \
  DEPLOY_WRAPPER_EXPECT_ENV='WRAPPER_NEW_DEFAULT=merged-before-actions' \
  bash "$deploy_wrapper_dir/deploy.sh" --load-images docker --foo bar
first_line="$(sed -n '1p' "$deploy_wrapper_log")"
second_line="$(sed -n '2p' "$deploy_wrapper_log")"
[ "$first_line" = "load-images" ] || fail "deploy.sh --load-images should load images before deploy"
[ "$second_line" = "deploy::false:docker --foo bar" ] || fail "deploy.sh --load-images should strip only the wrapper flag"

mv "$deploy_wrapper_dir/deploy/env/.env.example" "$deploy_wrapper_dir/deploy/env/.env.example.saved"
: > "$deploy_wrapper_log"
if DEPLOY_WRAPPER_LOG="$deploy_wrapper_log" bash "$deploy_wrapper_dir/deploy.sh" --load-images docker --foo bar >"$TMP_DIR/wrapper-missing-template.log" 2>&1; then
  mv "$deploy_wrapper_dir/deploy/env/.env.example.saved" "$deploy_wrapper_dir/deploy/env/.env.example"
  fail "deploy.sh should require the current .env.example before loading images"
fi
mv "$deploy_wrapper_dir/deploy/env/.env.example.saved" "$deploy_wrapper_dir/deploy/env/.env.example"
[ ! -s "$deploy_wrapper_log" ] || fail "missing .env.example should fail before image loading or deployment"
grep -q 'deploy/env/.env.example' "$TMP_DIR/wrapper-missing-template.log" || fail "missing template failure should identify deploy/env/.env.example"

: > "$deploy_wrapper_log"
DEPLOY_WRAPPER_LOG="$deploy_wrapper_log" bash "$deploy_wrapper_dir/deploy.sh" --defaults docker --foo bar
grep -q '^deploy:defaults:false:docker --foo bar$' "$deploy_wrapper_log" || fail "deploy.sh --defaults before target should enable defaults mode"

: > "$deploy_wrapper_log"
DEPLOY_WRAPPER_LOG="$deploy_wrapper_log" bash "$deploy_wrapper_dir/deploy.sh" docker --defaults --foo bar
grep -q '^deploy:defaults:false:docker --foo bar$' "$deploy_wrapper_log" || fail "deploy.sh --defaults after target should enable defaults mode and consume the flag"

: > "$deploy_wrapper_log"
DEPLOY_WRAPPER_LOG="$deploy_wrapper_log" bash "$deploy_wrapper_dir/deploy.sh" docker --config --foo bar
grep -q '^deploy:tui:false:docker --foo bar$' "$deploy_wrapper_log" || fail "online deploy.sh --config should enable TUI mode without the offline marker"

online_reuse_source="$TMP_DIR/online-reuse-source"
mkdir -p "$online_reuse_source/deploy/env"
printf 'ONLINE_REUSE_TEST=yes\n' > "$online_reuse_source/deploy/env/.env"
if DEPLOY_WRAPPER_LOG="$deploy_wrapper_log" bash "$deploy_wrapper_dir/deploy.sh" --reuse-from "$online_reuse_source" docker --foo bar >"$TMP_DIR/online-reuse.log" 2>&1; then
  fail "online deploy.sh should reject --reuse-from"
fi
grep -q 'offline package entrypoint' "$TMP_DIR/online-reuse.log" || fail "online --reuse-from error should explain that the option is offline-only"

: > "$deploy_wrapper_log"
DEPLOY_WRAPPER_LOG="$deploy_wrapper_log" REGISTRY_USERNAME=user REGISTRY_PASSWORD=secret bash "$deploy_wrapper_dir/deploy.sh" --push-images --image-registry-prefix registry.local/nexent docker --foo bar
first_line="$(sed -n '1p' "$deploy_wrapper_log")"
second_line="$(sed -n '2p' "$deploy_wrapper_log")"
[[ "$first_line" == "push:secret:--image-registry-prefix registry.local/nexent --load-images" ]] || fail "deploy.sh --push-images should delegate push args to push-images.sh"
[ "$second_line" = "deploy::false:docker --foo bar --image-registry-prefix registry.local/nexent" ] || fail "deploy.sh --push-images should forward image registry prefix to deploy config"
: > "$deploy_wrapper_log"
DEPLOY_WRAPPER_LOG="$deploy_wrapper_log" REGISTRY_USERNAME=user REGISTRY_PASSWORD=secret bash "$deploy_wrapper_dir/deploy.sh" --load-images --push-images --image-registry-prefix registry.local/nexent docker --foo bar
first_line="$(sed -n '1p' "$deploy_wrapper_log")"
second_line="$(sed -n '2p' "$deploy_wrapper_log")"
[[ "$first_line" == "push:secret:--image-registry-prefix registry.local/nexent --load-images" ]] || fail "deploy.sh --load-images --push-images should not load before push login"
[ "$second_line" = "deploy::false:docker --foo bar --image-registry-prefix registry.local/nexent" ] || fail "deploy.sh --load-images --push-images should forward deploy args"

if DEPLOY_WRAPPER_LOG="$deploy_wrapper_log" REGISTRY_USERNAME=user REGISTRY_PASSWORD=secret bash "$deploy_wrapper_dir/deploy.sh" --push-images docker --foo bar >/tmp/nexent-deploy-wrapper-missing-prefix.log 2>&1; then
  fail "deploy.sh --push-images should require image registry prefix in non-interactive mode"
fi
grep -q -- '--image-registry-prefix' /tmp/nexent-deploy-wrapper-missing-prefix.log || fail "deploy.sh missing prefix error should be explicit"

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
[ "$(cat "$latest_package_dir/VERSION")" = "latest" ] || fail "root VERSION should match requested latest package version"
grep -q '^DEPLOY_WRAPPER_DEFAULT_CONFIG_MODE="defaults"$' "$latest_package_dir/deploy.sh" || fail "offline deploy.sh should reuse the root entrypoint with defaults mode enabled"
offline_help="$(DEPLOYMENT_LANG=en bash "$latest_package_dir/deploy.sh" --help)"
echo "$offline_help" | grep -q "deploys with saved configuration or built-in defaults" || fail "offline deploy help should explain default non-interactive mode"
echo "$offline_help" | grep -q -- '--reuse-from DIR' || fail "offline deploy help should document --reuse-from"
printf '\nOFFLINE_TEMPLATE_ONLY=merged-before-actions\n' >> "$latest_package_dir/deploy/env/.env.example"

push_log="$TMP_DIR/push-images.log"
: > "$push_log"
PATH="$BIN_DIR:$PATH" \
  FAKE_DOCKER_LOG="$push_log" \
  FAKE_DOCKER_LOCAL_IMAGES="nexent/nexent:latest,nexent/nexent-web:latest,nexent/nexent-mcp:latest,docker.elastic.co/elasticsearch/elasticsearch:8.17.4,postgres:15-alpine,redis:alpine,quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z" \
  REGISTRY_PASSWORD=secret \
  bash "$latest_package_dir/push-images.sh" \
    --image-registry-prefix https://registry.local/nexent/ \
    --registry-username user \
    --output-env-file "$TMP_DIR/push-images.env" >/tmp/nexent-offline-package-push.log
grep -q '^login registry.local --username user --password-stdin password=secret$' "$push_log" || fail "push-images.sh should login to registry host with password stdin"
grep -q '^IMAGE_REGISTRY_PREFIX=registry.local/nexent$' "$TMP_DIR/push-images.env" || fail "push-images.sh should write selected registry prefix to output env file"
grep -q '^tag nexent/nexent:latest registry.local/nexent/nexent/nexent:latest$' "$push_log" || fail "push-images.sh should tag Nexent image with registry prefix"
grep -q '^push registry.local/nexent/nexent/nexent:latest$' "$push_log" || fail "push-images.sh should push prefixed Nexent image"
grep -q '^tag docker.elastic.co/elasticsearch/elasticsearch:8.17.4 registry.local/nexent/docker.elastic.co/elasticsearch/elasticsearch:8.17.4$' "$push_log" || fail "push-images.sh should tag third-party image with registry prefix"
: > "$push_log"
PATH="$BIN_DIR:$PATH" \
  FAKE_DOCKER_LOG="$push_log" \
  FAKE_DOCKER_LOCAL_IMAGES="nexent/nexent:latest,nexent/nexent-web:latest,nexent/nexent-mcp:latest,docker.elastic.co/elasticsearch/elasticsearch:8.17.4,postgres:15-alpine,redis:alpine,quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z" \
  REGISTRY_PASSWORD=secret \
  bash "$latest_package_dir/push-images.sh" \
    --load-images \
    --image-registry-prefix registry.local/nexent \
    --registry-username user >/tmp/nexent-offline-package-push-load.log
first_line="$(sed -n '1p' "$push_log")"
second_line="$(sed -n '2p' "$push_log")"
[ "$first_line" = "login registry.local --username user --password-stdin password=secret" ] || fail "push-images.sh should docker login before loading images"
[[ "$second_line" == load\ -i\ * ]] || fail "push-images.sh should load images only after docker login"
if PATH="$BIN_DIR:$PATH" REGISTRY_PASSWORD=secret bash "$latest_package_dir/push-images.sh" --image-registry-prefix registry.local/nexent >/tmp/nexent-offline-package-push-missing-user.log 2>&1; then
  fail "push-images.sh should require registry username in non-interactive mode"
fi
grep -q -- '--registry-username is required' /tmp/nexent-offline-package-push-missing-user.log || fail "push-images.sh missing username error should be explicit"

cat > "$latest_package_dir/load-images.sh" <<'SH'
#!/usr/bin/env bash
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "${DEPLOY_WRAPPER_EXPECT_ENV:-}" ]; then
  grep -Fqx "$DEPLOY_WRAPPER_EXPECT_ENV" "$script_dir/deploy/env/.env" || exit 1
fi
if [ -n "${DEPLOY_WRAPPER_EXPECT_MERGED_ENV:-}" ]; then
  grep -Fqx "$DEPLOY_WRAPPER_EXPECT_MERGED_ENV" "$script_dir/deploy/env/.env" || exit 1
fi
printf 'load-images\n' >> "$DEPLOY_WRAPPER_LOG"
SH
chmod +x "$latest_package_dir/load-images.sh"
cat > "$latest_package_dir/push-images.sh" <<'SH'
#!/usr/bin/env bash
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "${DEPLOY_WRAPPER_EXPECT_ENV:-}" ]; then
  grep -Fqx "$DEPLOY_WRAPPER_EXPECT_ENV" "$script_dir/deploy/env/.env" || exit 1
fi
if [ -n "${DEPLOY_WRAPPER_EXPECT_MERGED_ENV:-}" ]; then
  grep -Fqx "$DEPLOY_WRAPPER_EXPECT_MERGED_ENV" "$script_dir/deploy/env/.env" || exit 1
fi
args=("$@")
printf 'push:%s:%s\n' "${REGISTRY_PASSWORD:-}" "${args[*]}" >> "$DEPLOY_WRAPPER_LOG"
SH
chmod +x "$latest_package_dir/push-images.sh"
cat > "$latest_package_dir/deploy/deploy.sh" <<'SH'
#!/usr/bin/env bash
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "${DEPLOY_WRAPPER_EXPECT_ENV:-}" ]; then
  grep -Fqx "$DEPLOY_WRAPPER_EXPECT_ENV" "$script_dir/env/.env" || exit 1
fi
if [ -n "${DEPLOY_WRAPPER_EXPECT_MERGED_ENV:-}" ]; then
  grep -Fqx "$DEPLOY_WRAPPER_EXPECT_MERGED_ENV" "$script_dir/env/.env" || exit 1
fi
printf 'deploy:%s:%s:%s\n' "${NEXENT_DEPLOY_CONFIG_MODE:-}" "${NEXENT_DEPLOYMENT_OFFLINE:-}" "$*" >> "$DEPLOY_WRAPPER_LOG"
SH
chmod +x "$latest_package_dir/deploy/deploy.sh"

offline_deploy_log="$TMP_DIR/offline-deploy-wrapper.log"
: > "$offline_deploy_log"

missing_template_reuse_source="$TMP_DIR/missing-template-reuse-source"
mkdir -p "$missing_template_reuse_source/deploy/env"
printf 'SHOULD_NOT_BE_COPIED=yes\n' > "$missing_template_reuse_source/deploy/env/.env"
mv "$latest_package_dir/deploy/env/.env.example" "$latest_package_dir/deploy/env/.env.example.saved"
if DEPLOY_WRAPPER_LOG="$offline_deploy_log" bash "$latest_package_dir/deploy.sh" --reuse-from "$missing_template_reuse_source" --load-images docker --foo bar >"$TMP_DIR/offline-missing-template.log" 2>&1; then
  mv "$latest_package_dir/deploy/env/.env.example.saved" "$latest_package_dir/deploy/env/.env.example"
  fail "offline deploy.sh should require .env.example before loading images"
fi
mv "$latest_package_dir/deploy/env/.env.example.saved" "$latest_package_dir/deploy/env/.env.example"
[ ! -s "$offline_deploy_log" ] || fail "offline missing template failure should happen before image loading or deployment"
[ ! -f "$latest_package_dir/deploy/env/.env" ] || fail "offline missing template failure should happen before importing a reused .env"
grep -q 'deploy/env/.env.example' "$TMP_DIR/offline-missing-template.log" || fail "offline missing template failure should identify deploy/env/.env.example"

reuse_source="$TMP_DIR/previous package"
mkdir -p "$reuse_source/deploy/env" "$reuse_source/deploy/docker" "$reuse_source/deploy/k8s/helm/nexent"
printf 'REUSED_SECRET=do-not-print-this-value\n' > "$reuse_source/deploy/env/.env"
printf 'MONITORING_REUSED=yes\n' > "$reuse_source/deploy/env/monitoring.env"
printf 'DOCKER_OPTIONS=reused\n' > "$reuse_source/deploy/docker/deploy.options"
printf 'K8S_OPTIONS=reused\n' > "$reuse_source/deploy/k8s/deploy.options"
printf 'SOURCE_DERIVED=docker\n' > "$reuse_source/deploy/docker/.env.generated"
printf 'SOURCE_DERIVED=k8s\n' > "$reuse_source/deploy/k8s/helm/nexent/generated-values.yaml"

mkdir -p "$latest_package_dir/deploy/k8s/helm/nexent"
printf 'DOCKER_OPTIONS=current\n' > "$latest_package_dir/deploy/docker/deploy.options"
printf 'K8S_OPTIONS=keep-for-docker\n' > "$latest_package_dir/deploy/k8s/deploy.options"
printf 'CURRENT_DERIVED=docker\n' > "$latest_package_dir/deploy/docker/.env.generated"
printf 'CURRENT_DERIVED=k8s\n' > "$latest_package_dir/deploy/k8s/helm/nexent/generated-values.yaml"

: > "$offline_deploy_log"
DEPLOY_WRAPPER_LOG="$offline_deploy_log" \
  DEPLOY_WRAPPER_EXPECT_ENV='REUSED_SECRET=do-not-print-this-value' \
  DEPLOY_WRAPPER_EXPECT_MERGED_ENV='OFFLINE_TEMPLATE_ONLY=merged-before-actions' \
  bash "$latest_package_dir/deploy.sh" docker --reuse-from "$reuse_source" --load-images --foo bar >"$TMP_DIR/reuse-docker.log" 2>&1
first_line="$(sed -n '1p' "$offline_deploy_log")"
second_line="$(sed -n '2p' "$offline_deploy_log")"
[ "$first_line" = "load-images" ] || fail "--reuse-from should import files before loading images"
[ "$second_line" = "deploy:defaults:true:docker --foo bar" ] || fail "--reuse-from should be consumed before forwarding Docker deploy arguments"
grep -q '^REUSED_SECRET=do-not-print-this-value$' "$latest_package_dir/deploy/env/.env" || fail "Docker reuse should copy deploy/env/.env"
grep -q '^OFFLINE_TEMPLATE_ONLY=merged-before-actions$' "$latest_package_dir/deploy/env/.env" || fail "Docker reuse should merge variables from the current .env.example"
grep -q '^MONITORING_REUSED=yes$' "$latest_package_dir/deploy/env/monitoring.env" || fail "Docker reuse should copy monitoring.env"
grep -q '^DOCKER_OPTIONS=reused$' "$latest_package_dir/deploy/docker/deploy.options" || fail "Docker reuse should overwrite Docker deploy.options"
grep -q '^K8S_OPTIONS=keep-for-docker$' "$latest_package_dir/deploy/k8s/deploy.options" || fail "Docker reuse should not copy K8s deploy.options"
grep -q '^CURRENT_DERIVED=docker$' "$latest_package_dir/deploy/docker/.env.generated" || fail "Docker reuse should not copy derived .env.generated"
grep -q '^CURRENT_DERIVED=k8s$' "$latest_package_dir/deploy/k8s/helm/nexent/generated-values.yaml" || fail "Docker reuse should not copy K8s generated values"
! grep -q 'do-not-print-this-value' "$TMP_DIR/reuse-docker.log" || fail "--reuse-from should not print environment values"

printf 'DOCKER_OPTIONS=keep-for-k8s\n' > "$latest_package_dir/deploy/docker/deploy.options"
printf 'K8S_OPTIONS=current\n' > "$latest_package_dir/deploy/k8s/deploy.options"
: > "$offline_deploy_log"
DEPLOY_WRAPPER_LOG="$offline_deploy_log" \
  DEPLOY_WRAPPER_EXPECT_ENV='REUSED_SECRET=do-not-print-this-value' \
  DEPLOY_WRAPPER_EXPECT_MERGED_ENV='OFFLINE_TEMPLATE_ONLY=merged-before-actions' \
  REGISTRY_PASSWORD=secret \
  bash "$latest_package_dir/deploy.sh" --push-images --image-registry-prefix registry.local/nexent --reuse-from "$reuse_source" k8s --foo bar >"$TMP_DIR/reuse-k8s.log" 2>&1
first_line="$(sed -n '1p' "$offline_deploy_log")"
second_line="$(sed -n '2p' "$offline_deploy_log")"
[[ "$first_line" == "push:secret:--image-registry-prefix registry.local/nexent --load-images" ]] || fail "--reuse-from should import files before pushing images"
[ "$second_line" = "deploy:defaults:true:k8s --foo bar --image-registry-prefix registry.local/nexent" ] || fail "--reuse-from should be consumed before forwarding K8s deploy arguments"
grep -q '^K8S_OPTIONS=reused$' "$latest_package_dir/deploy/k8s/deploy.options" || fail "K8s reuse should overwrite K8s deploy.options"
grep -q '^DOCKER_OPTIONS=keep-for-k8s$' "$latest_package_dir/deploy/docker/deploy.options" || fail "K8s reuse should not copy Docker deploy.options"

: > "$offline_deploy_log"
DEPLOY_WRAPPER_LOG="$offline_deploy_log" bash "$latest_package_dir/deploy.sh" --reuse-from "$reuse_source" --config docker --foo bar >"$TMP_DIR/reuse-config.log" 2>&1
grep -q '^deploy:tui:true:docker --foo bar$' "$offline_deploy_log" || fail "--reuse-from should work with --config and preserve TUI mode"

minimal_reuse_source="$TMP_DIR/minimal previous package"
mkdir -p "$minimal_reuse_source/deploy/env"
printf 'MINIMAL_REUSE=yes\n' > "$minimal_reuse_source/deploy/env/.env"
: > "$offline_deploy_log"
DEPLOY_WRAPPER_LOG="$offline_deploy_log" bash "$latest_package_dir/deploy.sh" --reuse-from "$minimal_reuse_source" --defaults docker --foo bar >"$TMP_DIR/reuse-minimal.log" 2>&1
grep -q 'optional file not found' "$TMP_DIR/reuse-minimal.log" || fail "missing optional reuse files should produce warnings"
grep -q '^deploy:defaults:true:docker --foo bar$' "$offline_deploy_log" || fail "missing optional reuse files should not stop deployment"

missing_env_source="$TMP_DIR/missing-env-package"
mkdir -p "$missing_env_source/deploy/env"
if DEPLOY_WRAPPER_LOG="$offline_deploy_log" bash "$latest_package_dir/deploy.sh" --reuse-from "$missing_env_source" docker --foo bar >"$TMP_DIR/reuse-missing-env.log" 2>&1; then
  fail "--reuse-from should require deploy/env/.env"
fi
grep -q 'deploy/env/.env' "$TMP_DIR/reuse-missing-env.log" || fail "missing reuse .env error should identify the required file"

if DEPLOY_WRAPPER_LOG="$offline_deploy_log" bash "$latest_package_dir/deploy.sh" --reuse-from "$TMP_DIR/does-not-exist" docker --foo bar >"$TMP_DIR/reuse-missing-dir.log" 2>&1; then
  fail "--reuse-from should reject a missing directory"
fi
grep -q 'does not exist or is not a directory' "$TMP_DIR/reuse-missing-dir.log" || fail "missing reuse directory error should be explicit"

if DEPLOY_WRAPPER_LOG="$offline_deploy_log" bash "$latest_package_dir/deploy.sh" --reuse-from "$latest_package_dir" docker --foo bar >"$TMP_DIR/reuse-same-dir.log" 2>&1; then
  fail "--reuse-from should reject the current package directory"
fi
grep -q 'must differ from the current package directory' "$TMP_DIR/reuse-same-dir.log" || fail "same-directory reuse error should be explicit"

if DEPLOY_WRAPPER_LOG="$offline_deploy_log" bash "$latest_package_dir/deploy.sh" --reuse-from "$reuse_source" >"$TMP_DIR/reuse-missing-target.log" 2>&1; then
  fail "--reuse-from should require a deployment target"
fi
grep -q 'requires a docker or k8s deployment target' "$TMP_DIR/reuse-missing-target.log" || fail "missing reuse target error should be explicit"

: > "$offline_deploy_log"
DEPLOY_WRAPPER_LOG="$offline_deploy_log" bash "$latest_package_dir/deploy.sh" docker --foo bar
grep -q '^deploy:defaults:true:docker --foo bar$' "$offline_deploy_log" || fail "offline deploy.sh should default to non-interactive defaults mode"

: > "$offline_deploy_log"
DEPLOY_WRAPPER_LOG="$offline_deploy_log" bash "$latest_package_dir/deploy.sh" docker --config --foo bar
grep -q '^deploy:tui:true:docker --foo bar$' "$offline_deploy_log" || fail "offline deploy.sh --config should enable TUI mode and propagate the offline marker"

: > "$offline_deploy_log"
DEPLOY_WRAPPER_LOG="$offline_deploy_log" bash "$latest_package_dir/deploy.sh" docker --defaults --foo bar
grep -q '^deploy:defaults:true:docker --foo bar$' "$offline_deploy_log" || fail "offline deploy.sh --defaults should preserve defaults mode and consume the flag"

: > "$offline_deploy_log"
DEPLOY_WRAPPER_LOG="$offline_deploy_log" bash "$latest_package_dir/deploy.sh" --load-images docker --foo bar
first_line="$(sed -n '1p' "$offline_deploy_log")"
second_line="$(sed -n '2p' "$offline_deploy_log")"
[ "$first_line" = "load-images" ] || fail "offline deploy.sh --load-images should load images before deploy"
[ "$second_line" = "deploy:defaults:true:docker --foo bar" ] || fail "offline deploy.sh --load-images should preserve defaults mode"

: > "$offline_deploy_log"
DEPLOY_WRAPPER_LOG="$offline_deploy_log" REGISTRY_USERNAME=user REGISTRY_PASSWORD=secret bash "$latest_package_dir/deploy.sh" --push-images --image-registry-prefix registry.local/nexent docker --foo bar
first_line="$(sed -n '1p' "$offline_deploy_log")"
second_line="$(sed -n '2p' "$offline_deploy_log")"
[[ "$first_line" == "push:secret:--image-registry-prefix registry.local/nexent --load-images" ]] || fail "offline deploy.sh --push-images should push before deploy"
[ "$second_line" = "deploy:defaults:true:docker --foo bar --image-registry-prefix registry.local/nexent" ] || fail "offline deploy.sh --push-images should preserve defaults mode and forward registry prefix"

[ -f "$OUT_DIR/nexent-offline-docker-amd64-latest.zip" ] || fail "zip package should be created for latest package"
grep -q "nexent/nexent:latest" "$latest_package_dir/manifest.yaml" || fail "manifest should include local latest Nexent image"
grep -q '^pull .*nexent/nexent:latest$' "$latest_pull_log" || fail "latest Nexent image should be pulled"
grep -q '^pull .*nexent/nexent-web:latest$' "$latest_pull_log" || fail "latest Nexent web image should be pulled"
grep -q '^pull .*nexent/nexent-mcp:latest$' "$latest_pull_log" || fail "latest Nexent MCP image should be pulled"
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
[ "$(cat "$local_package_dir/VERSION")" = "v2.2.0" ] || fail "root VERSION should match requested package version"
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
