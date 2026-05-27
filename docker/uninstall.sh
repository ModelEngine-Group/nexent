#!/bin/bash

if [ -z "$BASH_VERSION" ]; then
  echo "❌ This script must be run with bash. Please use: bash uninstall.sh or ./uninstall.sh"
  exit 1
fi

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DELETE_VOLUMES=""

print_usage() {
  echo "Usage: $0 [delete-all] [options]"
  echo ""
  echo "Uninstall Docker deployment for Nexent."
  echo ""
  echo "Options:"
  echo "  --delete-volumes true|false  Control whether persistent data is removed"
  echo "  --remove-volumes             Alias for --delete-volumes true"
  echo "  --keep-volumes               Alias for --delete-volumes false"
  echo "  --help, -h                   Show this help message"
  echo ""
  echo "Examples:"
  echo "  bash uninstall.sh"
  echo "  bash uninstall.sh --delete-volumes false"
  echo "  bash uninstall.sh --delete-volumes true"
  echo "  bash uninstall.sh delete-all"
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
      echo "❌ Invalid boolean value: $value. Use true or false."
      exit 1
      ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    delete-all)
      DELETE_VOLUMES="true"
      shift
      ;;
    --delete-volumes)
      DELETE_VOLUMES="$2"
      shift 2
      ;;
    --remove-volumes)
      DELETE_VOLUMES="true"
      shift
      ;;
    --keep-volumes)
      DELETE_VOLUMES="false"
      shift
      ;;
    --help|-h)
      print_usage
      exit 0
      ;;
    *)
      echo "❌ Unknown option: $1"
      print_usage
      exit 1
      ;;
  esac
done

if [ -f ".env" ]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

if [ -f ".env.generated" ]; then
  set -a
  # shellcheck source=/dev/null
  source .env.generated
  set +a
fi

get_compose_version() {
  if command -v docker &> /dev/null; then
    local version_output
    version_output=$(docker compose version 2>/dev/null)
    if [[ $version_output =~ v([0-9]+\.[0-9]+\.[0-9]+) ]]; then
      echo "v2 ${BASH_REMATCH[1]}"
      return 0
    fi
  fi

  if command -v docker-compose &> /dev/null; then
    local version_output
    version_output=$(docker-compose --version 2>/dev/null)
    if [[ $version_output =~ ([0-9]+\.[0-9]+\.[0-9]+) ]]; then
      echo "v1 ${BASH_REMATCH[1]}"
      return 0
    fi
  fi

  echo "unknown"
  return 0
}

resolve_compose_command() {
  local version_info
  version_info="$(get_compose_version)"
  if [[ $version_info == "unknown" ]]; then
    echo "❌ Docker Compose not found or version detection failed"
    exit 1
  fi

  local version_type version_number
  version_type="$(echo "$version_info" | awk '{print $1}')"
  version_number="$(echo "$version_info" | awk '{print $2}')"

  case "$version_type" in
    v1)
      if [[ $version_number < "1.28.0" ]]; then
        echo "❌ Docker Compose V1 version is too old; please upgrade to V1.28.0+ or V2."
        exit 1
      fi
      docker_compose_command="docker-compose"
      ;;
    v2)
      docker_compose_command="docker compose"
      ;;
    *)
      echo "❌ Unknown Docker Compose version type: $version_type"
      exit 1
      ;;
  esac
}

resolve_delete_volumes() {
  if [ -n "$DELETE_VOLUMES" ]; then
    parse_bool_option "$DELETE_VOLUMES"
    return $?
  fi

  [ -t 0 ] || return 1

  echo ""
  echo "🧹 Delete Docker volumes and Nexent data directories?"
  echo "   This removes persistent data under ROOT_DIR, including elasticsearch, postgresql, redis, minio, scripts, and supabase volumes."
  local answer
  read -r -p "   Delete data volumes? [y/N]: " answer
  answer="$(sanitize_input "$answer")"
  [[ "$answer" =~ ^[Yy]$ ]]
}

docker_compose_down_file() {
  local compose_file="$1"
  local use_project_name="$2"
  local remove_volumes="$3"

  [ -f "$compose_file" ] || return 0

  local volume_args=()
  if [ "$remove_volumes" = "true" ]; then
    volume_args=(-v)
  fi

  if [ "$use_project_name" = "true" ]; then
    $docker_compose_command -p nexent -f "$compose_file" down --remove-orphans "${volume_args[@]}" || true
  else
    $docker_compose_command -f "$compose_file" down --remove-orphans "${volume_args[@]}" || true
  fi
}

remove_nexent_data_dirs() {
  local root_dir="${ROOT_DIR:-$HOME/nexent-data}"
  root_dir="${root_dir%/}"

  if [ -z "$root_dir" ] || [ "$root_dir" = "/" ]; then
    echo "❌ Refusing to remove unsafe ROOT_DIR: ${root_dir:-<empty>}"
    return 1
  fi

  local dirs=(
    "$root_dir/elasticsearch"
    "$root_dir/postgresql"
    "$root_dir/redis"
    "$root_dir/minio"
    "$root_dir/volumes"
    "$root_dir/openssh-server"
    "$root_dir/scripts"
  )

  local dir
  for dir in "${dirs[@]}"; do
    if [ -e "$dir" ]; then
      echo "🧹 Removing data directory: $dir"
      rm -rf "$dir"
    fi
  done
}

main() {
  local remove_volumes="false"
  if resolve_delete_volumes; then
    remove_volumes="true"
  fi

  resolve_compose_command

  echo "🛑 Stopping and removing Docker deployment..."
  if [ "$remove_volumes" = "true" ]; then
    echo "⚠️  Data volumes will be deleted."
  else
    echo "ℹ️  Data volumes will be preserved."
  fi

  docker_compose_down_file "docker-compose-monitoring.yml" false "$remove_volumes"
  docker_compose_down_file "docker-compose-supabase.prod.yml" true "$remove_volumes"
  docker_compose_down_file "docker-compose-supabase.yml" true "$remove_volumes"
  docker_compose_down_file "docker-compose.prod.yml" true "$remove_volumes"
  docker_compose_down_file "docker-compose.yml" true "$remove_volumes"

  if [ "$remove_volumes" = "true" ]; then
    remove_nexent_data_dirs
  fi

  echo "✅ Docker deployment removed."
}

main
