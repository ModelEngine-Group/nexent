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
  echo "  delete       Uninstall Helm release and delete namespace"
  echo "  delete-all   Uninstall Helm release and delete namespace"
  echo "  clean        Clean Helm release state only"
  echo ""
  echo "Options:"
  echo "  --delete-data true|false     Compatibility option; Helm removes managed PV/PVC resources"
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

delete_namespace_after_uninstall() {
  echo "Deleting namespace..."
  kubectl delete namespace "$NAMESPACE" --ignore-not-found=true || true
}

uninstall_preserve_data() {
  echo "Uninstalling Helm release..."
  helm uninstall "$RELEASE_NAME" --namespace "$NAMESPACE"
  delete_namespace_after_uninstall
  echo "Cleanup completed. Helm-managed resources were removed; hostPath data remains on the node."
  echo "Re-run './deploy.sh' to redeploy with existing data."
}

delete_all_data() {
  echo "Deleting Helm release and namespace..."
  if ! helm uninstall "$RELEASE_NAME" --namespace "$NAMESPACE"; then
    echo "Helm uninstall failed. Namespace was not deleted."
    return 1
  fi
  delete_namespace_after_uninstall
  echo "Cleanup completed. Helm-managed PV/PVC resources and the namespace have been deleted."
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
