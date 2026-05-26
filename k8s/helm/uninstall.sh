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
COMMAND="uninstall"

print_usage() {
  echo "Usage: $0 [delete|delete-all|clean] [options]"
  echo ""
  echo "Uninstall Nexent K8s resources."
  echo ""
  echo "Commands:"
  echo "  delete       Uninstall Helm release and preserve PVC/PV data"
  echo "  delete-all   Uninstall Helm release and delete PVC/PV data"
  echo "  clean        Clean Helm release state only"
  echo ""
  echo "Options:"
  echo "  --delete-data true|false     Control whether persistent data is deleted"
  echo "  --delete-volumes true|false  Alias for --delete-data"
  echo "  --remove-volumes             Alias for --delete-data true"
  echo "  --keep-volumes               Alias for --delete-data false"
  echo "  --namespace NAME             Kubernetes namespace (default: nexent)"
  echo "  --release NAME               Helm release name (default: nexent)"
  echo "  --help, -h                   Show this help message"
  echo ""
  echo "Examples:"
  echo "  bash uninstall.sh"
  echo "  bash uninstall.sh --delete-data false"
  echo "  bash uninstall.sh --delete-data true"
  echo "  bash uninstall.sh delete-all"
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
      shift
      ;;
    delete-all)
      COMMAND="uninstall"
      DELETE_DATA="true"
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

resolve_delete_data() {
  if [ -n "$DELETE_DATA" ]; then
    parse_bool_option "$DELETE_DATA"
    return $?
  fi

  [ -t 0 ] || return 1

  echo ""
  echo "Delete K8s persistent data?"
  echo "This removes PVCs, PVs, and the namespace."
  local answer
  read -r -p "Delete persistent data? [y/N]: " answer
  answer="$(sanitize_input "$answer")"
  [[ "$answer" =~ ^[Yy]$ ]]
}

uninstall_preserve_data() {
  echo "Uninstalling Helm release (preserving data)..."
  helm uninstall "$RELEASE_NAME" --namespace "$NAMESPACE" || true
  echo "Cleanup completed. Data is preserved in PVC/PV resources."
  echo "Re-run './deploy.sh' to redeploy with existing data."
}

delete_all_data() {
  echo "Deleting Helm release and persistent data..."
  helm uninstall "$RELEASE_NAME" --namespace "$NAMESPACE" || true

  echo "Waiting for pods to terminate..."
  kubectl wait --for=delete pod -l app=nexent-elasticsearch -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
  kubectl wait --for=delete pod -l app=nexent-postgresql -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
  kubectl wait --for=delete pod -l app=nexent-redis -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
  kubectl wait --for=delete pod -l app=nexent-minio -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
  kubectl wait --for=delete pod -l app=nexent-supabase-db -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
  kubectl wait --for=delete pod -l app=nexent-supabase-auth -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
  kubectl wait --for=delete pod -l app=nexent-supabase-kong -n "$NAMESPACE" --timeout=120s 2>/dev/null || true

  echo "Deleting PVCs..."
  kubectl delete pvc -n "$NAMESPACE" --all --ignore-not-found=true || true
  sleep 5

  echo "Deleting PersistentVolumes..."
  kubectl delete pv nexent-elasticsearch-pv nexent-postgresql-pv nexent-redis-pv nexent-minio-pv nexent-supabase-db-pv --ignore-not-found=true || true

  echo "Deleting namespace..."
  kubectl delete namespace "$NAMESPACE" --ignore-not-found=true || true

  echo "Cleanup completed. All resources including data have been deleted."
}

case "$COMMAND" in
  clean)
    clean_helm_state
    ;;
  uninstall)
    if resolve_delete_data; then
      delete_all_data
    else
      uninstall_preserve_data
    fi
    ;;
esac
