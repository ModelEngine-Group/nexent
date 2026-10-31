#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT="$SCRIPT_DIR/../k8s/backup.sh"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZH_GUIDE="$PROJECT_ROOT/doc/docs/zh/quick-start/kubernetes-upgrade-guide.md"
EN_GUIDE="$PROJECT_ROOT/doc/docs/en/quick-start/kubernetes-upgrade-guide.md"
TEST_DIR="${TMPDIR:-/tmp}/nexent-k8s-backup-test-$$"

cleanup() {
  if [ "${KEEP_TEST_DIR:-0}" = "1" ]; then
    printf 'Test artifacts retained at %s\n' "$TEST_DIR" >&2
  else
    rm -rf "$TEST_DIR"
  fi
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

assert_no_copy_calls() {
  local log_file="$1"
  local message="$2"
  if grep -Eq '(^| )cp( |$)|(^| )tar -C ' "$log_file"; then
    fail "$message"
  fi
}

[ -f "$BACKUP_SCRIPT" ] || fail "Kubernetes backup script is missing: $BACKUP_SCRIPT"

mkdir -p \
  "$TEST_DIR/bin" \
  "$TEST_DIR/workspace/deploy/k8s" \
  "$TEST_DIR/remote/nexent-postgresql" \
  "$TEST_DIR/remote/nexent-workspace/nested"
cp "$BACKUP_SCRIPT" "$TEST_DIR/workspace/deploy/k8s/backup.sh"
printf 'postgres-data\n' > "$TEST_DIR/remote/nexent-postgresql/data.txt"
printf 'workspace-data\n' > "$TEST_DIR/remote/nexent-workspace/workspace.txt"
printf 'nested-data\n' > "$TEST_DIR/remote/nexent-workspace/nested/file with space.txt"
printf 'hidden-data\n' > "$TEST_DIR/remote/nexent-workspace/.hidden"
ln -s workspace.txt "$TEST_DIR/remote/nexent-workspace/workspace-link"

REAL_TAR="$(command -v tar)"

cat > "$TEST_DIR/bin/kubectl" <<'FAKE_KUBECTL'
#!/usr/bin/env bash

set -euo pipefail

printf '%s\n' "$*" >> "$FAKE_KUBECTL_LOG"

remote_pvc_for_path() {
  case "$1" in
    /var/lib/postgresql/data*|database-0:/var/lib/postgresql/data/*)
      printf 'nexent-postgresql\n'
      ;;
    /mnt/nexent*|runtime-0:/mnt/nexent/*)
      printf 'nexent-workspace\n'
      ;;
    *)
      return 1
      ;;
  esac
}

case "${1:-}" in
  version)
    exit 0
    ;;
  get)
    case "${2:-}" in
      namespace)
        [ "${FAKE_NAMESPACE_MISSING:-0}" != "1" ]
        ;;
      pvc)
        if [ "${FAKE_NO_PVCS:-0}" = "1" ]; then
          exit 0
        fi
        if [ "${FAKE_UNBOUND:-0}" = "1" ]; then
          printf 'nexent-postgresql\tPending\n'
        else
          printf 'nexent-postgresql\tBound\n'
        fi
        printf 'nexent-workspace\tBound\n'
        if [ "${FAKE_EXTRA_UNMOUNTED:-0}" = "1" ]; then
          printf 'nexent-orphan\tBound\n'
        fi
        ;;
      pods)
        printf 'database-0\nruntime-0\n'
        ;;
      pod)
        pod="${3:-}"
        case "$*" in
          *'.spec.volumes'*)
            case "$pod" in
              database-0) printf 'database-data\tnexent-postgresql\n' ;;
              runtime-0) printf 'workspace-data\tnexent-workspace\n' ;;
              *) exit 1 ;;
            esac
            ;;
          *'.spec.containers'*)
            case "$pod" in
              database-0)
                printf 'postgresql\tdatabase-data|/var/lib/postgresql/data||;\n'
                ;;
              runtime-0)
                if [ "${FAKE_SUBPATH_ONLY:-0}" = "1" ]; then
                  printf 'nexent-runtime\tworkspace-data|/mnt/nexent|tenant-a|;\n'
                else
                  printf 'nexent-runtime\tworkspace-data|/mnt/nexent||;\n'
                fi
                ;;
              *) exit 1 ;;
            esac
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
    ;;
  exec)
    if [[ " $* " == *" du "* ]]; then
      if [[ " $* " == *" --apparent-size "* ]] && [ "${FAKE_APPARENT_SIZE_UNSUPPORTED:-0}" = "1" ]; then
        exit 1
      fi
      case "${!#}" in
        /var/lib/postgresql/data) printf '%s\t%s\n' "${FAKE_DATABASE_SIZE_KIB:-8}" "${!#}" ;;
        /mnt/nexent) printf '%s\t%s\n' "${FAKE_WORKSPACE_SIZE_KIB:-6}" "${!#}" ;;
        *) exit 1 ;;
      esac
      exit 0
    fi

    if [[ " $* " == *" sh -c "* ]] && [[ " $* " == *"command -v tar"* ]]; then
      [ "${FAKE_TAR_MISSING:-0}" != "1" ]
      exit
    fi

    if [[ " $* " == *" tar -C "* ]]; then
      [ "${FAKE_TAR_FAIL:-0}" != "1" ] || exit 19
      previous=""
      source_path=""
      for argument in "$@"; do
        if [ "$previous" = "-C" ]; then
          source_path="$argument"
          break
        fi
        previous="$argument"
      done
      pvc="$(remote_pvc_for_path "$source_path")"
      exec "$REAL_TAR" -C "$FAKE_REMOTE_ROOT/$pvc" -cf - .
    fi

    if [[ " $* " == *" bash -c "* ]]; then
      [ "${FAKE_PORTABLE_FAIL:-0}" != "1" ] || exit 23
      source_path="${!#}"
      pvc="$(remote_pvc_for_path "$source_path")"
      while IFS= read -r path; do
        relative_path="${path#"$FAKE_REMOTE_ROOT/$pvc"/}"
        encoded_path="$(printf '%s' "$relative_path" | base64 | tr -d '\n')"
        if [ -L "$path" ]; then
          link_target="$(readlink "$path")"
          encoded_target="$(printf '%s' "$link_target" | base64 | tr -d '\n')"
          printf 'l\t%s\t777\t%s\n' "$encoded_path" "$encoded_target"
        elif [ -d "$path" ]; then
          printf 'd\t%s\t755\t-\n' "$encoded_path"
        else
          printf 'f\t%s\t644\t-\n' "$encoded_path"
        fi
      done < <(find "$FAKE_REMOTE_ROOT/$pvc" -mindepth 1 -print)
      exit 0
    fi

    if [[ " $* " == *" cat "* ]]; then
      source_file="${!#}"
      pvc="$(remote_pvc_for_path "$source_file")"
      case "$pvc" in
        nexent-postgresql) relative_file="${source_file#/var/lib/postgresql/data/}" ;;
        nexent-workspace) relative_file="${source_file#/mnt/nexent/}" ;;
        *) exit 1 ;;
      esac
      exec /bin/cat "$FAKE_REMOTE_ROOT/$pvc/$relative_file"
    fi
    exit 1
    ;;
  cp)
    source_path=""
    for argument in "$@"; do
      case "$argument" in
        *:/*) source_path="$argument" ;;
      esac
    done
    pvc="$(remote_pvc_for_path "$source_path")"
    if [ "${FAKE_CP_FAIL:-0}" = "1" ] || [ "${FAKE_CP_FAIL_PVC:-}" = "$pvc" ]; then
      exit 17
    fi
    target="${!#}"
    mkdir -p "$target"
    cp -R "$FAKE_REMOTE_ROOT/$pvc/." "$target/"
    ;;
  *)
    exit 1
    ;;
esac
FAKE_KUBECTL
chmod +x "$TEST_DIR/bin/kubectl"

cat > "$TEST_DIR/bin/df" <<'FAKE_DF'
#!/usr/bin/env bash

set -euo pipefail

printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\n'
printf 'fake 100000 1 %s 1%% /fake\n' "${FAKE_AVAILABLE_SIZE_KIB:-1000}"
FAKE_DF
chmod +x "$TEST_DIR/bin/df"

export PATH="$TEST_DIR/bin:$PATH"
export FAKE_KUBECTL_LOG="$TEST_DIR/kubectl.log"
export FAKE_REMOTE_ROOT="$TEST_DIR/remote"
export REAL_TAR

HELP_OUTPUT="$(bash "$TEST_DIR/workspace/deploy/k8s/backup.sh" --help)"
assert_contains "$HELP_OUTPUT" "--backup-dir PATH" "help should document the backup directory"
assert_contains "$HELP_OUTPUT" "--namespace NAME" "help should document the namespace"
assert_not_contains "$HELP_OUTPUT" "confirm" "help should not expose an interactive confirmation"

if bash "$TEST_DIR/workspace/deploy/k8s/backup.sh" > "$TEST_DIR/missing.out" 2>&1; then
  fail "missing --backup-dir should fail"
fi
assert_contains "$(cat "$TEST_DIR/missing.out")" "--backup-dir is required" "missing argument should be explicit"

if bash "$TEST_DIR/workspace/deploy/k8s/backup.sh" --unknown \
  > "$TEST_DIR/unknown.out" 2>&1; then
  fail "unknown option should fail"
fi
assert_contains "$(cat "$TEST_DIR/unknown.out")" "Unknown option: --unknown" "unknown option should be explicit"

if FAKE_NAMESPACE_MISSING=1 bash "$TEST_DIR/workspace/deploy/k8s/backup.sh" \
  --backup-dir "$TEST_DIR/missing-namespace" --namespace absent \
  > "$TEST_DIR/missing-namespace.out" 2>&1; then
  fail "an inaccessible namespace should fail"
fi
assert_contains \
  "$(cat "$TEST_DIR/missing-namespace.out")" \
  "Cannot access Kubernetes namespace: absent" \
  "namespace failure should name the namespace"

: > "$FAKE_KUBECTL_LOG"
if FAKE_UNBOUND=1 bash "$TEST_DIR/workspace/deploy/k8s/backup.sh" \
  --backup-dir "$TEST_DIR/unbound" \
  > "$TEST_DIR/unbound.out" 2>&1; then
  fail "an unbound PVC should fail"
fi
assert_contains "$(cat "$TEST_DIR/unbound.out")" "PVC is not Bound: nexent-postgresql" "unbound error should name the PVC"
assert_no_copy_calls "$FAKE_KUBECTL_LOG" "an unbound PVC must fail before copying"

: > "$FAKE_KUBECTL_LOG"
if FAKE_EXTRA_UNMOUNTED=1 bash "$TEST_DIR/workspace/deploy/k8s/backup.sh" \
  --backup-dir "$TEST_DIR/unmounted" \
  > "$TEST_DIR/unmounted.out" 2>&1; then
  fail "an unmounted PVC should fail"
fi
assert_contains \
  "$(cat "$TEST_DIR/unmounted.out")" \
  "No running container fully mounts PVC: nexent-orphan" \
  "unmounted error should name the PVC"
assert_no_copy_calls "$FAKE_KUBECTL_LOG" "an unmounted PVC must fail before copying"

: > "$FAKE_KUBECTL_LOG"
if FAKE_SUBPATH_ONLY=1 bash "$TEST_DIR/workspace/deploy/k8s/backup.sh" \
  --backup-dir "$TEST_DIR/subpath" \
  > "$TEST_DIR/subpath.out" 2>&1; then
  fail "a PVC mounted only through subPath should fail"
fi
assert_contains \
  "$(cat "$TEST_DIR/subpath.out")" \
  "No running container fully mounts PVC: nexent-workspace" \
  "subPath-only error should name the PVC"
assert_no_copy_calls "$FAKE_KUBECTL_LOG" "a subPath-only PVC must fail before copying"

: > "$FAKE_KUBECTL_LOG"
if FAKE_DATABASE_SIZE_KIB=100 FAKE_WORKSPACE_SIZE_KIB=40 FAKE_AVAILABLE_SIZE_KIB=120 \
  bash "$TEST_DIR/workspace/deploy/k8s/backup.sh" \
    --backup-dir "$TEST_DIR/insufficient" \
    > "$TEST_DIR/insufficient.out" 2>&1; then
  fail "insufficient local space should fail"
fi
INSUFFICIENT_OUTPUT="$(cat "$TEST_DIR/insufficient.out")"
assert_contains "$INSUFFICIENT_OUTPUT" "Uncompressed PVC data size" "total source size should be logged"
assert_contains "$INSUFFICIENT_OUTPUT" "140 KiB required" "space check should include every PVC"
assert_contains "$INSUFFICIENT_OUTPUT" "[ERROR] Insufficient space" "space failure should be explicit"
assert_no_copy_calls "$FAKE_KUBECTL_LOG" "space failure must occur before copying"

: > "$FAKE_KUBECTL_LOG"
mkdir -p "$TEST_DIR/success"
SUCCESS_OUTPUT="$(
  NEXENT_BACKUP_TIMESTAMP=20260915-080000 \
  bash "$TEST_DIR/workspace/deploy/k8s/backup.sh" \
    --backup-dir "$TEST_DIR/success" --namespace nexent 2>&1
)"
SUCCESS_DIR="$TEST_DIR/success/k8s-20260915-080000"
SUCCESS_DIR_REAL="$(cd "$SUCCESS_DIR" && pwd -P)"
assert_file_exists \
  "$SUCCESS_DIR/nexent-postgresql/data.txt" \
  "PostgreSQL files should be stored under the actual PVC name"
assert_file_exists \
  "$SUCCESS_DIR/nexent-workspace/workspace.txt" \
  "workspace files should be stored under the actual PVC name"
assert_path_not_exists "$SUCCESS_DIR/data" "a generic data wrapper should not be created"
assert_contains "$SUCCESS_OUTPUT" "PVC nexent-postgresql" "PostgreSQL source should be logged"
assert_contains "$SUCCESS_OUTPUT" "PVC nexent-workspace" "workspace source should be logged"
assert_contains "$SUCCESS_OUTPUT" "[PASS] Pre-upgrade space check passed." "space success should precede copying"
assert_contains "$SUCCESS_OUTPUT" "[WARN] Stop user actions" "business-write warning should be visible"
assert_not_contains "$SUCCESS_OUTPUT" "Have all business writes stopped" "backup should not prompt for input"
assert_contains "$SUCCESS_OUTPUT" "[PASS] Backup complete: $SUCCESS_DIR_REAL" "success should print the final directory"
assert_not_contains "$(cat "$FAKE_KUBECTL_LOG")" " scale " "backup must not scale workloads"
assert_not_contains "$(cat "$FAKE_KUBECTL_LOG")" " delete " "backup must not delete workloads"
assert_not_contains "$(cat "$FAKE_KUBECTL_LOG")" " rollout " "backup must not restart workloads"
if find "$SUCCESS_DIR" -type f \( -name '*.tar' -o -name '*.gz' -o -name '*.zip' -o -name '*.sha256' \) | grep -q .; then
  fail "successful backup should not contain archives or checksum files"
fi

: > "$FAKE_KUBECTL_LOG"
mkdir -p "$TEST_DIR/fallback"
FALLBACK_OUTPUT="$(
  NEXENT_BACKUP_TIMESTAMP=20260915-080001 FAKE_CP_FAIL_PVC=nexent-workspace \
  bash "$TEST_DIR/workspace/deploy/k8s/backup.sh" \
    --backup-dir "$TEST_DIR/fallback" 2>&1
)"
FALLBACK_DIR="$TEST_DIR/fallback/k8s-20260915-080001"
assert_file_exists \
  "$FALLBACK_DIR/nexent-workspace/workspace.txt" \
  "tar fallback should stream and extract workspace files"
assert_contains "$FALLBACK_OUTPUT" "kubectl cp failed for PVC nexent-workspace" "fallback should be reported"
assert_contains "$(cat "$FAKE_KUBECTL_LOG")" "tar -C /mnt/nexent -cf - ." "fallback should stream tar from the container"
if find "$FALLBACK_DIR" -type f \( -name '*.tar' -o -name '*.gz' -o -name '*.zip' \) | grep -q .; then
  fail "tar fallback should not retain an archive"
fi

: > "$FAKE_KUBECTL_LOG"
mkdir -p "$TEST_DIR/no-tar-fallback"
NO_TAR_OUTPUT="$(
  NEXENT_BACKUP_TIMESTAMP=20260915-080005 \
  FAKE_CP_FAIL_PVC=nexent-workspace \
  FAKE_TAR_MISSING=1 \
  FAKE_TAR_FAIL=1 \
  bash "$TEST_DIR/workspace/deploy/k8s/backup.sh" \
    --backup-dir "$TEST_DIR/no-tar-fallback" 2>&1
)"
NO_TAR_DIR="$TEST_DIR/no-tar-fallback/k8s-20260915-080005"
assert_file_exists \
  "$NO_TAR_DIR/nexent-workspace/workspace.txt" \
  "a container without tar should fall back to per-file streaming"
assert_file_exists \
  "$NO_TAR_DIR/nexent-workspace/nested/file with space.txt" \
  "per-file streaming should preserve nested paths containing spaces"
assert_file_exists \
  "$NO_TAR_DIR/nexent-workspace/.hidden" \
  "per-file streaming should preserve hidden files"
[ -L "$NO_TAR_DIR/nexent-workspace/workspace-link" ] \
  || fail "per-file streaming should preserve symbolic links"
[ "$(readlink "$NO_TAR_DIR/nexent-workspace/workspace-link")" = "workspace.txt" ] \
  || fail "per-file streaming should preserve symbolic-link targets"
assert_contains \
  "$NO_TAR_OUTPUT" \
  "tar is unavailable for PVC nexent-workspace" \
  "the no-tar fallback should be reported"
assert_contains \
  "$(cat "$FAKE_KUBECTL_LOG")" \
  "cat /mnt/nexent/workspace.txt" \
  "the no-tar fallback should stream regular files with kubectl exec"
if find "$NO_TAR_DIR" -type f \( -name '*.tar' -o -name '*.gz' -o -name '*.zip' \) | grep -q .; then
  fail "per-file fallback should not retain an archive"
fi

: > "$FAKE_KUBECTL_LOG"
mkdir -p "$TEST_DIR/copy-failure"
if NEXENT_BACKUP_TIMESTAMP=20260915-080002 \
  FAKE_CP_FAIL=1 FAKE_TAR_FAIL=1 FAKE_PORTABLE_FAIL=1 \
  bash "$TEST_DIR/workspace/deploy/k8s/backup.sh" \
    --backup-dir "$TEST_DIR/copy-failure" \
    > "$TEST_DIR/copy-failure.out" 2>&1; then
  fail "cp and tar failure should fail the backup"
fi
COPY_FAILURE_OUTPUT="$(cat "$TEST_DIR/copy-failure.out")"
assert_contains "$COPY_FAILURE_OUTPUT" "Failed to copy PVC: nexent-postgresql" "copy error should name the PVC"
assert_contains "$COPY_FAILURE_OUTPUT" "Backup is incomplete" "failure should identify the partial backup"
assert_path_not_exists \
  "$TEST_DIR/copy-failure/k8s-20260915-080002" \
  "copy failure must not publish a final directory"
[ -d "$TEST_DIR/copy-failure/k8s-20260915-080002.partial" ] \
  || fail "copy failure should retain the partial directory"

: > "$FAKE_KUBECTL_LOG"
mkdir -p "$TEST_DIR/collision/k8s-20260915-080003"
if NEXENT_BACKUP_TIMESTAMP=20260915-080003 \
  bash "$TEST_DIR/workspace/deploy/k8s/backup.sh" \
    --backup-dir "$TEST_DIR/collision" \
    > "$TEST_DIR/collision.out" 2>&1; then
  fail "an existing final backup directory should fail"
fi
assert_contains "$(cat "$TEST_DIR/collision.out")" "Backup path already exists" "collision should report the existing path"
assert_no_copy_calls "$FAKE_KUBECTL_LOG" "path collision must fail before copying"

: > "$FAKE_KUBECTL_LOG"
mkdir -p "$TEST_DIR/apparent-fallback"
APPARENT_OUTPUT="$(
  NEXENT_BACKUP_TIMESTAMP=20260915-080004 FAKE_APPARENT_SIZE_UNSUPPORTED=1 \
  bash "$TEST_DIR/workspace/deploy/k8s/backup.sh" \
    --backup-dir "$TEST_DIR/apparent-fallback" 2>&1
)"
assert_contains "$APPARENT_OUTPUT" "[PASS] Backup complete:" "plain du fallback should complete"

SCRIPT_CONTENT="$(cat "$BACKUP_SCRIPT")"
assert_not_contains "$SCRIPT_CONTENT" "sudo " "backup script must not use sudo"
assert_not_contains "$SCRIPT_CONTENT" "sha256" "backup script must not generate checksum files"
assert_not_contains "$SCRIPT_CONTENT" "snapshot" "backup script must not use storage snapshots"
assert_not_contains "$SCRIPT_CONTENT" "gzip" "backup script must not compress data"

ZH_CONTENT="$(cat "$ZH_GUIDE")"
EN_CONTENT="$(cat "$EN_GUIDE")"
assert_contains \
  "$ZH_CONTENT" \
  "bash deploy/k8s/backup.sh" \
  "Chinese guide should use the Kubernetes backup script"
assert_contains \
  "$EN_CONTENT" \
  "bash deploy/k8s/backup.sh" \
  "English guide should use the Kubernetes backup script"
assert_contains "$ZH_CONTENT" "备份前必须停止业务写入" "Chinese guide should require stopping business writes"
assert_contains "$EN_CONTENT" "Business writes must stop" "English guide should require stopping business writes"
assert_contains "$ZH_CONTENT" "指定 namespace 中的全部 PVC" "Chinese guide should describe the complete PVC scope"
assert_contains "$EN_CONTENT" "every PVC in the specified namespace" "English guide should describe the complete PVC scope"
assert_contains "$ZH_CONTENT" "MinIO 等精简镜像不包含" "Chinese guide should document the no-tar fallback"
assert_contains "$EN_CONTENT" "minimal image such as MinIO" "English guide should document the no-tar fallback"
assert_not_contains "$ZH_CONTENT" "copy_from_app" "Chinese guide should not retain manual component copy commands"
assert_not_contains "$EN_CONTENT" "copy_from_app" "English guide should not retain manual component copy commands"
assert_contains "$ZH_CONTENT" "kubectl get pods -n nexent -o wide" "Chinese guide should check Pod status"
assert_contains "$EN_CONTENT" "kubectl get pods -n nexent -o wide" "English guide should check Pod status"
assert_not_contains "$ZH_CONTENT" "kubectl get deployment" "Chinese post-upgrade checks should not inspect Deployments"
assert_not_contains "$EN_CONTENT" "kubectl get deployment" "English post-upgrade checks should not inspect Deployments"
assert_not_contains "$ZH_CONTENT" "kubectl get pvc" "Chinese post-upgrade checks should not inspect PVCs"
assert_not_contains "$EN_CONTENT" "kubectl get pvc" "English post-upgrade checks should not inspect PVCs"
assert_not_contains "$ZH_CONTENT" "kubectl logs" "Chinese post-upgrade checks should not inspect logs"
assert_not_contains "$EN_CONTENT" "kubectl logs" "English post-upgrade checks should not inspect logs"
[ "$(grep -c '^## ' "$ZH_GUIDE")" -eq 3 ] || fail "Chinese guide should retain exactly three main sections"
[ "$(grep -c '^## ' "$EN_GUIDE")" -eq 3 ] || fail "English guide should retain exactly three main sections"

printf 'PASS: Kubernetes backup script checks succeeded.\n'
