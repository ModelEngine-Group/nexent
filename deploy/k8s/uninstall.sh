#!/bin/bash
# Helm uninstall script for Nexent.

if [ -z "$BASH_VERSION" ]; then
  echo "This script must be run with bash. Please use: bash uninstall.sh or ./uninstall.sh"
  exit 1
fi

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOYMENT_COMMON="$PROJECT_ROOT/deploy/common/common.sh"
cd "$SCRIPT_DIR"

if [ -f "$DEPLOYMENT_COMMON" ]; then
  # shellcheck source=/dev/null
  source "$DEPLOYMENT_COMMON"
fi

NAMESPACE="nexent"
RELEASE_NAME="nexent"
DELETE_DATA=""
DELETE_NAMESPACE=""
DELETE_LOCAL_DATA=""
LOCAL_DATA_DELETED="false"
COMMAND="uninstall"

print_usage() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "用法：$0 [delete|delete-all|clean] [选项]"
    echo ""
    echo "卸载 Nexent K8s 资源。"
    echo ""
    echo "命令："
    echo "  delete       卸载 Helm release 并删除 namespace"
    echo "  delete-all   卸载 Helm release、删除 namespace，并删除本地数据"
    echo "  clean        仅清理 Helm release 状态"
    echo ""
    echo "选项："
    echo "  --delete-data true|false        兼容选项；Helm 会删除托管的 PV/PVC 资源"
    echo "  --delete-volumes true|false     等同于 --delete-data"
    echo "  --remove-volumes                等同于 --delete-data true"
    echo "  --keep-volumes                  等同于 --delete-data false"
    echo "  --delete-local-data true|false  控制是否删除本地 PV 数据"
    echo "  --remove-local-data             等同于 --delete-local-data true"
    echo "  --keep-local-data               等同于 --delete-local-data false"
    echo "  --delete-namespace true|false   控制是否删除 namespace"
    echo "  --remove-namespace              等同于 --delete-namespace true"
    echo "  --keep-namespace                等同于 --delete-namespace false"
    echo "  --namespace NAME                Kubernetes namespace（默认：nexent）"
    echo "  --release NAME                  Helm release 名称（默认：nexent）"
    echo "  --help, -h                      显示帮助信息"
    echo ""
    echo "示例："
    echo "  bash uninstall.sh"
    echo "  bash uninstall.sh --delete-data false"
    echo "  bash uninstall.sh --delete-data true"
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
  echo "  delete       Uninstall Helm release and delete namespace"
  echo "  delete-all   Uninstall Helm release, delete namespace, and delete local data"
  echo "  clean        Clean Helm release state only"
  echo ""
  echo "Options:"
  echo "  --delete-data true|false     Compatibility option; Helm removes managed PV/PVC resources"
  echo "  --delete-volumes true|false  Alias for --delete-data"
  echo "  --remove-volumes             Alias for --delete-data true"
  echo "  --keep-volumes               Alias for --delete-data false"
  echo "  --delete-local-data true|false  Control whether local PV data is deleted"
  echo "  --remove-local-data             Alias for --delete-local-data true"
  echo "  --keep-local-data               Alias for --delete-local-data false"
  echo "  --delete-namespace true|false  Control whether the namespace is deleted"
  echo "  --remove-namespace             Alias for --delete-namespace true"
  echo "  --keep-namespace               Alias for --delete-namespace false"
  echo "  --namespace NAME             Kubernetes namespace (default: nexent)"
  echo "  --release NAME               Helm release name (default: nexent)"
  echo "  --help, -h                   Show this help message"
  echo ""
  echo "Examples:"
  echo "  bash uninstall.sh"
  echo "  bash uninstall.sh --delete-data false"
  echo "  bash uninstall.sh --delete-data true"
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
    --release)
      RELEASE_NAME="$2"
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

clean_helm_state() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "正在清理 Helm release 状态..."
  else
    echo "Cleaning Helm release state..."
  fi
  helm uninstall "$RELEASE_NAME" -n "$NAMESPACE" --no-hooks 2>/dev/null || true
  kubectl delete secret -n "$NAMESPACE" -l "owner=helm" --ignore-not-found=true 2>/dev/null || true
  kubectl delete secret -n "$NAMESPACE" --field-selector type=helm.sh/release.v1 --ignore-not-found=true 2>/dev/null || true
  kubectl delete secret -n "$NAMESPACE" -l "name=$RELEASE_NAME" --ignore-not-found=true 2>/dev/null || true
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "Helm 状态已清理。"
  else
    echo "Helm state cleaned."
  fi
}

helm_uninstall_release() {
  local output
  if output=$(helm uninstall "$RELEASE_NAME" --namespace "$NAMESPACE" 2>&1); then
    [ -z "$output" ] || printf '%s\n' "$output"
    return 0
  fi

  local status=$?
  [ -z "$output" ] || printf '%s\n' "$output"
  if printf '%s\n' "$output" | grep -qi 'not found'; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "Helm release '$RELEASE_NAME' 已不存在；继续清理。"
    else
      echo "Helm release '$RELEASE_NAME' is already absent; continuing cleanup."
    fi
    return 0
  fi

  return "$status"
}

delete_namespace_after_uninstall() {
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
  if resolve_delete_namespace; then
    delete_namespace_after_uninstall
  else
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "Namespace '$NAMESPACE' 已保留。"
    else
      echo "Namespace '$NAMESPACE' preserved."
    fi
  fi
}

local_volume_paths() {
  printf '%s\n' \
    "/var/lib/nexent" \
    "/var/lib/nexent-data/skills" \
    "/var/lib/nexent-data/nexent-elasticsearch" \
    "/var/lib/nexent-data/nexent-postgresql" \
    "/var/lib/nexent-data/nexent-redis" \
    "/var/lib/nexent-data/nexent-minio" \
    "/var/lib/nexent-data/nexent-supabase-db" \
    "/var/lib/nexent-data/nexent-phoenix" \
    "/var/lib/nexent-data/nexent-grafana" \
    "/var/lib/nexent-data/nexent-tempo" \
    "/var/lib/nexent-data/nexent-langfuse-postgres" \
    "/var/lib/nexent-data/nexent-langfuse-clickhouse" \
    "/var/lib/nexent-data/nexent-langfuse-clickhouse-logs" \
    "/var/lib/nexent-data/nexent-langfuse-minio" \
    "/var/lib/nexent-data/nexent-langfuse-redis"
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
      /var/lib/nexent|/var/lib/nexent-data/skills|/var/lib/nexent-data/nexent-*)
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
  cleanup_leftover_data_process_resources
  cleanup_leftover_monitoring_resources
}

uninstall_preserve_data() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "正在卸载 Helm release..."
  else
    echo "Uninstalling Helm release..."
  fi
  if ! helm_uninstall_release; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "Helm 卸载失败；继续尽力清理已知 Nexent 资源。"
    else
      echo "Helm uninstall failed; continuing best-effort cleanup of known Nexent resources."
    fi
  fi
  cleanup_leftover_nexent_resources
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
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "正在删除 Helm release..."
  else
    echo "Deleting Helm release..."
  fi
  if ! helm_uninstall_release; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "Helm 卸载失败。Namespace 未删除。"
    else
      echo "Helm uninstall failed. Namespace was not deleted."
    fi
    cleanup_leftover_nexent_resources
    return 1
  fi
  cleanup_leftover_nexent_resources
  maybe_delete_local_volume_data
  maybe_delete_namespace_after_uninstall
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "清理完成。Helm 托管的 PV/PVC 资源已随 release 删除。"
  else
    echo "Cleanup completed. Helm-managed PV/PVC resources were deleted with the release."
  fi
}

case "$COMMAND" in
  clean)
    clean_helm_state
    ;;
  uninstall)
    if [ -n "$DELETE_DATA" ] && parse_bool_option "$DELETE_DATA"; then
      delete_all_data
    else
      uninstall_preserve_data
    fi
    ;;
esac
