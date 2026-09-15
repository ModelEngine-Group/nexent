#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT="$SCRIPT_DIR/../docker/backup.sh"
TEST_DIR="${TMPDIR:-/tmp}/nexent-docker-backup-test-$$"

cleanup() {
  rm -rf "$TEST_DIR"
}

trap cleanup EXIT

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

assert_contains() {
  local content="$1"
  local expected="$2"
  local message="$3"
  [[ "$content" == *"$expected"* ]] || fail "$message"
}

assert_not_contains() {
  local content="$1"
  local unexpected="$2"
  local message="$3"
  [[ "$content" != *"$unexpected"* ]] || fail "$message"
}

assert_file_exists() {
  [ -f "$1" ] || fail "$2"
}

mkdir -p "$TEST_DIR/bin" "$TEST_DIR/workspace/deploy/docker" "$TEST_DIR/workspace/deploy/env" "$TEST_DIR/root"
cp "$BACKUP_SCRIPT" "$TEST_DIR/workspace/deploy/docker/backup.sh"
printf 'ROOT_DIR="%s"\n' "$TEST_DIR/root" > "$TEST_DIR/workspace/deploy/env/.env"
printf 'root-data\n' > "$TEST_DIR/root/data.txt"

cat > "$TEST_DIR/bin/docker" <<'FAKE_DOCKER'
#!/usr/bin/env bash

set -euo pipefail

printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"

case "${1:-}" in
  info)
    exit 0
    ;;
  inspect)
    case "$*" in
      *'{{.State.Running}}'*) printf 'true\n' ;;
      *'{{.Config.Image}}'*) printf 'fake-backend:latest\n' ;;
      *) exit 1 ;;
    esac
    ;;
  image)
    [ "${2:-}" = "inspect" ] || exit 1
    ;;
  volume)
    [ "${2:-}" = "ls" ] || exit 1
    case "$*" in
      *'com.docker.compose.project=nexent'*)
        if [ "${FAKE_NO_VOLUMES:-0}" != "1" ]; then
          printf 'test-volume\n'
        fi
        ;;
    esac
    ;;
  run)
    case "$*" in
      *'--entrypoint du'*)
        printf '%s\t/source\n' "${FAKE_VOLUME_SIZE_KIB:-4}"
        ;;
      *'--entrypoint cp'*)
        [ "${FAKE_COPY_FAIL:-0}" != "1" ] || exit 9
        backup_mount=""
        for argument in "$@"; do
          case "$argument" in
            *:/backup) backup_mount="${argument%:/backup}" ;;
          esac
        done
        [ -n "$backup_mount" ] || exit 1
        mkdir -p "$backup_mount"
        printf 'volume-data\n' > "$backup_mount/volume.txt"
        ;;
      *)
        exit 1
        ;;
    esac
    ;;
  *)
    exit 1
    ;;
esac
FAKE_DOCKER
chmod +x "$TEST_DIR/bin/docker"

cat > "$TEST_DIR/bin/du" <<'FAKE_DU'
#!/usr/bin/env bash

set -euo pipefail

last_argument="${!#}"
printf '%s\t%s\n' "${FAKE_ROOT_SIZE_KIB:-8}" "$last_argument"
FAKE_DU
chmod +x "$TEST_DIR/bin/du"

cat > "$TEST_DIR/bin/df" <<'FAKE_DF'
#!/usr/bin/env bash

set -euo pipefail

printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\n'
printf 'fake 100000 1 %s 1%% /fake\n' "${FAKE_AVAILABLE_SIZE_KIB:-1000}"
FAKE_DF
chmod +x "$TEST_DIR/bin/df"

export PATH="$TEST_DIR/bin:$PATH"
export FAKE_DOCKER_LOG="$TEST_DIR/docker.log"

HELP_OUTPUT="$(bash "$TEST_DIR/workspace/deploy/docker/backup.sh" --help)"
assert_contains "$HELP_OUTPUT" "--backup-dir PATH" "help should document the backup directory"
assert_contains "$HELP_OUTPUT" "--confirm-writes-stopped" "help should document non-interactive confirmation"

if bash "$TEST_DIR/workspace/deploy/docker/backup.sh" > "$TEST_DIR/missing.out" 2>&1; then
  fail "missing --backup-dir should fail"
fi
assert_contains "$(cat "$TEST_DIR/missing.out")" "--backup-dir is required" "missing argument error should be explicit"

if bash "$TEST_DIR/workspace/deploy/docker/backup.sh" --unknown \
  > "$TEST_DIR/unknown.out" 2>&1; then
  fail "unknown option should fail"
fi
assert_contains "$(cat "$TEST_DIR/unknown.out")" "Unknown option: --unknown" "unknown option error should be explicit"

if bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
  --backup-dir "$TEST_DIR/root/backup" --confirm-writes-stopped \
  > "$TEST_DIR/nested.out" 2>&1; then
  fail "backup directory under ROOT_DIR should fail"
fi
assert_contains "$(cat "$TEST_DIR/nested.out")" "must be outside ROOT_DIR" "nested backup path should be rejected"

: > "$FAKE_DOCKER_LOG"
mkdir -p "$TEST_DIR/insufficient"
if FAKE_ROOT_SIZE_KIB=100 FAKE_VOLUME_SIZE_KIB=10 FAKE_AVAILABLE_SIZE_KIB=50 \
  bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
    --backup-dir "$TEST_DIR/insufficient" --confirm-writes-stopped \
    > "$TEST_DIR/insufficient.out" 2>&1; then
  fail "insufficient space should fail"
fi
INSUFFICIENT_OUTPUT="$(cat "$TEST_DIR/insufficient.out")"
assert_contains "$INSUFFICIENT_OUTPUT" "[ERROR] Insufficient space" "space failure should be logged"
assert_not_contains "$(cat "$FAKE_DOCKER_LOG")" "--entrypoint cp" "space failure must occur before copying"

: > "$FAKE_DOCKER_LOG"
mkdir -p "$TEST_DIR/unconfirmed"
if bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
  --backup-dir "$TEST_DIR/unconfirmed" > "$TEST_DIR/unconfirmed.out" 2>&1; then
  fail "non-interactive backup without confirmation should fail"
fi
UNCONFIRMED_OUTPUT="$(cat "$TEST_DIR/unconfirmed.out")"
assert_contains "$UNCONFIRMED_OUTPUT" "[WARN] Stop user actions" "business-write warning should be visible"
assert_contains "$UNCONFIRMED_OUTPUT" "requires --confirm-writes-stopped" "non-interactive failure should explain confirmation"
assert_not_contains "$(cat "$FAKE_DOCKER_LOG")" "--entrypoint cp" "unconfirmed backup must not copy"

: > "$FAKE_DOCKER_LOG"
mkdir -p "$TEST_DIR/success"
SUCCESS_OUTPUT="$(bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
  --backup-dir "$TEST_DIR/success" --confirm-writes-stopped 2>&1)"
FINAL_BACKUP_DIR="$(find "$TEST_DIR/success" -mindepth 1 -maxdepth 1 -type d -name 'docker-*' | head -n 1)"
[ -n "$FINAL_BACKUP_DIR" ] || fail "successful backup should create a final directory"
assert_file_exists "$FINAL_BACKUP_DIR/root-dir/data.txt" "ROOT_DIR file should be copied"
assert_file_exists "$FINAL_BACKUP_DIR/volumes/test-volume/volume.txt" "named volume file should be copied"
assert_contains "$SUCCESS_OUTPUT" "[PASS] Pre-upgrade space check passed" "space check should pass before copying"
assert_contains "$SUCCESS_OUTPUT" "[PASS] Backup complete:" "success log should include the final path"
assert_not_contains "$(cat "$FAKE_DOCKER_LOG")" " stop" "backup must not stop containers"
assert_not_contains "$(cat "$FAKE_DOCKER_LOG")" " down" "backup must not run compose down"
if find "$FINAL_BACKUP_DIR" -type f \( -name '*.tar' -o -name '*.gz' -o -name '*.zip' -o -name '*.sha256' \) | grep -q .; then
  fail "successful backup should not create archives or checksum files"
fi

: > "$FAKE_DOCKER_LOG"
mkdir -p "$TEST_DIR/no-volumes"
NO_VOLUMES_OUTPUT="$(FAKE_NO_VOLUMES=1 bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
  --backup-dir "$TEST_DIR/no-volumes" --confirm-writes-stopped 2>&1)"
assert_contains "$NO_VOLUMES_OUTPUT" "Docker named volumes: none" "empty volume set should be reported"
NO_VOLUMES_BACKUP="$(find "$TEST_DIR/no-volumes" -mindepth 1 -maxdepth 1 -type d -name 'docker-*' | head -n 1)"
assert_file_exists "$NO_VOLUMES_BACKUP/root-dir/data.txt" "ROOT_DIR should be copied without named volumes"

: > "$FAKE_DOCKER_LOG"
mkdir -p "$TEST_DIR/copy-failure"
if FAKE_COPY_FAIL=1 bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
  --backup-dir "$TEST_DIR/copy-failure" --confirm-writes-stopped \
  > "$TEST_DIR/copy-failure.out" 2>&1; then
  fail "named volume copy failure should fail"
fi
COPY_FAILURE_OUTPUT="$(cat "$TEST_DIR/copy-failure.out")"
assert_contains "$COPY_FAILURE_OUTPUT" "Failed to copy Docker volume: test-volume" "copy failure should name the volume"
assert_contains "$COPY_FAILURE_OUTPUT" "Backup is incomplete" "copy failure should identify the partial backup"
if find "$TEST_DIR/copy-failure" -mindepth 1 -maxdepth 1 -type d -name 'docker-*' ! -name '*.partial' | grep -q .; then
  fail "copy failure should not create a final backup directory"
fi

SCRIPT_CONTENT="$(cat "$BACKUP_SCRIPT")"
assert_not_contains "$SCRIPT_CONTENT" "sudo " "backup script must not use sudo"
assert_not_contains "$SCRIPT_CONTENT" "tar " "backup script must not create tar archives"
assert_not_contains "$SCRIPT_CONTENT" "sha256" "backup script must not create SHA-256 files"

printf 'PASS: Docker pre-upgrade backup script tests completed successfully.\n'
