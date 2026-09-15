#!/usr/bin/env bash

set -euo pipefail

BACKUP_BASE=""
K8S_NAMESPACE="nexent"
BACKUP_STARTED="false"
BACKUP_COMPLETED="false"
PARTIAL_BACKUP_DIR=""
FINAL_BACKUP_DIR=""

PVC_NAMES=()
SOURCE_PODS=()
SOURCE_CONTAINERS=()
SOURCE_PATHS=()
SOURCE_SIZES_KIB=()

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
Usage: bash deploy/k8s/backup.sh --backup-dir PATH [options]

Check local space and copy Kubernetes PVC files before an upgrade.

Options:
  --backup-dir PATH  Local directory that will contain the backup
  --namespace NAME   Kubernetes namespace (default: nexent)
  --help, -h         Show this help message

Examples:
  bash deploy/k8s/backup.sh --backup-dir /mnt/backup/nexent
  bash deploy/k8s/backup.sh --backup-dir /mnt/backup/nexent --namespace nexent
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
      --namespace)
        [ "$#" -ge 2 ] || fail "--namespace requires a name."
        K8S_NAMESPACE="$2"
        shift 2
        ;;
      --namespace=*)
        K8S_NAMESPACE="${1#*=}"
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
  [ -n "$K8S_NAMESPACE" ] || fail "--namespace cannot be empty."
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

validate_local_environment() {
  command -v kubectl >/dev/null 2>&1 || fail "kubectl is not installed."
  command -v tar >/dev/null 2>&1 || fail "tar is not installed on the local machine."
  command -v du >/dev/null 2>&1 || fail "du is not installed on the local machine."
  command -v df >/dev/null 2>&1 || fail "df is not installed on the local machine."

  kubectl version --client >/dev/null 2>&1 || fail "kubectl is not available."
  kubectl get namespace "$K8S_NAMESPACE" >/dev/null 2>&1 \
    || fail "Cannot access Kubernetes namespace: $K8S_NAMESPACE"

  mkdir -p "$BACKUP_BASE" || fail "Cannot create backup directory: $BACKUP_BASE"
  [ -d "$BACKUP_BASE" ] || fail "Backup path is not a directory: $BACKUP_BASE"
  [ -w "$BACKUP_BASE" ] || fail "Backup directory is not writable: $BACKUP_BASE"
  BACKUP_BASE="$(cd "$BACKUP_BASE" && pwd -P)"

  local timestamp
  timestamp="${NEXENT_BACKUP_TIMESTAMP:-$(date -u +%Y%m%d-%H%M%S)}"
  [[ "$timestamp" =~ ^[0-9]{8}-[0-9]{6}$ ]] || fail "Invalid backup timestamp: $timestamp"
  FINAL_BACKUP_DIR="$BACKUP_BASE/k8s-$timestamp"
  PARTIAL_BACKUP_DIR="$FINAL_BACKUP_DIR.partial"

  [ ! -e "$FINAL_BACKUP_DIR" ] || fail "Backup path already exists: $FINAL_BACKUP_DIR"
  [ ! -e "$PARTIAL_BACKUP_DIR" ] || fail "Backup path already exists: $PARTIAL_BACKUP_DIR"
}

discover_pvcs() {
  local pvc_output
  local pvc_name
  local pvc_phase

  pvc_output="$(
    kubectl get pvc -n "$K8S_NAMESPACE" \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\n"}{end}'
  )" || fail "Cannot list PVCs in namespace: $K8S_NAMESPACE"

  PVC_NAMES=()
  while IFS=$'\t' read -r pvc_name pvc_phase; do
    [ -n "$pvc_name" ] || continue
    [ "$pvc_phase" = "Bound" ] || fail "PVC is not Bound: $pvc_name (status: ${pvc_phase:-unknown})"
    PVC_NAMES+=("$pvc_name")
  done <<< "$pvc_output"

  [ "${#PVC_NAMES[@]}" -gt 0 ] || fail "No PVCs found in namespace: $K8S_NAMESPACE"
  log_info "PVCs to back up: ${#PVC_NAMES[@]}"
}

find_pvc_source() {
  local requested_pvc="$1"
  local pod_output
  local pod
  local volume_output
  local volume_name
  local claim_name
  local matched_volume
  local container_output
  local container
  local mount_records
  local record
  local mounted_volume
  local mount_path
  local sub_path
  local sub_path_expr
  local mounts=()

  pod_output="$(
    kubectl get pods -n "$K8S_NAMESPACE" \
      --field-selector=status.phase=Running \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
  )" || fail "Cannot list running Pods in namespace: $K8S_NAMESPACE"

  while IFS= read -r pod; do
    [ -n "$pod" ] || continue
    volume_output="$(
      kubectl get pod "$pod" -n "$K8S_NAMESPACE" \
        -o jsonpath='{range .spec.volumes[*]}{.name}{"\t"}{.persistentVolumeClaim.claimName}{"\n"}{end}'
    )" || fail "Cannot inspect volumes for Pod: $pod"

    matched_volume=""
    while IFS=$'\t' read -r volume_name claim_name; do
      if [ "$claim_name" = "$requested_pvc" ]; then
        matched_volume="$volume_name"
        break
      fi
    done <<< "$volume_output"
    [ -n "$matched_volume" ] || continue

    container_output="$(
      kubectl get pod "$pod" -n "$K8S_NAMESPACE" \
        -o jsonpath='{range .spec.containers[*]}{.name}{"\t"}{range .volumeMounts[*]}{.name}{"|"}{.mountPath}{"|"}{.subPath}{"|"}{.subPathExpr}{";"}{end}{"\n"}{end}'
    )" || fail "Cannot inspect container mounts for Pod: $pod"

    while IFS=$'\t' read -r container mount_records; do
      [ -n "$container" ] || continue
      mounts=()
      IFS=';' read -r -a mounts <<< "${mount_records:-}"
      for record in "${mounts[@]}"; do
        [ -n "$record" ] || continue
        IFS='|' read -r mounted_volume mount_path sub_path sub_path_expr <<< "$record"
        if [ "$mounted_volume" = "$matched_volume" ] \
          && [ -n "$mount_path" ] \
          && [ -z "${sub_path:-}" ] \
          && [ -z "${sub_path_expr:-}" ]; then
          printf '%s\t%s\t%s\n' "$pod" "$container" "$mount_path"
          return 0
        fi
      done
    done <<< "$container_output"
  done <<< "$pod_output"

  return 1
}

discover_sources() {
  local pvc
  local source_record
  local pod
  local container
  local mount_path

  SOURCE_PODS=()
  SOURCE_CONTAINERS=()
  SOURCE_PATHS=()

  for pvc in "${PVC_NAMES[@]}"; do
    if ! source_record="$(find_pvc_source "$pvc")"; then
      fail "No running container fully mounts PVC: $pvc"
    fi
    IFS=$'\t' read -r pod container mount_path <<< "$source_record"
    [ -n "$pod" ] && [ -n "$container" ] && [ -n "$mount_path" ] \
      || fail "Cannot determine a complete mount for PVC: $pvc"

    SOURCE_PODS+=("$pod")
    SOURCE_CONTAINERS+=("$container")
    SOURCE_PATHS+=("$mount_path")
    log_info "PVC $pvc: $pod/$container:$mount_path"
  done
}

measure_remote_path_kib() {
  local pod="$1"
  local container="$2"
  local path="$3"
  local size_output

  if size_output="$(
    kubectl exec -n "$K8S_NAMESPACE" "$pod" -c "$container" -- \
      du -sk --apparent-size "$path" 2>/dev/null
  )"; then
    read_first_field "$size_output"
    return
  fi

  size_output="$(
    kubectl exec -n "$K8S_NAMESPACE" "$pod" -c "$container" -- \
      du -sk "$path"
  )" || return 1
  read_first_field "$size_output"
}

measure_sources() {
  local total_size_kib=0
  local index
  local pvc
  local size_kib

  SOURCE_SIZES_KIB=()
  for ((index = 0; index < ${#PVC_NAMES[@]}; index++)); do
    pvc="${PVC_NAMES[$index]}"
    size_kib="$(
      measure_remote_path_kib \
        "${SOURCE_PODS[$index]}" \
        "${SOURCE_CONTAINERS[$index]}" \
        "${SOURCE_PATHS[$index]}"
    )" || fail "Cannot measure PVC data: $pvc"
    [[ "$size_kib" =~ ^[0-9]+$ ]] || fail "Invalid size for PVC $pvc: $size_kib"
    SOURCE_SIZES_KIB+=("$size_kib")
    total_size_kib=$((total_size_kib + size_kib))
    log_info "PVC $pvc size: $(format_kib "$size_kib") ($size_kib KiB)"
  done

  TOTAL_SIZE_KIB="$total_size_kib"
}

check_space() {
  local df_output

  df_output="$(df -Pk "$BACKUP_BASE")" || fail "Cannot inspect free space: $BACKUP_BASE"
  AVAILABLE_SIZE_KIB="$(printf '%s\n' "$df_output" | LC_ALL=C awk 'END {print $4}')"
  [[ "$AVAILABLE_SIZE_KIB" =~ ^[0-9]+$ ]] \
    || fail "Cannot determine free space for: $BACKUP_BASE"

  log_info "Uncompressed PVC data size: $(format_kib "$TOTAL_SIZE_KIB") ($TOTAL_SIZE_KIB KiB)"
  log_info "Backup destination: $BACKUP_BASE"
  log_info "Available space: $(format_kib "$AVAILABLE_SIZE_KIB") ($AVAILABLE_SIZE_KIB KiB)"

  if [ "$AVAILABLE_SIZE_KIB" -lt "$TOTAL_SIZE_KIB" ]; then
    fail "Insufficient space: $TOTAL_SIZE_KIB KiB required, $AVAILABLE_SIZE_KIB KiB available."
  fi

  log_pass "Pre-upgrade space check passed."
}

copy_pvc() {
  local index="$1"
  local pvc="${PVC_NAMES[$index]}"
  local pod="${SOURCE_PODS[$index]}"
  local container="${SOURCE_CONTAINERS[$index]}"
  local source_path="${SOURCE_PATHS[$index]%/}"
  local copy_dir="$PARTIAL_BACKUP_DIR/.copy-$index"
  local target_dir="$PARTIAL_BACKUP_DIR/$pvc"
  local local_size_kib

  mkdir "$copy_dir" || fail "Cannot create copy directory for PVC: $pvc"
  log_info "Copying PVC $pvc from $pod/$container:$source_path"

  if kubectl cp -n "$K8S_NAMESPACE" -c "$container" \
    "$pod:$source_path/." "$copy_dir"; then
    mv "$copy_dir" "$target_dir" || fail "Cannot finalize copied PVC directory: $pvc"
  else
    log_warn "kubectl cp failed for PVC $pvc; using kubectl exec tar streaming."
    mv "$copy_dir" "$target_dir" || fail "Cannot prepare fallback directory for PVC: $pvc"
    if ! kubectl exec -n "$K8S_NAMESPACE" "$pod" -c "$container" -- \
      tar -C "$source_path" -cf - . | tar -C "$target_dir" -xf -; then
      fail "Failed to copy PVC: $pvc"
    fi
  fi

  [ -d "$target_dir" ] || fail "Backup target was not created for PVC: $pvc"
  local_size_kib="$(measure_local_path_kib "$target_dir")" \
    || fail "Cannot measure local backup for PVC: $pvc"
  [[ "$local_size_kib" =~ ^[0-9]+$ ]] || fail "Invalid local size for PVC $pvc: $local_size_kib"
  log_pass \
    "Copied PVC $pvc: source ${SOURCE_SIZES_KIB[$index]} KiB, local $local_size_kib KiB."
}

copy_all_pvcs() {
  local index

  mkdir "$PARTIAL_BACKUP_DIR" || fail "Cannot create partial backup directory: $PARTIAL_BACKUP_DIR"
  BACKUP_STARTED="true"

  for ((index = 0; index < ${#PVC_NAMES[@]}; index++)); do
    copy_pvc "$index"
  done

  mv "$PARTIAL_BACKUP_DIR" "$FINAL_BACKUP_DIR" \
    || fail "Cannot publish backup directory: $FINAL_BACKUP_DIR"
  BACKUP_COMPLETED="true"
  log_pass "Backup complete: $FINAL_BACKUP_DIR"
}

main() {
  parse_args "$@"
  validate_local_environment

  log_warn "Stop user actions, API requests, scheduled jobs, and all other business writes before backup."
  log_warn "Keep Pods running. This script does not detect writes or ask for confirmation."

  discover_pvcs
  discover_sources
  measure_sources
  check_space
  copy_all_pvcs
}

main "$@"
