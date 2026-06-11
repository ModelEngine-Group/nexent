# 北向 API 负载测试脚本

本脚本用于对 Nexent 北向 API 进行并发负载测试，支持高并发请求，帮助评估接口在高压情况下的性能表现和稳定性。

## 功能特性

- 支持多种端点测试（健康检查、Agent 列表、对话历史、聊天接口）
- 可配置的并发请求数（默认 100 并发）
- 支持持续压测模式
- 自动预热功能
- 详细的性能统计报告
- 支持自定义超时设置

## 快速开始

### 基本用法

```bash
# 测试健康检查端点（100 并发）
python scripts/load_test.py --endpoint health --concurrency 100

# 测试聊天接口
python scripts/load_test.py --endpoint chat --concurrency 100 --access-key YOUR_API_KEY
```

### 环境要求

- Python 3.8+
- httpx 库（已包含在项目依赖中）

## 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--base-url` | `http://localhost:5013/api` | API 服务地址 |
| `--access-key` | 空 | 认证 Token（Bearer 方式） |
| `--concurrency` | `100` | 并发请求数 |
| `--duration` | 无 | 测试持续时间（秒），不指定则执行单轮测试 |
| `--endpoint` | `health` | 测试的端点类型 |
| `--warmup` | `5` | 预热请求数量 |

## 支持的端点

| 端点 | API 路径 | 说明 | 需要的认证 |
|------|----------|------|-----------|
| `health` | `/nb/v1/health` | 健康检查接口 | 否 |
| `agents` | `/nb/v1/agents` | 获取 Agent 列表 | 是 |
| `conversations` | `/nb/v1/conversations` | 获取会话列表 | 是 |
| `chat` | `/nb/v1/chat/run` | 聊天接口 | 是 |

## 使用示例

### 1. 健康检查测试

测试服务是否正常运行，不需要认证：

```bash
python scripts/load_test.py --endpoint health --concurrency 100
```

### 2. Agent 列表查询测试

需要提供有效的 Access Key：

```bash
python scripts/load_test.py \
  --endpoint agents \
  --concurrency 100 \
  --access-key your_access_key_here
```

### 3. 聊天接口测试

测试核心对话功能的并发性能：

```bash
python scripts/load_test.py \
  --endpoint chat \
  --concurrency 100 \
  --access-key your_access_key_here
```

### 4. 持续压测模式

指定持续时间，持续发送并发请求，用于长时间稳定性测试：

```bash
python scripts/load_test.py \
  --endpoint chat \
  --concurrency 100 \
  --duration 60 \
  --access-key your_access_key_here
```

### 5. 自定义服务地址

测试远程或 Docker 环境中的服务：

```bash
python scripts/load_test.py \
  --base-url http://192.168.1.100:5013/api \
  --endpoint chat \
  --concurrency 100
```

### 6. 调整预热请求数

默认会发送 5 个预热请求，可以调整或禁用：

```bash
# 禁用预热
python scripts/load_test.py --endpoint health --warmup 0

# 增加预热请求
python scripts/load_test.py --endpoint chat --warmup 10 --access-key your_key
```

## 输出说明

### 测试结果示例

```
============================================================
Load Test Results
============================================================
Total Requests:       100
Successful:            100
Failed:                0
Success Rate:          100.00%
Duration:              2.35s
Throughput:            42.55 req/s

Response Times:
  Average:             2350.50 ms
  Min:                 1200.30 ms
  Max:                 4500.10 ms
  P50 (Median):         2100.00 ms
  P90:                  3800.00 ms
  P95:                  4100.00 ms
  P99:                  4400.00 ms

Status Codes:
  200: 100 (100.0%)
============================================================
```

### 指标说明

| 指标 | 说明 |
|------|------|
| `Total Requests` | 总请求数 |
| `Successful` | 成功请求数（HTTP 2xx 响应） |
| `Failed` | 失败请求数 |
| `Success Rate` | 请求成功率 |
| `Duration` | 测试总耗时 |
| `Throughput` | 吞吐量（请求/秒） |
| `Average` | 平均响应时间 |
| `Min / Max` | 最短/最长响应时间 |
| `P50 (Median)` | 中位数响应时间，50% 请求在此时间内完成 |
| `P90` | 90% 百分位，90% 请求在此时间内完成 |
| `P95` | 95% 百分位，95% 请求在此时间内完成 |
| `P99` | 99% 百分位，99% 请求在此时间内完成 |

## 性能基准参考

以下是在标准硬件环境下（4 核 CPU，8GB 内存）的参考数据：

### 健康检查接口

| 并发数 | 预期吞吐量 | 平均响应时间 |
|--------|-----------|-------------|
| 10 | 200-300 req/s | 30-50 ms |
| 50 | 500-800 req/s | 60-100 ms |
| 100 | 800-1200 req/s | 80-120 ms |

### 聊天接口

| 并发数 | 预期吞吐量 | 平均响应时间 | 说明 |
|--------|-----------|-------------|------|
| 10 | 5-10 req/s | 1000-2000 ms | 受 LLM 推理影响 |
| 50 | 10-20 req/s | 2500-4000 ms | 高并发时延迟增加 |
| 100 | 15-25 req/s | 4000-6000 ms | 需要服务资源充足 |

**注意：** 实际性能取决于 LLM 模型推理时间、网络延迟、服务器负载和数据库性能等因素。

## 集成到 CI/CD

### Shell 脚本集成

```bash
#!/bin/bash
# run_load_test.sh

echo "Starting load test..."

python scripts/load_test.py \
  --endpoint chat \
  --concurrency 100 \
  --access-key "$API_ACCESS_KEY" \
  --base-url "$API_BASE_URL"

if [ $? -eq 0 ]; then
    echo "Load test passed!"
else
    echo "Load test failed!"
    exit 1
fi
```

### GitHub Actions 集成

```yaml
name: Load Test

on:
  push:
    branches: [main]

jobs:
  load-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: pip install httpx

      - name: Run load test
        run: |
          python scripts/load_test.py \
            --endpoint health \
            --concurrency 100
        env:
          API_BASE_URL: ${{ secrets.API_BASE_URL }}
```

### Python 测试框架集成

```python
import subprocess
import pytest

def test_api_performance():
    """性能测试用例"""
    result = subprocess.run(
        [
            "python", "scripts/load_test.py",
            "--endpoint", "health",
            "--concurrency", "50"
        ],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0
    assert "Success Rate:          100.00%" in result.stdout

    # 验证响应时间在可接受范围内
    # 从输出中解析 P95 响应时间进行断言
```

## 常见问题

### Q: 如何获取 Access Key？

Access Key（API Key）需要通过后端管理界面或 API 创建，具体请参考用户文档。

### Q: 测试时返回 401 未授权错误？

确保使用了正确的 Access Key，并且该 Key 具有访问相应接口的权限。对于 `health` 端点不需要认证。

### Q: 响应时间较长是什么原因？

响应时间受多种因素影响：
- LLM 模型推理时间（聊天接口）
- 网络延迟
- 服务器负载
- 数据库查询性能
- 外部服务依赖

### Q: 如何调整超时时间？

当前脚本对普通请求设置了 30 秒超时，对聊天接口设置了 120 秒超时。如需调整，请修改脚本中的 `timeout` 参数。

### Q: 测试时出现大量超时错误？

可能原因：
1. 服务器资源不足，需要降低并发数
2. LLM 服务响应慢，建议检查模型服务状态
3. 网络问题，检查客户端与服务器之间的网络连接

### Q: 持续压测模式与单轮测试的区别？

- **单轮测试**：发送指定数量的请求后结束（`--concurrency N` 表示发送 N 个并发请求）
- **持续压测**：在指定时间内持续发送请求（`--duration S`），适合稳定性测试

### Q: 如何测试不同的聊天消息内容？

当前脚本使用固定的测试消息。如需自定义，可以修改 `get_chat_payload` 方法中的 `query` 字段。

## 性能优化建议

### 1. 预热服务

首次运行会自动执行 5 个预热请求，帮助建立连接池，避免冷启动影响测试结果。

### 2. 逐步增压

建议从较小并发开始，逐步增加负载，观察性能曲线：

```bash
# 第一轮：低并发基线测试
python scripts/load_test.py --endpoint chat --concurrency 10 --access-key your_key

# 第二轮：中等并发测试
python scripts/load_test.py --endpoint chat --concurrency 50 --access-key your_key

# 第三轮：高并发测试
python scripts/load_test.py --endpoint chat --concurrency 100 --access-key your_key
```

### 3. 监控资源

测试时建议同时监控服务器资源：
- CPU 使用率
- 内存使用量
- 网络带宽
- 数据库连接数

### 4. 多次测试

建议进行多次测试取平均值，以获得更稳定的性能数据。避免在服务器负载高峰时段进行测试。

### 5. 测试环境隔离

生产环境性能测试应该在测试环境或影子环境中进行，避免影响正常服务。

## 故障排查指南

### 问题诊断流程

1. **检查服务状态**：先使用 `--endpoint health` 确认服务正常运行
2. **检查认证**：确认 Access Key 有效且有权限
3. **降低并发**：减少 `--concurrency` 值，排除并发导致的问题
4. **查看详细错误**：观察输出中的错误信息

### 日志分析

查看失败请求的错误类型：
- **Timeout**：请求超时，可能是服务响应慢
- **Connection refused**：服务未启动或端口错误
- **500 Internal Server Error**：服务端错误，检查服务端日志
