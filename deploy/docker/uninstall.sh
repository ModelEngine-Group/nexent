#!/bin/bash

if [ -z "$BASH_VERSION" ]; then
  echo "❌ This script must be run with bash. Please use: bash uninstall.sh or ./uninstall.sh"
  exit 1
fi

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_ROOT="$PROJECT_ROOT/deploy"
DEPLOYMENT_COMMON="$DEPLOY_ROOT/common/common.sh"
ROOT_ENV_FILE="$PROJECT_ROOT/deploy/env/.env"
COMPOSE_DIR="$SCRIPT_DIR/compose"
MONITORING_ENV_FILE="$PROJECT_ROOT/deploy/env/monitoring.env"
cd "$SCRIPT_DIR"

if [ -f "$DEPLOYMENT_COMMON" ]; then
  # shellcheck source=/dev/null
  source "$DEPLOYMENT_COMMON"
fi

DELETE_VOLUMES=""

print_usage() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "用法：$0 [delete-all] [选项]"
    echo ""
    echo "卸载 Nexent Docker 部署。"
    echo ""
    echo "选项："
    echo "  --delete-volumes true|false  控制是否删除持久化数据"
    echo "  --remove-volumes             等同于 --delete-volumes true"
    echo "  --keep-volumes               等同于 --delete-volumes false"
    echo "  --help, -h                   显示帮助信息"
    echo ""
    echo "示例："
    echo "  bash uninstall.sh"
    echo "  bash uninstall.sh --delete-volumes false"
    echo "  bash uninstall.sh --delete-volumes true"
    echo "  bash uninstall.sh delete-all"
    return
  fi

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
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "❌ 无效布尔值：$value。请使用 true 或 false。"
      else
        echo "❌ Invalid boolean value: $value. Use true or false."
      fi
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
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "❌ 未知选项：$1"
      else
        echo "❌ Unknown option: $1"
      fi
      print_usage
      exit 1
      ;;
  esac
done

if [ -f "$ROOT_ENV_FILE" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_ENV_FILE"
  set +a
fi

if [ -f "$SCRIPT_DIR/.env.generated" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/.env.generated"
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
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "🧹 是否删除 Docker volumes 和 Nexent 数据目录？"
    echo "   这会删除 ROOT_DIR 下的持久化数据，包括 elasticsearch、postgresql、redis、minio、scripts 和 supabase volumes。"
  else
    echo "🧹 Delete Docker volumes and Nexent data directories?"
    echo "   This removes persistent data under ROOT_DIR, including elasticsearch, postgresql, redis, minio, scripts, and supabase volumes."
  fi
  local answer
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    read -r -p "   删除数据 volumes？[y/N]：" answer
  else
    read -r -p "   Delete data volumes? [y/N]: " answer
  fi
  answer="$(sanitize_input "$answer")"
  [[ "$answer" =~ ^[Yy]$ ]]
}

remove_docker_named_volumes() {
  command -v docker >/dev/null 2>&1 || return 0

  local volume_names
  volume_names="$(docker volume ls --format '{{.Name}}' 2>/dev/null || true)"
  [ -n "$volume_names" ] || return 0

  local volumes_to_remove=()
  local volume
  while IFS= read -r volume; do
    [ -n "$volume" ] || continue
    case "$volume" in
      nexent_*|nexent-*|monitor_*)
        volumes_to_remove+=("$volume")
        ;;
    esac
  done <<< "$volume_names"

  if [ "${#volumes_to_remove[@]}" -gt 0 ]; then
    echo "🧹 Removing Docker volumes: ${volumes_to_remove[*]}"
    docker volume rm -f "${volumes_to_remove[@]}" >/dev/null 2>&1 || true
  fi
}

monitoring_container_names() {
  printf '%s\n' \
    nexent-otel-collector \
    nexent-phoenix \
    nexent-langfuse-worker \
    nexent-langfuse-web \
    nexent-langfuse-clickhouse \
    nexent-langfuse-minio \
    nexent-langfuse-redis \
    nexent-langfuse-postgres \
    nexent-grafana \
    nexent-tempo \
    nexent-zipkin
}

monitoring_volume_names() {
  printf '%s\n' \
    monitor_phoenix-data \
    monitor_langfuse-postgres-data \
    monitor_langfuse-clickhouse-data \
    monitor_langfuse-clickhouse-logs \
    monitor_langfuse-minio-data \
    monitor_langfuse-redis-data \
    monitor_grafana-data \
    monitor_tempo-data
}

remove_docker_containers_by_name() {
  command -v docker >/dev/null 2>&1 || return 0

  local containers_to_remove=()
  local container
  while IFS= read -r container; do
    [ -n "$container" ] || continue
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$container"; then
      containers_to_remove+=("$container")
    fi
  done

  if [ "${#containers_to_remove[@]}" -gt 0 ]; then
    echo "🧹 Removing Docker containers: ${containers_to_remove[*]}"
    docker rm -f "${containers_to_remove[@]}" >/dev/null 2>&1 || true
  fi
}

remove_docker_volumes_by_name() {
  command -v docker >/dev/null 2>&1 || return 0

  local volumes_to_remove=()
  local volume
  while IFS= read -r volume; do
    [ -n "$volume" ] || continue
    if docker volume ls --format '{{.Name}}' 2>/dev/null | grep -qx "$volume"; then
      volumes_to_remove+=("$volume")
    fi
  done

  if [ "${#volumes_to_remove[@]}" -gt 0 ]; then
    echo "🧹 Removing Docker volumes: ${volumes_to_remove[*]}"
    docker volume rm -f "${volumes_to_remove[@]}" >/dev/null 2>&1 || true
  fi
}

docker_compose_down_file() {
  local compose_file="$1"
  local use_project_name="$2"
  local remove_volumes="$3"
  local env_file_args=()

  [ -f "$compose_file" ] || return 0

  local volume_args=()
  if [ "$remove_volumes" = "true" ]; then
    volume_args=(-v)
  fi
  if [ -f "$ROOT_ENV_FILE" ]; then
    env_file_args=(--env-file "$ROOT_ENV_FILE")
  fi
  if [ "$(basename "$compose_file")" = "docker-compose-monitoring.yml" ] && [ -f "$MONITORING_ENV_FILE" ]; then
    env_file_args+=(--env-file "$MONITORING_ENV_FILE")
  fi

  if [ "$use_project_name" = "true" ]; then
    $docker_compose_command "${env_file_args[@]}" -p nexent -f "$compose_file" down --remove-orphans "${volume_args[@]}" || true
  else
    $docker_compose_command "${env_file_args[@]}" -f "$compose_file" down --remove-orphans "${volume_args[@]}" || true
  fi
}

remove_nexent_data_dirs() {
  local root_dir="${ROOT_DIR:-$HOME/nexent-data}"
  local work_dir="$HOME/nexent"
  root_dir="${root_dir%/}"

  if [ -z "$root_dir" ] || [ "$root_dir" = "/" ]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "❌ 拒绝删除不安全的 ROOT_DIR：${root_dir:-<empty>}"
    else
      echo "❌ Refusing to remove unsafe ROOT_DIR: ${root_dir:-<empty>}"
    fi
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
    "$root_dir/skills"
    "$work_dir"
  )

  local dir
  for dir in "${dirs[@]}"; do
    if [ -e "$dir" ]; then
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "🧹 正在删除数据目录：$dir"
      else
        echo "🧹 Removing data directory: $dir"
      fi
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

  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "🛑 正在停止并删除 Docker 部署..."
  else
    echo "🛑 Stopping and removing Docker deployment..."
  fi
  if [ "$remove_volumes" = "true" ]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "⚠️  数据 volumes 将被删除。"
    else
      echo "⚠️  Data volumes will be deleted."
    fi
  else
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "ℹ️  数据 volumes 将被保留。"
    else
      echo "ℹ️  Data volumes will be preserved."
    fi
  fi

  docker_compose_down_file "$COMPOSE_DIR/docker-compose-monitoring.yml" false "$remove_volumes"
  remove_docker_containers_by_name < <(monitoring_container_names)
  if [ "$remove_volumes" = "true" ]; then
    remove_docker_volumes_by_name < <(monitoring_volume_names)
  fi
  docker_compose_down_file "$COMPOSE_DIR/docker-compose-supabase.prod.yml" true "$remove_volumes"
  docker_compose_down_file "$COMPOSE_DIR/docker-compose-supabase.yml" true "$remove_volumes"
  docker_compose_down_file "$COMPOSE_DIR/docker-compose.prod.yml" true "$remove_volumes"
  docker_compose_down_file "$COMPOSE_DIR/docker-compose.yml" true "$remove_volumes"

  if [ "$remove_volumes" = "true" ]; then
    remove_docker_named_volumes
    remove_nexent_data_dirs
  fi

  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "✅ Docker 部署已删除。"
  else
    echo "✅ Docker deployment removed."
  fi
}

main
