#!/bin/bash

# Nexent LLM Performance Monitoring Setup Script
# This script starts the OpenTelemetry Collector alone, or with a local
# Phoenix/Langfuse/Grafana/SkyWalking observability backend, or forward to
# online LangSmith.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITORING_DIR="$SCRIPT_DIR/monitoring"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose-monitoring.yml"

usage() {
    cat <<EOF
Usage: $(basename "$0") [otlp|collector|phoenix|langfuse|langsmith|grafana|zipkin]
       $(basename "$0") --stack <otlp|collector|phoenix|langfuse|langsmith|grafana|zipkin>

Stacks:
  otlp       Start OpenTelemetry Collector only. This is the default.
  collector  Alias for otlp.
  phoenix    Start Collector and local Arize Phoenix.
  langfuse   Start Collector and local Langfuse self-host stack.
  langsmith  Start Collector and forward traces to online LangSmith.
  grafana    Start Collector, Grafana, and Tempo.
  zipkin     Start Collector and local Zipkin.

Set MONITORING_PROVIDER in monitoring/monitoring.env to change the default.
EOF
}

STACK_ARG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --stack)
            if [ $# -lt 2 ]; then
                echo "❌ Error: --stack requires a value."
                usage
                exit 1
            fi
            STACK_ARG="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        otlp|collector|phoenix|langfuse|langsmith|grafana|zipkin)
            STACK_ARG="$1"
            shift
            ;;
        *)
            echo "❌ Error: unknown argument '$1'."
            usage
            exit 1
            ;;
    esac
done

echo "🚀 Starting Nexent LLM Performance Monitoring Setup..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running. Please start Docker first."
    exit 1
fi

# Create external network if it doesn't exist
if ! docker network ls | grep -q nexent_nexent; then
    echo "🔗 Creating nexent_nexent..."
    docker network create nexent_nexent
else
    echo "✅ nexent_nexent already exists"
fi

# Copy environment file if it doesn't exist
if [ ! -f "$MONITORING_DIR/monitoring.env" ]; then
    echo "📋 Creating monitoring.env from example..."
    cp "$MONITORING_DIR/monitoring.env.example" "$MONITORING_DIR/monitoring.env"
    echo "⚠️  Please review and update $MONITORING_DIR/monitoring.env as needed"
fi

# Load deployment options. Keep values shell-compatible in monitoring.env.
set -a
# shellcheck disable=SC1091
. "$MONITORING_DIR/monitoring.env"
set +a

MONITORING_PROVIDER="${STACK_ARG:-${MONITORING_PROVIDER:-otlp}}"
case "$MONITORING_PROVIDER" in
    collector|otlp)
        LOCAL_STACK="collector"
        BACKEND_MONITORING_PROVIDER="otlp"
        OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./monitoring/otel-collector-config.yml}"
        COMPOSE_PROFILES=()
        ;;
    phoenix)
        LOCAL_STACK="phoenix"
        BACKEND_MONITORING_PROVIDER="phoenix"
        OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./monitoring/otel-collector-phoenix-config.yml}"
        COMPOSE_PROFILES=(--profile phoenix)
        ;;
    langfuse)
        LOCAL_STACK="langfuse"
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
        LOCAL_STACK="langsmith"
        BACKEND_MONITORING_PROVIDER="langsmith"
        OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./monitoring/otel-collector-langsmith-config.yml}"
        COMPOSE_PROFILES=()
        LANGSMITH_OTLP_TRACES_ENDPOINT="${LANGSMITH_OTLP_TRACES_ENDPOINT:-https://api.smith.langchain.com/otel/v1/traces}"
        LANGSMITH_PROJECT="${LANGSMITH_PROJECT:-${MONITORING_PROJECT_NAME:-nexent}}"
        if [ -z "${LANGSMITH_API_KEY:-}" ]; then
            echo "❌ Error: LANGSMITH_API_KEY is required for the langsmith stack."
            echo "   Set it in $MONITORING_DIR/monitoring.env or export it before running this script."
            exit 1
        fi
        export LANGSMITH_API_KEY LANGSMITH_PROJECT LANGSMITH_OTLP_TRACES_ENDPOINT
        ;;
    grafana)
        LOCAL_STACK="grafana"
        BACKEND_MONITORING_PROVIDER="grafana"
        OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./monitoring/otel-collector-grafana-config.yml}"
        COMPOSE_PROFILES=(--profile grafana)
        ;;
    zipkin)
        LOCAL_STACK="zipkin"
        BACKEND_MONITORING_PROVIDER="zipkin"
        OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./monitoring/otel-collector-zipkin-config.yml}"
        COMPOSE_PROFILES=(--profile zipkin)
        ;;
    *)
        echo "❌ Error: unsupported MONITORING_PROVIDER '$MONITORING_PROVIDER'."
        usage
        exit 1
        ;;
esac
export OTEL_COLLECTOR_CONFIG_FILE

if docker compose version > /dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
elif command -v docker-compose > /dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
else
    echo "❌ Error: Docker Compose is not installed."
    exit 1
fi

# Start monitoring services
echo "🐳 Starting monitoring services with provider: $MONITORING_PROVIDER"
"${COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" --env-file "$MONITORING_DIR/monitoring.env" "${COMPOSE_PROFILES[@]}" up -d --remove-orphans

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 10

# Check service health with timeout
echo "🔍 Checking service health..."

# Function to check service health with timeout
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

# Check OpenTelemetry Collector HTTP receiver
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
    skywalking)
        check_service "SkyWalking UI" "http://localhost:${SKYWALKING_UI_PORT:-8080}" "${SKYWALKING_UI_PORT:-8080}" || true
        check_service "SkyWalking OAP HTTP API" "http://localhost:${SKYWALKING_OAP_HTTP_PORT:-12800}" "${SKYWALKING_OAP_HTTP_PORT:-12800}" || true
        ;;
esac

echo ""
echo "🎉 Monitoring setup complete!"
echo ""
echo "📊 Access your monitoring tools:"
echo "   • OTLP HTTP receiver: http://localhost:${OTEL_COLLECTOR_HTTP_PORT:-4318}"
echo "   • OTLP gRPC receiver: localhost:${OTEL_COLLECTOR_GRPC_PORT:-4317}"
case "$LOCAL_STACK" in
    phoenix)
        echo "   • Phoenix UI: http://localhost:${PHOENIX_PORT:-6006}"
        ;;
    langfuse)
        echo "   • Langfuse UI: http://localhost:${LANGFUSE_PORT:-3001}"
        echo "   • Langfuse admin: ${LANGFUSE_INIT_USER_EMAIL:-admin@nexent.local} / ${LANGFUSE_INIT_USER_PASSWORD:-nexent-langfuse-admin}"
        ;;
    langsmith)
        echo "   • LangSmith project: ${LANGSMITH_PROJECT:-nexent}"
        echo "   • LangSmith OTLP traces endpoint: ${LANGSMITH_OTLP_TRACES_ENDPOINT:-https://api.smith.langchain.com/otel/v1/traces}"
        ;;
    grafana)
        echo "   • Grafana UI: http://localhost:${GRAFANA_PORT:-3002}"
        echo "   • Grafana admin: ${GRAFANA_ADMIN_USER:-admin} / ${GRAFANA_ADMIN_PASSWORD:-nexent-grafana-admin}"
        echo "   • Tempo API: http://localhost:${TEMPO_PORT:-3200}"
        ;;
    skywalking)
        echo "   • SkyWalking UI: http://localhost:${SKYWALKING_UI_PORT:-8080}"
        echo "   • SkyWalking OAP HTTP API: http://localhost:${SKYWALKING_OAP_HTTP_PORT:-12800}"
        echo "   • SkyWalking OAP gRPC API: localhost:${SKYWALKING_OAP_GRPC_PORT:-11800}"
        ;;
    collector)
        echo "   • Configure Phoenix, Langfuse, LangSmith, Tempo, or another OTLP backend in monitoring.env"
        ;;
esac
echo ""
echo "🔧 To enable monitoring in your Nexent backend:"
echo "   1. Set ENABLE_TELEMETRY=true in your .env file"
echo "   2. Set MONITORING_PROVIDER=$BACKEND_MONITORING_PROVIDER in your .env file"
echo "   3. Set OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318 for Docker services"
echo "      or http://localhost:${OTEL_COLLECTOR_HTTP_PORT:-4318} for a backend running on the host"
echo "   4. Install performance dependencies:"
echo "      uv sync --extra performance"
echo "   5. Restart your Nexent backend service"
echo ""
echo "🔎 Key Trace Data to Inspect:"
echo "   • Agent span hierarchy"
echo "   • LLM generation spans"
echo "   • Tool call spans"
echo "   • Error events"
echo ""
echo "🛑 To stop monitoring services:"
echo "   ${COMPOSE_CMD[*]} -f $COMPOSE_FILE --env-file $MONITORING_DIR/monitoring.env --profile phoenix --profile langfuse --profile grafana --profile skywalking down --remove-orphans"
