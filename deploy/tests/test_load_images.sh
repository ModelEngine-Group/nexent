#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOAD_SCRIPT="$SCRIPT_DIR/../offline/load-images.sh"
TMP_DIR="${TMPDIR:-/tmp}/nexent-load-images-test-$$"
trap 'rm -rf "$TMP_DIR"' EXIT
mkdir -p "$TMP_DIR/package/images" "$TMP_DIR/bin"
cp "$LOAD_SCRIPT" "$TMP_DIR/package/load-images.sh"
: > "$TMP_DIR/package/images/nexent.tar"

fail() { echo "FAIL: $*"; exit 1; }

cat > "$TMP_DIR/bin/docker" <<'SH'
#!/usr/bin/env bash
printf 'docker:%s\n' "$*" >> "$IMAGE_LOADER_LOG"
SH
cat > "$TMP_DIR/bin/ctr" <<'SH'
#!/usr/bin/env bash
printf 'ctr:%s\n' "$*" >> "$IMAGE_LOADER_LOG"
if [ "${FAKE_CTR_FAIL_IMPORT:-false}" = "true" ] && [ "$4" = "import" ]; then
  exit 42
fi
SH
chmod +x "$TMP_DIR/bin/docker" "$TMP_DIR/bin/ctr"

: > "$TMP_DIR/loader.log"
PATH="$TMP_DIR/bin:/usr/bin:/bin" IMAGE_LOADER_LOG="$TMP_DIR/loader.log" bash "$TMP_DIR/package/load-images.sh" k8s >/dev/null
grep -Fq 'ctr:-n k8s.io images import' "$TMP_DIR/loader.log" || fail "K8s loading should import with ctr in k8s.io"
! grep -Fq 'docker:' "$TMP_DIR/loader.log" || fail "K8s loading should prefer ctr"

: > "$TMP_DIR/loader.log"
if PATH="$TMP_DIR/bin:/usr/bin:/bin" IMAGE_LOADER_LOG="$TMP_DIR/loader.log" FAKE_CTR_FAIL_IMPORT=true bash "$TMP_DIR/package/load-images.sh" k8s >/dev/null 2>&1; then
  fail "a failing ctr import should fail image loading"
fi
! grep -Fq 'docker:' "$TMP_DIR/loader.log" || fail "a failing ctr import should not fall back to Docker"

rm "$TMP_DIR/bin/ctr"
: > "$TMP_DIR/loader.log"
PATH="$TMP_DIR/bin:/usr/bin:/bin" IMAGE_LOADER_LOG="$TMP_DIR/loader.log" bash "$TMP_DIR/package/load-images.sh" k8s >/dev/null 2>"$TMP_DIR/fallback.log"
grep -Fq 'docker:load -i' "$TMP_DIR/loader.log" || fail "missing ctr should fall back to Docker"
grep -Fq 'falling back to Docker' "$TMP_DIR/fallback.log" || fail "Docker fallback should be visible"

: > "$TMP_DIR/loader.log"
PATH="$TMP_DIR/bin:/usr/bin:/bin" IMAGE_LOADER_LOG="$TMP_DIR/loader.log" bash "$TMP_DIR/package/load-images.sh" docker >/dev/null
grep -Fq 'docker:load -i' "$TMP_DIR/loader.log" || fail "Docker target should use Docker"

echo "Offline image loader tests passed."
