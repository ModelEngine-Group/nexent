#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
# Host-only orchestration; the worker image contains Python and the account SQL.
set -euo pipefail
set +x
umask 077
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mode=docker namespace=nexent database=nexent-postgresql source_name="" apply=false timeout=300
legacy_action="" with_auth=false production=false
config_target=nexent-config
allow_start=true env_file="$SCRIPT_DIR/../../../env/.env"
while [ "$#" -gt 0 ]; do
  case "$1" in
    up|down) legacy_action="$1"; shift ;;
    --with-auth) with_auth=true; shift ;;
    --production) production=true; shift ;;
    --deployment) mode="$2"; shift 2 ;;
    --namespace) namespace="$2"; shift 2 ;;
    --database-target) database="$2"; shift 2 ;;
    --config-target) config_target="$2"; shift 2 ;;
    --source-container) source_name="$2"; shift 2 ;;
    --env-file) env_file="$2"; shift 2 ;;
    --wait-timeout) timeout="$2"; shift 2 ;;
    --apply) apply=true; shift ;;
    --no-start-source) allow_start=false; shift ;;
    --deploy) shift ;;
    *) printf 'Unsupported migration argument: %s\n' "$1" >&2; exit 1 ;;
  esac
done
migration_stage=arguments
log_stage() { migration_stage="$1"; shift; printf '[account-migration][%s] %s\n' "$migration_stage" "$*" >&2; }
fail() { printf '[account-migration][%s] Failed; source retained and deployment stopped.\n' "$migration_stage" >&2; printf 'Account upgrade rejected: %s\n' "$*" >&2; exit 1; }
case "$mode" in docker|kubernetes) ;; *) fail "Unsupported deployment mode" ;; esac
case "$timeout" in ''|*[!0-9]*) fail "Invalid readiness timeout" ;; esac
[ "$timeout" -ge 1 ] && [ "$timeout" -le 300 ] || fail "Readiness timeout must be between 1 and 300"

# Exported values win over the existing, Shell-compatible deployment env file.
keys=(NEXENT_IMAGE POSTGRES_HOST POSTGRES_PORT POSTGRES_USER POSTGRES_DB NEXENT_POSTGRES_PASSWORD
  SUPABASE_POSTGRES_HOST SUPABASE_POSTGRES_PORT SUPABASE_POSTGRES_USER SUPABASE_POSTGRES_DB SUPABASE_POSTGRES_PASSWORD
  SUPABASE_MIGRATION_DB_CONTAINER SUPABASE_MIGRATION_AUTH_CONTAINER SUPABASE_MIGRATION_KONG_CONTAINER DEPLOYMENT_IMAGE_SOURCE
  ROOT_DIR SUPABASE_DATA_DIR SUPABASE_LOG_DIR SUPABASE_MIGRATION_PROJECT SUPABASE_MIGRATION_NETWORK
  JWT_SECRET SUPABASE_KEY SERVICE_ROLE_KEY DASHBOARD_PASSWORD SUPABASE_DB SUPABASE_GOTRUE SUPABASE_KONG
  SUPABASE_PUBLISHED_PORT SUPABASE_DB_CONFIG_VOLUME SUPABASE_MIGRATION_BIND_ADDRESS
  SUPABASE_KONG_HTTP_PORT SUPABASE_KONG_HTTPS_PORT JWT_EXPIRY SITE_URL API_EXTERNAL_URL
  DISABLE_SIGNUP ENABLE_EMAIL_SIGNUP ENABLE_EMAIL_AUTOCONFIRM ENABLE_ANONYMOUS_USERS
  ENABLE_PHONE_SIGNUP ENABLE_PHONE_AUTOCONFIRM DASHBOARD_USERNAME ADDITIONAL_REDIRECT_URLS
  MAILER_URLPATHS_INVITE MAILER_URLPATHS_CONFIRMATION MAILER_URLPATHS_RECOVERY MAILER_URLPATHS_EMAIL_CHANGE)
saved_keys=() saved_values=()
for key in "${keys[@]}"; do
  if declare -p "$key" >/dev/null 2>&1; then saved_keys+=("$key"); saved_values+=("${!key}"); fi
done
if [ -f "$env_file" ]; then set -a; source "$env_file"; set +a; fi
for index in "${!saved_keys[@]}"; do printf -v "${saved_keys[$index]}" '%s' "${saved_values[$index]}"; export "${saved_keys[$index]}"; done

platform() {
  if [ "$mode" = docker ]; then
    MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' docker "$@"
  else
    MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' kubectl --namespace "$namespace" "$@"
  fi
}
resource() { case "$1" in */*) printf '%s' "$1" ;; *) printf 'deployment/%s' "$1" ;; esac; }
inside() {
  local selected="$1"; shift
  if [ "$mode" = docker ]; then platform exec -i "$selected" "$@";
  else platform exec -i "$(resource "$selected")" -- "$@"; fi
}
inside_value() { inside "$1" sh -c 'printenv "$1" || true' migration "$2" 2>/dev/null || true; }
get_target() {
  target_user="${POSTGRES_USER:-$(inside_value "$database" POSTGRES_USER)}"
  target_db="${POSTGRES_DB:-$(inside_value "$database" POSTGRES_DB)}"
  target_port="$(inside_value "$database" PGPORT)"
  target_password="${NEXENT_POSTGRES_PASSWORD:-$(inside_value "$database" POSTGRES_PASSWORD)}"
  target_password="${target_password:-$(inside_value "$database" PGPASSWORD)}"
  target_user="${target_user:-postgres}"; target_db="${target_db:-nexent}"; target_port="${target_port:-5432}"
  [ -n "$target_password" ] || fail "Target database password is unavailable"
}
preflight() {
  local encoded
  encoded="$(printf '%s' "$target_password" | base64 | tr -d '\r\n')"
  # Secrets travel over stdin, never argv; suppress raw driver diagnostics.
  { printf '%s\n' "$encoded"; cat "$SCRIPT_DIR/inspect_accounts.sql"; } |
    inside "$database" sh -c 'IFS= read -r encoded; PGPASSWORD="$(printf "%s" "$encoded" | base64 -d)"; export PGPASSWORD; exec "$@"' migration \
      psql -X -qAt -h 127.0.0.1 -p "$target_port" -U "$target_user" -d "$target_db" -v ON_ERROR_STOP=1 2>/dev/null
}
get_source() {
  source_user="${SUPABASE_POSTGRES_USER:-}"; source_db="${SUPABASE_POSTGRES_DB:-}"
  source_password="${SUPABASE_POSTGRES_PASSWORD:-}"; source_port="${SUPABASE_POSTGRES_PORT:-}"
  if [ -n "$source_name" ]; then
    source_user="${source_user:-$(inside_value "$source_name" POSTGRES_USER)}"
    source_db="${source_db:-$(inside_value "$source_name" POSTGRES_DB)}"
    source_port="$(inside_value "$source_name" PGPORT)"
    source_password="${source_password:-$(inside_value "$source_name" POSTGRES_PASSWORD)}"
    source_password="${source_password:-$(inside_value "$source_name" PGPASSWORD)}"
  fi
  source_user="${source_user:-postgres}"; source_db="${source_db:-supabase}"; source_port="${source_port:-${source_name:+5432}}"; source_port="${source_port:-5436}"
  if [ -z "$source_password" ] && [ -t 0 ]; then
    read -r -s -p 'Supabase PostgreSQL password: ' source_password; printf '\n' >&2
  fi
  [ -n "$source_password" ] || fail "Set SUPABASE_POSTGRES_PASSWORD to the original source password"
}
worker_flag() {
  local pattern="\"$1\"[[:space:]]*:[[:space:]]*true([[:space:],}]|$)"
  [[ "$2" =~ $pattern ]]
}
export_connections() {
  export POSTGRES_HOST="$target_host" POSTGRES_PORT="$target_port" POSTGRES_USER="$target_user" POSTGRES_DB="$target_db" NEXENT_POSTGRES_PASSWORD="$target_password"
  export SUPABASE_POSTGRES_HOST="$source_host" SUPABASE_POSTGRES_PORT="$source_port" SUPABASE_POSTGRES_USER="$source_user" SUPABASE_POSTGRES_DB="$source_db" SUPABASE_POSTGRES_PASSWORD="$source_password"
}
cleanup_warning() { printf 'Account migration committed; source cleanup incomplete. Retain storage and remove remaining source workloads manually.\n' >&2; }
worker_command=(python /opt/deploy/sql/tools/supabase_to_postgres/migrate_docker.py --container --wait-timeout "$timeout")
[ "$apply" = false ] || worker_command+=(--apply)
if [ -n "$legacy_action" ]; then source "$SCRIPT_DIR/legacy.sh"; run_recovery; exit; fi
log_stage preflight "Inspecting target account coverage (mode=$mode target=$database)."
get_target
state="$(preflight)" || fail "Cannot inspect target database; check readiness and credentials"
log_stage preflight "Target account inspection: $state"
if worker_flag complete "$state"; then
  log_stage skipped "Account data is complete; source access and cleanup were not attempted."
  printf '%s\n' '{"skipped":true,"complete":true}'; exit 0
elif worker_flag account_table "$state"; then
  fail "Existing account data is incomplete; restore the consistent pre-upgrade backup before retrying. No automatic repair was attempted. See unresolved account IDs above."
elif [[ "$state" =~ \"legacy\"[[:space:]]*:[[:space:]]*false ]]; then
  log_stage skipped "No historical membership table; ordinary fresh initialization will run."
  printf '%s\n' '{"skipped":true,"new":true}'; exit 0
elif ! worker_flag legacy "$state"; then
  fail "Unexpected target preflight result"
fi
log_stage source "Account data is incomplete; preparing the original Supabase source."
[ -n "${NEXENT_IMAGE:-}" ] || fail "Set the deployment NEXENT_IMAGE before account migration"
source "$SCRIPT_DIR/migrate_${mode}.sh"
run_migration
