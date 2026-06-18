#!/usr/bin/env bash

# Shared deployment configuration helpers for Docker and Kubernetes deploy scripts.
# This file is intentionally dependency-light so it can be sourced from Bash-only
# install environments.

DEPLOYMENT_SCHEMA_VERSION="1"
DEPLOYMENT_COMPONENTS_DEFAULT="infrastructure,application"
DEPLOYMENT_PORT_POLICY_DEFAULT="development"
DEPLOYMENT_IMAGE_SOURCE_DEFAULT="general"
DEPLOYMENT_REGISTRY_PROFILE_DEFAULT="general"
DEPLOYMENT_MONITORING_PROVIDER_DEFAULT="otlp"

DEPLOYMENT_COMPONENTS=""
DEPLOYMENT_PORT_POLICY=""
DEPLOYMENT_IMAGE_SOURCE=""
DEPLOYMENT_REGISTRY_PROFILE=""
DEPLOYMENT_APP_VERSION=""
DEPLOYMENT_MONITORING_PROVIDER=""
DEPLOYMENT_CONFIG_PATH=""
DEPLOYMENT_USE_LOCAL_CONFIG="false"
DEPLOYMENT_RECONFIGURE="false"
DEPLOYMENT_LOCAL_CONFIG_PATH=""
DEPLOYMENT_SELECTED_DOCKER_SERVICES=""
DEPLOYMENT_SELECTED_HELM_CHARTS=""
DEPLOYMENT_LOADED_SCHEMA_VERSION=""
DEPLOYMENT_LOADED_APP_VERSION=""
DEPLOYMENT_CONFIG_FILE_LOADED="false"
DEPLOYMENT_DOCKER_PORTS=""

deployment_component_list="infrastructure application data-process supabase terminal monitoring"
deployment_port_policy_list="development production"
deployment_image_source_list="general mainland local-latest"
deployment_registry_profile_list="general mainland"
deployment_monitoring_provider_list="otlp phoenix langfuse langsmith grafana zipkin"

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
  DEPLOYMENT_APP_VERSION="${APP_VERSION:-latest}"
  DEPLOYMENT_MONITORING_PROVIDER="$DEPLOYMENT_MONITORING_PROVIDER_DEFAULT"
  DEPLOYMENT_CONFIG_PATH=""
  DEPLOYMENT_USE_LOCAL_CONFIG="false"
  DEPLOYMENT_RECONFIGURE="false"
  DEPLOYMENT_LOCAL_CONFIG_PATH="$(deployment_default_local_config_path)"
  DEPLOYMENT_LOADED_SCHEMA_VERSION=""
  DEPLOYMENT_LOADED_APP_VERSION=""
  DEPLOYMENT_CONFIG_FILE_LOADED="false"
  DEPLOYMENT_DOCKER_PORTS=""
  unset DEPLOYMENT_COMPONENTS_EXPLICIT DEPLOYMENT_PORT_POLICY_EXPLICIT DEPLOYMENT_REGISTRY_PROFILE_EXPLICIT
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
        DEPLOYMENT_RECONFIGURE="true"
        shift
        ;;
      --config)
        DEPLOYMENT_CONFIG_PATH="$2"
        shift 2
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
        portPolicy) DEPLOYMENT_PORT_POLICY="$value" ;;
        schemaVersion)
          [ "$load_mode" = "apply" ] && DEPLOYMENT_LOADED_SCHEMA_VERSION="$value"
          ;;
        imageSource) DEPLOYMENT_IMAGE_SOURCE="$value" ;;
        registryProfile) DEPLOYMENT_REGISTRY_PROFILE="$value" ;;
        appVersion)
          DEPLOYMENT_APP_VERSION="$value"
          [ "$load_mode" = "apply" ] && DEPLOYMENT_LOADED_APP_VERSION="$value"
          ;;
        monitoringProvider) DEPLOYMENT_MONITORING_PROVIDER="$value" ;;
      esac
    fi
  done < "$config_file"

  [ -n "$components" ] && DEPLOYMENT_COMPONENTS="$components"
  [ "$load_mode" = "apply" ] && DEPLOYMENT_CONFIG_FILE_LOADED="true"
  return 0
}

deployment_apply_legacy_inputs() {
  if [ -z "${DEPLOYMENT_COMPONENTS_EXPLICIT:-}" ]; then
    case "${DEPLOYMENT_VERSION:-}" in
      speed)
        deployment_warn "DEPLOYMENT_VERSION=speed is deprecated; use --components infrastructure,application."
        DEPLOYMENT_COMPONENTS="infrastructure,application"
        ;;
      full)
        deployment_warn "DEPLOYMENT_VERSION=full is deprecated; use --components infrastructure,application,supabase."
        DEPLOYMENT_COMPONENTS="infrastructure,application,supabase"
        ;;
    esac
  fi

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

  if [ -n "${IS_MAINLAND:-}" ] && [ -z "${DEPLOYMENT_REGISTRY_PROFILE_EXPLICIT:-}" ]; then
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
    deployment_error "Local config schemaVersion $DEPLOYMENT_LOADED_SCHEMA_VERSION is incompatible with $DEPLOYMENT_SCHEMA_VERSION. Re-run with --reconfigure."
    return 1
  fi
  if [ -n "$DEPLOYMENT_LOADED_APP_VERSION" ] && [ -n "${APP_VERSION:-}" ] && [ -z "${DEPLOYMENT_APP_VERSION_EXPLICIT:-}" ] && [ "$DEPLOYMENT_LOADED_APP_VERSION" != "$APP_VERSION" ]; then
    deployment_error "Local config appVersion $DEPLOYMENT_LOADED_APP_VERSION does not match current appVersion $APP_VERSION. Re-run with --reconfigure or pass --app-version."
    return 1
  fi

  local old_ifs="$IFS"
  local component
  IFS=','
  for component in $DEPLOYMENT_COMPONENTS; do
    component="$(deployment_trim "$component")"
    IFS="$old_ifs"
    deployment_is_valid_value "$component" $deployment_component_list || {
      deployment_error "Unknown deployment component: $component"
      return 1
    }
    IFS=','
  done
  IFS="$old_ifs"

  deployment_is_valid_value "$DEPLOYMENT_PORT_POLICY" $deployment_port_policy_list || {
    deployment_error "Unsupported port policy: $DEPLOYMENT_PORT_POLICY. Use development or production."
    return 1
  }
  deployment_is_valid_value "$DEPLOYMENT_IMAGE_SOURCE" $deployment_image_source_list || {
    deployment_error "Unsupported image source: $DEPLOYMENT_IMAGE_SOURCE. Use general, mainland, or local-latest."
    return 1
  }
  deployment_is_valid_value "$DEPLOYMENT_REGISTRY_PROFILE" $deployment_registry_profile_list || {
    deployment_error "Unsupported registry profile: $DEPLOYMENT_REGISTRY_PROFILE"
    return 1
  }
  deployment_is_valid_value "$DEPLOYMENT_MONITORING_PROVIDER" $deployment_monitoring_provider_list || {
    deployment_error "Unsupported monitoring provider: $DEPLOYMENT_MONITORING_PROVIDER"
    return 1
  }
}

deployment_tui_cancel() {
  printf '\033[?25h'
  printf '\033[2J\033[H'
  deployment_warn "Deployment configuration cancelled."
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
    "required core dependencies: Elasticsearch, PostgreSQL, Redis, MinIO"
    "Nexent app services: config, runtime, MCP, northbound API, web UI"
    "background file parsing, indexing, and knowledge processing workers"
    "user, tenant, login, invitation, and permission services"
    "OpenSSH container used by the terminal tool"
    "OpenTelemetry collector and optional tracing dashboard"
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
    printf 'Select deployment components\n'
    printf 'Choose which service groups to install. infrastructure is required and cannot be disabled.\n'
    printf 'Use Up/Down or j/k to move, Space to toggle, Enter to confirm, q to quit.\n\n'
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
    "collector only; use this when forwarding to an external OTLP backend"
    "local Phoenix UI for LLM traces and span inspection"
    "local self-hosted Langfuse stack; replace default secrets for production"
    "forward traces to hosted LangSmith; requires LANGSMITH_API_KEY"
    "local Grafana + Tempo dashboard for traces"
    "local Zipkin UI for trace browsing"
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
    printf 'Select monitoring provider\n'
    printf 'This is used only when the monitoring component is selected.\n'
    printf 'Provider controls where OpenTelemetry traces are stored and viewed.\n'
    printf 'Use Up/Down or j/k to move, Enter to confirm, b/Backspace to go back, q to quit.\n\n'
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
    "publish web plus debug/internal service ports for local troubleshooting"
    "publish only production entry ports; keep internal services private"
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
    printf 'Select port policy\n'
    printf 'This controls which service ports are exposed on the host or cluster node.\n'
    printf 'Choose development for local debugging; choose production for a smaller external surface.\n'
    printf 'Use Up/Down or j/k to move, Enter to confirm, b/Backspace to go back, q to quit.\n\n'
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

deployment_tui_select_image_source() {
  [ -t 0 ] || return 0
  [ -n "${DEPLOYMENT_IMAGE_SOURCE_EXPLICIT:-}" ] && return 0
  [ "$DEPLOYMENT_CONFIG_FILE_LOADED" = "true" ] && return 0

  local sources=(general mainland local-latest)
  local details=(
    "pull images from standard public registries"
    "pull from mainland China mirrors for better access in mainland networks"
    "use locally built Nexent :latest images and avoid pulling app images"
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
    printf 'Select image source\n'
    printf 'This controls where deployment images come from.\n'
    printf 'Use local-latest only after building Nexent images locally.\n'
    printf 'Use Up/Down or j/k to move, Enter to confirm, b/Backspace to go back, q to quit.\n\n'
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
  [ -f "$DEPLOYMENT_LOCAL_CONFIG_PATH" ] || return 0
  if [ "$DEPLOYMENT_RECONFIGURE" = "true" ]; then
    deployment_load_config_file "$DEPLOYMENT_LOCAL_CONFIG_PATH" defaults || return 1
    return 0
  fi
  if [ "$DEPLOYMENT_USE_LOCAL_CONFIG" = "true" ]; then
    DEPLOYMENT_CONFIG_PATH="$DEPLOYMENT_LOCAL_CONFIG_PATH"
    return 0
  fi
  [ -t 0 ] || return 0

  deployment_log "Existing deployment config found: $DEPLOYMENT_LOCAL_CONFIG_PATH"
  deployment_log "Choose how to handle saved deployment options:"
  deployment_log "  1) Use local config - skip the menus and reuse the saved components, port policy, image source, and monitoring provider."
  deployment_log "  2) Reconfigure - load the saved values as defaults, then show the menus so you can change them."
  deployment_log "     Choose this option when enabling or disabling monitoring, switching providers, or changing deployment scope."
  local input
  read -r -p "Choose [1/2] (default: 1): " input
  if [ "${input:-1}" = "1" ]; then
    DEPLOYMENT_CONFIG_PATH="$DEPLOYMENT_LOCAL_CONFIG_PATH"
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

deployment_apply_image_source() {
  local version="${DEPLOYMENT_APP_VERSION:-latest}"

  if [ "$DEPLOYMENT_IMAGE_SOURCE" = "local-latest" ]; then
    export NEXENT_IMAGE="nexent/nexent:latest"
    export NEXENT_WEB_IMAGE="nexent/nexent-web:latest"
    export NEXENT_DATA_PROCESS_IMAGE="nexent/nexent-data-process:latest"
    export NEXENT_MCP_DOCKER_IMAGE="nexent/nexent-mcp:latest"
    export OPENSSH_SERVER_IMAGE="nexent/nexent-ubuntu-terminal:latest"
  fi

  export NEXENT_IMAGE="${NEXENT_IMAGE:-nexent/nexent:$version}"
  export NEXENT_WEB_IMAGE="${NEXENT_WEB_IMAGE:-nexent/nexent-web:$version}"
  export NEXENT_DATA_PROCESS_IMAGE="${NEXENT_DATA_PROCESS_IMAGE:-nexent/nexent-data-process:$version}"
  export NEXENT_MCP_DOCKER_IMAGE="${NEXENT_MCP_DOCKER_IMAGE:-nexent/nexent-mcp:$version}"
  export ELASTICSEARCH_IMAGE="${ELASTICSEARCH_IMAGE:-docker.elastic.co/elasticsearch/elasticsearch:8.17.4}"
  export POSTGRESQL_IMAGE="${POSTGRESQL_IMAGE:-postgres:15-alpine}"
  export REDIS_IMAGE="${REDIS_IMAGE:-redis:alpine}"
  export MINIO_IMAGE="${MINIO_IMAGE:-quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z}"
  export OPENSSH_SERVER_IMAGE="${OPENSSH_SERVER_IMAGE:-nexent/nexent-ubuntu-terminal:$version}"
  export SUPABASE_KONG="${SUPABASE_KONG:-kong:2.8.1}"
  export SUPABASE_GOTRUE="${SUPABASE_GOTRUE:-supabase/gotrue:v2.170.0}"
  export SUPABASE_DB="${SUPABASE_DB:-supabase/postgres:15.8.1.060}"
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
      printf 'http://localhost:30006'
      ;;
    k8s:langfuse|helm:langfuse)
      printf 'http://localhost:30001'
      ;;
    k8s:grafana|helm:grafana)
      printf 'http://localhost:30002/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1'
      ;;
    k8s:zipkin|helm:zipkin)
      printf 'http://localhost:30011'
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
  mkdir -p "$(dirname "$output_file")"
  {
    printf 'NEXENT_IMAGE="%s"\n' "$NEXENT_IMAGE"
    printf 'NEXENT_WEB_IMAGE="%s"\n' "$NEXENT_WEB_IMAGE"
    printf 'NEXENT_DATA_PROCESS_IMAGE="%s"\n' "$NEXENT_DATA_PROCESS_IMAGE"
    printf 'NEXENT_MCP_DOCKER_IMAGE="%s"\n' "$NEXENT_MCP_DOCKER_IMAGE"
    printf 'ELASTICSEARCH_IMAGE="%s"\n' "$ELASTICSEARCH_IMAGE"
    printf 'POSTGRESQL_IMAGE="%s"\n' "$POSTGRESQL_IMAGE"
    printf 'REDIS_IMAGE="%s"\n' "$REDIS_IMAGE"
    printf 'MINIO_IMAGE="%s"\n' "$MINIO_IMAGE"
    printf 'OPENSSH_SERVER_IMAGE="%s"\n' "$OPENSSH_SERVER_IMAGE"
    printf 'SUPABASE_KONG="%s"\n' "$SUPABASE_KONG"
    printf 'SUPABASE_GOTRUE="%s"\n' "$SUPABASE_GOTRUE"
    printf 'SUPABASE_DB="%s"\n' "$SUPABASE_DB"
    printf 'ENABLE_TELEMETRY="%s"\n' "$(deployment_monitoring_enabled)"
    printf 'MONITORING_PROVIDER="%s"\n' "$DEPLOYMENT_MONITORING_PROVIDER"
    printf 'MONITORING_DASHBOARD_URL="%s"\n' "$(deployment_monitoring_dashboard_url docker)"
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
  [ "$DEPLOYMENT_IMAGE_SOURCE" = "local-latest" ] && local_pull_policy="Never"

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
}

deployment_render_k8s_port_values() {
  local northbound_type="ClusterIP"
  local internal_type="ClusterIP"
  if [ "$DEPLOYMENT_PORT_POLICY" = "development" ]; then
    northbound_type="NodePort"
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
  local northbound_type="ClusterIP"
  local internal_type="ClusterIP"
  [ "$DEPLOYMENT_IMAGE_SOURCE" = "local-latest" ] && local_pull_policy="Never"
  if [ "$DEPLOYMENT_PORT_POLICY" = "development" ]; then
    northbound_type="NodePort"
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
  printf '  service:\n    type: "%s"\n    nodePort: 30999\n' "$internal_type"
  printf 'nexent-supabase-db:\n'
  printf '  enabled: %s\n' "$(deployment_chart_enabled supabase)"
  printf '  image:\n    repository: "%s"\n    tag: "%s"\n    pullPolicy: "IfNotPresent"\n' "$(deployment_image_repo "$SUPABASE_DB")" "$(deployment_image_tag "$SUPABASE_DB")"
  printf '  service:\n    type: "%s"\n    nodePort: 30436\n' "$internal_type"
  printf 'nexent-common:\n'
  printf '  images:\n    mcp:\n      repository: "%s"\n      tag: "%s"\n      pullPolicy: "%s"\n' "$(deployment_image_repo "$NEXENT_MCP_DOCKER_IMAGE")" "$(deployment_image_tag "$NEXENT_MCP_DOCKER_IMAGE")" "$local_pull_policy"
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
    printf '  monitoring:\n'
    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring"; then
      printf '    enabled: true\n'
    else
      printf '    enabled: false\n'
    fi
    printf '    provider: "%s"\n' "$DEPLOYMENT_MONITORING_PROVIDER"
    printf '    dashboardUrl: "%s"\n' "$(deployment_monitoring_dashboard_url k8s)"
    printf 'nexent-monitoring:\n'
    if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring"; then
      printf '  enabled: true\n'
    else
      printf '  enabled: false\n'
    fi
    printf '  provider: "%s"\n' "$DEPLOYMENT_MONITORING_PROVIDER"
    deployment_render_helm_chart_values
  } > "$output_file"
}

deployment_persist_local_config() {
  local output_file="${1:-$DEPLOYMENT_LOCAL_CONFIG_PATH}"
  mkdir -p "$(dirname "$output_file")"
  {
    printf 'schemaVersion: "%s"\n' "$DEPLOYMENT_SCHEMA_VERSION"
    printf 'appVersion: "%s"\n' "$DEPLOYMENT_APP_VERSION"
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
    printf 'monitoringProvider: "%s"\n' "$DEPLOYMENT_MONITORING_PROVIDER"
  } > "$output_file"
}

deployment_print_summary() {
  local target="${1:-all}"

  deployment_log "Deployment components: $DEPLOYMENT_COMPONENTS"
  deployment_log "Port policy: $DEPLOYMENT_PORT_POLICY"
  deployment_log "Image source: $DEPLOYMENT_IMAGE_SOURCE"
  if deployment_csv_contains "$DEPLOYMENT_COMPONENTS" "monitoring"; then
    deployment_log "Monitoring provider: $DEPLOYMENT_MONITORING_PROVIDER"
  fi
  case "$target" in
    docker)
      deployment_log "Docker services: $DEPLOYMENT_SELECTED_DOCKER_SERVICES"
      deployment_log "Docker published ports: $DEPLOYMENT_DOCKER_PORTS"
      ;;
    k8s|helm)
      deployment_log "Helm charts: $DEPLOYMENT_SELECTED_HELM_CHARTS"
      ;;
    *)
      deployment_log "Docker services: $DEPLOYMENT_SELECTED_DOCKER_SERVICES"
      deployment_log "Helm charts: $DEPLOYMENT_SELECTED_HELM_CHARTS"
      deployment_log "Docker published ports: $DEPLOYMENT_DOCKER_PORTS"
      ;;
  esac
}

deployment_prepare_config() {
  deployment_init_defaults

  local raw_args=("$@")
  local arg
  for arg in "${raw_args[@]}"; do
    case "$arg" in
      --components) DEPLOYMENT_COMPONENTS_EXPLICIT="true" ;;
      --port-policy) DEPLOYMENT_PORT_POLICY_EXPLICIT="true" ;;
      --image-source) DEPLOYMENT_IMAGE_SOURCE_EXPLICIT="true" ;;
      --registry-profile) DEPLOYMENT_REGISTRY_PROFILE_EXPLICIT="true" ;;
      --app-version|--version) DEPLOYMENT_APP_VERSION_EXPLICIT="true" ;;
      --monitoring-provider) DEPLOYMENT_MONITORING_PROVIDER_EXPLICIT="true" ;;
    esac
  done

  deployment_parse_common_args "$@"
  if [ -n "${DEPLOYMENT_REGISTRY_PROFILE_EXPLICIT:-}" ] && [ -z "${DEPLOYMENT_IMAGE_SOURCE_EXPLICIT:-}" ]; then
    DEPLOYMENT_IMAGE_SOURCE="$DEPLOYMENT_REGISTRY_PROFILE"
  fi
  deployment_maybe_select_local_config
  if [ -n "$DEPLOYMENT_CONFIG_PATH" ] && [ "$DEPLOYMENT_RECONFIGURE" != "true" ]; then
    deployment_load_config_file "$DEPLOYMENT_CONFIG_PATH" || return 1
  fi
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
  deployment_validate || return 1
  deployment_compute_selection
}
