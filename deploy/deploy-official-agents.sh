#!/usr/bin/env bash

# Deploy official Agent bundles bundled with the Nexent repository.
# Run this script after Nexent itself is installed and ready.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_ROOT="$ROOT_DIR/deploy/docker/assets/official-agents"
TARGET_CONTAINER="nexent-config"
TARGET_CONTAINER_DIR="/mnt/nexent/official-agents"
NAMESPACE="nexent"
DEPLOY_OFFICIAL_K8S=false
PROFILES=""

usage() {
  cat <<'EOF'
Usage: deploy-official-agents.sh [options]

Official Agent bundles are read from:
  deploy/docker/assets/official-agents

Options:
  --kubernetes               Sync through kubectl instead of Docker
  --namespace NAME           Kubernetes namespace (default: nexent)
  -h, --help                 Show this help

Without options, the script interactively asks which Agent profiles to deploy.
EOF
}

die() {
  printf 'ERROR: %s\n' "$*"
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --kubernetes) DEPLOY_OFFICIAL_K8S=true; shift ;;
    --namespace) NAMESPACE="${2:?missing value for --namespace}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -d "$SOURCE_ROOT" ] || die "official Agent directory not found: $SOURCE_ROOT"

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/nexent-official-agents.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

declare -a AVAILABLE_DIRS=()
declare -a AVAILABLE_NAMES=()

load_profiles() {
  local path
  while IFS= read -r -d '' path; do
    AVAILABLE_DIRS+=("$path")
    AVAILABLE_NAMES+=("$(basename "$path")")
  done < <(find "$SOURCE_ROOT" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
  [ "${#AVAILABLE_DIRS[@]}" -gt 0 ] || die "no official Agent profiles found in $SOURCE_ROOT"
}

select_profiles() {
  local i selection token index found name
  load_profiles

  printf '\nAvailable official Agent profiles:\n'
  for i in "${!AVAILABLE_NAMES[@]}"; do
    printf '  %d) %s\n' "$((i + 1))" "${AVAILABLE_NAMES[$i]}"
  done
  printf '\n'
  read -r -p "Select profiles (comma-separated numbers, or all): " selection
  [ -n "$selection" ] || die "no profiles selected"

  if [ "$selection" = "all" ] || [ "$selection" = "ALL" ]; then
    PROFILES="$(IFS=,; printf '%s' "${AVAILABLE_NAMES[*]}")"
    return
  fi

  local -a selected_names=()
  IFS=',' read -r -a tokens <<< "$selection"
  for token in "${tokens[@]}"; do
    token="$(printf '%s' "$token" | xargs)"
    [[ "$token" =~ ^[0-9]+$ ]] || die "invalid profile selection: $token"
    index=$((token - 1))
    [ "$index" -ge 0 ] && [ "$index" -lt "${#AVAILABLE_NAMES[@]}" ] \
      || die "profile selection out of range: $token"
    found=false
    for name in "${selected_names[@]}"; do
      [ "$name" = "${AVAILABLE_NAMES[$index]}" ] && found=true
    done
    [ "$found" = true ] || selected_names+=("${AVAILABLE_NAMES[$index]}")
  done
  [ "${#selected_names[@]}" -gt 0 ] || die "no profiles selected"
  PROFILES="$(IFS=,; printf '%s' "${selected_names[*]}")"
}

copy_profile_to_docker() {
  local profile="$1" source="$2" target docker_source
  target="$TMP_ROOT/staged/$profile"
  mkdir -p "$target"
  cp -R "$source/." "$target/"

  command -v docker >/dev/null 2>&1 || die "docker is required for Docker deployment"
  docker inspect "$TARGET_CONTAINER" >/dev/null 2>&1 || die "container not found: $TARGET_CONTAINER"
  MSYS_NO_PATHCONV=1 docker exec "$TARGET_CONTAINER" rm -rf "$TARGET_CONTAINER_DIR/$profile"
  MSYS_NO_PATHCONV=1 docker exec "$TARGET_CONTAINER" mkdir -p "$TARGET_CONTAINER_DIR/$profile"
  docker_source="$target"
  if command -v cygpath >/dev/null 2>&1; then
    docker_source="$(cygpath -w "$target")"
  fi
  MSYS_NO_PATHCONV=1 docker cp "$docker_source/." "$TARGET_CONTAINER:$TARGET_CONTAINER_DIR/$profile/"
}

copy_profile_to_kubernetes() {
  local profile="$1" source="$2"
  command -v kubectl >/dev/null 2>&1 || die "kubectl is required for Kubernetes deployment"
  kubectl get deployment/nexent-config -n "$NAMESPACE" >/dev/null 2>&1 || die "Kubernetes deployment nexent-config not found in namespace $NAMESPACE"
  local nexent_user_dir="${NEXENT_USER_DIR:-$HOME/nexent}"
  local target="$nexent_user_dir/official-agents/$profile"
  rm -rf "$target"
  mkdir -p "$target"
  cp -R "$source/." "$target/"
  printf 'Copied %s to %s (Kubernetes persistent directory)\n' "$profile" "$target"
}

copy_profiles() {
  local profile source
  IFS=',' read -r -a selected <<< "$PROFILES"
  for profile in "${selected[@]}"; do
    source="$SOURCE_ROOT/$profile"
    [ -d "$source" ] || die "profile directory not found: $profile"
    find "$source" -type f -name agent.json -print -quit | grep -q . || die "profile has no agent.json: $profile"
    if [ "$DEPLOY_OFFICIAL_K8S" = true ]; then
      copy_profile_to_kubernetes "$profile" "$source"
    else
      copy_profile_to_docker "$profile" "$source"
    fi
  done
}

sync_repository() {
  local response synchronized
  if [ "$DEPLOY_OFFICIAL_K8S" = true ]; then
    response="$(kubectl exec deployment/nexent-config -n "$NAMESPACE" -- curl -fsS -X POST --get --data-urlencode "profiles=$PROFILES" http://127.0.0.1:5010/repository/agent/internal/official/sync)" || die "official Agent synchronization request failed"
  else
    response="$(docker exec "$TARGET_CONTAINER" curl -fsS -X POST --get --data-urlencode "profiles=$PROFILES" http://127.0.0.1:5010/repository/agent/internal/official/sync)" || die "official Agent synchronization request failed"
  fi
  synchronized="$(printf '%s' "$response" | sed -n 's/.*"synchronized"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')"
  [ -n "$synchronized" ] || die "invalid official Agent synchronization response: $response"
  printf 'Synchronized %s official Agent bundle(s)\n' "$synchronized"
}

select_profiles
copy_profiles
sync_repository
printf 'Official Agent deployment completed for profiles: %s\n' "$PROFILES"
