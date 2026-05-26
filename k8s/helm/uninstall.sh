#!/bin/bash
# Helm uninstall script for Nexent.

if [ -z "$BASH_VERSION" ]; then
  echo "This script must be run with bash. Please use: bash uninstall.sh or ./uninstall.sh"
  exit 1
fi

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

NAMESPACE="nexent"
RELEASE_NAME="nexent"
DELETE_DATA=""
DELETE_NAMESPACE=""
DELETE_LOCAL_DATA=""
LOCAL_DATA_DELETED="false"
COMMAND="uninstall"

print_usage() {
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
  echo "  --delete-local-data true|false  Control whether hostPath data is deleted"
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
      echo "Invalid boolean value: $value. Use true or false."
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
      echo "Unknown option: $1"
      print_usage
      exit 1
      ;;
  esac
done

clean_helm_state() {
  echo "Cleaning Helm release state..."
  helm uninstall "$RELEASE_NAME" -n "$NAMESPACE" --no-hooks 2>/dev/null || true
  kubectl delete secret -n "$NAMESPACE" -l "owner=helm" --ignore-not-found=true 2>/dev/null || true
  kubectl delete secret -n "$NAMESPACE" --field-selector type=helm.sh/release.v1 --ignore-not-found=true 2>/dev/null || true
  kubectl delete secret -n "$NAMESPACE" -l "name=$RELEASE_NAME" --ignore-not-found=true 2>/dev/null || true
  echo "Helm state cleaned."
}

delete_namespace_after_uninstall() {
  echo "Deleting namespace..."
  kubectl delete namespace "$NAMESPACE" --ignore-not-found=true || true
}

resolve_delete_namespace() {
  if [ -n "$DELETE_NAMESPACE" ]; then
    parse_bool_option "$DELETE_NAMESPACE"
    return $?
  fi

  [ -t 0 ] || return 1

  echo ""
  echo "Delete Kubernetes namespace '$NAMESPACE'?"
  local answer
  read -r -p "Delete namespace? [y/N]: " answer
  answer="$(sanitize_input "$answer")"
  [[ "$answer" =~ ^[Yy]$ ]]
}

maybe_delete_namespace_after_uninstall() {
  if resolve_delete_namespace; then
    delete_namespace_after_uninstall
  else
    echo "Namespace '$NAMESPACE' preserved."
  fi
}

local_volume_paths() {
  printf '%s\n' \
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
  echo "Delete local hostPath volume data under /var/lib/nexent-data?"
  local answer
  read -r -p "Delete local volume data? [y/N]: " answer
  answer="$(sanitize_input "$answer")"
  [[ "$answer" =~ ^[Yy]$ ]]
}

delete_local_volume_data() {
  echo "Deleting local hostPath volume data..."

  local path
  while IFS= read -r path; do
    case "$path" in
      /var/lib/nexent-data/nexent-*)
        if [ -e "$path" ]; then
          echo "Removing $path"
          rm -rf -- "$path"
        fi
        ;;
      *)
        echo "Refusing to remove unsafe path: $path"
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
    echo "Local hostPath volume data preserved."
  fi
}

uninstall_preserve_data() {
  echo "Uninstalling Helm release..."
  helm uninstall "$RELEASE_NAME" --namespace "$NAMESPACE"
  maybe_delete_local_volume_data
  maybe_delete_namespace_after_uninstall
  echo "Cleanup completed. Helm-managed resources were removed."
  if [ "$LOCAL_DATA_DELETED" = "true" ]; then
    echo "Re-run './deploy.sh' to redeploy with fresh local data."
  else
    echo "Re-run './deploy.sh' to redeploy with existing data."
  fi
}

delete_all_data() {
  echo "Deleting Helm release..."
  if ! helm uninstall "$RELEASE_NAME" --namespace "$NAMESPACE"; then
    echo "Helm uninstall failed. Namespace was not deleted."
    return 1
  fi
  maybe_delete_local_volume_data
  maybe_delete_namespace_after_uninstall
  echo "Cleanup completed. Helm-managed PV/PVC resources were deleted with the release."
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
