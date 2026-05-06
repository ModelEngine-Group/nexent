#!/bin/bash

# Nexent LLM Performance Monitoring Setup Script
# This script starts the OpenTelemetry Collector alone, or with a local
# Phoenix/Langfuse observability backend.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITORING_DIR="$SCRIPT_DIR/monitoring"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose-monitoring.yml"

usage() {
    cat <<EOF
Usage: $(basename "$0") [collector|phoenix|langfuse]
       $(basename "$0") --stack <collector|phoenix|langfuse>

Stacks:
  collector  Start OpenTelemetry Collector only. This is the default.
  phoenix    Start Collector and local Arize Phoenix.
  langfuse   Start Collector and local Langfuse self-host stack.

Set MONITORING_STACK in monitoring/monitoring.env to change the default.
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
        collector|phoenix|langfuse)
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
if ! docker network ls | grep -q nexent-network; then
    echo "🔗 Creating nexent-network..."
    docker network create nexent-network
else
    echo "✅ nexent-network already exists"
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

MONITORING_STACK="${STACK_ARG:-${MONITORING_STACK:-collector}}"
case "$MONITORING_STACK" in
    collector)
        OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./monitoring/otel-collector-config.yml}"
        COMPOSE_PROFILES=()
        ;;
    phoenix)
        OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./monitoring/otel-collector-phoenix-config.yml}"
        COMPOSE_PROFILES=(--profile phoenix)
        ;;
    langfuse)
        OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./monitoring/otel-collector-langfuse-config.yml}"
        COMPOSE_PROFILES=(--profile langfuse)
        LANGFUSE_INIT_PROJECT_PUBLIC_KEY="${LANGFUSE_INIT_PROJECT_PUBLIC_KEY:-pk-lf-nexent-local}"
        LANGFUSE_INIT_PROJECT_SECRET_KEY="${LANGFUSE_INIT_PROJECT_SECRET_KEY:-sk-lf-nexent-local}"
        if [ -z "${LANGFUSE_OTLP_AUTH_HEADER:-}" ]; then
            LANGFUSE_OTLP_AUTH_HEADER="Basic $(printf "%s:%s" "$LANGFUSE_INIT_PROJECT_PUBLIC_KEY" "$LANGFUSE_INIT_PROJECT_SECRET_KEY" | base64 | tr -d '\n')"
        fi
        export LANGFUSE_OTLP_AUTH_HEADER
        ;;
    *)
        echo "❌ Error: unsupported MONITORING_STACK '$MONITORING_STACK'."
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
echo "🐳 Starting monitoring services with stack: $MONITORING_STACK"
"${COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" --env-file "$MONITORING_DIR/monitoring.env" "${COMPOSE_PROFILES[@]}" up -d

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

case "$MONITORING_STACK" in
    phoenix)
        check_service "Phoenix UI" "http://localhost:${PHOENIX_PORT:-6006}" "${PHOENIX_PORT:-6006}" || true
        ;;
    langfuse)
        check_service "Langfuse UI" "http://localhost:${LANGFUSE_PORT:-3001}" "${LANGFUSE_PORT:-3001}" || true
        ;;
esac

echo ""
echo "🎉 Monitoring setup complete!"
echo ""
echo "📊 Access your monitoring tools:"
echo "   • OTLP HTTP receiver: http://localhost:${OTEL_COLLECTOR_HTTP_PORT:-4318}"
echo "   • OTLP gRPC receiver: localhost:${OTEL_COLLECTOR_GRPC_PORT:-4317}"
case "$MONITORING_STACK" in
    phoenix)
        echo "   • Phoenix UI: http://localhost:${PHOENIX_PORT:-6006}"
        ;;
    langfuse)
        echo "   • Langfuse UI: http://localhost:${LANGFUSE_PORT:-3001}"
        echo "   • Langfuse admin: ${LANGFUSE_INIT_USER_EMAIL:-admin@nexent.local} / ${LANGFUSE_INIT_USER_PASSWORD:-nexent-langfuse-admin}"
        ;;
    collector)
        echo "   • Configure Phoenix, Langfuse, Jaeger, or another OTLP backend in monitoring.env"
        ;;
esac
echo ""
echo "🔧 To enable monitoring in your Nexent backend:"
echo "   1. Set ENABLE_TELEMETRY=true in your .env file"
echo "   2. Set OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318 for Docker services"
echo "      or http://localhost:${OTEL_COLLECTOR_HTTP_PORT:-4318} for a backend running on the host"
echo "   3. Install performance dependencies:"
echo "      uv sync --extra performance"
echo "   4. Restart your Nexent backend service"
echo ""
echo "📈 Key Metrics to Monitor:"
echo "   • Token Generation Rate (tokens/second)"
echo "   • Time to First Token (TTFT)"
echo "   • Request Duration"
echo "   • Error Rates"
echo ""
echo "🛑 To stop monitoring services:"
echo "   ${COMPOSE_CMD[*]} -f $COMPOSE_FILE --env-file $MONITORING_DIR/monitoring.env --profile phoenix --profile langfuse down"
