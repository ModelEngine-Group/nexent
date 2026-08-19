# webhook\_server.py 使用文档

Webhook 服务，用于从 Langfuse UI 或命令行触发 benchmark 实验。

## 功能

- 接收 Langfuse UI "Run Experiment" 按钮的 webhook 请求，在后台运行实验
- 接收 curl/HTTP 直接调用，触发实验或重新评分
- 兼容两种 payload 格式（Langfuse camelCase / 直接调用 snake\_case）
- 后台异步执行，立即返回确认

## 启动

```bash
backend/.venv/bin/python sdk/benchmark/generic/integrations/langfuse/webhook_server.py --port 8090 --host 127.0.0.1
```

| 参数       | 默认值       | 说明   |
| -------- | --------- | ---- |
| `--port` | `8090`    | 监听端口 |
| `--host` | `127.0.0.1` | 监听地址 |

Webhook 服务本身不提供身份认证。不要将其直接暴露到公网；远程使用时必须通过带有认证、请求大小限制和限流的反向代理，并只开放必要路径。

## API 端点

### POST /webhook

触发实验或重新评分。

#### Payload 格式

服务同时接受两种格式，自动识别：

**格式 A — 直接调用（curl / 脚本）：**

```json
{
  "dataset_name": "gsm8k-n10",
  "config": {
    "mode": "run",
    "evaluators": ["numeric_answer"],
    "max_steps": 15,
    "run_name": "my-experiment"
  }
}
```

**格式 B — Langfuse UI（自动发送）：**

```json
{
  "projectId": "ctxdbg",
  "datasetId": "uuid-xxx",
  "datasetName": "gsm8k-n10",
  "payload": "{\"mode\":\"run\",\"evaluators\":[\"numeric_answer\"],\"max_steps\":15}"
}
```

> Langfuse UI 的 "Default config" 文本框内容会被序列化为 JSON 字符串放在 `payload` 字段中，服务端自动解析。

#### 顶层字段

| 字段（格式 A）       | 字段（格式 B）      |  必填 | 说明                    |
| -------------- | ------------- | :-: | --------------------- |
| `dataset_name` | `datasetName` |  ✅  | Langfuse 数据集名称        |
| `dataset_id`   | `datasetId`   |  否  | 数据集 ID（当前未使用）         |
| —              | `projectId`   |  否  | Langfuse 项目 ID（当前未使用） |
| `config`       | —             |  否  | 配置对象（dict）            |
| —              | `payload`     |  否  | 配置对象（JSON 字符串）        |

> `config` 和 `payload` 二选一。如果同时提供，优先使用 `config`。

#### config / payload 内部字段

| 字段             | 类型          | 默认值                  | 说明                                  |
| -------------- | ----------- | -------------------- | ----------------------------------- |
| `mode`         | `str`       | `"run"`              | `"run"` 运行新实验，`"rescore"` 重新评分已有结果  |
| `evaluators`   | `list[str]` | `["numeric_answer"]` | 评分器名称列表                             |
| `max_steps`    | `int`       | `10`                 | Agent 最大执行步数                        |
| `temperature`  | `float`     | `0.1`                | LLM 温度                              |
| `language`     | `str`       | `"en"`               | `"en"` 或 `"zh"`                     |
| `run_name`     | `str`       | 自动生成                 | 实验运行名称                              |
| `existing_run` | `str`       | —                    | `mode="rescore"` 时必填，指定要重新评分的已有运行名称 |

#### 可用评分器

| 评分器              | 说明                | 适用场景         |
| ---------------- | ----------------- | ------------ |
| `numeric_answer` | 提取数字并比较           | 数学题、计算题      |
| `exact_match`    | SQuAD 标准化后精确匹配    | 短答案 QA       |
| `em`             | `exact_match` 的别名 | 同上           |
| `f1`             | Token 级 F1 分数     | 开放式 QA       |
| `keyword_match`  | 关键词命中率            | 需要包含特定关键词的回答 |

#### 响应

**成功：**

```json
{"status": "accepted", "mode": "run", "run_name": "my-experiment"}
```

```json
{"status": "accepted", "mode": "rescore", "run_name": "my-run-rescore-numeric_answer"}
```

**失败：**

```json
{"status": "error", "message": "dataset_name is required (send dataset_name or datasetName)"}
```

```json
{"status": "error", "message": "existing_run is required for rescore mode"}
```

```json
{"status": "error", "message": "invalid payload JSON: ..."}
```

### GET /health

健康检查。

```json
{"status": "ok", "service": "nexent-benchmark-webhook"}
```

### GET /evaluators

列出所有可用评分器。

```json
{"evaluators": ["exact_match", "em", "f1", "keyword_match", "numeric_answer"]}
```

## 使用示例

### 1. curl 直接触发实验

```bash
curl -X POST http://localhost:8090/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_name": "gsm8k-n10",
    "config": {
      "mode": "run",
      "evaluators": ["numeric_answer"],
      "max_steps": 15,
      "run_name": "curl-test-1"
    }
  }'

curl -X POST http://47.116.185.156:8090/webhook \
  -H "Content-Type: application/json" \
  -d '{"dataset_name":"gsm8k-n10","config":{"mode":"run","evaluators":["numeric_answer"],"max_steps":15,"run_name": "curl-test-frp"}}'

curl -X POST http://47.116.185.156/webhook \
  -H "Content-Type: application/json" \
  -d '{"dataset_name":"gsm8k-n10","config":{"mode":"run","evaluators":["numeric_answer"],"max_steps":15,"run_name": "curl-frp-caddy"}}'
```

### 2. curl 重新评分

```bash
curl -X POST http://localhost:8090/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_name": "gsm8k-n10",
    "config": {
      "mode": "rescore",
      "existing_run": "curl-test-1",
      "evaluators": ["em", "f1"],
      "run_name": "curl-test-1-rescore"
    }
  }'
```

### 3. Langfuse UI 配置

1. 打开 Langfuse UI → **Datasets** → 选择数据集
2. 点击 **Start Experiment**
3. 点击 **⚡** (Custom Experiment)
4. 填写配置：

| 配置项                | 值                                                                                                 |
| ------------------ | ------------------------------------------------------------------------------------------------- |
| **URL**            | `https://<your-ngrok-host>.ngrok-free.dev/webhook`                                                |
| **Default config** | `{"mode": "run", "evaluators": ["numeric_answer"], "max_steps": 15, "run_name": "langfuse-test"}` |

1. 点击 **Save**
2. 之后每次点击 **Run** 按钮即可触发实验

### 4. 模拟 Langfuse UI 发送的格式（调试用）

```bash
curl -X POST http://localhost:8090/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "projectId": "ctxdbg",
    "datasetId": "test-uuid",
    "datasetName": "gsm8k-n10",
    "payload": "{\"mode\":\"run\",\"evaluators\":[\"numeric_answer\"],\"max_steps\":15,\"run_name\":\"langfuse-format-test\"}"
  }'
```

## 环境要求

- Python 3.11（使用 `backend/.venv`）
- `.env` 文件中配置 Langfuse 连接信息：
  - `LANGFUSE_PUBLIC_KEY`
  - `LANGFUSE_SECRET_KEY`
  - `LANGFUSE_HOST`
- 如果使用 ngrok 等内网穿透工具，确保 URL 可达

## 执行流程

```
Langfuse UI / curl
       │
       ▼
  POST /webhook
       │
       ├─ 格式归一化（camelCase → snake_case, payload 字符串 → dict）
       ├─ 校验 dataset_name 必填
       │
       ├─ mode="run"     → 后台: run_experiment_task()
       │   ├─ 从 Langfuse 获取数据集
       │   ├─ 逐条运行 Nexent Agent（调用 LLM）
       │   ├─ 评分器打分 → 写入 Langfuse trace score
       │   └─ 关联 dataset item → dataset run
       │
       └─ mode="rescore" → 后台: rescore_task()
           ├─ 获取已有 run 的 trace output
           ├─ 用新评分器重新打分（不调用 LLM）
           └─ 写入新的 dataset run
```
