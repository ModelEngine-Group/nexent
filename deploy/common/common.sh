#!/usr/bin/env bash

# Shared deployment configuration helpers for Docker and Kubernetes deploy scripts.
# This file is intentionally dependency-light so it can be sourced from Bash-only
# install environments.

DEPLOYMENT_SCHEMA_VERSION="1"
DEPLOYMENT_COMPONENTS_DEFAULT="infrastructure,application,data-process,supabase"
DEPLOYMENT_PORT_POLICY_DEFAULT="development"
DEPLOYMENT_IMAGE_SOURCE_DEFAULT="general"
DEPLOYMENT_REGISTRY_PROFILE_DEFAULT="general"
DEPLOYMENT_IMAGE_REGISTRY_PREFIX_DEFAULT=""
DEPLOYMENT_MONITORING_PROVIDER_DEFAULT="otlp"

DEPLOYMENT_COMPONENTS=""
DEPLOYMENT_PORT_POLICY=""
DEPLOYMENT_IMAGE_SOURCE=""
DEPLOYMENT_REGISTRY_PROFILE=""
DEPLOYMENT_IMAGE_REGISTRY_PREFIX=""
DEPLOYMENT_APP_VERSION=""
DEPLOYMENT_MONITORING_PROVIDER=""
DEPLOYMENT_USE_LOCAL_CONFIG="false"
DEPLOYMENT_RECONFIGURE="false"
DEPLOYMENT_LOCAL_CONFIG_PATH=""
DEPLOYMENT_SELECTED_DOCKER_SERVICES=""
DEPLOYMENT_SELECTED_HELM_CHARTS=""
DEPLOYMENT_LOADED_SCHEMA_VERSION=""
DEPLOYMENT_CONFIG_FILE_LOADED="false"
DEPLOYMENT_DOCKER_PORTS=""
DEPLOYMENT_ROOT_ENV=""
DEPLOYMENT_LANGUAGE="${DEPLOYMENT_LANGUAGE:-}"

deployment_component_list="infrastructure application data-process supabase terminal monitoring"
deployment_port_policy_list="development production"
deployment_image_source_list="general mainland local-latest"
deployment_registry_profile_list="general mainland"
deployment_monitoring_provider_list="otlp phoenix langfuse langsmith grafana zipkin"

deployment_locale_value_is_zh() {
  local value="$1"
  value="${value%%:*}"
  value="${value%%.*}"
  value="${value//-/_}"
  value="$(printf '%s' "$value" | LC_ALL=C tr '[:upper:]' '[:lower:]')"

  case "$value" in
    zh|zh_*|cn|chinese)
      return 0
      ;;
  esac
  return 1
}

deployment_detect_language() {
  local explicit="${DEPLOYMENT_LANG:-}"
  explicit="$(printf '%s' "$explicit" | LC_ALL=C tr '[:upper:]' '[:lower:]')"
  case "$explicit" in
    zh|zh_*|zh-*|cn|chinese)
      printf 'zh\n'
      return 0
      ;;
    en|en_*|en-*|c|posix)
      printf 'en\n'
      return 0
      ;;
  esac

  if deployment_locale_value_is_zh "${LC_ALL:-}"; then
    printf 'zh\n'
  elif deployment_locale_value_is_zh "${LC_MESSAGES:-}"; then
    printf 'zh\n'
  elif deployment_locale_value_is_zh "${LANGUAGE:-}"; then
    printf 'zh\n'
  elif deployment_locale_value_is_zh "${LANG:-}"; then
    printf 'zh\n'
  else
    printf 'en\n'
  fi
}

deployment_init_language() {
  if [ -z "${DEPLOYMENT_LANGUAGE:-}" ]; then
    DEPLOYMENT_LANGUAGE="$(deployment_detect_language)"
  fi

  case "$DEPLOYMENT_LANGUAGE" in
    zh|zh_*|zh-*|cn|chinese)
      DEPLOYMENT_LANGUAGE="zh"
      ;;
    *)
      DEPLOYMENT_LANGUAGE="en"
      ;;
  esac
  export -n DEPLOYMENT_LANGUAGE 2>/dev/null || true
}

deployment_language() {
  printf '%s\n' "${DEPLOYMENT_LANGUAGE:-en}"
}

deployment_init_language

deployment_i18n_format() {
  local lang="$1"
  local key="$2"

  if [ "$lang" = "zh" ]; then
    case "$key" in
      password.validation) printf '密码至少 8 位，并且包含大写字母、小写字母和数字。' ;;
      env.created_from_docker) printf '✅ 已从 docker/.env 创建 deploy/env/.env' ;;
      env.created_from_example) printf '✅ 已从 deploy/env/.env.example 创建 deploy/env/.env' ;;
      env.root_missing) printf '未找到 deploy/env/.env，且没有可用的 docker/.env 或 deploy/env/.env.example 模板' ;;
      validation.local_config_schema) printf '%s' '本地配置 schemaVersion %s 与 %s 不兼容。请使用 --reconfigure 重新配置。' ;;
      validation.unknown_component) printf '%s' '未知部署组件：%s' ;;
      validation.unsupported_port_policy) printf '%s' '不支持的端口策略：%s。可用值：development 或 production。' ;;
      validation.unsupported_image_source) printf '%s' '不支持的镜像源：%s。可用值：general、mainland 或 local-latest。' ;;
      validation.unsupported_registry_profile) printf '%s' '不支持的 registry profile：%s' ;;
      validation.unsupported_image_registry_prefix) printf '%s' '不支持的镜像仓库前缀：%s。请使用 registry.example.com/project 格式，不要包含空格。' ;;
      validation.unsupported_monitoring_provider) printf '%s' '不支持的监控 provider：%s' ;;
      tui.cancelled) printf '已取消部署配置。' ;;
      tui.components.title) printf '选择部署组件' ;;
      tui.components.subtitle) printf '选择要安装的服务组。infrastructure 为必选项，不能禁用。' ;;
      tui.components.help) printf '使用 Up/Down 或 j/k 移动，空格切换，Enter 确认，q 退出。' ;;
      tui.component.infrastructure) printf '必需核心依赖：Elasticsearch、PostgreSQL、Redis、MinIO' ;;
      tui.component.application) printf 'Nexent 应用服务：config、runtime、MCP、northbound API、web UI' ;;
      tui.component.data_process) printf '后台文件解析、索引和知识处理 Worker' ;;
      tui.component.supabase) printf '用户、租户、登录、邀请和权限服务' ;;
      tui.component.terminal) printf '终端工具使用的 OpenSSH 容器' ;;
      tui.component.monitoring) printf 'OpenTelemetry Collector 和可选链路追踪看板' ;;
      tui.monitoring.title) printf '选择监控 provider' ;;
      tui.monitoring.subtitle) printf '仅在选择 monitoring 组件时使用。' ;;
      tui.monitoring.description) printf 'Provider 决定 OpenTelemetry traces 的存储和查看位置。' ;;
      tui.radio.help) printf '使用 Up/Down 或 j/k 移动，Enter 确认，b/Backspace 返回，q 退出。' ;;
      tui.monitoring.otlp) printf '仅 Collector；用于转发到外部 OTLP 后端' ;;
      tui.monitoring.phoenix) printf '本地 Phoenix UI，用于查看 LLM traces 和 span' ;;
      tui.monitoring.langfuse) printf '本地自托管 Langfuse；生产环境请替换默认密钥' ;;
      tui.monitoring.langsmith) printf '转发 traces 到托管 LangSmith；需要 LANGSMITH_API_KEY' ;;
      tui.monitoring.grafana) printf '本地 Grafana + Tempo traces 看板' ;;
      tui.monitoring.zipkin) printf '本地 Zipkin trace 浏览 UI' ;;
      tui.port.title) printf '选择端口策略' ;;
      tui.port.subtitle) printf '控制哪些服务端口暴露到主机或集群节点。' ;;
      tui.port.description) printf '本地调试选择 development；更小外部暴露面选择 production。' ;;
      tui.port.development) printf '暴露 Web 和调试/内部服务端口，便于本地排查' ;;
      tui.port.production) printf '只暴露生产入口端口，内部服务保持私有' ;;
      tui.image.title) printf '选择镜像源' ;;
      tui.image.description) printf '每个选项展示将使用的后端镜像 tag 示例。' ;;
      image_build.detail.main) printf '后端 API 服务' ;;
      image_build.detail.web) printf 'Next.js 前端' ;;
      image_build.detail.data_process) printf '文档解析和向量化 Worker' ;;
      image_build.detail.mcp) printf 'MCP 代理镜像' ;;
      image_build.detail.terminal) printf 'OpenSSH 终端工具镜像' ;;
      image_build.detail.docs) printf 'VitePress 文档站点' ;;
      local_config.found) printf '%s' '发现已有部署配置：%s' ;;
      local_config.choose) printf '请选择如何处理已保存的部署选项：' ;;
      local_config.use) printf '  1) 使用本地配置 - 跳过菜单，复用已保存的组件、端口策略、镜像源、镜像仓库前缀和监控 provider。' ;;
      local_config.reconfigure) printf '  2) 重新配置 - 将已保存的值作为默认值，并显示菜单供修改。' ;;
      local_config.reconfigure_hint) printf '     启用/禁用监控、切换 provider 或调整部署范围时请选择此项。' ;;
      prompt.choose_1_2) printf '请选择 [1/2]（默认：1）：' ;;
      summary.components) printf '%s' '部署组件：%s' ;;
      summary.port_policy) printf '%s' '端口策略：%s' ;;
      summary.image_source) printf '%s' '镜像源：%s' ;;
      summary.image_registry_prefix) printf '%s' '镜像仓库前缀：%s' ;;
      summary.monitoring_provider) printf '%s' '监控 provider：%s' ;;
      summary.docker_services) printf '%s' 'Docker 服务：%s' ;;
      summary.docker_ports) printf '%s' 'Docker 暴露端口：%s' ;;
      summary.helm_charts) printf '%s' 'Helm charts：%s' ;;
      *) return 1 ;;
    esac
  else
    case "$key" in
      password.validation) printf 'Password must be at least 8 characters and include uppercase letters, lowercase letters, and numbers.' ;;
      env.created_from_docker) printf '✅ Created deploy/env/.env from docker/.env' ;;
      env.created_from_example) printf '✅ Created deploy/env/.env from deploy/env/.env.example' ;;
      env.root_missing) printf 'deploy/env/.env not found and no docker/.env or deploy/env/.env.example template is available' ;;
      validation.local_config_schema) printf '%s' 'Local config schemaVersion %s is incompatible with %s. Re-run with --reconfigure.' ;;
      validation.unknown_component) printf '%s' 'Unknown deployment component: %s' ;;
      validation.unsupported_port_policy) printf '%s' 'Unsupported port policy: %s. Use development or production.' ;;
      validation.unsupported_image_source) printf '%s' 'Unsupported image source: %s. Use general, mainland, or local-latest.' ;;
      validation.unsupported_registry_profile) printf '%s' 'Unsupported registry profile: %s' ;;
      validation.unsupported_image_registry_prefix) printf '%s' 'Unsupported image registry prefix: %s. Use registry.example.com/project format without spaces.' ;;
      validation.unsupported_monitoring_provider) printf '%s' 'Unsupported monitoring provider: %s' ;;
      tui.cancelled) printf 'Deployment configuration cancelled.' ;;
      tui.components.title) printf 'Select deployment components' ;;
      tui.components.subtitle) printf 'Choose which service groups to install. infrastructure is required and cannot be disabled.' ;;
      tui.components.help) printf 'Use Up/Down or j/k to move, Space to toggle, Enter to confirm, q to quit.' ;;
      tui.component.infrastructure) printf 'required core dependencies: Elasticsearch, PostgreSQL, Redis, MinIO' ;;
      tui.component.application) printf 'Nexent app services: config, runtime, MCP, northbound API, web UI' ;;
      tui.component.data_process) printf 'background file parsing, indexing, and knowledge processing workers' ;;
      tui.component.supabase) printf 'user, tenant, login, invitation, and permission services' ;;
      tui.component.terminal) printf 'OpenSSH container used by the terminal tool' ;;
      tui.component.monitoring) printf 'OpenTelemetry collector and optional tracing dashboard' ;;
      tui.monitoring.title) printf 'Select monitoring provider' ;;
      tui.monitoring.subtitle) printf 'This is used only when the monitoring component is selected.' ;;
      tui.monitoring.description) printf 'Provider controls where OpenTelemetry traces are stored and viewed.' ;;
      tui.radio.help) printf 'Use Up/Down or j/k to move, Enter to confirm, b/Backspace to go back, q to quit.' ;;
      tui.monitoring.otlp) printf 'collector only; use this when forwarding to an external OTLP backend' ;;
      tui.monitoring.phoenix) printf 'local Phoenix UI for LLM traces and span inspection' ;;
      tui.monitoring.langfuse) printf 'local self-hosted Langfuse stack; replace default secrets for production' ;;
      tui.monitoring.langsmith) printf 'forward traces to hosted LangSmith; requires LANGSMITH_API_KEY' ;;
      tui.monitoring.grafana) printf 'local Grafana + Tempo dashboard for traces' ;;
      tui.monitoring.zipkin) printf 'local Zipkin UI for trace browsing' ;;
      tui.port.title) printf 'Select port policy' ;;
      tui.port.subtitle) printf 'This controls which service ports are exposed on the host or cluster node.' ;;
      tui.port.description) printf 'Choose development for local debugging; choose production for a smaller external surface.' ;;
      tui.port.development) printf 'publish web plus debug/internal service ports for local troubleshooting' ;;
      tui.port.production) printf 'publish only production entry ports; keep internal services private' ;;
      tui.image.title) printf 'Select image source' ;;
      tui.image.description) printf 'Each option shows the backend image tag pattern that will be used.' ;;
      image_build.detail.main) printf 'backend API service' ;;
      image_build.detail.web) printf 'Next.js frontend' ;;
      image_build.detail.data_process) printf 'document parsing and vectorization worker' ;;
      image_build.detail.mcp) printf 'MCP proxy image' ;;
      image_build.detail.terminal) printf 'OpenSSH terminal tool image' ;;
      image_build.detail.docs) printf 'VitePress documentation site' ;;
      local_config.found) printf '%s' 'Existing deployment config found: %s' ;;
      local_config.choose) printf 'Choose how to handle saved deployment options:' ;;
      local_config.use) printf '  1) Use local config - skip the menus and reuse the saved components, port policy, image source, image registry prefix, and monitoring provider.' ;;
      local_config.reconfigure) printf '  2) Reconfigure - load the saved values as defaults, then show the menus so you can change them.' ;;
      local_config.reconfigure_hint) printf '     Choose this option when enabling or disabling monitoring, switching providers, or changing deployment scope.' ;;
      prompt.choose_1_2) printf 'Choose [1/2] (default: 1): ' ;;
      summary.components) printf '%s' 'Deployment components: %s' ;;
      summary.port_policy) printf '%s' 'Port policy: %s' ;;
      summary.image_source) printf '%s' 'Image source: %s' ;;
      summary.image_registry_prefix) printf '%s' 'Image registry prefix: %s' ;;
      summary.monitoring_provider) printf '%s' 'Monitoring provider: %s' ;;
      summary.docker_services) printf '%s' 'Docker services: %s' ;;
      summary.docker_ports) printf '%s' 'Docker published ports: %s' ;;
      summary.helm_charts) printf '%s' 'Helm charts: %s' ;;
      *) return 1 ;;
    esac
  fi
}

deployment_i18n() {
  local key="$1"
  shift || true
  local lang
  local format
  lang="${DEPLOYMENT_LANGUAGE:-en}"
  format="$(deployment_i18n_format "$lang" "$key" || true)"
  if [ -z "$format" ]; then
    printf '%s\n' "$key"
    return 0
  fi
  printf "$format\n" "$@"
}

deployment_prompt() {
  local key="$1"
  shift || true
  local lang
  local format
  lang="${DEPLOYMENT_LANGUAGE:-en}"
  format="$(deployment_i18n_format "$lang" "$key" || true)"
  if [ -z "$format" ]; then
    printf '%s' "$key"
    return 0
  fi
  printf "$format" "$@"
}

deployment_log() {
  printf '%s\n' "$*"
}

deployment_warn() {
  printf '⚠️  %s\n' "$*" >&2
}

deployment_error() {
  printf '❌ %s\n' "$*" >&2
}

deployment_csv_contains() {
  local list="$1"
  local item="$2"
  local old_ifs="$IFS"
  IFS=','
  for value in $list; do
    value="$(deployment_trim "$value")"
    if [ "$value" = "$item" ]; then
      IFS="$old_ifs"
      return 0
    fi
  done
  IFS="$old_ifs"
  return 1
}

deployment_trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

deployment_validate_password() {
  local password="$1"

  [ -n "$password" ] || return 1
  [ "${#password}" -ge 8 ] || return 1
  [[ "$password" =~ [A-Z] ]] || return 1
  [[ "$password" =~ [a-z] ]] || return 1
  [[ "$password" =~ [0-9] ]] || return 1
  return 0
}

deployment_password_validation_message() {
  deployment_i18n password.validation
}

deployment_ensure_root_env() {
  local project_root="$1"
  local docker_dir="${2:-$project_root/docker}"
  local env_dir="$project_root/deploy/env"
  local root_env="$env_dir/.env"
  local root_example="$env_dir/.env.example"
  local docker_env="$docker_dir/.env"

  mkdir -p "$env_dir"
  DEPLOYMENT_ROOT_ENV="$root_env"
  export DEPLOYMENT_ROOT_ENV

  if [ -f "$root_env" ]; then
    return 0
  fi

  if [ -f "$docker_env" ]; then
    cp "$docker_env" "$root_env"
    deployment_log "$(deployment_i18n env.created_from_docker)"
    return 0
  fi

  if [ -f "$root_example" ]; then
    cp "$root_example" "$root_env"
    deployment_log "$(deployment_i18n env.created_from_example)"
    return 0
  fi

  deployment_error "$(deployment_i18n env.root_missing)"
  return 1
}

deployment_source_root_env() {
  local project_root="$1"
  local docker_dir="${2:-$project_root/docker}"

  deployment_ensure_root_env "$project_root" "$docker_dir" || return 1

  set -a
  # shellcheck source=/dev/null
  source "$DEPLOYMENT_ROOT_ENV"
  set +a
}

deployment_env_dir() {
  if [ -n "${DEPLOYMENT_ROOT_ENV:-}" ]; then
    dirname "$DEPLOYMENT_ROOT_ENV"
    return 0
  fi

  local common_dir
  common_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  printf '%s\n' "$(cd "$common_dir/../env" && pwd)"
}

deployment_monitoring_env_example_file() {
  printf '%s/monitoring.env.example\n' "$(deployment_env_dir)"
}

deployment_monitoring_env_file() {
  printf '%s/monitoring.env\n' "$(deployment_env_dir)"
}

deployment_legacy_monitoring_env_file() {
  printf '%s/../docker/assets/monitoring/monitoring.env\n' "$(deployment_env_dir)"
}

deployment_source_env_file() {
  local env_file="$1"
  [ -f "$env_file" ] || return 0

  set -a
  # shellcheck source=/dev/null
  source "$env_file"
  set +a
}

deployment_env_values_payload() {
  local env_file="${DEPLOYMENT_ROOT_ENV:-}"
  local monitoring_env_file
  local files=()

  if [ -n "$env_file" ] && [ -f "$env_file" ]; then
    files+=("$env_file")
  else
    deployment_warn "deploy/env/.env is not available; environment rollout checksum will use available env files only."
  fi

  monitoring_env_file="$(deployment_monitoring_env_file)"
  if [ -f "$monitoring_env_file" ]; then
    files+=("$monitoring_env_file")
  fi

  [ "${#files[@]}" -gt 0 ] || return 0

  awk '
    /^[[:space:]]*($|#)/ { next }
    {
      line = $0
      sub(/\r$/, "", line)
      sub(/^[[:space:]]*/, "", line)
      sub(/^export[[:space:]]+/, "", line)
      if (line !~ /^[A-Za-z_][A-Za-z0-9_]*=/) {
        next
      }
      key = line
      sub(/=.*/, "", key)
      value = line
      sub(/^[^=]*=/, "", value)
      values[key] = key "=" value
    }
    END {
      for (key in values) {
        print values[key]
      }
    }
  ' "${files[@]}" | LC_ALL=C sort -t '=' -k1,1
}

deployment_env_values_checksum() {
  deployment_sha256_string "$(deployment_env_values_payload)"
}

deployment_update_env_var_file() {
  local env_file="$1"
  local key="$2"
  local value="$3"
  local escaped_value
  local current_value

  DEPLOYMENT_LAST_ENV_WRITE_CHANGED="false"

  touch "$env_file"
  escaped_value=$(printf '%s' "$value" | sed -e 's/\\/\\\\/g' -e 's/&/\\&/g')

  if grep -q "^${key}=" "$env_file"; then
    current_value="$(deployment_get_env_var_file "$env_file" "$key" || true)"
    if [ "$current_value" = "$value" ]; then
      return 0
    fi
    sed -i.bak "s~^${key}=.*~${key}=\"${escaped_value}\"~" "$env_file"
    rm -f "${env_file}.bak"
  else
    printf '%s="%s"\n' "$key" "$value" >> "$env_file"
  fi
  DEPLOYMENT_LAST_ENV_WRITE_CHANGED="true"
}

deployment_get_env_var_file() {
  local env_file="$1"
  local key="$2"
  local line value

  [ -f "$env_file" ] || return 1
  line="$(grep -E "^${key}=" "$env_file" | tail -n 1 || true)"
  [ -n "$line" ] || return 1
  value="${line#*=}"
  value="${value%$'\r'}"
  value="$(printf '%s' "$value" | sed 's/[[:space:]]*$//')"
  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value="${value#\"}"
    value="${value%\"}"
  elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
    value="${value#\'}"
    value="${value%\'}"
  fi
  printf '%s' "$value"
}

deployment_sync_env_defaults() {
  local example_file="$1"
  local env_file="$2"
  local line key value env_value

  if [ ! -f "$example_file" ]; then
    deployment_error "Monitoring env example not found: $example_file"
    return 1
  fi

  mkdir -p "$(dirname "$env_file")"
  touch "$env_file"

  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    line="$(deployment_trim "$line")"
    case "$line" in
      ""|\#*)
        continue
        ;;
    esac
    [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue

    key="${line%%=*}"
    if grep -q "^${key}=" "$env_file"; then
      continue
    fi

    value="${line#*=}"
    env_value="$(printenv "$key" 2>/dev/null || true)"
    if [ -n "$env_value" ]; then
      value="$env_value"
    fi
    deployment_update_env_var_file "$env_file" "$key" "$value"
  done < "$example_file"
}

deployment_monitoring_env_value() {
  local key="$1"
  local default_value="${2:-}"
  local env_file
  local value

  env_file="$(deployment_monitoring_env_file)"
  if value="$(deployment_get_env_var_file "$env_file" "$key" 2>/dev/null)"; then
    printf '%s' "$value"
    return 0
  fi
  if [ "${!key+x}" = "x" ]; then
    printf '%s' "${!key}"
    return 0
  fi
  printf '%s' "$default_value"
}

deployment_update_monitoring_env_var() {
  local key="$1"
  local value="$2"
  deployment_update_env_var_file "$(deployment_monitoring_env_file)" "$key" "$value"
}

deployment_monitoring_collector_config_file() {
  local target="${1:-docker}"
  local provider="${2:-${MONITORING_PROVIDER:-$DEPLOYMENT_MONITORING_PROVIDER}}"
  local config_name

  case "$provider" in
    phoenix)
      config_name="otel-collector-phoenix-config.yml"
      ;;
    langfuse)
      config_name="otel-collector-langfuse-config.yml"
      ;;
    langsmith)
      config_name="otel-collector-langsmith-config.yml"
      ;;
    grafana)
      config_name="otel-collector-grafana-config.yml"
      ;;
    zipkin)
      config_name="otel-collector-zipkin-config.yml"
      ;;
    otlp|*)
      config_name="otel-collector-config.yml"
      ;;
  esac

  case "$target" in
    docker)
      printf '../assets/monitoring/%s' "$config_name"
      ;;
    k8s|helm)
      printf '%s' "$config_name"
      ;;
    *)
      printf '%s' "$config_name"
      ;;
  esac
}

deployment_prepare_monitoring_env() {
  local target="${1:-docker}"
  local env_file
  local example_file
  local legacy_file
  local telemetry_enabled
  local dashboard_url
  local existing_dashboard_url
  local provider
  local collector_config_file
  local otlp_endpoint
  local langfuse_public_key
  local langfuse_secret_key
  local langfuse_auth_header
  local langsmith_api_key

  env_file="$(deployment_monitoring_env_file)"
  example_file="$(deployment_monitoring_env_example_file)"
  legacy_file="$(deployment_legacy_monitoring_env_file)"

  if [ ! -f "$env_file" ] && [ -f "$legacy_file" ]; then
    mkdir -p "$(dirname "$env_file")"
    cp "$legacy_file" "$env_file"
    deployment_log "✅ Migrated monitoring.env to $env_file"
  fi

  deployment_sync_env_defaults "$example_file" "$env_file" || return 1
  deployment_source_env_file "$env_file"

  telemetry_enabled="$(deployment_monitoring_enabled)"
  provider="$DEPLOYMENT_MONITORING_PROVIDER"

  deployment_update_monitoring_env_var "ENABLE_TELEMETRY" "$telemetry_enabled"
  deployment_update_monitoring_env_var "MONITORING_PROVIDER" "$provider"

  deployment_source_env_file "$env_file"
  existing_dashboard_url="$(deployment_get_env_var_file "$env_file" "MONITORING_DASHBOARD_URL" 2>/dev/null || true)"
  if [ "$telemetry_enabled" != "true" ]; then
    deployment_update_monitoring_env_var "MONITORING_DASHBOARD_URL" ""
  elif [ -z "$existing_dashboard_url" ]; then
    dashboard_url="$(deployment_monitoring_dashboard_url "$target")"
    deployment_update_monitoring_env_var "MONITORING_DASHBOARD_URL" "$dashboard_url"
  fi

  case "$target" in
    k8s|helm)
      otlp_endpoint="http://nexent-otel-collector:4318"
      ;;
    docker|*)
      otlp_endpoint="http://otel-collector:4318"
      ;;
  esac
  deployment_update_monitoring_env_var "OTEL_EXPORTER_OTLP_ENDPOINT" "$otlp_endpoint"
  deployment_update_monitoring_env_var "OTEL_EXPORTER_OTLP_PROTOCOL" "http"

  collector_config_file="$(deployment_monitoring_collector_config_file "$target" "$provider")"
  deployment_update_monitoring_env_var "OTEL_COLLECTOR_CONFIG_FILE" "$collector_config_file"

  if [ "$provider" = "langfuse" ]; then
    langfuse_public_key="$(deployment_monitoring_env_value "LANGFUSE_INIT_PROJECT_PUBLIC_KEY" "pk-lf-nexent-local")"
    langfuse_secret_key="$(deployment_monitoring_env_value "LANGFUSE_INIT_PROJECT_SECRET_KEY" "sk-lf-nexent-local")"
    langfuse_auth_header="Basic $(printf "%s:%s" "$langfuse_public_key" "$langfuse_secret_key" | base64 | tr -d '\n')"
    deployment_update_monitoring_env_var "LANGFUSE_OTLP_AUTH_HEADER" "$langfuse_auth_header"
  fi

  if [ "$provider" = "langsmith" ]; then
    langsmith_api_key="$(deployment_monitoring_env_value "LANGSMITH_API_KEY" "")"
    deployment_update_monitoring_env_var "LANGSMITH_API_KEY" "$langsmith_api_key"
    deployment_update_monitoring_env_var "LANGSMITH_PROJECT" "$(deployment_monitoring_env_value "LANGSMITH_PROJECT" "nexent")"
    deployment_update_monitoring_env_var "LANGSMITH_OTLP_TRACES_ENDPOINT" "$(deployment_monitoring_env_value "LANGSMITH_OTLP_TRACES_ENDPOINT" "https://api.smith.langchain.com/otel/v1/traces")"
  fi

  deployment_source_env_file "$env_file"
  DEPLOYMENT_MONITORING_PROVIDER="${MONITORING_PROVIDER:-$DEPLOYMENT_MONITORING_PROVIDER}"
  export DEPLOYMENT_MONITORING_PROVIDER
}

deployment_sha256_string() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | awk '{print $1}'
  else
    printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
  fi
}

deployment_sha256_file() {
  local file="$1"
  [ -f "$file" ] || {
    deployment_sha256_string ""
    return 0
  }
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  else
    shasum -a 256 "$file" | awk '{print $1}'
  fi
}

deployment_join_csv() {
  local sep=""
  local out=""
  local value
  for value in "$@"; do
    [ -z "$value" ] && continue
    out="${out}${sep}${value}"
    sep=","
  done
  printf '%s' "$out"
}

deployment_default_local_config_path() {
  if [ -n "${DEPLOY_OPTIONS_FILE:-}" ]; then
    printf '%s' "$DEPLOY_OPTIONS_FILE"
    return 0
  fi

  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  printf '%s/local-config.yaml' "$script_dir"
}

deployment_init_defaults() {
  DEPLOYMENT_COMPONENTS="$DEPLOYMENT_COMPONENTS_DEFAULT"
  DEPLOYMENT_PORT_POLICY="$DEPLOYMENT_PORT_POLICY_DEFAULT"
  DEPLOYMENT_IMAGE_SOURCE="$DEPLOYMENT_IMAGE_SOURCE_DEFAULT"
  DEPLOYMENT_REGISTRY_PROFILE="$DEPLOYMENT_REGISTRY_PROFILE_DEFAULT"
  DEPLOYMENT_IMAGE_REGISTRY_PREFIX="$DEPLOYMENT_IMAGE_REGISTRY_PREFIX_DEFAULT"
  DEPLOYMENT_APP_VERSION="${APP_VERSION:-latest}"
  DEPLOYMENT_MONITORING_PROVIDER="$DEPLOYMENT_MONITORING_PROVIDER_DEFAULT"
  DEPLOYMENT_USE_LOCAL_CONFIG="false"
  DEPLOYMENT_RECONFIGURE="false"
  DEPLOYMENT_ROTATE_SECRETS="false"
  DEPLOYMENT_REFRESH_ES_KEY="false"
  DEPLOYMENT_LOCAL_CONFIG_PATH="$(deployment_default_local_config_path)"
  DEPLOYMENT_LOADED_SCHEMA_VERSION=""
  DEPLOYMENT_CONFIG_FILE_LOADED="false"
  DEPLOYMENT_CONFIG_VALUES_LOADED="false"
  DEPLOYMENT_DOCKER_PORTS=""
  unset DEPLOYMENT_COMPONENTS_EXPLICIT DEPLOYMENT_PORT_POLICY_EXPLICIT DEPLOYMENT_REGISTRY_PROFILE_EXPLICIT
  unset DEPLOYMENT_IMAGE_REGISTRY_PREFIX_EXPLICIT
  unset DEPLOYMENT_MONITORING_PROVIDER_EXPLICIT DEPLOYMENT_IMAGE_SOURCE_EXPLICIT DEPLOYMENT_APP_VERSION_EXPLICIT
}

deployment_parse_common_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --components)
        DEPLOYMENT_COMPONENTS="$2"
        shift 2
        ;;
      --port-policy)
        DEPLOYMENT_PORT_POLICY="$2"
        shift 2
        ;;
      --image-source)
        DEPLOYMENT_IMAGE_SOURCE="$2"
        shift 2
        ;;
      --registry-profile)
        DEPLOYMENT_REGISTRY_PROFILE="$2"
        shift 2
        ;;
      --image-registry-prefix|--registry-prefix|--image-registry)
        DEPLOYMENT_IMAGE_REGISTRY_PREFIX="$2"
        shift 2
        ;;
      --app-version|--version)
        DEPLOYMENT_APP_VERSION="$2"
        shift 2
        ;;
      --monitoring-provider)
        DEPLOYMENT_MONITORING_PROVIDER="$2"
        shift 2
        ;;
      --use-local-config)
        DEPLOYMENT_USE_LOCAL_CONFIG="true"
        shift
        ;;
      --reconfigure)
        NEXENT_DEPLOY_CONFIG_MODE="tui"
        DEPLOYMENT_RECONFIGURE="true"
        shift
        ;;
      --defaults)
        NEXENT_DEPLOY_CONFIG_MODE="defaults"
        DEPLOYMENT_RECONFIGURE="false"
        shift
        ;;
      --rotate-secrets)
        DEPLOYMENT_ROTATE_SECRETS="true"
        shift
        ;;
      --refresh-es-key)
        DEPLOYMENT_REFRESH_ES_KEY="true"
        shift
        ;;
      --config)
        NEXENT_DEPLOY_CONFIG_MODE="tui"
        DEPLOYMENT_RECONFIGURE="true"
        shift
        ;;
      --local-config)
        DEPLOYMENT_LOCAL_CONFIG_PATH="$2"
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done
}

deployment_load_config_file() {
  local config_file="$1"
  local load_mode="${2:-apply}"
  [ -z "$config_file" ] && return 0
  [ ! -f "$config_file" ] && {
    deployment_error "Deployment config not found: $config_file"
    return 1
  }

  local in_components="false"
  local components=""
  local loaded_config_value="false"
  local line key value item
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    [ -z "$(deployment_trim "$line")" ] && continue

    if [[ "$line" =~ ^components:[[:space:]]*$ ]]; then
      in_components="true"
      continue
    fi

    if [ "$in_components" = "true" ]; then
      if [[ "$line" =~ ^[[:space:]]*-[[:space:]]*([^[:space:]]+) ]]; then
        item="${BASH_REMATCH[1]}"
        components="$(deployment_join_csv "$components" "$item")"
        continue
      fi
      in_components="false"
    fi

    if [[ "$line" =~ ^([A-Za-z][A-Za-z0-9_]*):[[:space:]]*(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      value="$(deployment_trim "${BASH_REMATCH[2]}")"
      value="${value%\"}"
      value="${value#\"}"
      case "$key" in
        portPolicy)
          DEPLOYMENT_PORT_POLICY="$value"
          loaded_config_value="true"
          ;;
        schemaVersion)
          [ "$load_mode" = "apply" ] && DEPLOYMENT_LOADED_SCHEMA_VERSION="$value"
          loaded_config_value="true"
          ;;
        imageSource)
          DEPLOYMENT_IMAGE_SOURCE="$value"
          loaded_config_value="true"
          ;;
        registryProfile)
          DEPLOYMENT_REGISTRY_PROFILE="$value"
          loaded_config_value="true"
          ;;
        imageRegistryPrefix)
          DEPLOYMENT_IMAGE_REGISTRY_PREFIX="$value"
          loaded_config_value="true"
          ;;
        monitoringProvider)
          DEPLOYMENT_MONITORING_PROVIDER="$value"
          loaded_config_value="true"
          ;;
      esac
    fi
  done < "$config_file"

  if [ -n "$components" ]; then
    DEPLOYMENT_COMPONENTS="$components"
    loaded_config_value="true"
  fi
  [ "$loaded_config_value" = "true" ] && DEPLOYMENT_CONFIG_VALUES_LOADED="true"
  [ "$load_mode" = "apply" ] && DEPLOYMENT_CONFIG_FILE_LOADED="true"
  return 0
}

deployment_apply_legacy_inputs() {
  if [ -z "${DEPLOYMENT_COMPONENTS_EXPLICIT:-}" ] && [ "$DEPLOYMENT_CONFIG_VALUES_LOADED" != "true" ]; then
    case "${DEPLOYMENT_VERSION:-}" in
      speed)
        deployment_warn "DEPLOYMENT_VERSION=speed is deprecated; use --components infrastructure,application."
        DEPLOYMENT_COMPONENTS="infrastructure,application"
        ;;
      full)
        deployment_warn "DEPLOYMENT_VERSION=full is deprecated; use --components infrastructure,application,data-process,supabase."
        DEPLOYMENT_COMPONENTS="infrastructure,application,data-process,supabase"
        ;;
    esac
  fi

  if [ "$DEPLOYMENT_CONFIG_VALUES_LOADED" != "true" ]; then
    case "${DEPLOYMENT_MODE:-}" in
      development)
        deployment_warn "DEPLOYMENT_MODE=development is deprecated; use --port-policy development."
        [ -z "${DEPLOYMENT_PORT_POLICY_EXPLICIT:-}" ] && DEPLOYMENT_PORT_POLICY="development"
        ;;
      production)
        deployment_warn "DEPLOYMENT_MODE=production is deprecated; use --port-policy production."
        [ -z "${DEPLOYMENT_PORT_POLICY_EXPLICIT:-}" ] && DEPLOYMENT_PORT_POLICY="production"
        ;;
      infrastructure)
        deployment_warn "DEPLOYMENT_MODE=infrastructure is deprecated; use --components infrastructure."
        [ -z "${DEPLOYMENT_COMPONENTS_EXPLICIT:-}" ] && DEPLOYMENT_COMPONENTS="infrastructure"
        [ -z "${DEPLOYMENT_PORT_POLICY_EXPLICIT:-}" ] && DEPLOYMENT_PORT_POLICY="development"
        ;;
    esac
  fi

  if [ -n "${IS_MAINLAND:-}" ] && [ -z "${DEPLOYMENT_REGISTRY_PROFILE_EXPLICIT:-}" ] && [ "$DEPLOYMENT_CONFIG_VALUES_LOADED" != "true" ]; then
    if [[ "$IS_MAINLAND" =~ ^[Yy]$ ]]; then
      deployment_warn "--is-mainland Y is deprecated; use --image-source mainland."
      DEPLOYMENT_IMAGE_SOURCE="mainland"
      DEPLOYMENT_REGISTRY_PROFILE="mainland"
    else
      deployment_warn "--is-mainland N is deprecated; use --image-source general."
      DEPLOYMENT_IMAGE_SOURCE="general"
      DEPLOYMENT_REGISTRY_PROFILE="general"
    fi
  fi
}

deployment_normalize_image_source() {
  case "$DEPLOYMENT_IMAGE_SOURCE" in
    registry)
      deployment_warn "--image-source registry is deprecated; use --image-source general or --image-source mainland."
      case "$DEPLOYMENT_REGISTRY_PROFILE" in
        mainland) DEPLOYMENT_IMAGE_SOURCE="mainland" ;;
        general|"") DEPLOYMENT_IMAGE_SOURCE="general" ;;
        *)
          deployment_error "Unsupported registry profile for registry image source: $DEPLOYMENT_REGISTRY_PROFILE"
          return 1
          ;;
      esac
      ;;
    general|mainland|local-latest)
      ;;
  esac

  case "$DEPLOYMENT_IMAGE_SOURCE" in
    mainland) DEPLOYMENT_REGISTRY_PROFILE="mainland" ;;
    general|local-latest) DEPLOYMENT_REGISTRY_PROFILE="general" ;;
  esac
}

deployment_normalize_image_registry_prefix_value() {
  local prefix="$1"
  prefix="$(deployment_trim "$prefix")"
  prefix="${prefix#http://}"
  prefix="${prefix#https://}"
  while [[ "$prefix" == */ ]]; do
    prefix="${prefix%/}"
  done
  printf '%s' "$prefix"
}

deployment_normalize_image_registry_prefix() {
  DEPLOYMENT_IMAGE_REGISTRY_PREFIX="$(deployment_normalize_image_registry_prefix_value "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX")"
}

deployment_add_image_registry_prefix() {
  local image="$1"
  local prefix="${2:-$DEPLOYMENT_IMAGE_REGISTRY_PREFIX}"
  prefix="$(deployment_normalize_image_registry_prefix_value "$prefix")"

  if [ -z "$prefix" ]; then
    printf '%s' "$image"
    return 0
  fi
  case "$image" in
    "$prefix"/*)
      printf '%s' "$image"
      ;;
    *)
      printf '%s/%s' "$prefix" "$image"
      ;;
  esac
}

deployment_ensure_required_components() {
  local source_components="$DEPLOYMENT_COMPONENTS"
  local normalized=""
  local component

  if ! deployment_csv_contains "$source_components" "infrastructure"; then
    deployment_warn "Component infrastructure is required and has been added."
    source_components="$(deployment_join_csv "$source_components" "infrastructure")"
  fi

  for component in $deployment_component_list; do
    if deployment_csv_contains "$source_components" "$component"; then
      normalized="$(deployment_join_csv "$normalized" "$component")"
    fi
  done

  if [ -n "$normalized" ]; then
    DEPLOYMENT_COMPONENTS="$normalized"
  fi
}

deployment_is_valid_value() {
  local value="$1"
  shift
  local allowed
  for allowed in "$@"; do
    [ "$value" = "$allowed" ] && return 0
  done
  return 1
}

deployment_validate() {
  if [ -n "$DEPLOYMENT_LOADED_SCHEMA_VERSION" ] && [ "$DEPLOYMENT_LOADED_SCHEMA_VERSION" != "$DEPLOYMENT_SCHEMA_VERSION" ]; then
    deployment_error "$(deployment_i18n validation.local_config_schema "$DEPLOYMENT_LOADED_SCHEMA_VERSION" "$DEPLOYMENT_SCHEMA_VERSION")"
    return 1
  fi
  local old_ifs="$IFS"
  local component
  IFS=','
  for component in $DEPLOYMENT_COMPONENTS; do
    component="$(deployment_trim "$component")"
    IFS="$old_ifs"
    deployment_is_valid_value "$component" $deployment_component_list || {
      deployment_error "$(deployment_i18n validation.unknown_component "$component")"
      return 1
    }
    IFS=','
  done
  IFS="$old_ifs"

  deployment_is_valid_value "$DEPLOYMENT_PORT_POLICY" $deployment_port_policy_list || {
    deployment_error "$(deployment_i18n validation.unsupported_port_policy "$DEPLOYMENT_PORT_POLICY")"
    return 1
  }
  deployment_is_valid_value "$DEPLOYMENT_IMAGE_SOURCE" $deployment_image_source_list || {
    deployment_error "$(deployment_i18n validation.unsupported_image_source "$DEPLOYMENT_IMAGE_SOURCE")"
    return 1
  }
  deployment_is_valid_value "$DEPLOYMENT_REGISTRY_PROFILE" $deployment_registry_profile_list || {
    deployment_error "$(deployment_i18n validation.unsupported_registry_profile "$DEPLOYMENT_REGISTRY_PROFILE")"
    return 1
  }
  if [[ "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX" == *[[:space:]]* ]]; then
    deployment_error "$(deployment_i18n validation.unsupported_image_registry_prefix "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX")"
    return 1
  fi
  deployment_is_valid_value "$DEPLOYMENT_MONITORING_PROVIDER" $deployment_monitoring_provider_list || {
    deployment_error "$(deployment_i18n validation.unsupported_monitoring_provider "$DEPLOYMENT_MONITORING_PROVIDER")"
    return 1
  }
}

deployment_tui_cancel() {
  printf '\033[?25h'
  printf '\033[2J\033[H'
  deployment_warn "$(deployment_i18n tui.cancelled)"
  return 130
}

deployment_tui_back() {
  printf '\033[?25h'
  printf '\033[2J\033[H'
  return 131
}

deployment_tui_is_back_key() {
  case "$1" in
    b|B|$'\177'|$'\010')
      return 0
      ;;
  esac
  return 1
}

deployment_tui_multiselect_components() {
  [ -t 0 ] || return 0
  [ -n "${DEPLOYMENT_COMPONENTS_EXPLICIT:-}" ] && return 0
  [ "$DEPLOYMENT_CONFIG_FILE_LOADED" = "true" ] && return 0

  local components=(infrastructure application data-process supabase terminal monitoring)
  local details=(
    "$(deployment_i18n tui.component.infrastructure)"
    "$(deployment_i18n tui.component.application)"
    "$(deployment_i18n tui.component.data_process)"
    "$(deployment_i18n tui.component.supabase)"
    "$(deployment_i18n tui.component.terminal)"
    "$(deployment_i18n tui.component.monitoring)"
  )
  local selected=(0 0 0 0 0 0)
  local cursor=0
  local i component key key_tail selection

  for i in "${!components[@]}"; do
    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "${components[$i]}"; then
      selected[$i]=1
    fi
  done

  deployment_tui_render_components() {
    printf '\033[2J\033[H'
    printf '%s\n' "$(deployment_i18n tui.components.title)"
    printf '%s\n' "$(deployment_i18n tui.components.subtitle)"
    printf '%s\n\n' "$(deployment_i18n tui.components.help)"
    local row marker check
    for row in "${!components[@]}"; do
      marker=" "
      [ "$row" -eq "$cursor" ] && marker=">"
      check=" "
      [ "${selected[$row]}" = "1" ] && check="*"
      printf '%s [%s] %s - %s\n' "$marker" "$check" "${components[$row]}" "${details[$row]}"
    done
  }

  printf '\033[?25l'
  while true; do
    deployment_tui_render_components
    IFS= read -rsn1 key || key=""
    if [ -z "$key" ]; then
      selection=""
      for i in "${!components[@]}"; do
        if [ "${selected[$i]}" = "1" ]; then
          selection="$(deployment_join_csv "$selection" "${components[$i]}")"
        fi
      done
      if [ -n "$selection" ]; then
        DEPLOYMENT_COMPONENTS="$selection"
        break
      fi
      continue
    fi

    if [ "$key" = $'\033' ]; then
      IFS= read -rsn2 -t 0.1 key_tail || key_tail=""
      key="${key}${key_tail}"
    fi

    case "$key" in
      $'\033[A'|k|K)
        cursor=$((cursor - 1))
        [ "$cursor" -lt 0 ] && cursor=$((${#components[@]} - 1))
        ;;
      $'\033[B'|j|J)
        cursor=$((cursor + 1))
        [ "$cursor" -ge "${#components[@]}" ] && cursor=0
        ;;
      " ")
        if [ "$cursor" -eq 0 ]; then
          selected[$cursor]=1
        elif [ "${selected[$cursor]}" = "1" ]; then
          selected[$cursor]=0
        else
          selected[$cursor]=1
        fi
        ;;
      q|Q)
        deployment_tui_cancel
        return $?
        ;;
      *)
        if deployment_tui_is_back_key "$key"; then
          continue
        fi
        ;;
    esac
  done
  printf '\033[?25h'
  printf '\033[2J\033[H'
}

deployment_tui_select_monitoring_provider() {
  deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring" || return 0
  [ -t 0 ] || return 0
  [ -n "${DEPLOYMENT_MONITORING_PROVIDER_EXPLICIT:-}" ] && return 0
  [ "$DEPLOYMENT_CONFIG_FILE_LOADED" = "true" ] && return 0

  local providers=(otlp phoenix langfuse langsmith grafana zipkin)
  local details=(
    "$(deployment_i18n tui.monitoring.otlp)"
    "$(deployment_i18n tui.monitoring.phoenix)"
    "$(deployment_i18n tui.monitoring.langfuse)"
    "$(deployment_i18n tui.monitoring.langsmith)"
    "$(deployment_i18n tui.monitoring.grafana)"
    "$(deployment_i18n tui.monitoring.zipkin)"
  )
  local cursor=0
  local i key key_tail

  for i in "${!providers[@]}"; do
    if [ "${providers[$i]}" = "$DEPLOYMENT_MONITORING_PROVIDER" ]; then
      cursor="$i"
      break
    fi
  done

  deployment_tui_render_monitoring_provider() {
    printf '\033[2J\033[H'
    printf '%s\n' "$(deployment_i18n tui.monitoring.title)"
    printf '%s\n' "$(deployment_i18n tui.monitoring.subtitle)"
    printf '%s\n' "$(deployment_i18n tui.monitoring.description)"
    printf '%s\n\n' "$(deployment_i18n tui.radio.help)"
    local row marker radio
    for row in "${!providers[@]}"; do
      marker=" "
      [ "$row" -eq "$cursor" ] && marker=">"
      radio=" "
      [ "$row" -eq "$cursor" ] && radio="*"
      printf '%s (%s) %s - %s\n' "$marker" "$radio" "${providers[$row]}" "${details[$row]}"
    done
  }

  printf '\033[?25l'
  while true; do
    deployment_tui_render_monitoring_provider
    IFS= read -rsn1 key || key=""
    if [ -z "$key" ]; then
      DEPLOYMENT_MONITORING_PROVIDER="${providers[$cursor]}"
      break
    fi

    if [ "$key" = $'\033' ]; then
      IFS= read -rsn2 -t 0.1 key_tail || key_tail=""
      key="${key}${key_tail}"
    fi

    case "$key" in
      $'\033[A'|k|K)
        cursor=$((cursor - 1))
        [ "$cursor" -lt 0 ] && cursor=$((${#providers[@]} - 1))
        ;;
      $'\033[B'|j|J)
        cursor=$((cursor + 1))
        [ "$cursor" -ge "${#providers[@]}" ] && cursor=0
        ;;
      q|Q)
        deployment_tui_cancel
        return $?
        ;;
      *)
        if deployment_tui_is_back_key "$key"; then
          deployment_tui_back
          return $?
        fi
        ;;
    esac
  done
  printf '\033[?25h'
  printf '\033[2J\033[H'
}

deployment_tui_select_port_policy() {
  [ -t 0 ] || return 0
  [ -n "${DEPLOYMENT_PORT_POLICY_EXPLICIT:-}" ] && return 0
  [ "$DEPLOYMENT_CONFIG_FILE_LOADED" = "true" ] && return 0

  local policies=(development production)
  local details=(
    "$(deployment_i18n tui.port.development)"
    "$(deployment_i18n tui.port.production)"
  )
  local cursor=0
  local i key key_tail

  for i in "${!policies[@]}"; do
    if [ "${policies[$i]}" = "$DEPLOYMENT_PORT_POLICY" ]; then
      cursor="$i"
      break
    fi
  done

  deployment_tui_render_port_policy() {
    printf '\033[2J\033[H'
    printf '%s\n' "$(deployment_i18n tui.port.title)"
    printf '%s\n' "$(deployment_i18n tui.port.subtitle)"
    printf '%s\n' "$(deployment_i18n tui.port.description)"
    printf '%s\n\n' "$(deployment_i18n tui.radio.help)"
    local row marker radio
    for row in "${!policies[@]}"; do
      marker=" "
      [ "$row" -eq "$cursor" ] && marker=">"
      radio=" "
      [ "$row" -eq "$cursor" ] && radio="*"
      printf '%s (%s) %s - %s\n' "$marker" "$radio" "${policies[$row]}" "${details[$row]}"
    done
  }

  printf '\033[?25l'
  while true; do
    deployment_tui_render_port_policy
    IFS= read -rsn1 key || key=""
    if [ -z "$key" ]; then
      DEPLOYMENT_PORT_POLICY="${policies[$cursor]}"
      break
    fi

    if [ "$key" = $'\033' ]; then
      IFS= read -rsn2 -t 0.1 key_tail || key_tail=""
      key="${key}${key_tail}"
    fi

    case "$key" in
      $'\033[A'|k|K)
        cursor=$((cursor - 1))
        [ "$cursor" -lt 0 ] && cursor=$((${#policies[@]} - 1))
        ;;
      $'\033[B'|j|J)
        cursor=$((cursor + 1))
        [ "$cursor" -ge "${#policies[@]}" ] && cursor=0
        ;;
      q|Q)
        deployment_tui_cancel
        return $?
        ;;
      *)
        if deployment_tui_is_back_key "$key"; then
          deployment_tui_back
          return $?
        fi
        ;;
    esac
  done
  printf '\033[?25h'
  printf '\033[2J\033[H'
}

deployment_image_source_example_tag() {
  local source="$1"
  local version="${DEPLOYMENT_APP_VERSION:-${APP_VERSION:-latest}}"
  local prefix="nexent"

  case "$source" in
    mainland)
      prefix="ccr.ccs.tencentyun.com/nexent-hub"
      ;;
    local-latest)
      version="latest"
      ;;
  esac

  printf '%s/nexent:%s' "$prefix" "$version"
}

deployment_tui_select_image_source() {
  [ -t 0 ] || return 0
  [ -n "${DEPLOYMENT_IMAGE_SOURCE_EXPLICIT:-}" ] && return 0
  [ "$DEPLOYMENT_CONFIG_FILE_LOADED" = "true" ] && return 0

  local sources=(general mainland local-latest)
  local details=(
    "$(deployment_image_source_example_tag general)"
    "$(deployment_image_source_example_tag mainland)"
    "$(deployment_image_source_example_tag local-latest)"
  )
  local cursor=0
  local i key key_tail

  for i in "${!sources[@]}"; do
    if [ "${sources[$i]}" = "$DEPLOYMENT_IMAGE_SOURCE" ]; then
      cursor="$i"
      break
    fi
  done

  deployment_tui_render_image_source() {
    printf '\033[2J\033[H'
    printf '%s\n' "$(deployment_i18n tui.image.title)"
    printf '%s\n' "$(deployment_i18n tui.image.description)"
    printf '%s\n\n' "$(deployment_i18n tui.radio.help)"
    local row marker radio
    for row in "${!sources[@]}"; do
      marker=" "
      [ "$row" -eq "$cursor" ] && marker=">"
      radio=" "
      [ "$row" -eq "$cursor" ] && radio="*"
      printf '%s (%s) %s - %s\n' "$marker" "$radio" "${sources[$row]}" "${details[$row]}"
    done
  }

  printf '\033[?25l'
  while true; do
    deployment_tui_render_image_source
    IFS= read -rsn1 key || key=""
    if [ -z "$key" ]; then
      DEPLOYMENT_IMAGE_SOURCE="${sources[$cursor]}"
      break
    fi

    if [ "$key" = $'\033' ]; then
      IFS= read -rsn2 -t 0.1 key_tail || key_tail=""
      key="${key}${key_tail}"
    fi

    case "$key" in
      $'\033[A'|k|K)
        cursor=$((cursor - 1))
        [ "$cursor" -lt 0 ] && cursor=$((${#sources[@]} - 1))
        ;;
      $'\033[B'|j|J)
        cursor=$((cursor + 1))
        [ "$cursor" -ge "${#sources[@]}" ] && cursor=0
        ;;
      q|Q)
        deployment_tui_cancel
        return $?
        ;;
      *)
        if deployment_tui_is_back_key "$key"; then
          deployment_tui_back
          return $?
        fi
        ;;
    esac
  done
  printf '\033[?25h'
  printf '\033[2J\033[H'

}

deployment_tui_step_should_run() {
  local step="$1"
  [ -t 0 ] || return 1

  case "$step" in
    0)
      [ -z "${DEPLOYMENT_COMPONENTS_EXPLICIT:-}" ] && [ "$DEPLOYMENT_CONFIG_FILE_LOADED" != "true" ]
      ;;
    1)
      [ -z "${DEPLOYMENT_PORT_POLICY_EXPLICIT:-}" ] && [ "$DEPLOYMENT_CONFIG_FILE_LOADED" != "true" ]
      ;;
    2)
      [ -z "${DEPLOYMENT_IMAGE_SOURCE_EXPLICIT:-}" ] && [ "$DEPLOYMENT_CONFIG_FILE_LOADED" != "true" ]
      ;;
    3)
      deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring" && [ -z "${DEPLOYMENT_MONITORING_PROVIDER_EXPLICIT:-}" ] && [ "$DEPLOYMENT_CONFIG_FILE_LOADED" != "true" ]
      ;;
    *)
      return 1
      ;;
  esac
}

deployment_tui_next_step() {
  local step="$1"
  step=$((step + 1))
  while [ "$step" -lt 4 ]; do
    if deployment_tui_step_should_run "$step"; then
      printf '%s' "$step"
      return 0
    fi
    step=$((step + 1))
  done
  printf '4'
}

deployment_tui_previous_step() {
  local current_step="$1"
  local step=$((current_step - 1))
  while [ "$step" -ge 0 ]; do
    if deployment_tui_step_should_run "$step"; then
      printf '%s' "$step"
      return 0
    fi
    step=$((step - 1))
  done
  printf '%s' "$current_step"
}

deployment_run_tui_configuration() {
  local step=0
  local result=0
  local config_mode="${NEXENT_DEPLOY_CONFIG_MODE:-}"

  if [ "$config_mode" = "defaults" ]; then
    return 0
  fi

  if { [ "$config_mode" = "tui" ] || [ "$DEPLOYMENT_RECONFIGURE" = "true" ]; } && [ ! -t 0 ]; then
    deployment_error "Interactive deployment configuration requires a TTY."
    return 1
  fi

  if ! deployment_tui_step_should_run "$step"; then
    step="$(deployment_tui_next_step "$step")"
  fi

  while [ "$step" -lt 4 ]; do
    case "$step" in
      0)
        deployment_ensure_required_components
        deployment_tui_multiselect_components
        result=$?
        [ "$result" -eq 0 ] && deployment_ensure_required_components
        ;;
      1)
        deployment_tui_select_port_policy
        result=$?
        ;;
      2)
        deployment_tui_select_image_source
        result=$?
        ;;
      3)
        deployment_tui_select_monitoring_provider
        result=$?
        ;;
      *)
        return 1
        ;;
    esac

    case "$result" in
      0)
        step="$(deployment_tui_next_step "$step")"
        ;;
      130)
        return 130
        ;;
      131)
        step="$(deployment_tui_previous_step "$step")"
        ;;
      *)
        return "$result"
        ;;
    esac
  done
}

deployment_maybe_select_local_config() {
  local config_mode="${NEXENT_DEPLOY_CONFIG_MODE:-}"

  case "$config_mode" in
    ""|defaults|tui)
      ;;
    *)
      deployment_error "Unsupported NEXENT_DEPLOY_CONFIG_MODE: $config_mode. Use defaults or tui."
      return 1
      ;;
  esac

  [ -f "$DEPLOYMENT_LOCAL_CONFIG_PATH" ] || return 0
  if [ "$config_mode" = "defaults" ] || [ "$DEPLOYMENT_USE_LOCAL_CONFIG" = "true" ]; then
    deployment_load_config_file "$DEPLOYMENT_LOCAL_CONFIG_PATH" || return 1
    return 0
  fi
  if [ "$config_mode" = "tui" ] || [ "$DEPLOYMENT_RECONFIGURE" = "true" ]; then
    deployment_load_config_file "$DEPLOYMENT_LOCAL_CONFIG_PATH" defaults || return 1
    return 0
  fi
  [ -t 0 ] || return 0

  deployment_log "$(deployment_i18n local_config.found "$DEPLOYMENT_LOCAL_CONFIG_PATH")"
  deployment_log "$(deployment_i18n local_config.choose)"
  deployment_log "$(deployment_i18n local_config.use)"
  deployment_log "$(deployment_i18n local_config.reconfigure)"
  deployment_log "$(deployment_i18n local_config.reconfigure_hint)"
  local input
  read -r -p "$(deployment_prompt prompt.choose_1_2)" input
  if [ "${input:-1}" = "1" ]; then
    deployment_load_config_file "$DEPLOYMENT_LOCAL_CONFIG_PATH" || return 1
  else
    DEPLOYMENT_RECONFIGURE="true"
    deployment_load_config_file "$DEPLOYMENT_LOCAL_CONFIG_PATH" defaults || return 1
  fi
}

deployment_compute_selection() {
  local docker_services=()
  local helm_charts=()

  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "infrastructure"; then
    docker_services+=(nexent-elasticsearch nexent-postgresql redis nexent-minio)
    helm_charts+=(nexent-elasticsearch nexent-postgresql nexent-redis nexent-minio)
  fi
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "application"; then
    docker_services+=(nexent-config nexent-runtime nexent-mcp nexent-northbound nexent-web)
    helm_charts+=(nexent-config nexent-runtime nexent-mcp nexent-northbound nexent-web)
  fi
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "data-process"; then
    docker_services+=(nexent-data-process)
    helm_charts+=(nexent-data-process)
  fi
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
    docker_services+=(kong auth db)
    helm_charts+=(nexent-supabase-kong nexent-supabase-auth nexent-supabase-db)
  fi
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "terminal"; then
    docker_services+=(nexent-openssh-server)
    helm_charts+=(nexent-openssh)
  fi
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring"; then
    docker_services+=(nexent-monitoring)
    helm_charts+=(nexent-monitoring)
  fi

  DEPLOYMENT_SELECTED_DOCKER_SERVICES="${docker_services[*]}"
  DEPLOYMENT_SELECTED_HELM_CHARTS="${helm_charts[*]}"
  DEPLOYMENT_DOCKER_PORTS="$(deployment_compute_docker_ports)"
}

deployment_compute_docker_ports() {
  local ports=()

  if [ "$DEPLOYMENT_PORT_POLICY" = "production" ]; then
    deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "application" && ports+=(3000 5013)
    deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "terminal" && ports+=(2222)
    printf '%s\n' "${ports[*]}"
    return 0
  fi

  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "infrastructure"; then
    ports+=(9210 9310 5434 6379 9010 9011)
  fi
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "application"; then
    ports+=(5010 5014 5011 5015 5013 3000)
  fi
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "data-process"; then
    ports+=(5012 5555 8265)
  fi
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
    ports+=(8000 8443 "${SUPABASE_POSTGRES_PORT:-5436}")
  fi
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "terminal"; then
    ports+=(2222)
  fi
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring"; then
    case "$DEPLOYMENT_MONITORING_PROVIDER" in
      phoenix) ports+=(6006) ;;
      grafana) ports+=(30006) ;;
      zipkin) ports+=(9411) ;;
      langfuse) ports+=(30011) ;;
      otlp|langsmith|*) ports+=(4318) ;;
    esac
  fi

  printf '%s\n' "${ports[*]}"
}

deployment_image_repo() {
  local image="$1"
  printf '%s' "${image%:*}"
}

deployment_image_tag() {
  local image="$1"
  printf '%s' "${image##*:}"
}

deployment_image_rollout_checksum() {
  local image="$1"
  local image_id=""

  if command -v docker >/dev/null 2>&1; then
    image_id="$(docker image inspect --format '{{.Id}}' "$image" 2>/dev/null || true)"
    if [ -n "$image_id" ]; then
      deployment_sha256_string "local-image=${image}|id=${image_id}"
      return 0
    fi
    deployment_warn "Local image not found: $image; same-tag image changes cannot be detected from this host."
  else
    deployment_warn "Docker is not available; same-tag image changes cannot be detected for $image."
  fi

  deployment_sha256_string "image-ref=${image}"
}

deployment_render_image_rollout_checksums() {
  printf '    backendImage: "%s"\n' "$(deployment_image_rollout_checksum "$NEXENT_IMAGE")"
  printf '    webImage: "%s"\n' "$(deployment_image_rollout_checksum "$NEXENT_WEB_IMAGE")"
  printf '    dataProcessImage: "%s"\n' "$(deployment_image_rollout_checksum "$NEXENT_DATA_PROCESS_IMAGE")"
  printf '    sshImage: "%s"\n' "$(deployment_image_rollout_checksum "$OPENSSH_SERVER_IMAGE")"
}

deployment_apply_image_source() {
  local version="${DEPLOYMENT_APP_VERSION:-latest}"
  local image_var

  if [ "$DEPLOYMENT_IMAGE_SOURCE" = "local-latest" ]; then
    export NEXENT_IMAGE="nexent/nexent:latest"
    export NEXENT_WEB_IMAGE="nexent/nexent-web:latest"
    export NEXENT_DATA_PROCESS_IMAGE="nexent/nexent-data-process:latest"
    export NEXENT_MCP_DOCKER_IMAGE="nexent/nexent-mcp:latest"
    export NEXENT_SANDBOX_IMAGE="nexent/nexent-sandbox:latest"
    export OPENSSH_SERVER_IMAGE="nexent/nexent-ubuntu-terminal:latest"
  fi

  export NEXENT_IMAGE="${NEXENT_IMAGE:-nexent/nexent:$version}"
  export NEXENT_WEB_IMAGE="${NEXENT_WEB_IMAGE:-nexent/nexent-web:$version}"
  export NEXENT_DATA_PROCESS_IMAGE="${NEXENT_DATA_PROCESS_IMAGE:-nexent/nexent-data-process:$version}"
  export NEXENT_MCP_DOCKER_IMAGE="${NEXENT_MCP_DOCKER_IMAGE:-nexent/nexent-mcp:$version}"
  export NEXENT_SANDBOX_IMAGE="${NEXENT_SANDBOX_IMAGE:-nexent/nexent-sandbox:$version}"
  export ELASTICSEARCH_IMAGE="${ELASTICSEARCH_IMAGE:-docker.elastic.co/elasticsearch/elasticsearch:8.17.4}"
  export POSTGRESQL_IMAGE="${POSTGRESQL_IMAGE:-postgres:15-alpine}"
  export REDIS_IMAGE="${REDIS_IMAGE:-redis:alpine}"
  export MINIO_IMAGE="${MINIO_IMAGE:-quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z}"
  export OPENSSH_SERVER_IMAGE="${OPENSSH_SERVER_IMAGE:-nexent/nexent-ubuntu-terminal:$version}"
  export SUPABASE_KONG="${SUPABASE_KONG:-kong:2.8.1}"
  export SUPABASE_GOTRUE="${SUPABASE_GOTRUE:-supabase/gotrue:v2.170.0}"
  export SUPABASE_DB="${SUPABASE_DB:-supabase/postgres:15.8.1.060}"

  export OTEL_COLLECTOR_IMAGE="${OTEL_COLLECTOR_IMAGE:-otel/opentelemetry-collector-contrib:0.151.0}"
  export PHOENIX_IMAGE="${PHOENIX_IMAGE:-arizephoenix/phoenix:15}"
  export TEMPO_IMAGE="${TEMPO_IMAGE:-grafana/tempo:2.10.5}"
  export GRAFANA_IMAGE="${GRAFANA_IMAGE:-grafana/grafana:12.4}"
  export ZIPKIN_IMAGE="${ZIPKIN_IMAGE:-openzipkin/zipkin:latest}"
  export LANGFUSE_WORKER_IMAGE="${LANGFUSE_WORKER_IMAGE:-docker.io/langfuse/langfuse-worker:3}"
  export LANGFUSE_WEB_IMAGE="${LANGFUSE_WEB_IMAGE:-docker.io/langfuse/langfuse:3}"
  export CLICKHOUSE_IMAGE="${CLICKHOUSE_IMAGE:-docker.io/clickhouse/clickhouse-server:26.3-alpine}"
  export LANGFUSE_MINIO_IMAGE="${LANGFUSE_MINIO_IMAGE:-docker.io/minio/minio:RELEASE.2023-12-20T01-00-02Z}"
  export LANGFUSE_REDIS_IMAGE="${LANGFUSE_REDIS_IMAGE:-docker.io/redis:alpine}"
  export LANGFUSE_POSTGRES_IMAGE="${LANGFUSE_POSTGRES_IMAGE:-docker.io/postgres:15-alpine}"

  if [ -n "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX" ]; then
    for image_var in \
      NEXENT_IMAGE \
      NEXENT_WEB_IMAGE \
      NEXENT_DATA_PROCESS_IMAGE \
      NEXENT_MCP_DOCKER_IMAGE \
      NEXENT_SANDBOX_IMAGE \
      ELASTICSEARCH_IMAGE \
      POSTGRESQL_IMAGE \
      REDIS_IMAGE \
      MINIO_IMAGE \
      OPENSSH_SERVER_IMAGE \
      SUPABASE_KONG \
      SUPABASE_GOTRUE \
      SUPABASE_DB \
      OTEL_COLLECTOR_IMAGE \
      PHOENIX_IMAGE \
      TEMPO_IMAGE \
      GRAFANA_IMAGE \
      ZIPKIN_IMAGE \
      LANGFUSE_WORKER_IMAGE \
      LANGFUSE_WEB_IMAGE \
      CLICKHOUSE_IMAGE \
      LANGFUSE_MINIO_IMAGE \
      LANGFUSE_REDIS_IMAGE \
      LANGFUSE_POSTGRES_IMAGE; do
      export "$image_var=$(deployment_add_image_registry_prefix "${!image_var}")"
    done
  fi
}

deployment_monitoring_enabled() {
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring"; then
    printf 'true'
  else
    printf 'false'
  fi
}

deployment_monitoring_dashboard_url() {
  local target="${1:-docker}"

  if ! deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring"; then
    printf ''
    return 0
  fi

  case "$target:$DEPLOYMENT_MONITORING_PROVIDER" in
    docker:phoenix)
      printf 'http://localhost:%s' "${PHOENIX_PORT:-6006}"
      ;;
    docker:langfuse)
      printf 'http://localhost:%s' "${LANGFUSE_PORT:-3001}"
      ;;
    docker:grafana)
      printf 'http://localhost:%s/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1' "${GRAFANA_PORT:-3002}"
      ;;
    docker:zipkin)
      printf 'http://localhost:%s' "${ZIPKIN_PORT:-9411}"
      ;;
    k8s:phoenix|helm:phoenix)
      printf 'http://localhost:%s' "${K8S_PHOENIX_NODE_PORT:-30006}"
      ;;
    k8s:langfuse|helm:langfuse)
      printf 'http://localhost:%s' "${K8S_LANGFUSE_NODE_PORT:-30001}"
      ;;
    k8s:grafana|helm:grafana)
      printf 'http://localhost:%s/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1' "${K8S_GRAFANA_NODE_PORT:-30002}"
      ;;
    k8s:zipkin|helm:zipkin)
      printf 'http://localhost:%s' "${K8S_ZIPKIN_NODE_PORT:-30011}"
      ;;
    *:langsmith)
      printf 'https://smith.langchain.com/'
      ;;
    *)
      printf ''
      ;;
  esac
}

deployment_render_docker_env() {
  local output_file="$1"
  local compose_image_registry_prefix=""
  [ -n "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX" ] && compose_image_registry_prefix="${DEPLOYMENT_IMAGE_REGISTRY_PREFIX}/"
  mkdir -p "$(dirname "$output_file")"
  {
    printf 'DEPLOYMENT_IMAGE_REGISTRY_PREFIX="%s"\n' "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX"
    printf 'NEXENT_IMAGE_REGISTRY_PREFIX="%s"\n' "$compose_image_registry_prefix"
    printf 'NEXENT_IMAGE="%s"\n' "$NEXENT_IMAGE"
    printf 'NEXENT_WEB_IMAGE="%s"\n' "$NEXENT_WEB_IMAGE"
    printf 'NEXENT_DATA_PROCESS_IMAGE="%s"\n' "$NEXENT_DATA_PROCESS_IMAGE"
    printf 'NEXENT_MCP_DOCKER_IMAGE="%s"\n' "$NEXENT_MCP_DOCKER_IMAGE"
    printf 'NEXENT_SANDBOX_IMAGE="%s"\n' "$NEXENT_SANDBOX_IMAGE"
    printf 'ELASTICSEARCH_IMAGE="%s"\n' "$ELASTICSEARCH_IMAGE"
    printf 'POSTGRESQL_IMAGE="%s"\n' "$POSTGRESQL_IMAGE"
    printf 'REDIS_IMAGE="%s"\n' "$REDIS_IMAGE"
    printf 'MINIO_IMAGE="%s"\n' "$MINIO_IMAGE"
    printf 'OPENSSH_SERVER_IMAGE="%s"\n' "$OPENSSH_SERVER_IMAGE"
    printf 'SUPABASE_KONG="%s"\n' "$SUPABASE_KONG"
    printf 'SUPABASE_GOTRUE="%s"\n' "$SUPABASE_GOTRUE"
    printf 'SUPABASE_DB="%s"\n' "$SUPABASE_DB"
    printf 'OTEL_COLLECTOR_IMAGE="%s"\n' "$OTEL_COLLECTOR_IMAGE"
    printf 'PHOENIX_IMAGE="%s"\n' "$PHOENIX_IMAGE"
    printf 'TEMPO_IMAGE="%s"\n' "$TEMPO_IMAGE"
    printf 'GRAFANA_IMAGE="%s"\n' "$GRAFANA_IMAGE"
    printf 'ZIPKIN_IMAGE="%s"\n' "$ZIPKIN_IMAGE"
    printf 'LANGFUSE_WORKER_IMAGE="%s"\n' "$LANGFUSE_WORKER_IMAGE"
    printf 'LANGFUSE_WEB_IMAGE="%s"\n' "$LANGFUSE_WEB_IMAGE"
    printf 'CLICKHOUSE_IMAGE="%s"\n' "$CLICKHOUSE_IMAGE"
    printf 'LANGFUSE_MINIO_IMAGE="%s"\n' "$LANGFUSE_MINIO_IMAGE"
    printf 'LANGFUSE_REDIS_IMAGE="%s"\n' "$LANGFUSE_REDIS_IMAGE"
    printf 'LANGFUSE_POSTGRES_IMAGE="%s"\n' "$LANGFUSE_POSTGRES_IMAGE"
  } > "$output_file"
}

deployment_render_component_values() {
  local component
  for component in $deployment_component_list; do
    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "$component"; then
      printf '    %s: true\n' "$component"
    else
      printf '    %s: false\n' "$component"
    fi
  done
}

deployment_render_image_values() {
  local local_pull_policy="IfNotPresent"
  [ "$DEPLOYMENT_IMAGE_SOURCE" = "local-latest" ] && [ -z "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX" ] && local_pull_policy="Never"

  printf 'nexent-config:\n'
  printf '  images:\n    backend:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_IMAGE")" "$(deployment_image_tag "$NEXENT_IMAGE")" "$local_pull_policy"
  printf 'nexent-runtime:\n'
  printf '  images:\n    backend:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_IMAGE")" "$(deployment_image_tag "$NEXENT_IMAGE")" "$local_pull_policy"
  printf 'nexent-mcp:\n'
  printf '  images:\n    backend:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_IMAGE")" "$(deployment_image_tag "$NEXENT_IMAGE")" "$local_pull_policy"
  printf 'nexent-northbound:\n'
  printf '  images:\n    backend:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_IMAGE")" "$(deployment_image_tag "$NEXENT_IMAGE")" "$local_pull_policy"
  printf 'nexent-web:\n'
  printf '  images:\n    web:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_WEB_IMAGE")" "$(deployment_image_tag "$NEXENT_WEB_IMAGE")" "$local_pull_policy"
  printf 'nexent-data-process:\n'
  printf '  images:\n    dataProcess:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_DATA_PROCESS_IMAGE")" "$(deployment_image_tag "$NEXENT_DATA_PROCESS_IMAGE")" "$local_pull_policy"
  printf 'nexent-elasticsearch:\n'
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$ELASTICSEARCH_IMAGE")" "$(deployment_image_tag "$ELASTICSEARCH_IMAGE")"
  printf 'nexent-postgresql:\n'
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$POSTGRESQL_IMAGE")" "$(deployment_image_tag "$POSTGRESQL_IMAGE")"
  printf 'nexent-redis:\n'
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$REDIS_IMAGE")" "$(deployment_image_tag "$REDIS_IMAGE")"
  printf 'nexent-minio:\n'
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$MINIO_IMAGE")" "$(deployment_image_tag "$MINIO_IMAGE")"
  printf 'nexent-openssh:\n'
  printf '  images:\n    openssh:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$OPENSSH_SERVER_IMAGE")" "$(deployment_image_tag "$OPENSSH_SERVER_IMAGE")" "$local_pull_policy"
  printf 'nexent-supabase-kong:\n'
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$SUPABASE_KONG")" "$(deployment_image_tag "$SUPABASE_KONG")"
  printf 'nexent-supabase-auth:\n'
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$SUPABASE_GOTRUE")" "$(deployment_image_tag "$SUPABASE_GOTRUE")"
  printf 'nexent-supabase-db:\n'
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$SUPABASE_DB")" "$(deployment_image_tag "$SUPABASE_DB")"
  printf 'nexent-common:\n'
  printf '  images:\n    mcp:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_MCP_DOCKER_IMAGE")" "$(deployment_image_tag "$NEXENT_MCP_DOCKER_IMAGE")" "$local_pull_policy"
  printf '    sandbox:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_SANDBOX_IMAGE")" "$(deployment_image_tag "$NEXENT_SANDBOX_IMAGE")" "$local_pull_policy"
}

deployment_render_k8s_port_values() {
  local northbound_type="NodePort"
  local internal_type="ClusterIP"
  if [ "$DEPLOYMENT_PORT_POLICY" = "development" ]; then
    internal_type="NodePort"
  fi

  printf 'nexent-web:\n'
  printf '  services:\n    web:\n      type: "NodePort"\n      nodePort: 30000\n'
  printf 'nexent-northbound:\n'
  printf '  services:\n    northbound:\n      type: "%s"\n      nodePort: 30013\n' "$northbound_type"
  printf 'nexent-config:\n'
  printf '  service:\n    type: "%s"\n    nodePort: 30010\n' "$internal_type"
  printf 'nexent-runtime:\n'
  printf '  service:\n    type: "%s"\n    nodePort: 30014\n' "$internal_type"
  printf 'nexent-mcp:\n'
  printf '  service:\n    type: "%s"\n    nodePorts:\n      http: 30011\n      httpAlt: 30015\n' "$internal_type"
  printf 'nexent-data-process:\n'
  printf '  service:\n    type: "%s"\n    nodePorts:\n      http: 30012\n      flower: 30555\n      rayDashboard: 30265\n' "$internal_type"
  printf 'nexent-elasticsearch:\n'
  printf '  service:\n    type: "%s"\n    nodePorts:\n      http: 30920\n      transport: 30930\n' "$internal_type"
  printf 'nexent-postgresql:\n'
  printf '  service:\n    type: "%s"\n    nodePort: 30432\n' "$internal_type"
  printf 'nexent-redis:\n'
  printf '  service:\n    type: "%s"\n    nodePort: 30379\n' "$internal_type"
  printf 'nexent-minio:\n'
  printf '  service:\n    type: "%s"\n    nodePorts:\n      api: 30090\n      console: 30091\n' "$internal_type"
  printf 'nexent-supabase-kong:\n'
  printf '  service:\n    type: "%s"\n    nodePorts:\n      proxy: 30080\n      proxySsl: 30443\n' "$internal_type"
  printf 'nexent-supabase-auth:\n'
  printf '  service:\n    type: "%s"\n    nodePort: 30999\n' "$internal_type"
  printf 'nexent-supabase-db:\n'
  printf '  service:\n    type: "%s"\n    nodePort: 30436\n' "$internal_type"
}

deployment_chart_enabled() {
  local component="$1"
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "$component"; then
    printf 'true'
  else
    printf 'false'
  fi
}

deployment_render_helm_chart_values() {
  local local_pull_policy="IfNotPresent"
  local northbound_type="NodePort"
  local internal_type="ClusterIP"
  [ "$DEPLOYMENT_IMAGE_SOURCE" = "local-latest" ] && [ -z "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX" ] && local_pull_policy="Never"
  if [ "$DEPLOYMENT_PORT_POLICY" = "development" ]; then
    internal_type="NodePort"
  fi

  printf 'nexent-config:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled application)"
  printf '  images:\n    backend:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_IMAGE")" "$(deployment_image_tag "$NEXENT_IMAGE")" "$local_pull_policy"
  printf '  service:\n    type: "%s"\n    nodePort: 30010\n' "$internal_type"
  printf 'nexent-runtime:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled application)"
  printf '  images:\n    backend:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_IMAGE")" "$(deployment_image_tag "$NEXENT_IMAGE")" "$local_pull_policy"
  printf '  service:\n    type: "%s"\n    nodePort: 30014\n' "$internal_type"
  printf 'nexent-mcp:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled application)"
  printf '  images:\n    backend:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_IMAGE")" "$(deployment_image_tag "$NEXENT_IMAGE")" "$local_pull_policy"
  printf '  service:\n    type: "%s"\n    nodePorts:\n      http: 30011\n      httpAlt: 30015\n' "$internal_type"
  printf 'nexent-northbound:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled application)"
  printf '  images:\n    backend:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_IMAGE")" "$(deployment_image_tag "$NEXENT_IMAGE")" "$local_pull_policy"
  printf '  services:\n    northbound:\n      type: "%s"\n      nodePort: 30013\n' "$northbound_type"
  printf 'nexent-web:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled application)"
  printf '  images:\n    web:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_WEB_IMAGE")" "$(deployment_image_tag "$NEXENT_WEB_IMAGE")" "$local_pull_policy"
  printf '  services:\n    web:\n      type: "NodePort"\n      nodePort: 30000\n'
  printf 'nexent-data-process:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled data-process)"
  printf '  images:\n    dataProcess:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_DATA_PROCESS_IMAGE")" "$(deployment_image_tag "$NEXENT_DATA_PROCESS_IMAGE")" "$local_pull_policy"
  printf '  service:\n    type: "%s"\n    nodePorts:\n      http: 30012\n      flower: 30555\n      rayDashboard: 30265\n' "$internal_type"
  printf 'nexent-elasticsearch:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled infrastructure)"
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$ELASTICSEARCH_IMAGE")" "$(deployment_image_tag "$ELASTICSEARCH_IMAGE")"
  printf '  service:\n    type: "%s"\n    nodePorts:\n      http: 30920\n      transport: 30930\n' "$internal_type"
  printf 'nexent-postgresql:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled infrastructure)"
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$POSTGRESQL_IMAGE")" "$(deployment_image_tag "$POSTGRESQL_IMAGE")"
  printf '  service:\n    type: "%s"\n    nodePort: 30432\n' "$internal_type"
  printf 'nexent-redis:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled infrastructure)"
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$REDIS_IMAGE")" "$(deployment_image_tag "$REDIS_IMAGE")"
  printf '  service:\n    type: "%s"\n    nodePort: 30379\n' "$internal_type"
  printf 'nexent-minio:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled infrastructure)"
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$MINIO_IMAGE")" "$(deployment_image_tag "$MINIO_IMAGE")"
  printf '  service:\n    type: "%s"\n    nodePorts:\n      api: 30090\n      console: 30091\n' "$internal_type"
  printf 'nexent-openssh:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled terminal)"
  printf '  images:\n    openssh:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$OPENSSH_SERVER_IMAGE")" "$(deployment_image_tag "$OPENSSH_SERVER_IMAGE")" "$local_pull_policy"
  printf 'nexent-supabase-kong:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled supabase)"
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$SUPABASE_KONG")" "$(deployment_image_tag "$SUPABASE_KONG")"
  printf '  service:\n    type: "%s"\n    nodePorts:\n      proxy: 30080\n      proxySsl: 30443\n' "$internal_type"
  printf 'nexent-supabase-auth:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled supabase)"
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$SUPABASE_GOTRUE")" "$(deployment_image_tag "$SUPABASE_GOTRUE")"
  printf '  initImage:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$POSTGRESQL_IMAGE")" "$(deployment_image_tag "$POSTGRESQL_IMAGE")"
  printf '  service:\n    type: "%s"\n    nodePort: 30999\n' "$internal_type"
  printf 'nexent-supabase-db:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled supabase)"
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$SUPABASE_DB")" "$(deployment_image_tag "$SUPABASE_DB")"
  printf '  service:\n    type: "%s"\n    nodePort: 30436\n' "$internal_type"
  printf 'nexent-common:\n'
  printf '  images:\n    mcp:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_MCP_DOCKER_IMAGE")" "$(deployment_image_tag "$NEXENT_MCP_DOCKER_IMAGE")" "$local_pull_policy"
  printf '    sandbox:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_SANDBOX_IMAGE")" "$(deployment_image_tag "$NEXENT_SANDBOX_IMAGE")" "$local_pull_policy"
}

deployment_yaml_quote() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "$value"
}

deployment_render_helm_monitoring_global_values() {
  local enabled
  enabled="$(deployment_monitoring_enabled)"

  printf '  monitoring:\n'
  printf '    enabled: %s\n' "$enabled"
  printf '    provider: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value MONITORING_PROVIDER "$DEPLOYMENT_MONITORING_PROVIDER")")"
  printf '    dashboardUrl: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value MONITORING_DASHBOARD_URL "$(deployment_monitoring_dashboard_url k8s)")")"
  printf '    projectName: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value MONITORING_PROJECT_NAME "nexent")")"
  printf '    serviceName: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value OTEL_SERVICE_NAME "nexent-backend")")"
  printf '    otlpEndpoint: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value OTEL_EXPORTER_OTLP_ENDPOINT "http://nexent-otel-collector:4318")")"
  printf '    otlpTracesEndpoint: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value OTEL_EXPORTER_OTLP_TRACES_ENDPOINT "")")"
  printf '    otlpMetricsEndpoint: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value OTEL_EXPORTER_OTLP_METRICS_ENDPOINT "")")"
  printf '    otlpProtocol: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value OTEL_EXPORTER_OTLP_PROTOCOL "http")")"
  printf '    otlpHeaders: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value OTEL_EXPORTER_OTLP_HEADERS "")")"
  printf '    otlpAuthorization: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value OTEL_EXPORTER_OTLP_AUTHORIZATION "")")"
  printf '    otlpApiKey: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value OTEL_EXPORTER_OTLP_X_API_KEY "")")"
  printf '    otlpLangfuseIngestionVersion: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION "")")"
  printf '    langsmithApiKey: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGSMITH_API_KEY "")")"
  printf '    langsmithProject: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGSMITH_PROJECT "nexent")")"
  printf '    langsmithOtlpTracesEndpoint: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGSMITH_OTLP_TRACES_ENDPOINT "https://api.smith.langchain.com/otel/v1/traces")")"
  printf '    otlpMetricsEnabled: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value OTEL_EXPORTER_OTLP_METRICS_ENABLED "true")")"
  printf '    instrumentRequests: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value MONITORING_INSTRUMENT_REQUESTS "false")")"
  printf '    fastapiIncludedUrls: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value MONITORING_FASTAPI_INCLUDED_URLS "/agent/run")")"
  printf '    fastapiExcludedUrls: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value MONITORING_FASTAPI_EXCLUDED_URLS "")")"
  printf '    fastapiExcludeSpans: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value MONITORING_FASTAPI_EXCLUDE_SPANS "receive,send")")"
  printf '    telemetrySampleRate: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value TELEMETRY_SAMPLE_RATE "1.0")")"
  printf '    traceContentMode: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value MONITORING_TRACE_CONTENT_MODE "full")")"
  printf '    traceMaxChars: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value MONITORING_TRACE_MAX_CHARS "4000")")"
  printf '    traceMaxItems: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value MONITORING_TRACE_MAX_ITEMS "20")")"
}

deployment_render_monitoring_image_value() {
  local key="$1"
  local repository="$2"
  local tag="$3"
  local image
  image="$(deployment_add_image_registry_prefix "${repository}:${tag}")"

  printf '    %s:\n' "$key"
  printf '      repository: %s\n' "$(deployment_yaml_quote "$(deployment_image_repo "$image")")"
  printf '      tag: %s\n' "$(deployment_yaml_quote "$(deployment_image_tag "$image")")"
}

deployment_render_helm_monitoring_chart_values() {
  local enabled
  local langfuse_nextauth_url
  local otel_collector_tag
  local phoenix_tag
  local tempo_tag
  local grafana_tag
  local zipkin_tag
  local langfuse_tag
  local clickhouse_tag
  local minio_tag
  local redis_tag
  local postgres_tag
  enabled="$(deployment_monitoring_enabled)"
  langfuse_nextauth_url="$(deployment_monitoring_env_value K8S_LANGFUSE_NEXTAUTH_URL "http://localhost:${K8S_LANGFUSE_NODE_PORT:-30001}")"
  otel_collector_tag="$(deployment_monitoring_env_value OTEL_COLLECTOR_VERSION "0.151.0")"
  phoenix_tag="$(deployment_monitoring_env_value PHOENIX_VERSION "15")"
  tempo_tag="$(deployment_monitoring_env_value TEMPO_VERSION "2.10.5")"
  grafana_tag="$(deployment_monitoring_env_value GRAFANA_VERSION "12.4")"
  zipkin_tag="$(deployment_monitoring_env_value ZIPKIN_VERSION "latest")"
  langfuse_tag="$(deployment_monitoring_env_value LANGFUSE_VERSION "3")"
  clickhouse_tag="$(deployment_monitoring_env_value LANGFUSE_CLICKHOUSE_VERSION "26.3-alpine")"
  minio_tag="$(deployment_monitoring_env_value LANGFUSE_MINIO_VERSION "RELEASE.2023-12-20T01-00-02Z")"
  redis_tag="$(deployment_monitoring_env_value LANGFUSE_REDIS_VERSION "alpine")"
  postgres_tag="$(deployment_monitoring_env_value LANGFUSE_POSTGRES_VERSION "15-alpine")"

  printf 'nexent-monitoring:\n'
  printf '  enabled: %s\n' "$enabled"
  printf '  provider: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value MONITORING_PROVIDER "$DEPLOYMENT_MONITORING_PROVIDER")")"
  printf '  images:\n'
  deployment_render_monitoring_image_value otelCollector otel/opentelemetry-collector-contrib "$otel_collector_tag"
  deployment_render_monitoring_image_value phoenix arizephoenix/phoenix "$phoenix_tag"
  deployment_render_monitoring_image_value tempo grafana/tempo "$tempo_tag"
  deployment_render_monitoring_image_value grafana grafana/grafana "$grafana_tag"
  deployment_render_monitoring_image_value zipkin openzipkin/zipkin "$zipkin_tag"
  deployment_render_monitoring_image_value langfuseWeb docker.io/langfuse/langfuse "$langfuse_tag"
  deployment_render_monitoring_image_value langfuseWorker docker.io/langfuse/langfuse-worker "$langfuse_tag"
  deployment_render_monitoring_image_value clickhouse docker.io/clickhouse/clickhouse-server "$clickhouse_tag"
  deployment_render_monitoring_image_value minio docker.io/minio/minio "$minio_tag"
  deployment_render_monitoring_image_value redis docker.io/redis "$redis_tag"
  deployment_render_monitoring_image_value postgres docker.io/postgres "$postgres_tag"
  printf '  collector:\n'
  printf '    configFile: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value OTEL_COLLECTOR_CONFIG_FILE "$(deployment_monitoring_collector_config_file k8s "$DEPLOYMENT_MONITORING_PROVIDER")")")"
  printf '    service:\n'
  printf '      grpcPort: %s\n' "$(deployment_monitoring_env_value OTEL_COLLECTOR_GRPC_PORT "4317")"
  printf '      httpPort: %s\n' "$(deployment_monitoring_env_value OTEL_COLLECTOR_HTTP_PORT "4318")"
  printf '    env:\n'
  printf '      langsmithApiKey: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGSMITH_API_KEY "")")"
  printf '      langsmithProject: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGSMITH_PROJECT "nexent")")"
  printf '      langsmithOtlpTracesEndpoint: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGSMITH_OTLP_TRACES_ENDPOINT "https://api.smith.langchain.com/otel/v1/traces")")"
  printf '      langfuseOtlpAuthHeader: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_OTLP_AUTH_HEADER "")")"
  printf '  phoenix:\n'
  printf '    service:\n'
  printf '      port: %s\n' "$(deployment_monitoring_env_value PHOENIX_PORT "6006")"
  printf '      nodePort: %s\n' "$(deployment_monitoring_env_value K8S_PHOENIX_NODE_PORT "30006")"
  printf '  grafana:\n'
  printf '    adminUser: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value GRAFANA_ADMIN_USER "admin")")"
  printf '    adminPassword: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value GRAFANA_ADMIN_PASSWORD "nexent@4321")")"
  printf '    defaultLanguage: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value GRAFANA_DEFAULT_LANGUAGE "zh-Hans")")"
  printf '    service:\n'
  printf '      port: %s\n' "$(deployment_monitoring_env_value GRAFANA_PORT "3002")"
  printf '      nodePort: %s\n' "$(deployment_monitoring_env_value K8S_GRAFANA_NODE_PORT "30002")"
  printf '  tempo:\n'
  printf '    service:\n'
  printf '      port: %s\n' "$(deployment_monitoring_env_value TEMPO_PORT "3200")"
  printf '  zipkin:\n'
  printf '    service:\n'
  printf '      port: %s\n' "$(deployment_monitoring_env_value ZIPKIN_PORT "9411")"
  printf '      nodePort: %s\n' "$(deployment_monitoring_env_value K8S_ZIPKIN_NODE_PORT "30011")"
  printf '  langfuse:\n'
  printf '    nextauthUrl: %s\n' "$(deployment_yaml_quote "$langfuse_nextauth_url")"
  printf '    nextauthSecret: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_NEXTAUTH_SECRET "nexent-langfuse-secret")")"
  printf '    salt: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_SALT "nexent-langfuse-salt")")"
  printf '    encryptionKey: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_ENCRYPTION_KEY "0000000000000000000000000000000000000000000000000000000000000000")")"
  printf '    telemetryEnabled: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_TELEMETRY_ENABLED "false")")"
  printf '    enableExperimentalFeatures: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_ENABLE_EXPERIMENTAL_FEATURES "false")")"
  printf '    init:\n'
  printf '      orgId: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_INIT_ORG_ID "nexent")")"
  printf '      orgName: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_INIT_ORG_NAME "Nexent")")"
  printf '      projectId: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_INIT_PROJECT_ID "nexent")")"
  printf '      projectName: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_INIT_PROJECT_NAME "Nexent")")"
  printf '      projectPublicKey: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_INIT_PROJECT_PUBLIC_KEY "pk-lf-nexent-local")")"
  printf '      projectSecretKey: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_INIT_PROJECT_SECRET_KEY "sk-lf-nexent-local")")"
  printf '      userEmail: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_INIT_USER_EMAIL "admin@nexent.com")")"
  printf '      userName: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_INIT_USER_NAME "admin")")"
  printf '      userPassword: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_INIT_USER_PASSWORD "nexent@4321")")"
  printf '    service:\n'
  printf '      nodePort: %s\n' "$(deployment_monitoring_env_value K8S_LANGFUSE_NODE_PORT "30001")"
  printf '    postgres:\n'
  printf '      user: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_POSTGRES_USER "postgres")")"
  printf '      password: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_POSTGRES_PASSWORD "nexent@4321")")"
  printf '      database: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_POSTGRES_DB "postgres")")"
  printf '    clickhouse:\n'
  printf '      user: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_CLICKHOUSE_USER "clickhouse")")"
  printf '      password: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_CLICKHOUSE_PASSWORD "clickhouse")")"
  printf '    minio:\n'
  printf '      rootUser: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_MINIO_ROOT_USER "minio")")"
  printf '      rootPassword: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_MINIO_ROOT_PASSWORD "miniosecret")")"
  printf '      bucket: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_S3_BUCKET "langfuse")")"
  printf '    redis:\n'
  printf '      auth: %s\n' "$(deployment_yaml_quote "$(deployment_monitoring_env_value LANGFUSE_REDIS_AUTH "myredissecret")")"
}

deployment_render_helm_values() {
  local output_file="$1"
  mkdir -p "$(dirname "$output_file")"
  {
    printf 'global:\n'
    printf '  deploymentSchemaVersion: "%s"\n' "$DEPLOYMENT_SCHEMA_VERSION"
    printf '  deploymentComponents:\n'
    deployment_render_component_values
    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "supabase"; then
      printf '  deploymentVersion: "full"\n'
    else
      printf '  deploymentVersion: "speed"\n'
    fi
    printf '  portPolicy: "%s"\n' "$DEPLOYMENT_PORT_POLICY"
    printf '  imageSource: "%s"\n' "$DEPLOYMENT_IMAGE_SOURCE"
    printf '  imageRegistryPrefix: "%s"\n' "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX"
    deployment_render_helm_monitoring_global_values
    deployment_render_helm_monitoring_chart_values
    deployment_render_helm_chart_values
  } > "$output_file"
}

deployment_persist_local_config() {
  local output_file="${1:-$DEPLOYMENT_LOCAL_CONFIG_PATH}"
  mkdir -p "$(dirname "$output_file")"
  {
    printf 'schemaVersion: "%s"\n' "$DEPLOYMENT_SCHEMA_VERSION"
    printf 'components:\n'
    local old_ifs="$IFS"
    IFS=','
    local component
    for component in $DEPLOYMENT_COMPONENTS; do
      component="$(deployment_trim "$component")"
      printf '  - %s\n' "$component"
    done
    IFS="$old_ifs"
    printf 'portPolicy: "%s"\n' "$DEPLOYMENT_PORT_POLICY"
    printf 'imageSource: "%s"\n' "$DEPLOYMENT_IMAGE_SOURCE"
    printf 'imageRegistryPrefix: "%s"\n' "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX"
    printf 'monitoringProvider: "%s"\n' "$DEPLOYMENT_MONITORING_PROVIDER"
  } > "$output_file"
}

deployment_print_summary() {
  local target="${1:-all}"

  deployment_log "$(deployment_i18n summary.components "$DEPLOYMENT_COMPONENTS")"
  deployment_log "$(deployment_i18n summary.port_policy "$DEPLOYMENT_PORT_POLICY")"
  deployment_log "$(deployment_i18n summary.image_source "$DEPLOYMENT_IMAGE_SOURCE")"
  if [ -n "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX" ]; then
    deployment_log "$(deployment_i18n summary.image_registry_prefix "$DEPLOYMENT_IMAGE_REGISTRY_PREFIX")"
  fi
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring"; then
    deployment_log "$(deployment_i18n summary.monitoring_provider "$DEPLOYMENT_MONITORING_PROVIDER")"
  fi
  case "$target" in
    docker)
      deployment_log "$(deployment_i18n summary.docker_services "$DEPLOYMENT_SELECTED_DOCKER_SERVICES")"
      deployment_log "$(deployment_i18n summary.docker_ports "$DEPLOYMENT_DOCKER_PORTS")"
      ;;
    k8s|helm)
      deployment_log "$(deployment_i18n summary.helm_charts "$DEPLOYMENT_SELECTED_HELM_CHARTS")"
      ;;
    *)
      deployment_log "$(deployment_i18n summary.docker_services "$DEPLOYMENT_SELECTED_DOCKER_SERVICES")"
      deployment_log "$(deployment_i18n summary.helm_charts "$DEPLOYMENT_SELECTED_HELM_CHARTS")"
      deployment_log "$(deployment_i18n summary.docker_ports "$DEPLOYMENT_DOCKER_PORTS")"
      ;;
  esac
}

deployment_prepare_config() {
  local NEXENT_DEPLOY_CONFIG_MODE="${NEXENT_DEPLOY_CONFIG_MODE:-}"

  deployment_init_defaults

  local raw_args=("$@")
  local arg
  for arg in "${raw_args[@]}"; do
    case "$arg" in
      --components) DEPLOYMENT_COMPONENTS_EXPLICIT="true" ;;
      --port-policy) DEPLOYMENT_PORT_POLICY_EXPLICIT="true" ;;
      --image-source) DEPLOYMENT_IMAGE_SOURCE_EXPLICIT="true" ;;
      --registry-profile) DEPLOYMENT_REGISTRY_PROFILE_EXPLICIT="true" ;;
      --image-registry-prefix|--registry-prefix|--image-registry) DEPLOYMENT_IMAGE_REGISTRY_PREFIX_EXPLICIT="true" ;;
      --app-version|--version) DEPLOYMENT_APP_VERSION_EXPLICIT="true" ;;
      --monitoring-provider) DEPLOYMENT_MONITORING_PROVIDER_EXPLICIT="true" ;;
      --config) DEPLOYMENT_RECONFIGURE="true" ;;
      --reconfigure) DEPLOYMENT_RECONFIGURE="true" ;;
      --defaults) DEPLOYMENT_RECONFIGURE="false" ;;
      --rotate-secrets) DEPLOYMENT_ROTATE_SECRETS="true" ;;
      --refresh-es-key) DEPLOYMENT_REFRESH_ES_KEY="true" ;;
    esac
  done

  deployment_parse_common_args "$@"
  if [ -n "${DEPLOYMENT_REGISTRY_PROFILE_EXPLICIT:-}" ] && [ -z "${DEPLOYMENT_IMAGE_SOURCE_EXPLICIT:-}" ]; then
    DEPLOYMENT_IMAGE_SOURCE="$DEPLOYMENT_REGISTRY_PROFILE"
  fi
  deployment_maybe_select_local_config || return 1
  deployment_apply_legacy_inputs
  deployment_parse_common_args "$@"
  if [ -n "${DEPLOYMENT_REGISTRY_PROFILE_EXPLICIT:-}" ] && [ -z "${DEPLOYMENT_IMAGE_SOURCE_EXPLICIT:-}" ]; then
    DEPLOYMENT_IMAGE_SOURCE="$DEPLOYMENT_REGISTRY_PROFILE"
  fi
  deployment_ensure_required_components
  local tui_result=0
  deployment_run_tui_configuration || tui_result=$?
  [ "$tui_result" -eq 0 ] || return "$tui_result"
  deployment_normalize_image_source || return 1
  deployment_normalize_image_registry_prefix
  deployment_validate || return 1
  deployment_compute_selection
}
