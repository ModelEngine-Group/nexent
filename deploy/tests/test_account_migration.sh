#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
# Controlled platform boundary: all host work remains Shell, including K8s failures.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATION="$SCRIPT_DIR/../sql/tools/supabase_to_postgres/migrate.sh"
temporary="$(mktemp -d)"
trap 'rm -f "$temporary/bin/kubectl" "$temporary/bin/python" "$temporary/bin/python3" "$temporary/log" "$temporary/out" "$temporary/error" "$temporary/job.yaml" "$temporary/.env"; rm -rf "$temporary/backups"; rmdir "$temporary/bin" "$temporary" 2>/dev/null || true' EXIT
mkdir "$temporary/bin"
export MIGRATION_LOG="$temporary/log" MIGRATION_JOB="$temporary/job.yaml"
cat > "$temporary/bin/kubectl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$MIGRATION_LOG"
[ "$1" != --namespace ] || shift 2
case "$1" in
  exec)
    case "$*" in
      *psql*) cat >/dev/null; case "${FAKE_STATE:-legacy}" in incomplete) echo '{"complete":false,"legacy":true,"account_table":true,"accounts":0,"members":1,"unresolved_ids":["old-user"]}' ;; complete) echo '{"complete":true,"legacy":true,"accounts":1,"members":1,"unresolved_ids":[]}' ;; fresh) echo '{"complete":false,"legacy":false,"accounts":0,"members":0,"unresolved_ids":[]}' ;; *) echo '{"complete":false,"legacy":true,"accounts":0,"members":1,"unresolved_ids":["old-user"]}' ;; esac ;;
      *PGPORT*) echo 5432 ;;
      *POSTGRES_PASSWORD*) echo source-original-private ;;
    esac ;;
  get)
    case "$*" in
      *status.succeeded*) [ "${FAKE_FAILURE:-false}" = false ] && echo '1:' || echo ':1' ;;
      *volumeName*) echo owned-pv ;;
      *claimName*) [ "${FAKE_PERSISTENT:-true}" = false ] || echo owned-pvc ;;
      *replicas*) echo 0 ;;
      *clusterIP*) echo 10.0.0.1 ;;
      *ports*) echo 5432 ;;
      *imagePullSecrets*) echo private-registry ;;
      *' -o name'*) echo deployment/nexent-supabase-db ;;
      *' -o yaml'*) echo 'apiVersion: v1' ;;
    esac ;;
  create)
    if [ "$2" = -f ]; then cp "$3" "$MIGRATION_JOB"; fi
    if [ "$2" = secret ]; then
      for value in "$@"; do
        case "$value" in --from-file=SUPABASE_POSTGRES_PASSWORD=*)
          path="${value#--from-file=SUPABASE_POSTGRES_PASSWORD=}"
          [ "$(cat "$path")" = "source-original-private" ] || exit 45 ;;
        esac
      done
    fi ;;
  logs)
    if [ "${FAKE_FAILURE:-false}" = true ]; then echo 'Account migration conflict IDs: ["old-user","new-user"]';
    elif [ "${FAKE_CONFIRM:-true}" = false ]; then echo '{"source":1,"dry_run":false}';
    else echo '{"source":1,"dry_run":false,"committed":true}'; fi ;;
  *) ;;
esac
SH
for name in python python3; do
  printf '#!/usr/bin/env bash\nprintf "Forbidden host Python" >&2\nexit 99\n' > "$temporary/bin/$name"
done
chmod +x "$temporary/bin/"*
export PATH="$temporary/bin:$PATH"
export POSTGRES_USER=postgres POSTGRES_DB=postgres NEXENT_POSTGRES_PASSWORD=target-private
export NEXENT_IMAGE=owned-worker:current
unset SUPABASE_POSTGRES_PASSWORD SUPABASE_POSTGRES_HOST SUPABASE_MIGRATION_DB_CONTAINER
printf '%s\n' '# Intentionally empty' > "$temporary/.env"
assert_has() { grep -Fq -- "$2" "$1" || { echo "FAIL: missing $2" >&2; exit 1; }; }
assert_absent() { if grep -Fq -- "$2" "$1"; then echo "FAIL: unexpected $2" >&2; exit 1; fi; }
run_case() {
  : > "$MIGRATION_LOG"
  bash "$MIGRATION" --deployment kubernetes --namespace owned-test --env-file "$temporary/.env" --wait-timeout 1 "$@" > "$temporary/out" 2> "$temporary/error"
}
for state in fresh complete; do
  FAKE_STATE="$state" run_case --apply
  assert_absent "$MIGRATION_LOG" 'create '
  assert_absent "$MIGRATION_LOG" 'scale '
done
if FAKE_STATE=incomplete run_case --apply; then echo 'FAIL: existing incomplete data was accepted'; exit 1; fi
assert_has "$temporary/error" 'old-user'
assert_has "$temporary/error" 'No automatic repair'
assert_absent "$MIGRATION_LOG" 'create '
assert_absent "$MIGRATION_LOG" 'scale '
run_case
assert_has "$temporary/error" '[account-migration][preflight]'
assert_has "$temporary/error" 'old-user'
assert_has "$temporary/error" '[account-migration][worker]'
assert_has "$MIGRATION_JOB" 'kind: Job'
assert_has "$MIGRATION_JOB" 'automountServiceAccountToken: false'
assert_has "$MIGRATION_JOB" 'imagePullSecrets:'
assert_has "$MIGRATION_JOB" 'private-registry'
assert_has "$MIGRATION_JOB" 'migrate_docker.py'
assert_has "$MIGRATION_LOG" 'patch pv owned-pv'
assert_has "$MIGRATION_LOG" 'scale deployment/nexent-supabase-db'
assert_absent "$MIGRATION_LOG" 'delete deployment,service'
assert_has "$MIGRATION_LOG" 'delete secret account-migration-'
run_case --apply
assert_has "$MIGRATION_LOG" 'delete deployment,service nexent-supabase-db'
assert_has "$MIGRATION_LOG" 'delete job account-migration-'
if FAKE_FAILURE=true run_case --apply; then echo 'FAIL: failed Job was accepted'; exit 1; fi
assert_has "$temporary/error" 'old-user'
assert_absent "$MIGRATION_LOG" 'delete deployment,service'
assert_has "$MIGRATION_LOG" 'delete secret account-migration-'
if FAKE_CONFIRM=false run_case --apply; then echo 'FAIL: source cleanup accepted an unconfirmed commit'; exit 1; fi
assert_absent "$MIGRATION_LOG" 'delete deployment,service'
if FAKE_PERSISTENT=false run_case --apply; then echo 'FAIL: ephemeral source was accepted'; exit 1; fi
assert_absent "$MIGRATION_LOG" 'create secret'
assert_absent "$temporary/out" 'target-private'
assert_absent "$temporary/error" 'source-original-private'
echo 'Shell-only Kubernetes migration contracts passed.'
