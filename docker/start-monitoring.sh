#!/bin/bash

# Nexent LLM Performance Monitoring Setup Script
# This script starts the OpenTelemetry Collector alone, or with a local
# Phoenix/Langfuse/Grafana/Zipkin observability backend, or forwards to
# online LangSmith.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITORING_DIR="$SCRIPT_DIR/monitoring"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose-monitoring.yml"

SUPPORTED_STACKS="otlp, collector, phoenix, langfuse, langsmith, grafana, zipkin"

usage() {
    cat <<EOF
Usage:
  $(basename "$0") [otlp|collector|phoenix|langfuse|langsmith|grafana|zipkin]
  $(basename "$0") --stack <otlp|collector|phoenix|langfuse|langsmith|grafana|zipkin>
  $(basename "$0") <start|up> [stack]
  $(basename "$0") <stop|down> [stack]
  $(basename "$0") <uninstall|remove> [stack]

Stacks are mutually exclusive. Starting one stack removes containers from the
other monitoring stacks while preserving their data volumes.

Stacks:
  otlp       Start OpenTelemetry Collector only. This is the default.
  collector  Alias for otlp.
  phoenix    Start Collector and local Arize Phoenix.
  langfuse   Start Collector and local Langfuse self-host stack.
  langsmith  Start Collector and forward traces to online LangSmith.
  grafana    Start Collector, Grafana, and Tempo.
  zipkin     Start Collector and local Zipkin.

Actions:
  start/up     Start the selected stack and stop containers from other stacks.
  stop/down    Stop and remove containers for the selected stack. Data is kept.
  uninstall    Stop and remove containers and data volumes for the selected stack.

Set MONITORING_PROVIDER in monitoring/monitoring.env to change the default stack.
EOF
}

ACTION="start"
STACK_ARG=""

set_stack_arg() {
    local value="$1"
    if [ -n "$STACK_ARG" ] && [ "$STACK_ARG" != "$value" ]; then
        echo "❌ Error: multiple monitoring stacks specified: '$STACK_ARG' and '$value'."
        usage
        exit 1
    fi
    STACK_ARG="$value"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --stack)
            if [ $# -lt 2 ]; then
                echo "❌ Error: --stack requires a value."
                usage
                exit 1
            fi
            set_stack_arg "$2"
            shift 2
            ;;
        --stop|--down)
            ACTION="stop"
            shift
            ;;
        --uninstall|--remove)
            ACTION="uninstall"
            shift
            ;;
        start|up)
            ACTION="start"
            shift
            ;;
        stop|down)
            ACTION="stop"
            shift
            ;;
        uninstall|remove)
            ACTION="uninstall"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        otlp|collector|phoenix|langfuse|langsmith|grafana|zipkin)
            set_stack_arg "$1"
            shift
            ;;
        *)
            echo "❌ Error: unknown argument '$1'."
            usage
            exit 1
            ;;
    esac
done

normalize_stack() {
    case "$1" in
        ""|otlp|collector)
            echo "collector"
            ;;
        phoenix|langfuse|langsmith|grafana|zipkin)
            echo "$1"
            ;;
        *)
            echo "❌ Error: unsupported monitoring provider '$1'. Supported: $SUPPORTED_STACKS." >&2
            exit 1
            ;;
    esac
}

if [ -n "$STACK_ARG" ]; then
    normalize_stack "$STACK_ARG" > /dev/null
fi

remove_containers() {
    if [ "$#" -eq 0 ]; then
        return
    fi

    local existing=()
    local container
    for container in "$@"; do
        if docker ps -a --format '{{.Names}}' | grep -qx "$container"; then
            existing+=("$container")
        fi
    done

    if [ "${#existing[@]}" -gt 0 ]; then
        docker rm -f "${existing[@]}" > /dev/null
        echo "🧹 Removed containers: ${existing[*]}"
    fi
}

remove_volumes() {
    if [ "$#" -eq 0 ]; then
        return
    fi

    local existing=()
    local volume
    for volume in "$@"; do
        if docker volume ls --format '{{.Name}}' | grep -qx "$volume"; then
            existing+=("$volume")
        fi
    done

    if [ "${#existing[@]}" -gt 0 ]; then
        docker volume rm "${existing[@]}" > /dev/null
        echo "🧹 Removed volumes: ${existing[*]}"
    fi
}

stack_containers() {
    case "$1" in
        collector|langsmith)
            echo "nexent-otel-collector"
            ;;
        phoenix)
            echo "nexent-otel-collector nexent-phoenix"
            ;;
        langfuse)
            echo "nexent-otel-collector nexent-langfuse-worker nexent-langfuse-web nexent-langfuse-clickhouse nexent-langfuse-minio nexent-langfuse-redis nexent-langfuse-postgres"
            ;;
        grafana)
            echo "nexent-otel-collector nexent-grafana nexent-tempo"
            ;;
        zipkin)
            echo "nexent-otel-collector nexent-zipkin"
            ;;
    esac
}

stack_data_volumes() {
    case "$1" in
        phoenix)
            echo "monitor_phoenix-data"
            ;;
        langfuse)
            echo "monitor_langfuse-postgres-data monitor_langfuse-clickhouse-data monitor_langfuse-clickhouse-logs monitor_langfuse-minio-data monitor_langfuse-redis-data"
            ;;
        grafana)
            echo "monitor_grafana-data monitor_tempo-data"
            ;;
        collector|langsmith|zipkin)
            echo ""
            ;;
    esac
}

all_backend_containers() {
    echo "nexent-phoenix nexent-langfuse-worker nexent-langfuse-web nexent-langfuse-clickhouse nexent-langfuse-minio nexent-langfuse-redis nexent-langfuse-postgres nexent-grafana nexent-tempo nexent-zipkin"
}

incompatible_containers() {
    local stack="$1"
    local containers
    containers="$(all_backend_containers)"
    case "$stack" in
        phoenix)
            echo "$containers" | sed 's/nexent-phoenix//g'
            ;;
        langfuse)
            echo "$containers" | sed 's/nexent-langfuse-worker//g; s/nexent-langfuse-web//g; s/nexent-langfuse-clickhouse//g; s/nexent-langfuse-minio//g; s/nexent-langfuse-redis//g; s/nexent-langfuse-postgres//g'
            ;;
        grafana)
            echo "$containers" | sed 's/nexent-grafana//g; s/nexent-tempo//g'
            ;;
        zipkin)
            echo "$containers" | sed 's/nexent-zipkin//g'
            ;;
        collector|langsmith)
            echo "$containers"
            ;;
    esac
}

configure_stack() {
    MONITORING_PROVIDER="${STACK_ARG:-${MONITORING_PROVIDER:-otlp}}"
    LOCAL_STACK="$(normalize_stack "$MONITORING_PROVIDER")"

    case "$LOCAL_STACK" in
        collector)
            BACKEND_MONITORING_PROVIDER="otlp"
            OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./monitoring/otel-collector-config.yml}"
            COMPOSE_PROFILES=()
            ;;
        phoenix)
            BACKEND_MONITORING_PROVIDER="phoenix"
            OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./monitoring/otel-collector-phoenix-config.yml}"
            COMPOSE_PROFILES=(--profile phoenix)
            ;;
        langfuse)
            BACKEND_MONITORING_PROVIDER="langfuse"
            OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./monitoring/otel-collector-langfuse-config.yml}"
            COMPOSE_PROFILES=(--profile langfuse)
            LANGFUSE_INIT_PROJECT_PUBLIC_KEY="${LANGFUSE_INIT_PROJECT_PUBLIC_KEY:-pk-lf-nexent-local}"
            LANGFUSE_INIT_PROJECT_SECRET_KEY="${LANGFUSE_INIT_PROJECT_SECRET_KEY:-sk-lf-nexent-local}"
            if [ -z "${LANGFUSE_OTLP_AUTH_HEADER:-}" ]; then
                LANGFUSE_OTLP_AUTH_HEADER="Basic $(printf "%s:%s" "$LANGFUSE_INIT_PROJECT_PUBLIC_KEY" "$LANGFUSE_INIT_PROJECT_SECRET_KEY" | base64 | tr -d '\n')"
            fi
            export LANGFUSE_OTLP_AUTH_HEADER
            ;;
        langsmith)
            BACKEND_MONITORING_PROVIDER="langsmith"
            OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./monitoring/otel-collector-langsmith-config.yml}"
            COMPOSE_PROFILES=()
            LANGSMITH_OTLP_TRACES_ENDPOINT="${LANGSMITH_OTLP_TRACES_ENDPOINT:-https://api.smith.langchain.com/otel/v1/traces}"
            LANGSMITH_PROJECT="${LANGSMITH_PROJECT:-nexent}"
            if [ "$ACTION" = "start" ] && [ -z "${LANGSMITH_API_KEY:-}" ]; then
                echo "❌ Error: LANGSMITH_API_KEY is required for the langsmith stack."
                echo "   Set it in $MONITORING_DIR/monitoring.env or export it before running this script."
                exit 1
            fi
            export LANGSMITH_API_KEY LANGSMITH_PROJECT LANGSMITH_OTLP_TRACES_ENDPOINT
            ;;
        grafana)
            BACKEND_MONITORING_PROVIDER="grafana"
            OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./monitoring/otel-collector-grafana-config.yml}"
            COMPOSE_PROFILES=(--profile grafana)
            ;;
        zipkin)
            BACKEND_MONITORING_PROVIDER="zipkin"
            OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./monitoring/otel-collector-zipkin-config.yml}"
            COMPOSE_PROFILES=(--profile zipkin)
            ;;
    esac
    export OTEL_COLLECTOR_CONFIG_FILE
}

dashboard_url() {
    case "$LOCAL_STACK" in
        phoenix)
            echo "http://localhost:${PHOENIX_PORT:-6006}"
            ;;
        langfuse)
            echo "http://localhost:${LANGFUSE_PORT:-3001}"
            ;;
        langsmith)
            echo "https://smith.langchain.com/"
            ;;
        grafana)
            echo "http://localhost:${GRAFANA_PORT:-3002}/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1"
            ;;
        zipkin)
            echo "http://localhost:${ZIPKIN_PORT:-9411}"
            ;;
        collector)
            echo ""
            ;;
    esac
}

print_access_hints() {
    local dashboard
    dashboard="$(dashboard_url)"

    echo ""
    echo "📊 Access your monitoring tools:"
    echo "   • OTLP HTTP receiver: http://localhost:${OTEL_COLLECTOR_HTTP_PORT:-4318}"
    echo "   • OTLP gRPC receiver: localhost:${OTEL_COLLECTOR_GRPC_PORT:-4317}"
    echo "   • Docker backend endpoint: http://otel-collector:4318"

    case "$LOCAL_STACK" in
        phoenix)
            echo "   • Phoenix UI: $dashboard"
            echo "   • Phoenix direct gRPC ingest: localhost:${PHOENIX_GRPC_HOST_PORT:-4319}"
            ;;
        langfuse)
            echo "   • Langfuse UI: $dashboard"
            echo "   • Langfuse admin: ${LANGFUSE_INIT_USER_EMAIL:-admin@nexent.com} / ${LANGFUSE_INIT_USER_PASSWORD:-nexent@4321}"
            echo "   • Langfuse project keys: ${LANGFUSE_INIT_PROJECT_PUBLIC_KEY:-pk-lf-nexent-local} / ${LANGFUSE_INIT_PROJECT_SECRET_KEY:-sk-lf-nexent-local}"
            echo "   • MinIO API: http://localhost:${LANGFUSE_MINIO_API_PORT:-9092}"
            echo "   • MinIO console: http://localhost:${LANGFUSE_MINIO_CONSOLE_PORT:-9093}"
            ;;
        langsmith)
            echo "   • LangSmith UI: $dashboard"
            echo "   • LangSmith project: ${LANGSMITH_PROJECT:-nexent}"
            echo "   • LangSmith OTLP traces endpoint: ${LANGSMITH_OTLP_TRACES_ENDPOINT:-https://api.smith.langchain.com/otel/v1/traces}"
            echo "   • No local LangSmith UI is started; open the hosted UI and select the project above."
            ;;
        grafana)
            echo "   • Grafana dashboard: $dashboard"
            echo "   • Grafana home: http://localhost:${GRAFANA_PORT:-3002}"
            echo "   • Grafana admin: ${GRAFANA_ADMIN_USER:-admin} / ${GRAFANA_ADMIN_PASSWORD:-nexent@4321}"
            echo "   • Tempo API: http://localhost:${TEMPO_PORT:-3200}"
            ;;
        zipkin)
            echo "   • Zipkin UI: $dashboard"
            ;;
        collector)
            echo "   • Collector-only mode has no monitoring UI."
            echo "   • View Collector logs: docker logs -f nexent-otel-collector"
            echo "   • Configure Phoenix, Langfuse, LangSmith, Grafana/Tempo, Zipkin, or another OTLP backend when you need a UI."
            ;;
    esac

    echo ""
    echo "🔗 Frontend monitoring entry:"
    if [ -n "$dashboard" ]; then
        echo "   Set MONITORING_DASHBOARD_URL=$dashboard"
    else
        echo "   Leave MONITORING_DASHBOARD_URL empty to hide the monitoring entry."
    fi
}

print_backend_hints() {
    echo ""
    echo "🔧 To enable monitoring in your Nexent backend:"
    echo "   1. Set ENABLE_TELEMETRY=true in docker/.env"
    echo "   2. Set MONITORING_PROVIDER=$BACKEND_MONITORING_PROVIDER in docker/.env"
    echo "   3. Set OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318 for Docker services"
    echo "      or http://localhost:${OTEL_COLLECTOR_HTTP_PORT:-4318} for a backend running on the host"
    echo "   4. Set MONITORING_DASHBOARD_URL as shown above when a UI is available"
    echo "   5. Install performance dependencies:"
    echo "      uv sync --extra performance"
    echo "   6. Restart your Nexent backend service"
}

print_uninstall_hints() {
    echo ""
    echo "🛑 Stop or uninstall this monitoring stack:"
    echo "   • Stop containers and keep data:"
    echo "     $(basename "$0") stop $LOCAL_STACK"
    echo "   • Remove containers and this stack's data volumes:"
    echo "     $(basename "$0") uninstall $LOCAL_STACK"
    echo ""
    echo "   Stacks are mutually exclusive; do not run multiple monitoring providers in parallel."
}

load_env_for_start() {
    if [ ! -f "$MONITORING_DIR/monitoring.env" ]; then
        echo "📋 Creating monitoring.env from example..."
        cp "$MONITORING_DIR/monitoring.env.example" "$MONITORING_DIR/monitoring.env"
        echo "⚠️  Please review and update $MONITORING_DIR/monitoring.env as needed"
    fi

    set -a
    # shellcheck disable=SC1091
    . "$MONITORING_DIR/monitoring.env"
    set +a
}

load_env_if_present() {
    if [ -f "$MONITORING_DIR/monitoring.env" ]; then
        set -a
        # shellcheck disable=SC1091
        . "$MONITORING_DIR/monitoring.env"
        set +a
    fi
}

resolve_compose_cmd() {
    if docker compose version > /dev/null 2>&1; then
        COMPOSE_CMD=(docker compose)
    elif command -v docker-compose > /dev/null 2>&1; then
        COMPOSE_CMD=(docker-compose)
    else
        echo "❌ Error: Docker Compose is not installed."
        exit 1
    fi
}

check_service() {
    local name=$1
    local url=$2
    local port=$3

    if curl -s --max-time 5 --connect-timeout 3 "$url" > /dev/null 2>&1; then
        echo "✅ $name is running at http://localhost:$port"
        return 0
    else
        echo "⚠️  $name may not be ready yet (will start in background)"
        return 1
    fi
}

check_stack_health() {
    echo "🔍 Checking service health..."
    check_service "OpenTelemetry Collector HTTP receiver" "http://localhost:${OTEL_COLLECTOR_HTTP_PORT:-4318}" "${OTEL_COLLECTOR_HTTP_PORT:-4318}" || true

    case "$LOCAL_STACK" in
        phoenix)
            check_service "Phoenix UI" "http://localhost:${PHOENIX_PORT:-6006}" "${PHOENIX_PORT:-6006}" || true
            ;;
        langfuse)
            check_service "Langfuse UI" "http://localhost:${LANGFUSE_PORT:-3001}" "${LANGFUSE_PORT:-3001}" || true
            ;;
        langsmith)
            echo "✅ LangSmith forwarding is configured for project: ${LANGSMITH_PROJECT:-nexent}"
            ;;
        grafana)
            check_service "Grafana" "http://localhost:${GRAFANA_PORT:-3002}/api/health" "${GRAFANA_PORT:-3002}" || true
            check_service "Tempo API" "http://localhost:${TEMPO_PORT:-3200}/ready" "${TEMPO_PORT:-3200}" || true
            ;;
        zipkin)
            check_service "Zipkin UI" "http://localhost:${ZIPKIN_PORT:-9411}" "${ZIPKIN_PORT:-9411}" || true
            ;;
    esac
}

start_stack() {
    echo "🚀 Starting Nexent LLM Performance Monitoring Setup..."

    if ! docker info > /dev/null 2>&1; then
        echo "❌ Error: Docker is not running. Please start Docker first."
        exit 1
    fi

    resolve_compose_cmd

    if ! docker network ls --format '{{.Name}}' | grep -qx nexent_network; then
        echo "🔗 Creating nexent_network..."
        docker network create nexent_network
    else
        echo "✅ nexent_network already exists"
    fi

    load_env_for_start
    configure_stack

    local incompatible
    incompatible="$(incompatible_containers "$LOCAL_STACK")"
    if [ -n "$incompatible" ]; then
        # shellcheck disable=SC2086
        remove_containers $incompatible
    fi

    echo "🐳 Starting monitoring services with provider: $MONITORING_PROVIDER"
    echo "   Selected stack: $LOCAL_STACK"
    "${COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" --env-file "$MONITORING_DIR/monitoring.env" "${COMPOSE_PROFILES[@]}" up -d --remove-orphans

    echo "⏳ Waiting for services to start..."
    sleep 10
    check_stack_health

    echo ""
    echo "🎉 Monitoring setup complete!"
    print_access_hints
    print_backend_hints
    echo ""
    echo "🔎 Key Trace Data to Inspect:"
    echo "   • Agent span hierarchy"
    echo "   • LLM generation spans"
    echo "   • Retriever and memory spans"
    echo "   • Tool call spans"
    echo "   • Error events"
    print_uninstall_hints
}

stop_or_uninstall_stack() {
    local remove_data="$1"

    if ! docker info > /dev/null 2>&1; then
        echo "❌ Error: Docker is not running. Please start Docker first."
        exit 1
    fi

    load_env_if_present
    configure_stack

    local containers
    containers="$(stack_containers "$LOCAL_STACK")"
    echo "🛑 Removing monitoring containers for stack: $LOCAL_STACK"
    # shellcheck disable=SC2086
    remove_containers $containers

    if [ "$remove_data" = "true" ]; then
        local volumes
        volumes="$(stack_data_volumes "$LOCAL_STACK")"
        if [ -n "$volumes" ]; then
            echo "🧹 Removing data volumes for stack: $LOCAL_STACK"
            # shellcheck disable=SC2086
            remove_volumes $volumes
        else
            echo "ℹ️  Stack '$LOCAL_STACK' has no dedicated local data volumes."
        fi
        echo "✅ Monitoring stack '$LOCAL_STACK' has been uninstalled."
    else
        echo "✅ Monitoring stack '$LOCAL_STACK' has been stopped. Data volumes were kept."
    fi

    echo ""
    echo "ℹ️  The shared Docker network 'nexent_network' is kept because it is also used by Nexent services."
}

case "$ACTION" in
    start)
        start_stack
        ;;
    stop)
        stop_or_uninstall_stack false
        ;;
    uninstall)
        stop_or_uninstall_stack true
        ;;
esac
