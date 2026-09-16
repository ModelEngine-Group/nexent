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
  command -v base64 >/dev/null 2>&1 || fail "base64 is not installed on the local machine."
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

decode_base64_value() {
  local encoded_value="$1"
  local decoded_value
  local reencoded_value

  if decoded_value="$(printf '%s' "$encoded_value" | base64 --decode 2>/dev/null)"; then
    :
  elif decoded_value="$(printf '%s' "$encoded_value" | base64 -D 2>/dev/null)"; then
    :
  else
    return 1
  fi

  reencoded_value="$(printf '%s' "$decoded_value" | base64 | tr -d '\r\n')" || return 1
  [ "$reencoded_value" = "$encoded_value" ] || return 1
  printf '%s' "$decoded_value"
}

is_safe_relative_path() {
  local relative_path="$1"

  case "$relative_path" in
    ""|.|..|/*|../*|*/../*|*/..|*$'\n'*|*$'\r'*|*$'\t'*)
      return 1
      ;;
  esac
  return 0
}

remote_has_tar() {
  local pod="$1"
  local container="$2"

  kubectl exec -n "$K8S_NAMESPACE" "$pod" -c "$container" -- \
    sh -c 'command -v tar >/dev/null 2>&1' >/dev/null 2>&1
}

stream_with_tar() {
  local pod="$1"
  local container="$2"
  local source_path="$3"
  local target_dir="$4"

  kubectl exec -n "$K8S_NAMESPACE" "$pod" -c "$container" -- \
    tar -C "$source_path" -cf - . | tar -C "$target_dir" -xf -
}

stream_without_tar() {
  local index="$1"
  local pvc="${PVC_NAMES[$index]}"
  local pod="${SOURCE_PODS[$index]}"
  local container="${SOURCE_CONTAINERS[$index]}"
  local source_path="${SOURCE_PATHS[$index]%/}"
  local target_dir="$2"
  local manifest_file="$PARTIAL_BACKUP_DIR/.manifest-$index"
  local manifest_script
  local entry_type
  local encoded_path
  local mode
  local encoded_link_target
  local relative_path
  local local_path
  local remote_path
  local link_target
  local directory_count=0
  local file_count=0
  local link_count=0
  local directory_index
  local directory_paths=()
  local directory_modes=()

  manifest_script='set -euo pipefail
shopt -s dotglob nullglob globstar
root="${1%/}"
[ -n "$root" ] || root="/"
[ -d "$root" ]
for path in "$root"/**; do
  relative_path="${path#"$root"/}"
  [ -n "$relative_path" ] || continue
  encoded_path="$(printf "%s" "$relative_path" | base64 | tr -d "\n")"
  mode="$(stat -c "%a" -- "$path")"
  if [ -L "$path" ]; then
    link_target="$(readlink -- "$path")"
    encoded_link_target="$(printf "%s" "$link_target" | base64 | tr -d "\n")"
    printf "l\t%s\t%s\t%s\n" "$encoded_path" "$mode" "$encoded_link_target"
  elif [ -d "$path" ]; then
    printf "d\t%s\t%s\t-\n" "$encoded_path" "$mode"
  elif [ -f "$path" ]; then
    printf "f\t%s\t%s\t-\n" "$encoded_path" "$mode"
  else
    printf "unsupported file type under %s: %s\n" "$root" "$relative_path" >&2
    exit 66
  fi
done'

  log_warn "tar is unavailable for PVC $pvc; using per-file kubectl exec streaming."
  if ! kubectl exec -n "$K8S_NAMESPACE" "$pod" -c "$container" -- \
    bash -c "$manifest_script" _ "$source_path" > "$manifest_file"; then
    return 1
  fi

  while IFS=$'\t' read -r entry_type encoded_path mode encoded_link_target; do
    [ -n "$entry_type" ] || continue
    relative_path="$(decode_base64_value "$encoded_path")" || return 1
    is_safe_relative_path "$relative_path" || return 1
    [[ "$mode" =~ ^[0-7]{3,4}$ ]] || return 1
    local_path="$target_dir/$relative_path"

    case "$entry_type" in
      d)
        mkdir -p "$local_path" || return 1
        directory_paths+=("$relative_path")
        directory_modes+=("$mode")
        directory_count=$((directory_count + 1))
        ;;
      f)
        mkdir -p "$(dirname "$local_path")" || return 1
        [ ! -e "$local_path" ] && [ ! -L "$local_path" ] || return 1
        remote_path="$source_path/$relative_path"
        if ! kubectl exec -n "$K8S_NAMESPACE" "$pod" -c "$container" -- \
          cat "$remote_path" > "$local_path"; then
          return 1
        fi
        chmod "$mode" "$local_path" || return 1
        file_count=$((file_count + 1))
        ;;
      l)
        mkdir -p "$(dirname "$local_path")" || return 1
        [ ! -e "$local_path" ] && [ ! -L "$local_path" ] || return 1
        link_target="$(decode_base64_value "$encoded_link_target")" || return 1
        ln -s "$link_target" "$local_path" || return 1
        link_count=$((link_count + 1))
        ;;
      *)
        return 1
        ;;
    esac
  done < "$manifest_file"

  for ((directory_index = ${#directory_paths[@]} - 1; directory_index >= 0; directory_index--)); do
    chmod \
      "${directory_modes[$directory_index]}" \
      "$target_dir/${directory_paths[$directory_index]}" \
      || return 1
  done

  rm -f "$manifest_file" || return 1
  log_pass \
    "Streamed PVC $pvc without tar: $directory_count directories, $file_count files, $link_count links."
}

copy_pvc() {
  local index="$1"
  local pvc="${PVC_NAMES[$index]}"
  local pod="${SOURCE_PODS[$index]}"
  local container="${SOURCE_CONTAINERS[$index]}"
  local source_path="${SOURCE_PATHS[$index]%/}"
  local copy_dir="$PARTIAL_BACKUP_DIR/.copy-$index"
  local fallback_dir="$PARTIAL_BACKUP_DIR/.fallback-$index"
  local target_dir="$PARTIAL_BACKUP_DIR/$pvc"
  local local_size_kib

  mkdir "$copy_dir" || fail "Cannot create copy directory for PVC: $pvc"
  log_info "Copying PVC $pvc from $pod/$container:$source_path"

  if kubectl cp -n "$K8S_NAMESPACE" -c "$container" \
    "$pod:$source_path/." "$copy_dir"; then
    mv "$copy_dir" "$target_dir" || fail "Cannot finalize copied PVC directory: $pvc"
  else
    log_warn "kubectl cp failed for PVC $pvc; using kubectl exec streaming."
    rm -rf "$copy_dir" || fail "Cannot discard the failed kubectl cp output for PVC: $pvc"
    mkdir "$fallback_dir" || fail "Cannot create fallback directory for PVC: $pvc"

    if remote_has_tar "$pod" "$container"; then
      log_info "Streaming PVC $pvc with kubectl exec tar."
      if ! stream_with_tar "$pod" "$container" "$source_path" "$fallback_dir"; then
        log_warn "tar streaming failed for PVC $pvc; trying per-file streaming."
        rm -rf "$fallback_dir" || fail "Cannot reset the fallback directory for PVC: $pvc"
        mkdir "$fallback_dir" || fail "Cannot recreate the fallback directory for PVC: $pvc"
        stream_without_tar "$index" "$fallback_dir" || fail "Failed to copy PVC: $pvc"
      fi
    else
      stream_without_tar "$index" "$fallback_dir" || fail "Failed to copy PVC: $pvc"
    fi
    mv "$fallback_dir" "$target_dir" || fail "Cannot finalize fallback PVC directory: $pvc"
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
