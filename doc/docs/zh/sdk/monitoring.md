# 🚀 Nexent LLM 监控系统

专门监控大模型 Token 生成速度和性能的企业级监控解决方案。

## 📊 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                Nexent LLM 监控系统                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Nexent API ──► OpenTelemetry ──► Jaeger (链路追踪)    │
│      │                  │                               │
│      │                  └──────► Prometheus (指标收集)  │
│      │                             │                   │
│      └─► OpenAI LLM                └──► Grafana (可视化) │
│          (Token 监控)                                   │
└─────────────────────────────────────────────────────────┘
```

## ⚡ 快速启动（5分钟）

```bash
# 1. 启动监控服务
./docker/start-monitoring.sh

# 2. 安装性能监控依赖  
uv sync --extra performance

# 3. 启用监控
export ENABLE_TELEMETRY=true

# 4. 启动后端服务
python backend/edit_time_service.py
python backend/runtime_service.py
```

## 📊 访问监控界面

| 界面 | 地址 | 用途 |
|------|------|------|
| **Grafana 仪表板** | http://localhost:3005 | LLM 性能监控 |
| **Jaeger 链路追踪** | http://localhost:16686 | 请求链路分析 |  
| **Prometheus 指标** | http://localhost:9090 | 原始监控数据 |

### 🔐 Grafana 登录信息

首次访问 Grafana (http://localhost:3005) 时需要登录：

```
用户名: admin
密码: admin
```

**首次登录后会要求修改密码，可以：**
- 设置新密码（推荐）
- 点击 "Skip" 跳过（开发环境）

**登录后可以看到：**
- 📊 **LLM Performance Dashboard** - 预配置的性能仪表板
- 📈 **数据源配置** - 自动连接到 Prometheus 和 Jaeger
- 🎯 **实时监控面板** - Token 生成速度、延迟等关键指标

## 🎯 核心功能特性

### ⚡ LLM 专用监控
- **Token 生成速度**: 实时监控每秒生成的 token 数量
- **TTFT (Time to First Token)**: 首个 token 返回延迟
- **流式响应分析**: 每个 token 的生成时间戳
- **模型性能对比**: 不同模型的性能基准

### 🔍 分布式链路追踪
- **完整请求链路**: 从 HTTP 到 LLM 的端到端追踪
- **性能瓶颈识别**: 自动定位慢查询和异常
- **错误根因分析**: 快速定位问题根源

### 🛠️ 开发友好设计
- **一行代码接入**: 使用装饰器快速添加监控
- **零依赖降级**: 未安装监控依赖时自动跳过
- **零感知使用**: 无需手动检查监控状态，自动处理
- **灵活配置**: 环境变量控制监控行为

## 🛠️ 添加监控到代码

### 🎯 推荐方式：单例模式 (v2.1+)

```python
# 后端服务中使用 - 直接使用全局配置好的 monitoring_manager
from utils.monitoring import monitoring_manager

# API 端点监控
@monitoring_manager.monitor_endpoint("my_service.my_function")
async def my_api_function():
    return {"status": "ok"}

# LLM 调用监控
@monitoring_manager.monitor_llm_call("gpt-4", "chat_completion")
def call_llm(messages):
    # 自动获得 Token 级别监控
    return llm_response

# 手动添加监控事件
monitoring_manager.add_span_event("custom_event", {"key": "value"})
monitoring_manager.set_span_attributes(user_id="123", action="process")
```

### 📦 SDK中直接使用

```python
from nexent.monitor import get_monitoring_manager

# 获取全局监控管理器 - 在backend已自动配置
monitor = get_monitoring_manager()

# 使用装饰器
@monitor.monitor_llm_call("claude-3", "completion")
def my_llm_function():
    return "response"

# 或者在业务逻辑中直接使用
with monitor.trace_llm_request("custom_operation", "my_model") as span:
    # 执行业务逻辑
    result = process_data()
    monitor.add_span_event("processing_completed")
    return result
```

### ✨ 全局配置自动化

监控配置已在 `backend/utils/monitoring.py` 中自动初始化：

```python
# 无需手动配置 - 系统启动时自动完成
# monitoring_manager 已经使用环境变量配置完成
from utils.monitoring import monitoring_manager

# 直接使用即可，无需检查是否开启
@monitoring_manager.monitor_endpoint("my_function")
def my_function():
    pass

# FastAPI应用初始化
monitoring_manager.setup_fastapi_app(app)
```

### 🔒 自动启停设计

- **智能监控**: 根据 `ENABLE_TELEMETRY` 环境变量自动启停
- **零感知使用**: 外部代码无需检查监控状态，直接使用所有功能
- **优雅降级**: 未开启时静默无效果，开启时正常工作
- **默认关闭**: 未配置时自动视为关闭状态

```bash
# 开启监控
export ENABLE_TELEMETRY=true

# 关闭监控  
export ENABLE_TELEMETRY=false
```

## 📊 核心监控指标

| 指标 | 描述 | 重要性 |
|------|------|-------|
| `llm_token_generation_rate` | Token 生成速度 (tokens/s) | ⭐⭐⭐ |
| `llm_time_to_first_token_seconds` | 首 Token 延迟 | ⭐⭐⭐ |
| `llm_request_duration_seconds` | 完整请求耗时 | ⭐⭐⭐ |
| `llm_total_tokens` | 输入/输出 Token 数量 | ⭐⭐ |
| `llm_error_count` | LLM 调用错误数 | ⭐⭐⭐ |

## 🔧 环境配置

```bash
# 添加到 .env 文件
cat >> .env << EOF
ENABLE_TELEMETRY=true
SERVICE_NAME=nexent-backend
JAEGER_ENDPOINT=http://localhost:14268/api/traces
LLM_SLOW_REQUEST_THRESHOLD_SECONDS=5.0
LLM_SLOW_TOKEN_RATE_THRESHOLD=10.0
TELEMETRY_SAMPLE_RATE=1.0  # 开发环境，生产环境推荐 0.1
EOF
```

## 🛠️ 验证系统

```bash
# 检查指标端点
curl http://localhost:8000/metrics

# 验证依赖安装
python -c "from backend.utils.monitoring import MONITORING_AVAILABLE; print(f'监控可用: {MONITORING_AVAILABLE}')"
```

## 🆘 故障排除

### 监控数据为空？
```bash
# 检查服务状态
docker-compose -f docker/docker-compose-monitoring.yml ps

# 检查依赖安装
python -c "import opentelemetry; print('✅ 监控依赖已安装')"
```

### 端口冲突？
```bash
# 检查端口占用
lsof -i :3005 -i :9090 -i :16686
```

### 依赖安装问题？
```bash
# 重新安装性能依赖
uv sync --extra performance

# 检查 pyproject.toml 中的 performance 配置
cat backend/pyproject.toml | grep -A 20 "performance"
```

### 服务名显示为 unknown_service？
```bash
# 检查环境变量配置
echo "SERVICE_NAME: $SERVICE_NAME"

# 重启监控服务以应用新配置
./docker/start-monitoring.sh
```

## 🧹 数据管理

### 清理 Jaeger 追踪数据
```bash
# 方法1: 重启 Jaeger 容器（最简单）
docker-compose -f docker/docker-compose-monitoring.yml restart nexent-jaeger

# 方法2: 完全重建 Jaeger 容器和数据
docker-compose -f docker/docker-compose-monitoring.yml stop nexent-jaeger
docker-compose -f docker/docker-compose-monitoring.yml rm -f nexent-jaeger
docker-compose -f docker/docker-compose-monitoring.yml up -d nexent-jaeger

# 方法3: 清理所有监控数据（重建所有容器）
docker-compose -f docker/docker-compose-monitoring.yml down
docker-compose -f docker/docker-compose-monitoring.yml up -d
```

### 清理 Prometheus 指标数据
```bash
# 重启 Prometheus 容器
docker-compose -f docker/docker-compose-monitoring.yml restart nexent-prometheus

# 完全清理 Prometheus 数据
docker-compose -f docker/docker-compose-monitoring.yml stop nexent-prometheus
docker volume rm docker_prometheus_data 2>/dev/null || true
docker-compose -f docker/docker-compose-monitoring.yml up -d nexent-prometheus
```

### 清理 Grafana 配置
```bash
# 重置 Grafana 配置和仪表板
docker-compose -f docker/docker-compose-monitoring.yml stop nexent-grafana
docker volume rm docker_grafana_data 2>/dev/null || true
docker-compose -f docker/docker-compose-monitoring.yml up -d nexent-grafana
```

## 📈 典型问题分析

### Token 生成速度慢 (< 5 tokens/s)
1. **分析**: Grafana → Token Generation Rate 面板
2. **解决**: 检查模型服务负载、优化输入 prompt 长度

### 请求响应慢 (> 10s)
1. **分析**: Jaeger → 查看完整链路追踪
2. **解决**: 定位瓶颈环节（数据库/LLM/网络）

### 错误率突增 (> 10%)
1. **分析**: Prometheus → llm_error_count 指标
2. **解决**: 检查模型服务可用性、验证 API 密钥

## 🎉 开始使用

设置完成后你可以：

1. 📊 在 Grafana 中查看 **LLM Performance Dashboard**
2. 🔍 在 Jaeger 中追踪每个请求的完整链路  
3. 📈 分析 Token 生成速度和性能瓶颈
4. 🚨 设置性能告警和阈值

享受高效的 LLM 性能监控！ 🚀
