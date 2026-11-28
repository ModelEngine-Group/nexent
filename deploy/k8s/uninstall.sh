#!/bin/bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
# Helm uninstall script for Nexent.

if [ -z "$BASH_VERSION" ]; then
  echo "This script must be run with bash. Please use: bash uninstall.sh or ./uninstall.sh"
  exit 1
fi

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOYMENT_COMMON="$PROJECT_ROOT/deploy/common/common.sh"
DEPLOY_OPTIONS_FILE="$SCRIPT_DIR/deploy.options"
cd "$SCRIPT_DIR"

if [ -f "$DEPLOYMENT_COMMON" ]; then
  # shellcheck source=/dev/null
  source "$DEPLOYMENT_COMMON"
fi

NAMESPACE="nexent"
APPLICATION_RELEASE_NAME="nexent"
INFRASTRUCTURE_RELEASE_NAME="nexent-infrastructure"
RELEASE_SCOPE="all"
DELETE_DATA=""
DELETE_PVC=""
DELETE_NAMESPACE=""
DELETE_LOCAL_DATA=""
LOCAL_DATA_DELETED="false"
PERSISTENCE_MODE=""
COMMAND="uninstall"
DYNAMIC_PVC_NAMES=()
DYNAMIC_PVC_UIDS=()
DYNAMIC_PVCS_WITHOUT_KEEP=()

print_usage() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "用法：$0 [delete|delete-all|clean] [选项]"
    echo ""
    echo "卸载 Nexent K8s 资源。"
    echo ""
    echo "命令："
    echo "  delete       卸载 Helm release 并请求删除 namespace"
    echo "  delete-all   卸载 Helm release、请求删除 namespace，并在 local 模式下删除本地数据"
    echo "  clean        仅清理 Helm release 状态"
    echo ""
    echo "选项："
    echo "  --delete-data true|false        兼容选项，控制 Helm 卸载失败后的清理行为"
    echo "  --delete-volumes true|false     等同于 --delete-data"
    echo "  --remove-volumes                等同于 --delete-data true"
    echo "  --keep-volumes                  等同于 --delete-data false"
    echo "  --delete-pvc true|false         删除或保留所选 release 的动态 PVC（默认保留）"
    echo "  --delete-local-data true|false  控制是否删除本地 PV 数据（仅 local 模式）"
    echo "  --remove-local-data             等同于 --delete-local-data true（仅 local 模式）"
    echo "  --keep-local-data               等同于 --delete-local-data false（仅 local 模式）"
    echo "  --delete-namespace true|false   控制是否删除 namespace"
    echo "  --remove-namespace              等同于 --delete-namespace true"
    echo "  --keep-namespace                等同于 --delete-namespace false"
    echo "  --namespace NAME                Kubernetes namespace（默认：nexent）"
    echo "  --release-scope SCOPE           all、infrastructure 或 nexent（默认：all）"
    echo "  --help, -h                      显示帮助信息"
    echo ""
    echo "示例："
    echo "  bash uninstall.sh"
    echo "  bash uninstall.sh --delete-data false"
    echo "  bash uninstall.sh --release-scope nexent --keep-namespace"
    echo "  bash uninstall.sh --release-scope infrastructure --keep-namespace"
    echo "  bash uninstall.sh --delete-data true"
    echo "  bash uninstall.sh --delete-pvc true --keep-namespace"
    echo "  bash uninstall.sh --delete-local-data true"
    echo "  bash uninstall.sh --keep-local-data"
    echo "  bash uninstall.sh --keep-namespace"
    echo "  bash uninstall.sh --delete-namespace true"
    echo "  bash uninstall.sh delete-all"
    echo "  bash uninstall.sh delete-all --keep-local-data"
    echo "  bash uninstall.sh clean"
    return
  fi

  echo "Usage: $0 [delete|delete-all|clean] [options]"
  echo ""
  echo "Uninstall Nexent K8s resources."
  echo ""
  echo "Commands:"
  echo "  delete       Uninstall Helm release and request namespace deletion"
  echo "  delete-all   Uninstall Helm release, request namespace deletion, and delete local data in local mode"
  echo "  clean        Clean Helm release state only"
  echo ""
  echo "Options:"
  echo "  --delete-data true|false     Compatibility option for cleanup after Helm uninstall fails"
  echo "  --delete-volumes true|false  Alias for --delete-data"
  echo "  --remove-volumes             Alias for --delete-data true"
  echo "  --keep-volumes               Alias for --delete-data false"
  echo "  --delete-pvc true|false      Delete or keep dynamic PVCs in the selected release scope (default: keep)"
  echo "  --delete-local-data true|false  Control whether local PV data is deleted (local mode only)"
  echo "  --remove-local-data             Alias for --delete-local-data true (local mode only)"
  echo "  --keep-local-data               Alias for --delete-local-data false (local mode only)"
  echo "  --delete-namespace true|false  Control whether the namespace is deleted"
  echo "  --remove-namespace             Alias for --delete-namespace true"
  echo "  --keep-namespace               Alias for --delete-namespace false"
  echo "  --namespace NAME             Kubernetes namespace (default: nexent)"
  echo "  --release-scope SCOPE        all, infrastructure, or nexent (default: all)"
  echo "  --help, -h                   Show this help message"
  echo ""
  echo "Examples:"
  echo "  bash uninstall.sh"
  echo "  bash uninstall.sh --delete-data false"
  echo "  bash uninstall.sh --release-scope nexent --keep-namespace"
  echo "  bash uninstall.sh --release-scope infrastructure --keep-namespace"
  echo "  bash uninstall.sh --delete-data true"
  echo "  bash uninstall.sh --delete-pvc true --keep-namespace"
  echo "  bash uninstall.sh --delete-local-data true"
  echo "  bash uninstall.sh --keep-local-data"
  echo "  bash uninstall.sh --keep-namespace"
  echo "  bash uninstall.sh --delete-namespace true"
  echo "  bash uninstall.sh delete-all"
  echo "  bash uninstall.sh delete-all --keep-local-data"
  echo "  bash uninstall.sh clean"
}

sanitize_input() {
  local input="$1"
  printf "%s" "$input" | tr -d '\r'
}

trim_deploy_option() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

unquote_deploy_option() {
  local value
  value="$(trim_deploy_option "$1")"
  value="${value%$'\r'}"
  value="${value%%#*}"
  value="$(trim_deploy_option "$value")"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "$value"
}

load_persistence_mode() {
  local line trimmed value in_k8s_section
  [ -f "$DEPLOY_OPTIONS_FILE" ] || return 0

  in_k8s_section="false"
  while IFS= read -r line || [ -n "$line" ]; do
    trimmed="$(trim_deploy_option "${line%%#*}")"
    [ -z "$trimmed" ] && continue

    if [[ "$trimmed" =~ ^PERSISTENCE_MODE=(.*)$ ]]; then
      PERSISTENCE_MODE="$(unquote_deploy_option "${BASH_REMATCH[1]}")"
      continue
    fi

    if [[ "$trimmed" =~ ^k8s:[[:space:]]*$ ]]; then
      in_k8s_section="true"
      continue
    fi

    if [[ "$line" =~ ^[A-Za-z][A-Za-z0-9_]*:[[:space:]]* ]]; then
      in_k8s_section="false"
      continue
    fi

    if [ "$in_k8s_section" = "true" ] \
      && [[ "$line" =~ ^[[:space:]]+persistenceMode:[[:space:]]*(.*)$ ]]; then
      value="$(unquote_deploy_option "${BASH_REMATCH[1]}")"
      PERSISTENCE_MODE="$value"
    fi
  done < "$DEPLOY_OPTIONS_FILE"
}

parse_bool_option() {
  local value
  value="$(sanitize_input "${1:-}")"
  case "$value" in
    true|TRUE|True|yes|YES|Yes|y|Y|1) return 0 ;;
    false|FALSE|False|no|NO|No|n|N|0) return 1 ;;
    *)
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "无效布尔值：$value。请使用 true 或 false。"
      else
        echo "Invalid boolean value: $value. Use true or false."
      fi
      exit 1
      ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    delete)
      COMMAND="uninstall"
      DELETE_DATA="false"
      DELETE_NAMESPACE="true"
      shift
      ;;
    delete-all)
      COMMAND="uninstall"
      DELETE_DATA="true"
      DELETE_NAMESPACE="true"
      DELETE_LOCAL_DATA="true"
      shift
      ;;
    clean)
      COMMAND="clean"
      shift
      ;;
    --delete-data|--delete-volumes)
      DELETE_DATA="$2"
      shift 2
      ;;
    --remove-volumes)
      DELETE_DATA="true"
      shift
      ;;
    --keep-volumes)
      DELETE_DATA="false"
      shift
      ;;
    --delete-pvc)
      if [ "$#" -lt 2 ]; then
        echo "Error: --delete-pvc requires true or false." >&2
        exit 1
      fi
      if parse_bool_option "$2"; then
        DELETE_PVC="true"
      else
        DELETE_PVC="false"
      fi
      shift 2
      ;;
    --delete-local-data)
      DELETE_LOCAL_DATA="$2"
      shift 2
      ;;
    --remove-local-data)
      DELETE_LOCAL_DATA="true"
      shift
      ;;
    --keep-local-data)
      DELETE_LOCAL_DATA="false"
      shift
      ;;
    --delete-namespace)
      DELETE_NAMESPACE="$2"
      shift 2
      ;;
    --remove-namespace)
      DELETE_NAMESPACE="true"
      shift
      ;;
    --keep-namespace)
      DELETE_NAMESPACE="false"
      shift
      ;;
    --namespace)
      NAMESPACE="$2"
      shift 2
      ;;
    --release-scope)
      RELEASE_SCOPE="$2"
      shift 2
      ;;
    --release)
      APPLICATION_RELEASE_NAME="$2"
      shift 2
      ;;
    --help|-h)
      print_usage
      exit 0
      ;;
    *)
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "未知选项：$1"
      else
        echo "Unknown option: $1"
      fi
      print_usage
      exit 1
      ;;
  esac
done

load_persistence_mode

case "$RELEASE_SCOPE" in
  all|infrastructure|nexent) ;;
  *)
    echo "Error: --release-scope must be all, infrastructure, or nexent."
    exit 1
    ;;
esac

if [ "$APPLICATION_RELEASE_NAME" != "nexent" ]; then
  INFRASTRUCTURE_RELEASE_NAME="${APPLICATION_RELEASE_NAME}-infrastructure"
fi

helm_release_exists() {
  local release_name="$1"
  helm status "$release_name" --namespace "$NAMESPACE" >/dev/null 2>&1
}

guard_infrastructure_uninstall() {
  if [ "$RELEASE_SCOPE" = "infrastructure" ] && helm_release_exists "$APPLICATION_RELEASE_NAME"; then
    echo "Error: cannot uninstall '$INFRASTRUCTURE_RELEASE_NAME' while '$APPLICATION_RELEASE_NAME' still exists."
    echo "Uninstall the Nexent release first or use --release-scope all."
    return 1
  fi
}

# Nexent's static claims specify a volumeName in the stored Helm manifest.
manifest_pvc_policies() {
  awk '
    function emit() {
      if (kind == "PersistentVolumeClaim" && name != "") {
        print name "|" (static_volume ? "local" : "dynamic") "|" (keep ? "keep" : "delete")
      }
    }
    /^---([[:space:]]|$)/ { emit(); kind = name = section = ""; static_volume = keep = 0; next }
    /^Error: / && kind == "" { print; next }
    /^kind:[[:space:]]/ { kind = $2 }
    /^[[:alpha:]][^:]*:/ { section = $1 }
    section == "metadata:" && /^  name:[[:space:]]/ { name = $2; gsub(/["\047\r]/, "", name) }
    section == "metadata:" && /^    helm\.sh\/resource-policy:[[:space:]]/ {
      policy = $2; gsub(/["\047\r]/, "", policy); keep = (policy == "keep")
    }
    section == "spec:" && /^  volumeName:[[:space:]]/ {
      volume = $2; gsub(/["\047\r]/, "", volume); static_volume = (volume != "")
    }
    END { emit() }
  '
}

discover_dynamic_pvcs() {
  local live_claims release manifest_claims name uid owner owner_namespace mode manifest_entry manifest_mode policy
  local releases=()
  [ "$RELEASE_SCOPE" = "infrastructure" ] || releases+=("$APPLICATION_RELEASE_NAME")
  [ "$RELEASE_SCOPE" = "nexent" ] || releases+=("$INFRASTRUCTURE_RELEASE_NAME")

  live_claims=$(kubectl get pvc -n "$NAMESPACE" --ignore-not-found -o \
    'jsonpath={range .items[*]}{.metadata.name}{"|"}{.metadata.uid}{"|"}{.metadata.annotations.meta\.helm\.sh/release-name}{"|"}{.metadata.annotations.meta\.helm\.sh/release-namespace}{"|"}{.metadata.labels.nexent\.io/persistence-mode}{"\n"}{end}') || return 1
  for release in "${releases[@]}"; do
    if ! manifest_claims=$(set -o pipefail; helm get manifest "$release" --namespace "$NAMESPACE" 2>&1 | manifest_pvc_policies); then
      if ! grep -qiE 'release: not found|release "[^"]+" not found' <<< "$manifest_claims"; then
        printf 'Error: unable to read the Helm manifest for %s. %s\n' "$release" "$manifest_claims" >&2
        return 1
      fi
      manifest_claims=""
    fi

    while IFS='|' read -r name uid owner owner_namespace mode; do
      [ "$owner" = "$release" ] && [ "$owner_namespace" = "$NAMESPACE" ] || continue
      manifest_entry=$(awk -F '|' -v name="$name" '$1 == name {print $2 "|" $3; exit}' <<< "$manifest_claims")
      IFS='|' read -r manifest_mode policy <<< "$manifest_entry"
      [ "$mode" = "dynamic" ] || [ "$manifest_mode" = "dynamic" ] || continue
      if [[ ! "$uid" =~ ^[a-zA-Z0-9-]+$ ]]; then
        printf 'Error: unable to identify PVC %s/%s by UID.\n' "$NAMESPACE" "$name" >&2
        return 1
      fi
      DYNAMIC_PVC_NAMES+=("$name")
      DYNAMIC_PVC_UIDS+=("$uid")
      if [ "$policy" = "delete" ]; then
        DYNAMIC_PVCS_WITHOUT_KEEP+=("$release/$name")
      fi
    done <<< "$live_claims"
  done
}

resolve_delete_pvcs() {
  if [ -n "$DELETE_PVC" ]; then
    [ "$DELETE_PVC" = "true" ]
    return
  fi
  [ "$COMMAND" = "uninstall" ] && [ "${#DYNAMIC_PVC_NAMES[@]}" -gt 0 ] && [ -t 0 ] || return 1
  local answer
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    IFS= read -r -p "删除所选 release 的动态 PVC？这可能删除卷中的数据。直接回车保留，输入小写 y 删除。[y/N]：" answer || return 1
  else
    IFS= read -r -p "Delete dynamic PVCs for the selected releases? This can delete volume data. Press Enter to keep them or type lowercase y to delete. [y/N]: " answer || return 1
  fi
  [ "${answer%$'\r'}" = "y" ]
}

prepare_dynamic_pvcs() {
  discover_dynamic_pvcs || return 1
  if resolve_delete_pvcs; then
    if [ "$COMMAND" = "clean" ]; then
      echo "Error: --delete-pvc true requires an uninstall command." >&2
      return 1
    fi
    DELETE_PVC="true"
  else
    DELETE_PVC="false"
    if [ "${#DYNAMIC_PVCS_WITHOUT_KEEP[@]}" -gt 0 ]; then
      printf 'Error: the installed Helm release lacks a keep policy for these dynamic PVCs: %s\n' \
        "${DYNAMIC_PVCS_WITHOUT_KEEP[*]}" >&2
      echo "Upgrade the release with the current chart before uninstalling to preserve these PVCs." >&2
      return 1
    fi
  fi
  if [ "${#DYNAMIC_PVC_NAMES[@]}" -gt 0 ] && [ -z "$PERSISTENCE_MODE" ]; then
    PERSISTENCE_MODE="dynamic"
  fi
}

cleanup_dynamic_pvcs() {
  [ "${#DYNAMIC_PVC_NAMES[@]}" -gt 0 ] || return 0
  if [ "$DELETE_PVC" = "false" ]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "动态 PVC 已保留：${DYNAMIC_PVC_NAMES[*]}"
    else
      echo "Preserved dynamic PVCs: ${DYNAMIC_PVC_NAMES[*]}"
    fi
    return 0
  fi

  local index name uid output
  for index in "${!DYNAMIC_PVC_NAMES[@]}"; do
    name="${DYNAMIC_PVC_NAMES[index]}"
    uid="${DYNAMIC_PVC_UIDS[index]}"
    # A claim recreated after discovery has a different UID.
    if ! output=$(kubectl delete --raw "/api/v1/namespaces/$NAMESPACE/persistentvolumeclaims/$name" -f - 2>&1 <<< \
      "{\"apiVersion\":\"v1\",\"kind\":\"DeleteOptions\",\"preconditions\":{\"uid\":\"$uid\"}}"); then
      if ! grep -qi '(NotFound)' <<< "$output"; then
        printf 'Error: unable to delete PVC %s/%s. %s\n' "$NAMESPACE" "$name" "$output" >&2
        return 1
      fi
    else
      printf 'Requested deletion of PVC %s/%s\n' "$NAMESPACE" "$name"
    fi
  done
}

clean_one_helm_release_state() {
  local release_name="$1"
  helm uninstall "$release_name" -n "$NAMESPACE" --no-hooks 2>/dev/null || true
  kubectl delete secret -n "$NAMESPACE" -l "name=$release_name" --ignore-not-found=true 2>/dev/null || true
}

clean_helm_state() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "正在清理 Helm release 状态..."
  else
    echo "Cleaning Helm release state..."
  fi
  guard_infrastructure_uninstall || return 1
  if [ "$RELEASE_SCOPE" = "all" ] || [ "$RELEASE_SCOPE" = "nexent" ]; then
    clean_one_helm_release_state "$APPLICATION_RELEASE_NAME"
  fi
  if [ "$RELEASE_SCOPE" = "all" ] || [ "$RELEASE_SCOPE" = "infrastructure" ]; then
    clean_one_helm_release_state "$INFRASTRUCTURE_RELEASE_NAME"
  fi
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "Helm 状态已清理。"
  else
    echo "Helm state cleaned."
  fi
}

helm_uninstall_release() {
  local release_name="$1"
  local output
  local status
  if output=$(helm uninstall "$release_name" --namespace "$NAMESPACE" 2>&1); then
    [ -z "$output" ] || printf '%s\n' "$output"
    return 0
  else
    status=$?
  fi

  [ -z "$output" ] || printf '%s\n' "$output"
  if printf '%s\n' "$output" | grep -qi 'not found'; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "Helm release '$release_name' 已不存在；继续清理。"
    else
      echo "Helm release '$release_name' is already absent; continuing cleanup."
    fi
    return 0
  fi

  return "$status"
}

helm_uninstall_scoped_releases() {
  guard_infrastructure_uninstall || return 1

  if [ "$RELEASE_SCOPE" = "all" ] || [ "$RELEASE_SCOPE" = "nexent" ]; then
    helm_uninstall_release "$APPLICATION_RELEASE_NAME" || return 1
  fi
  if [ "$RELEASE_SCOPE" = "all" ] || [ "$RELEASE_SCOPE" = "infrastructure" ]; then
    helm_uninstall_release "$INFRASTRUCTURE_RELEASE_NAME" || return 1
  fi
}

delete_namespace_after_uninstall() {
  if [ "$RELEASE_SCOPE" != "all" ]; then
    echo "Error: namespace deletion is only allowed with --release-scope all."
    return 1
  fi
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "正在删除 namespace..."
  else
    echo "Deleting namespace..."
  fi
  kubectl delete namespace "$NAMESPACE" --ignore-not-found=true || true
}

resolve_delete_namespace() {
  if [ -n "$DELETE_NAMESPACE" ]; then
    parse_bool_option "$DELETE_NAMESPACE"
    return $?
  fi

  [ -t 0 ] || return 1

  echo ""
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "是否删除 Kubernetes namespace '$NAMESPACE'？"
  else
    echo "Delete Kubernetes namespace '$NAMESPACE'?"
  fi
  local answer
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    read -r -p "删除 namespace？[y/N]：" answer
  else
    read -r -p "Delete namespace? [y/N]: " answer
  fi
  answer="$(sanitize_input "$answer")"
  [[ "$answer" =~ ^[Yy]$ ]]
}

maybe_delete_namespace_after_uninstall() {
  if [ "$DELETE_PVC" = "false" ] && [ "${#DYNAMIC_PVC_NAMES[@]}" -gt 0 ]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "Namespace '$NAMESPACE' 已保留，以保留动态 PVC。"
    else
      echo "Namespace '$NAMESPACE' preserved with its dynamic PVCs."
    fi
  elif [ "$RELEASE_SCOPE" = "all" ] && resolve_delete_namespace; then
    delete_namespace_after_uninstall
  else
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "Namespace '$NAMESPACE' 已保留。"
    else
      echo "Namespace '$NAMESPACE' preserved."
    fi
  fi
}

validate_scope_options() {
  if [ "$RELEASE_SCOPE" != "all" ] && [ -n "$DELETE_NAMESPACE" ] && parse_bool_option "$DELETE_NAMESPACE"; then
    echo "Error: --delete-namespace true is only allowed with --release-scope all."
    return 1
  fi
}

local_volume_paths() {
  if [ "$RELEASE_SCOPE" = "all" ] || [ "$RELEASE_SCOPE" = "nexent" ]; then
    printf '%s\n' \
      "/var/lib/nexent" \
      "/var/lib/nexent-data/skills" \
      "/var/lib/nexent-data/logs" \
      "/var/lib/nexent-data/project-config" \
      "/var/lib/nexent-data/nexent-ssh-keys" \
      "/var/lib/nexent-data/nexent-supabase-db" \
      "/var/lib/nexent-data/nexent-phoenix" \
      "/var/lib/nexent-data/nexent-grafana" \
      "/var/lib/nexent-data/nexent-tempo" \
      "/var/lib/nexent-data/nexent-langfuse-postgres" \
      "/var/lib/nexent-data/nexent-langfuse-clickhouse" \
      "/var/lib/nexent-data/nexent-langfuse-clickhouse-logs" \
      "/var/lib/nexent-data/nexent-langfuse-minio" \
      "/var/lib/nexent-data/nexent-langfuse-redis"
  fi
  if [ "$RELEASE_SCOPE" = "all" ] || [ "$RELEASE_SCOPE" = "infrastructure" ]; then
    printf '%s\n' \
      "/var/lib/nexent-data/nexent-elasticsearch" \
      "/var/lib/nexent-data/nexent-postgresql" \
      "/var/lib/nexent-data/nexent-redis" \
      "/var/lib/nexent-data/nexent-minio"
  fi
}

resolve_delete_local_data() {
  if [ -n "$DELETE_LOCAL_DATA" ]; then
    parse_bool_option "$DELETE_LOCAL_DATA"
    return $?
  fi

  [ -t 0 ] || return 1

  echo ""
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "是否删除 /var/lib/nexent 和 /var/lib/nexent-data 下的本地 PV 数据？"
  else
    echo "Delete local PV data under /var/lib/nexent and /var/lib/nexent-data?"
  fi
  local answer
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    read -r -p "删除本地 volume 数据？[y/N]：" answer
  else
    read -r -p "Delete local volume data? [y/N]: " answer
  fi
  answer="$(sanitize_input "$answer")"
  [[ "$answer" =~ ^[Yy]$ ]]
}

delete_local_volume_data() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "正在删除本地 PV 数据..."
  else
    echo "Deleting local PV data..."
  fi

  local path
  while IFS= read -r path; do
    case "$path" in
      /var/lib/nexent|/var/lib/nexent-data/skills|/var/lib/nexent-data/logs|/var/lib/nexent-data/project-config|/var/lib/nexent-data/nexent-*)
        if [ -e "$path" ]; then
          if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
            echo "正在删除 $path"
          else
            echo "Removing $path"
          fi
          rm -rf -- "$path"
        fi
        ;;
      *)
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
          echo "拒绝删除不安全路径：$path"
        else
          echo "Refusing to remove unsafe path: $path"
        fi
        return 1
      ;;
    esac
  done < <(local_volume_paths)
  LOCAL_DATA_DELETED="true"
}

maybe_delete_local_volume_data() {
  case "$PERSISTENCE_MODE" in
    dynamic|existing)
      if [ -n "$DELETE_LOCAL_DATA" ]; then
        parse_bool_option "$DELETE_LOCAL_DATA" || true
      fi
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "持久化模式为 '$PERSISTENCE_MODE'，跳过本地 PV 目录清理。"
      else
        echo "Persistence mode is '$PERSISTENCE_MODE'; skipping local PV directory cleanup."
      fi
      return 0
      ;;
  esac

  if resolve_delete_local_data; then
    delete_local_volume_data
  else
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "本地 PV 数据已保留。"
    else
      echo "Local PV data preserved."
    fi
  fi
}

cleanup_leftover_data_process_resources() {
  if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
    return 0
  fi

  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "正在清理残留的 nexent-data-process 资源..."
  else
    echo "Cleaning up leftover nexent-data-process resources..."
  fi
  kubectl delete deployment nexent-data-process -n "$NAMESPACE" --ignore-not-found=true 2>/dev/null || true
  kubectl delete service nexent-data-process -n "$NAMESPACE" --ignore-not-found=true 2>/dev/null || true
  kubectl delete rs,pod -n "$NAMESPACE" -l app=nexent-data-process --ignore-not-found=true 2>/dev/null || true
}

cleanup_leftover_monitoring_resources() {
  if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
    return 0
  fi

  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "正在清理残留的 monitoring 资源..."
  else
    echo "Cleaning up leftover monitoring resources..."
  fi
  local app
  for app in \
    nexent-otel-collector \
    nexent-phoenix \
    nexent-tempo \
    nexent-grafana \
    nexent-zipkin \
    nexent-langfuse-postgres \
    nexent-langfuse-clickhouse \
    nexent-langfuse-minio \
    nexent-langfuse-redis \
    nexent-langfuse-web \
    nexent-langfuse-worker
  do
    kubectl delete deployment,service,configmap,rs,pod -n "$NAMESPACE" -l app="$app" --ignore-not-found=true 2>/dev/null || true
  done
}

cleanup_leftover_nexent_resources() {
  if [ "$RELEASE_SCOPE" = "all" ] || [ "$RELEASE_SCOPE" = "nexent" ]; then
    cleanup_leftover_data_process_resources
    cleanup_leftover_monitoring_resources
  fi
}

uninstall_preserve_data() {
  guard_infrastructure_uninstall || return 1
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "正在卸载 Helm release..."
  else
    echo "Uninstalling Helm release..."
  fi
  if ! helm_uninstall_scoped_releases; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "Helm 卸载失败；继续尽力清理已知 Nexent 资源。"
    else
      echo "Helm uninstall failed; continuing best-effort cleanup of known Nexent resources."
    fi
  fi
  cleanup_leftover_nexent_resources
  cleanup_dynamic_pvcs || return 1
  maybe_delete_local_volume_data
  maybe_delete_namespace_after_uninstall
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "清理完成。Helm 托管资源已删除。"
  else
    echo "Cleanup completed. Helm-managed resources were removed."
  fi
  if [ "$LOCAL_DATA_DELETED" = "true" ]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "重新运行 './deploy.sh' 可使用全新的本地数据部署。"
    else
      echo "Re-run './deploy.sh' to redeploy with fresh local data."
    fi
  else
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "重新运行 './deploy.sh' 可使用现有数据部署。"
    else
      echo "Re-run './deploy.sh' to redeploy with existing data."
    fi
  fi
}

delete_all_data() {
  guard_infrastructure_uninstall || return 1
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "正在删除 Helm release..."
  else
    echo "Deleting Helm release..."
  fi
  if ! helm_uninstall_scoped_releases; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "Helm 卸载失败。Namespace 未删除。"
    else
      echo "Helm uninstall failed. Namespace was not deleted."
    fi
    cleanup_leftover_nexent_resources
    return 1
  fi
  cleanup_leftover_nexent_resources
  cleanup_dynamic_pvcs || return 1
  maybe_delete_local_volume_data
  maybe_delete_namespace_after_uninstall
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "清理完成。"
  else
    echo "Cleanup completed."
  fi
}

case "$COMMAND" in
  clean)
    validate_scope_options
    guard_infrastructure_uninstall
    prepare_dynamic_pvcs
    clean_helm_state
    ;;
  uninstall)
    validate_scope_options
    guard_infrastructure_uninstall
    prepare_dynamic_pvcs
    if { [ -n "$DELETE_DATA" ] && parse_bool_option "$DELETE_DATA"; } || [ "$DELETE_PVC" = "true" ]; then
      delete_all_data
    else
      uninstall_preserve_data
    fi
    ;;
esac
