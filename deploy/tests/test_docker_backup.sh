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

assert_path_not_exists() {
  [ ! -e "$1" ] || fail "$2"
}

mkdir -p \
  "$TEST_DIR/bin" \
  "$TEST_DIR/workspace/deploy/docker" \
  "$TEST_DIR/workspace/deploy/env" \
  "$TEST_DIR/root" \
  "$TEST_DIR/nexent-user"
cp "$BACKUP_SCRIPT" "$TEST_DIR/workspace/deploy/docker/backup.sh"
{
  printf 'ROOT_DIR="%s"\n' "$TEST_DIR/root"
  printf 'NEXENT_USER_DIR="%s"\n' "$TEST_DIR/nexent-user"
} > "$TEST_DIR/workspace/deploy/env/.env"
printf 'root-data\n' > "$TEST_DIR/root/data.txt"
printf 'user-data\n' > "$TEST_DIR/nexent-user/user-data.txt"
NEXENT_USER_DIR_REAL="$(cd "$TEST_DIR/nexent-user" && pwd -P)"

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
          printf '%s\n' "${FAKE_VOLUME_NAME:-test-volume}"
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
if [ "$last_argument" = "$FAKE_NEXENT_USER_DIR" ]; then
  size_kib="${FAKE_USER_SIZE_KIB:-6}"
else
  size_kib="${FAKE_ROOT_SIZE_KIB:-8}"
fi
printf '%s\t%s\n' "$size_kib" "$last_argument"
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
export FAKE_NEXENT_USER_DIR="$NEXENT_USER_DIR_REAL"

HELP_OUTPUT="$(bash "$TEST_DIR/workspace/deploy/docker/backup.sh" --help)"
assert_contains "$HELP_OUTPUT" "--backup-dir PATH" "help should document the backup directory"
assert_not_contains "$HELP_OUTPUT" "--confirm-writes-stopped" "help should not expose a write-confirmation option"

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
  --backup-dir "$TEST_DIR/removed-option" --confirm-writes-stopped \
  > "$TEST_DIR/removed-option.out" 2>&1; then
  fail "removed --confirm-writes-stopped option should fail"
fi
assert_contains \
  "$(cat "$TEST_DIR/removed-option.out")" \
  "Unknown option: --confirm-writes-stopped" \
  "removed confirmation option should be reported as unknown"

if bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
  --backup-dir "$TEST_DIR/root/backup" \
  > "$TEST_DIR/nested.out" 2>&1; then
  fail "backup directory under ROOT_DIR should fail"
fi
assert_contains "$(cat "$TEST_DIR/nested.out")" "must be outside ROOT_DIR" "nested backup path should be rejected"

if bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
  --backup-dir "$TEST_DIR/nexent-user/backup" \
  > "$TEST_DIR/nested-user.out" 2>&1; then
  fail "backup directory under NEXENT_USER_DIR should fail"
fi
assert_contains \
  "$(cat "$TEST_DIR/nested-user.out")" \
  "must be outside NEXENT_USER_DIR" \
  "backup path under NEXENT_USER_DIR should be rejected"

mkdir -p "$TEST_DIR/collision/source-a/shared" "$TEST_DIR/collision/source-b/shared" "$TEST_DIR/collision/backup"
{
  printf 'ROOT_DIR="%s"\n' "$TEST_DIR/collision/source-a/shared"
  printf 'NEXENT_USER_DIR="%s"\n' "$TEST_DIR/collision/source-b/shared"
} > "$TEST_DIR/collision.env"
if NEXENT_BACKUP_ENV_FILE="$TEST_DIR/collision.env" \
  bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
    --backup-dir "$TEST_DIR/collision/backup" \
    > "$TEST_DIR/collision.out" 2>&1; then
  fail "matching source basenames should fail"
fi
assert_contains \
  "$(cat "$TEST_DIR/collision.out")" \
  "Backup source names collide: shared" \
  "matching source basenames should report the conflicting name"

mkdir -p "$TEST_DIR/volume-collision"
if FAKE_VOLUME_NAME=root bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
  --backup-dir "$TEST_DIR/volume-collision" \
  > "$TEST_DIR/volume-collision.out" 2>&1; then
  fail "volume name matching a source basename should fail"
fi
assert_contains \
  "$(cat "$TEST_DIR/volume-collision.out")" \
  "Backup source names collide: root" \
  "volume collision should report the conflicting name"

: > "$FAKE_DOCKER_LOG"
mkdir -p "$TEST_DIR/insufficient"
if FAKE_ROOT_SIZE_KIB=100 FAKE_VOLUME_SIZE_KIB=10 FAKE_AVAILABLE_SIZE_KIB=50 \
  bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
    --backup-dir "$TEST_DIR/insufficient" \
    > "$TEST_DIR/insufficient.out" 2>&1; then
  fail "insufficient space should fail"
fi
INSUFFICIENT_OUTPUT="$(cat "$TEST_DIR/insufficient.out")"
assert_contains "$INSUFFICIENT_OUTPUT" "[ERROR] Insufficient space" "space failure should be logged"
assert_not_contains "$(cat "$FAKE_DOCKER_LOG")" "--entrypoint cp" "space failure must occur before copying"

: > "$FAKE_DOCKER_LOG"
mkdir -p "$TEST_DIR/user-space-boundary"
if FAKE_ROOT_SIZE_KIB=100 FAKE_USER_SIZE_KIB=40 FAKE_VOLUME_SIZE_KIB=10 FAKE_AVAILABLE_SIZE_KIB=120 \
  bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
    --backup-dir "$TEST_DIR/user-space-boundary" \
    > "$TEST_DIR/user-space-boundary.out" 2>&1; then
  fail "space check should include NEXENT_USER_DIR"
fi
USER_SPACE_OUTPUT="$(cat "$TEST_DIR/user-space-boundary.out")"
assert_contains "$USER_SPACE_OUTPUT" "NEXENT_USER_DIR size" "user directory size should be logged"
assert_contains "$USER_SPACE_OUTPUT" "150 KiB required" "total size should include NEXENT_USER_DIR"
assert_not_contains "$(cat "$FAKE_DOCKER_LOG")" "--entrypoint cp" "user directory space failure must occur before copying"

: > "$FAKE_DOCKER_LOG"
mkdir -p "$TEST_DIR/success"
SUCCESS_OUTPUT="$(bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
  --backup-dir "$TEST_DIR/success" 2>&1)"
FINAL_BACKUP_DIR="$(find "$TEST_DIR/success" -mindepth 1 -maxdepth 1 -type d -name 'docker-*' | head -n 1)"
[ -n "$FINAL_BACKUP_DIR" ] || fail "successful backup should create a final directory"
assert_file_exists "$FINAL_BACKUP_DIR/root/data.txt" "ROOT_DIR file should use its original directory name"
assert_file_exists \
  "$FINAL_BACKUP_DIR/nexent-user/user-data.txt" \
  "NEXENT_USER_DIR file should use its original directory name"
assert_file_exists "$FINAL_BACKUP_DIR/test-volume/volume.txt" "named volume should use its original name"
assert_path_not_exists "$FINAL_BACKUP_DIR/root-dir" "generic root-dir wrapper should not be created"
assert_path_not_exists \
  "$FINAL_BACKUP_DIR/nexent-user-dir" \
  "generic nexent-user-dir wrapper should not be created"
assert_path_not_exists "$FINAL_BACKUP_DIR/volumes" "generic volumes wrapper should not be created"
assert_contains "$SUCCESS_OUTPUT" "Persistent user directory: $NEXENT_USER_DIR_REAL" "NEXENT_USER_DIR should be logged"
assert_contains "$SUCCESS_OUTPUT" "NEXENT_USER_DIR size" "NEXENT_USER_DIR size should be logged"
assert_contains "$SUCCESS_OUTPUT" "[PASS] Pre-upgrade space check passed" "space check should pass before copying"
assert_contains "$SUCCESS_OUTPUT" "[WARN] Stop user actions" "business-write warning should remain visible"
assert_not_contains "$SUCCESS_OUTPUT" "Have all business writes stopped" "backup should not prompt for input"
assert_contains "$SUCCESS_OUTPUT" "[PASS] Backup complete:" "success log should include the final path"
assert_not_contains "$(cat "$FAKE_DOCKER_LOG")" " stop" "backup must not stop containers"
assert_not_contains "$(cat "$FAKE_DOCKER_LOG")" " down" "backup must not run compose down"
if find "$FINAL_BACKUP_DIR" -type f \( -name '*.tar' -o -name '*.gz' -o -name '*.zip' -o -name '*.sha256' \) | grep -q .; then
  fail "successful backup should not create archives or checksum files"
fi

: > "$FAKE_DOCKER_LOG"
mkdir -p "$TEST_DIR/no-volumes"
NO_VOLUMES_OUTPUT="$(FAKE_NO_VOLUMES=1 bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
  --backup-dir "$TEST_DIR/no-volumes" 2>&1)"
assert_contains "$NO_VOLUMES_OUTPUT" "Docker named volumes: none" "empty volume set should be reported"
NO_VOLUMES_BACKUP="$(find "$TEST_DIR/no-volumes" -mindepth 1 -maxdepth 1 -type d -name 'docker-*' | head -n 1)"
assert_file_exists "$NO_VOLUMES_BACKUP/root/data.txt" "ROOT_DIR should be copied without named volumes"
assert_file_exists \
  "$NO_VOLUMES_BACKUP/nexent-user/user-data.txt" \
  "NEXENT_USER_DIR should be copied without named volumes"

mkdir -p "$TEST_DIR/default-root" "$TEST_DIR/default-home/nexent" "$TEST_DIR/default-user-dir"
printf 'default-root-data\n' > "$TEST_DIR/default-root/data.txt"
printf 'default-user-data\n' > "$TEST_DIR/default-home/nexent/data.txt"
printf 'ROOT_DIR="%s"\n' "$TEST_DIR/default-root" > "$TEST_DIR/default.env"
DEFAULT_NEXENT_USER_DIR_REAL="$(cd "$TEST_DIR/default-home/nexent" && pwd -P)"
DEFAULT_OUTPUT="$(
  HOME="$TEST_DIR/default-home" \
  NEXENT_BACKUP_ENV_FILE="$TEST_DIR/default.env" \
  FAKE_NEXENT_USER_DIR="$DEFAULT_NEXENT_USER_DIR_REAL" \
  FAKE_NO_VOLUMES=1 \
  bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
    --backup-dir "$TEST_DIR/default-user-dir" 2>&1
)"
DEFAULT_BACKUP="$(find "$TEST_DIR/default-user-dir" -mindepth 1 -maxdepth 1 -type d -name 'docker-*' | head -n 1)"
assert_file_exists \
  "$DEFAULT_BACKUP/nexent/data.txt" \
  "unset NEXENT_USER_DIR should default to HOME/nexent"
assert_file_exists \
  "$DEFAULT_BACKUP/default-root/data.txt" \
  "ROOT_DIR should retain its original name with a default user directory"
assert_contains \
  "$DEFAULT_OUTPUT" \
  "Persistent user directory: $DEFAULT_NEXENT_USER_DIR_REAL" \
  "default NEXENT_USER_DIR should be logged"

: > "$FAKE_DOCKER_LOG"
mkdir -p "$TEST_DIR/copy-failure"
if FAKE_COPY_FAIL=1 bash "$TEST_DIR/workspace/deploy/docker/backup.sh" \
  --backup-dir "$TEST_DIR/copy-failure" \
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
assert_not_contains "$SCRIPT_CONTENT" "Have all business writes stopped" "backup script must not prompt for confirmation"
assert_not_contains "$SCRIPT_CONTENT" "--confirm-writes-stopped" "backup script must not require a confirmation option"

printf 'PASS: Docker pre-upgrade backup script tests completed successfully.\n'
