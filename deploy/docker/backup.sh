#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ROOT_ENV_FILE="${NEXENT_BACKUP_ENV_FILE:-$PROJECT_ROOT/deploy/env/.env}"

BACKUP_BASE=""
BACKUP_STARTED="false"
BACKUP_COMPLETED="false"
PARTIAL_BACKUP_DIR=""
ROOT_BACKUP_NAME=""
NEXENT_USER_BACKUP_NAME=""

log_info() {
  printf '[INFO] %s\n' "$*"
}

log_warn() {
  printf '[WARN] %s\n' "$*" >&2
}

log_pass() {
  printf '[PASS] %s\n' "$*"
}

log_error() {
  printf '[ERROR] %s\n' "$*" >&2
}

fail() {
  log_error "$*"
  exit 1
}

print_usage() {
  cat <<'USAGE'
Usage: bash deploy/docker/backup.sh --backup-dir PATH [options]

Check local space and copy Docker persistent files before an upgrade.

Options:
  --backup-dir PATH  Local directory that will contain the backup
  --help, -h         Show this help message

Examples:
  bash deploy/docker/backup.sh --backup-dir /mnt/backup/nexent
USAGE
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --backup-dir)
        [ "$#" -ge 2 ] || fail "--backup-dir requires a path."
        BACKUP_BASE="$2"
        shift 2
        ;;
      --backup-dir=*)
        BACKUP_BASE="${1#*=}"
        shift
        ;;
      --help|-h)
        print_usage
        exit 0
        ;;
      *)
        log_error "Unknown option: $1"
        print_usage >&2
        exit 1
        ;;
    esac
  done

  [ -n "$BACKUP_BASE" ] || fail "--backup-dir is required."
}

format_kib() {
  LC_ALL=C awk -v kib="$1" 'BEGIN {
    if (kib >= 1048576) {
      printf "%.2f GiB", kib / 1048576
    } else if (kib >= 1024) {
      printf "%.2f MiB", kib / 1024
    } else {
      printf "%d KiB", kib
    }
  }'
}

read_first_field() {
  local value="$1"
  local first_field
  read -r first_field _ <<< "$value"
  printf '%s\n' "$first_field"
}

measure_local_path_kib() {
  local path="$1"
  local size_output

  if size_output="$(du -sk --apparent-size "$path" 2>/dev/null)"; then
    read_first_field "$size_output"
    return
  fi

  if size_output="$(du -skA "$path" 2>/dev/null)"; then
    read_first_field "$size_output"
    return
  fi

  size_output="$(du -sk "$path")" || return 1
  read_first_field "$size_output"
}

on_exit() {
  local status="$?"
  if [ "$status" -ne 0 ] && [ "$BACKUP_STARTED" = "true" ] && [ "$BACKUP_COMPLETED" != "true" ]; then
    log_error "Backup is incomplete. Inspect but do not use: $PARTIAL_BACKUP_DIR"
  fi
}

trap on_exit EXIT

load_deployment_env() {
  [ -r "$ROOT_ENV_FILE" ] || fail "Deployment environment file is not readable: $ROOT_ENV_FILE"

  set -a
  # shellcheck source=/dev/null
  source "$ROOT_ENV_FILE"
  set +a

  [ -n "${ROOT_DIR:-}" ] || fail "ROOT_DIR is not set in $ROOT_ENV_FILE"
  [ -d "$ROOT_DIR" ] || fail "ROOT_DIR does not exist: $ROOT_DIR"
  [ -r "$ROOT_DIR" ] || fail "ROOT_DIR is not readable: $ROOT_DIR"
  ROOT_DIR="$(cd "$ROOT_DIR" && pwd -P)"

  [ -n "${HOME:-}" ] || fail "HOME is not set; cannot resolve the default NEXENT_USER_DIR."
  NEXENT_USER_DIR="${NEXENT_USER_DIR:-$HOME/nexent}"
  [ -d "$NEXENT_USER_DIR" ] || fail "NEXENT_USER_DIR does not exist: $NEXENT_USER_DIR"
  [ -r "$NEXENT_USER_DIR" ] || fail "NEXENT_USER_DIR is not readable: $NEXENT_USER_DIR"
  NEXENT_USER_DIR="$(cd "$NEXENT_USER_DIR" && pwd -P)"
}

validate_backup_base() {
  mkdir -p "$BACKUP_BASE" || fail "Cannot create backup directory: $BACKUP_BASE"
  [ -d "$BACKUP_BASE" ] || fail "Backup path is not a directory: $BACKUP_BASE"
  [ -w "$BACKUP_BASE" ] || fail "Backup directory is not writable: $BACKUP_BASE"
  BACKUP_BASE="$(cd "$BACKUP_BASE" && pwd -P)"

  case "$BACKUP_BASE" in
    "$ROOT_DIR"|"$ROOT_DIR"/*)
      fail "Backup directory must be outside ROOT_DIR: $ROOT_DIR"
      ;;
  esac

  case "$BACKUP_BASE" in
    "$NEXENT_USER_DIR"|"$NEXENT_USER_DIR"/*)
      fail "Backup directory must be outside NEXENT_USER_DIR: $NEXENT_USER_DIR"
      ;;
  esac
}

validate_docker() {
  command -v docker >/dev/null 2>&1 || fail "Docker CLI is not installed."
  docker info >/dev/null 2>&1 || fail "Docker daemon is not available."

  local config_running
  config_running="$(docker inspect --format '{{.State.Running}}' nexent-config 2>/dev/null || true)"
  [ "$config_running" = "true" ] || fail "The nexent-config container is not running."

  BACKUP_HELPER_IMAGE="$(docker inspect --format '{{.Config.Image}}' nexent-config)"
  [ -n "$BACKUP_HELPER_IMAGE" ] || fail "Cannot determine the deployed backend image."
  docker image inspect "$BACKUP_HELPER_IMAGE" >/dev/null 2>&1 \
    || fail "The deployed backend image is not available locally: $BACKUP_HELPER_IMAGE"
}

discover_volumes() {
  local volume_output
  volume_output="$({
    docker volume ls --filter label=com.docker.compose.project=nexent --format '{{.Name}}'
    docker volume ls --filter label=com.docker.compose.project=monitor --format '{{.Name}}'
  } | LC_ALL=C sort -u)" || fail "Cannot list Docker named volumes."

  VOLUMES=()
  if [ -n "$volume_output" ]; then
    while IFS= read -r volume; do
      [ -n "$volume" ] || continue
      VOLUMES+=("$volume")
    done <<< "$volume_output"
  fi
}

validate_backup_layout_names() {
  ROOT_BACKUP_NAME="${ROOT_DIR##*/}"
  NEXENT_USER_BACKUP_NAME="${NEXENT_USER_DIR##*/}"

  [ -n "$ROOT_BACKUP_NAME" ] || fail "Cannot determine the backup name for ROOT_DIR: $ROOT_DIR"
  [ -n "$NEXENT_USER_BACKUP_NAME" ] \
    || fail "Cannot determine the backup name for NEXENT_USER_DIR: $NEXENT_USER_DIR"

  if [ "$ROOT_BACKUP_NAME" = "$NEXENT_USER_BACKUP_NAME" ]; then
    fail "Backup source names collide: $ROOT_BACKUP_NAME"
  fi

  local volume
  for volume in "${VOLUMES[@]}"; do
    if [ "$volume" = "$ROOT_BACKUP_NAME" ] || [ "$volume" = "$NEXENT_USER_BACKUP_NAME" ]; then
      fail "Backup source names collide: $volume"
    fi
  done
}

measure_sources() {
  ROOT_SIZE_KIB="$(measure_local_path_kib "$ROOT_DIR")" || fail "Cannot measure ROOT_DIR: $ROOT_DIR"
  [[ "$ROOT_SIZE_KIB" =~ ^[0-9]+$ ]] || fail "Invalid ROOT_DIR size: $ROOT_SIZE_KIB"

  NEXENT_USER_SIZE_KIB="$(measure_local_path_kib "$NEXENT_USER_DIR")" \
    || fail "Cannot measure NEXENT_USER_DIR: $NEXENT_USER_DIR"
  [[ "$NEXENT_USER_SIZE_KIB" =~ ^[0-9]+$ ]] \
    || fail "Invalid NEXENT_USER_DIR size: $NEXENT_USER_SIZE_KIB"

  TOTAL_SIZE_KIB=$((ROOT_SIZE_KIB + NEXENT_USER_SIZE_KIB))
  VOLUME_SIZES_KIB=()

  log_info "Persistent data directory: $ROOT_DIR"
  log_info "ROOT_DIR size: $(format_kib "$ROOT_SIZE_KIB") ($ROOT_SIZE_KIB KiB)"
  log_info "Persistent user directory: $NEXENT_USER_DIR"
  log_info "NEXENT_USER_DIR size: $(format_kib "$NEXENT_USER_SIZE_KIB") ($NEXENT_USER_SIZE_KIB KiB)"

  if [ "${#VOLUMES[@]}" -eq 0 ]; then
    log_info "Docker named volumes: none"
    return
  fi

  local volume
  local volume_size_output
  local volume_size_kib
  for volume in "${VOLUMES[@]}"; do
    volume_size_output="$(
      docker run --rm --network none --user 0 --entrypoint du \
        -v "$volume:/source:ro" "$BACKUP_HELPER_IMAGE" -sk --apparent-size /source
    )" || fail "Cannot measure Docker volume: $volume"
    volume_size_kib="$(read_first_field "$volume_size_output")"
    [[ "$volume_size_kib" =~ ^[0-9]+$ ]] || fail "Invalid size for Docker volume $volume: $volume_size_kib"
    VOLUME_SIZES_KIB+=("$volume_size_kib")
    TOTAL_SIZE_KIB=$((TOTAL_SIZE_KIB + volume_size_kib))
    log_info "Docker volume $volume: $(format_kib "$volume_size_kib") ($volume_size_kib KiB)"
  done
}

check_space() {
  local df_output
  df_output="$(df -Pk "$BACKUP_BASE")" || fail "Cannot inspect free space: $BACKUP_BASE"
  AVAILABLE_SIZE_KIB="$(printf '%s\n' "$df_output" | LC_ALL=C awk 'END {print $4}')"
  [[ "$AVAILABLE_SIZE_KIB" =~ ^[0-9]+$ ]] || fail "Cannot determine free space for: $BACKUP_BASE"

  log_info "Uncompressed source size: $(format_kib "$TOTAL_SIZE_KIB") ($TOTAL_SIZE_KIB KiB)"
  log_info "Backup destination: $BACKUP_BASE"
  log_info "Available space: $(format_kib "$AVAILABLE_SIZE_KIB") ($AVAILABLE_SIZE_KIB KiB)"

  if [ "$AVAILABLE_SIZE_KIB" -lt "$TOTAL_SIZE_KIB" ]; then
    fail "Insufficient space: $AVAILABLE_SIZE_KIB KiB available, $TOTAL_SIZE_KIB KiB required."
  fi

  log_pass "Pre-upgrade space check passed."
}

warn_writes_stopped() {
  log_warn "Stop user actions, API requests, scheduled jobs, and other business writes before copying."
  log_warn "Containers remain running, so this file copy is not a point-in-time snapshot."
}

copy_files() {
  local stamp
  local final_backup_dir
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  final_backup_dir="$BACKUP_BASE/docker-$stamp"
  PARTIAL_BACKUP_DIR="$final_backup_dir.partial"

  [ ! -e "$final_backup_dir" ] || fail "Backup directory already exists: $final_backup_dir"
  [ ! -e "$PARTIAL_BACKUP_DIR" ] || fail "Partial backup directory already exists: $PARTIAL_BACKUP_DIR"

  BACKUP_STARTED="true"
  mkdir -p \
    "$PARTIAL_BACKUP_DIR/$ROOT_BACKUP_NAME" \
    "$PARTIAL_BACKUP_DIR/$NEXENT_USER_BACKUP_NAME" \
    || fail "Cannot create backup layout: $PARTIAL_BACKUP_DIR"

  log_info "Copying ROOT_DIR files..."
  cp -a "$ROOT_DIR/." "$PARTIAL_BACKUP_DIR/$ROOT_BACKUP_NAME/" \
    || fail "Failed to copy ROOT_DIR files."
  log_pass "ROOT_DIR files copied."

  log_info "Copying NEXENT_USER_DIR files..."
  cp -a "$NEXENT_USER_DIR/." "$PARTIAL_BACKUP_DIR/$NEXENT_USER_BACKUP_NAME/" \
    || fail "Failed to copy NEXENT_USER_DIR files."
  log_pass "NEXENT_USER_DIR files copied."

  local volume
  for volume in "${VOLUMES[@]}"; do
    log_info "Copying Docker volume: $volume"
    mkdir -p "$PARTIAL_BACKUP_DIR/$volume" \
      || fail "Cannot create backup directory for volume: $volume"
    docker run --rm --network none --user 0 --entrypoint cp \
      -v "$volume:/source:ro" \
      -v "$PARTIAL_BACKUP_DIR/$volume:/backup" \
      "$BACKUP_HELPER_IMAGE" -a /source/. /backup/ \
      || fail "Failed to copy Docker volume: $volume"
    log_pass "Docker volume copied: $volume"
  done

  mv "$PARTIAL_BACKUP_DIR" "$final_backup_dir" \
    || fail "Cannot finalize backup directory: $final_backup_dir"
  BACKUP_COMPLETED="true"

  local source_entries
  local backup_entries
  local user_source_entries
  local user_backup_entries
  local backup_size_output
  local backup_size_kib
  source_entries="$(find "$ROOT_DIR" -mindepth 1 | wc -l | tr -d ' ')"
  backup_entries="$(find "$final_backup_dir/$ROOT_BACKUP_NAME" -mindepth 1 | wc -l | tr -d ' ')"
  user_source_entries="$(find "$NEXENT_USER_DIR" -mindepth 1 | wc -l | tr -d ' ')"
  user_backup_entries="$(find "$final_backup_dir/$NEXENT_USER_BACKUP_NAME" -mindepth 1 | wc -l | tr -d ' ')"
  backup_size_output="$(du -sk "$final_backup_dir")"
  backup_size_kib="$(read_first_field "$backup_size_output")"

  log_info "ROOT_DIR entries at completion: source=$source_entries backup=$backup_entries"
  log_info "NEXENT_USER_DIR entries at completion: source=$user_source_entries backup=$user_backup_entries"
  log_info "Backup disk usage: $(format_kib "$backup_size_kib") ($backup_size_kib KiB)"
  log_pass "Backup complete: $final_backup_dir"
}

main() {
  parse_args "$@"
  load_deployment_env
  validate_backup_base
  validate_docker
  discover_volumes
  validate_backup_layout_names
  measure_sources
  check_space
  warn_writes_stopped
  copy_files
}

main "$@"
