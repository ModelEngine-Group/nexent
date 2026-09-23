#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKFLOW="$PROJECT_ROOT/.github/workflows/docker-deploy.yml"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nexent-ci-deploy-test.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT
mkdir -p "$TMP_DIR/bin" "$TMP_DIR/project"
export CI_TEST_PROJECT="$TMP_DIR/project" CI_TEST_LOG="$TMP_DIR/commands.log"
export CI_TEST_COMMON="$PROJECT_ROOT/deploy/common/common.sh"
export CI_TEST_IMAGE_SOURCE="$PROJECT_ROOT/deploy/env/image-source.general.env"
export DEPLOYMENT_LANG=en

fail() { echo "FAIL: $*" >&2; exit 1; }

extract_step() {
  awk -v title="$1" '
    /^      - name:/ { selected = index($0, "- name: " title) > 0; in_run = 0 }
    selected && /^        run: \|/ { in_run = 1; next }
    selected && in_run { sub(/^          /, ""); print }
  ' "$WORKFLOW" | sed 's|\$HOME/nexent|$CI_TEST_PROJECT|g; s/${{ secrets\.[A-Z_]* }}/test-secret/g'
}

cat > "$TMP_DIR/bin/docker" <<'SH'
#!/usr/bin/env bash
printf 'docker:%s\n' "$*" >> "$CI_TEST_LOG"
if [ "$1 $2" = 'image inspect' ] && [ "$3" = "${CI_TEST_MISSING_IMAGE:-}" ]; then
  exit 1
fi
SH
cat > "$TMP_DIR/bin/cp" <<'SH'
#!/usr/bin/env bash
exit 0
SH
cat > "$TMP_DIR/bin/sed" <<'SH'
#!/usr/bin/env bash
exit 0
SH
cat > "$TMP_DIR/project/deploy.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'deploy:%s\n' "$*" >> "$CI_TEST_LOG"
source "$CI_TEST_COMMON"
deployment_prepare_config "$@" --local-config "$CI_TEST_PROJECT/absent.yaml"
export APP_VERSION="$DEPLOYMENT_APP_VERSION"
source "$CI_TEST_IMAGE_SOURCE"
deployment_apply_image_source
printf 'resolved:%s:%s:%s:%s:%s:%s:%s\n' "$DEPLOYMENT_PORT_POLICY" "$DEPLOYMENT_COMPONENTS" \
  "$NEXENT_IMAGE" "$NEXENT_WEB_IMAGE" "$NEXENT_DATA_PROCESS_IMAGE" \
  "$NEXENT_MCP_DOCKER_IMAGE" "$NEXENT_SANDBOX_IMAGE" >> "$CI_TEST_LOG"
SH
chmod +x "$TMP_DIR/bin/"* "$TMP_DIR/project/deploy.sh"

# DEPLOY-CI-001: the workflow must use its input tag without rewriting production scripts.
! grep -q 'Force APP_VERSION\|--version 2' "$WORKFLOW" || fail "workflow still overrides the input version"
grep -Fq 'APP_VERSION: ${{ inputs.app_version }}' "$WORKFLOW" || fail "workflow must export the input version"
extract_step 'Verify local application images' > "$TMP_DIR/check.sh"
extract_step 'Start docs container' > "$TMP_DIR/docs.sh"
extract_step 'Deploy with deploy.sh' > "$TMP_DIR/deploy.sh"
for step in check docs deploy; do
  [ -s "$TMP_DIR/$step.sh" ] || fail "missing executable $step step"
done

for version in latest v2.6.0 feature-ci.123; do
  for mode in development production; do
    : > "$CI_TEST_LOG"
    for step in check docs deploy; do
      PATH="$TMP_DIR/bin:$PATH" APP_VERSION="$version" DEPLOYMENT_MODE="$mode" \
        bash -e "$TMP_DIR/$step.sh"
    done
    for name in nexent nexent-web nexent-data-process nexent-mcp nexent-sandbox nexent-docs; do
      grep -Fqx "docker:image inspect nexent/$name:$version" "$CI_TEST_LOG" || fail "missing preflight for $name:$version"
    done
    grep -Fqx "docker:run -d --name nexent-docs -p 4173:4173 nexent/nexent-docs:$version" "$CI_TEST_LOG" || fail "docs must use the input tag"
    grep -Fqx "resolved:$mode:infrastructure,application,data-process,supabase:nexent/nexent:$version:nexent/nexent-web:$version:nexent/nexent-data-process:$version:nexent/nexent-mcp:$version:nexent/nexent-sandbox:$version" "$CI_TEST_LOG" || fail "resolved deployment configuration must retain version, components and mode"
    grep -Fq -- "--root-dir $CI_TEST_PROJECT-$mode-data" "$CI_TEST_LOG" || fail "mode-specific data directory must be preserved"
    grep -Fq -- '--defaults docker' "$CI_TEST_LOG" || fail "CI must skip interactive configuration"
  done
done

# DEPLOY-CI-002: a missing local image fails before deployment and names the image.
: > "$CI_TEST_LOG"
if PATH="$TMP_DIR/bin:$PATH" APP_VERSION=v2.6.0 CI_TEST_MISSING_IMAGE=nexent/nexent-web:v2.6.0 \
  bash -e "$TMP_DIR/check.sh" > "$TMP_DIR/missing.log" 2>&1; then
  fail "missing image must fail preflight"
fi
grep -Fq 'nexent/nexent-web:v2.6.0' "$TMP_DIR/missing.log" || fail "preflight must identify the missing image"
! grep -q 'docker:stop\|docker:run\|deploy:' "$CI_TEST_LOG" || fail "preflight must not mutate containers"

echo "Docker deployment workflow tests passed (six version/mode combinations and missing image)."
