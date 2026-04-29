#!/bin/bash

# Nexent LLM Performance Monitoring Setup Script
# This script starts the OpenTelemetry Collector used by Nexent monitoring.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITORING_DIR="$SCRIPT_DIR/monitoring"

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

# Start monitoring services
echo "🐳 Starting monitoring services..."
docker-compose -f "$SCRIPT_DIR/docker-compose-monitoring.yml" --env-file "$MONITORING_DIR/monitoring.env" up -d

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
check_service "OpenTelemetry Collector HTTP receiver" "http://localhost:4318" "4318" || true

echo ""
echo "🎉 Monitoring setup complete!"
echo ""
echo "📊 Access your monitoring tools:"
echo "   • OTLP HTTP receiver: http://localhost:4318"
echo "   • OTLP gRPC receiver: localhost:4317"
echo "   • Configure Phoenix, Langfuse, Jaeger, or another OTLP backend in monitoring.env"
echo ""
echo "🔧 To enable monitoring in your Nexent backend:"
echo "   1. Set ENABLE_TELEMETRY=true in your .env file"
echo "   2. Install performance dependencies:"
echo "      uv sync --extra performance"
echo "   3. Restart your Nexent backend service"
echo ""
echo "📈 Key Metrics to Monitor:"
echo "   • Token Generation Rate (tokens/second)"
echo "   • Time to First Token (TTFT)"
echo "   • Request Duration"
echo "   • Error Rates"
echo ""
echo "🛑 To stop monitoring services: docker-compose -f docker-compose-monitoring.yml down"
