# 🚀 Nexent LLM Monitoring System

Enterprise-grade monitoring solution specifically designed for monitoring LLM token generation speed and performance.

## 📊 System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                Nexent LLM Monitoring System            │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Nexent API ──► OpenTelemetry ──► Jaeger (Tracing)     │
│      │                  │                               │
│      │                  └──────► Prometheus (Metrics)   │
│      │                             │                   │
│      └─► OpenAI LLM                └──► Grafana (Visualization) │
│          (Token Monitoring)                             │
└─────────────────────────────────────────────────────────┘
```

## ⚡ Quick Start (5 minutes)

```bash
# 1. Start monitoring services
./docker/start-monitoring.sh

# 2. Install performance monitoring dependencies  
uv sync --extra performance

# 3. Enable monitoring
export ENABLE_TELEMETRY=true

# 4. Start backend service
python backend/edit_time_service.py
python backend/runtime_service.py
```

## 📊 Access Monitoring Interfaces

| Interface | URL | Purpose |
|-----------|-----|---------|
| **Grafana Dashboard** | http://localhost:3005 | LLM Performance Monitoring |
| **Jaeger Tracing** | http://localhost:16686 | Request Trace Analysis |  
| **Prometheus Metrics** | http://localhost:9090 | Raw Monitoring Data |

### 🔐 Grafana Login Information

When first accessing Grafana (http://localhost:3005), you need to login:

```
Username: admin
Password: admin
```

**After first login, you'll be prompted to change password:**
- Set a new password (recommended)
- Click "Skip" to skip (development environment)

**After login, you can see:**
- 📊 **LLM Performance Dashboard** - Pre-configured performance dashboard
- 📈 **Data Source Configuration** - Auto-connected to Prometheus and Jaeger
- 🎯 **Real-time Monitoring Panel** - Key metrics like token generation speed, latency

## 🎯 Core Features

### ⚡ LLM-Specific Monitoring
- **Token Generation Speed**: Real-time monitoring of tokens generated per second
- **TTFT (Time to First Token)**: First token return latency
- **Streaming Response Analysis**: Generation timestamp for each token
- **Model Performance Comparison**: Performance benchmarks across different models

### 🔍 Distributed Tracing
- **Complete Request Chain**: End-to-end tracing from HTTP to LLM
- **Performance Bottleneck Detection**: Automatically identify slow queries and anomalies
- **Error Root Cause Analysis**: Quickly locate problem sources

### 🛠️ Developer-Friendly Design
- **One-Line Integration**: Quick monitoring with decorators
- **Zero-Dependency Degradation**: Auto-skip when monitoring dependencies are missing
- **Zero-Touch Usage**: No need to manually check monitoring status, handled automatically
- **Flexible Configuration**: Environment variable controlled behavior

## 🛠️ Adding Monitoring to Code

### 🎯 Recommended Approach: Singleton Pattern (v2.1+)

```python
# Backend service usage - directly use globally configured monitoring_manager
from utils.monitoring import monitoring_manager

# API endpoint monitoring
@monitoring_manager.monitor_endpoint("my_service.my_function")
async def my_api_function():
    return {"status": "ok"}

# LLM call monitoring
@monitoring_manager.monitor_llm_call("gpt-4", "chat_completion")
def call_llm(messages):
    # Automatically get token-level monitoring
    return llm_response

# Manual monitoring events
monitoring_manager.add_span_event("custom_event", {"key": "value"})
monitoring_manager.set_span_attributes(user_id="123", action="process")
```

### 📦 Direct SDK Usage

```python
from nexent.monitor import get_monitoring_manager

# Get global monitoring manager - already configured in backend
monitor = get_monitoring_manager()

# Use decorators
@monitor.monitor_llm_call("claude-3", "completion")
def my_llm_function():
    return "response"

# Or use directly in business logic
with monitor.trace_llm_request("custom_operation", "my_model") as span:
    # Execute business logic
    result = process_data()
    monitor.add_span_event("processing_completed")
    return result
```

### ✨ Global Configuration Automation

Monitoring configuration is auto-initialized in `backend/utils/monitoring.py`:

```python
# No manual configuration needed - auto-completed at system startup
# monitoring_manager already configured with environment variables
from utils.monitoring import monitoring_manager

# Direct usage without checking if enabled
@monitoring_manager.monitor_endpoint("my_function")
def my_function():
    pass

# FastAPI application initialization
monitoring_manager.setup_fastapi_app(app)
```

### 🔒 Auto Start/Stop Design

- **Smart Monitoring**: Auto start/stop based on `ENABLE_TELEMETRY` environment variable
- **Zero-Touch Usage**: External code doesn't need to check monitoring status, use all features directly
- **Graceful Degradation**: Silent no-effect when disabled, normal operation when enabled
- **Default Off**: Auto-disabled when not configured

```bash
# Enable monitoring
export ENABLE_TELEMETRY=true

# Disable monitoring  
export ENABLE_TELEMETRY=false
```

## 📊 Core Monitoring Metrics

| Metric | Description | Importance |
|--------|-------------|------------|
| `llm_token_generation_rate` | Token generation speed (tokens/s) | ⭐⭐⭐ |
| `llm_time_to_first_token_seconds` | First token latency | ⭐⭐⭐ |
| `llm_request_duration_seconds` | Complete request duration | ⭐⭐⭐ |
| `llm_total_tokens` | Input/output token count | ⭐⭐ |
| `llm_error_count` | LLM call error count | ⭐⭐⭐ |

## 🔧 Environment Configuration

```bash
# Add to .env file
cat >> .env << EOF
ENABLE_TELEMETRY=true
SERVICE_NAME=nexent-backend
JAEGER_ENDPOINT=http://localhost:14268/api/traces
LLM_SLOW_REQUEST_THRESHOLD_SECONDS=5.0
LLM_SLOW_TOKEN_RATE_THRESHOLD=10.0
TELEMETRY_SAMPLE_RATE=1.0  # Development environment, production recommended 0.1
EOF
```

## 🛠️ System Verification

```bash
# Check metrics endpoint
curl http://localhost:8000/metrics

# Verify dependency installation
python -c "from backend.utils.monitoring import MONITORING_AVAILABLE; print(f'Monitoring Available: {MONITORING_AVAILABLE}')"
```

## 🆘 Troubleshooting

### No monitoring data?
```bash
# Check service status
docker-compose -f docker/docker-compose-monitoring.yml ps

# Check dependency installation
python -c "import opentelemetry; print('✅ Monitoring dependencies installed')"
```

### Port conflicts?
```bash
# Check port usage
lsof -i :3005 -i :9090 -i :16686
```

### Dependency installation issues?
```bash
# Reinstall performance dependencies
uv sync --extra performance

# Check performance configuration in pyproject.toml
cat backend/pyproject.toml | grep -A 20 "performance"
```

### Service name shows as unknown_service?
```bash
# Check environment variable configuration
echo "SERVICE_NAME: $SERVICE_NAME"

# Restart monitoring service to apply new configuration
./docker/start-monitoring.sh
```

## 🧹 Data Management

### Clean Jaeger Trace Data
```bash
# Method 1: Restart Jaeger container (simplest)
docker-compose -f docker/docker-compose-monitoring.yml restart nexent-jaeger

# Method 2: Completely rebuild Jaeger container and data
docker-compose -f docker/docker-compose-monitoring.yml stop nexent-jaeger
docker-compose -f docker/docker-compose-monitoring.yml rm -f nexent-jaeger
docker-compose -f docker/docker-compose-monitoring.yml up -d nexent-jaeger

# Method 3: Clean all monitoring data (rebuild all containers)
docker-compose -f docker/docker-compose-monitoring.yml down
docker-compose -f docker/docker-compose-monitoring.yml up -d
```

### Clean Prometheus Metrics Data
```bash
# Restart Prometheus container
docker-compose -f docker/docker-compose-monitoring.yml restart nexent-prometheus

# Completely clean Prometheus data
docker-compose -f docker/docker-compose-monitoring.yml stop nexent-prometheus
docker volume rm docker_prometheus_data 2>/dev/null || true
docker-compose -f docker/docker-compose-monitoring.yml up -d nexent-prometheus
```

### Clean Grafana Configuration
```bash
# Reset Grafana configuration and dashboards
docker-compose -f docker/docker-compose-monitoring.yml stop nexent-grafana
docker volume rm docker_grafana_data 2>/dev/null || true
docker-compose -f docker/docker-compose-monitoring.yml up -d nexent-grafana
```

## 📈 Typical Problem Analysis

### Slow token generation (< 5 tokens/s)
1. **Analysis**: Grafana → Token Generation Rate panel
2. **Solution**: Check model service load, optimize input prompt length

### Slow request response (> 10s)
1. **Analysis**: Jaeger → View complete trace chain
2. **Solution**: Locate bottleneck (database/LLM/network)

### Error rate spike (> 10%)
1. **Analysis**: Prometheus → llm_error_count metric
2. **Solution**: Check model service availability, verify API keys

## 🎉 Getting Started

After setup completion, you can:

1. 📊 View **LLM Performance Dashboard** in Grafana
2. 🔍 Trace complete request chains in Jaeger  
3. 📈 Analyze token generation speed and performance bottlenecks
4. 🚨 Set performance alerts and thresholds

Enjoy efficient LLM performance monitoring! 🚀
