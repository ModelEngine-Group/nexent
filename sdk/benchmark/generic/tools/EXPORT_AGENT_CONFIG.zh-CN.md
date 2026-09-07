# export_agent_config.py 使用文档

从 Nexent PostgreSQL 数据库导出 Agent 配置到 YAML 文件，供 `run_benchmark.py` 使用。

## 功能

- 连接 Nexent PostgreSQL 数据库
- 根据 agent_id 或 display_name 查询 Agent 配置
- 导出完整的 Agent 配置到 YAML 文件，包括：
  - 基本信息（名称、描述、问候语、示例问题）
  - Agent 配置（max_steps、context_manager、verification_config 等）
  - Prompts（duty_prompt、constraint_prompt、few_shots_prompt）
  - 工具、子 Agent、技能配置

## 数据库连接

默认连接参数（可通过环境变量覆盖）：

| 参数 | 环境变量 | 默认值 |
|------|---------|--------|
| Host | `NEXENT_DB_HOST` | `localhost` |
| Port | `NEXENT_DB_PORT` | `5434` |
| Database | `NEXENT_DB_NAME` | `nexent` |
| User | `NEXENT_DB_USER` | `root` |
| Password | `NEXENT_DB_PASSWORD` | `nexent@4321` |

## 命令行参数

| 参数 | 必填 | 说明 |
|------|:---:|------|
| `--agent-id` | 二选一 | Agent ID |
| `--name` | 二选一 | Agent 展示名称（display_name） |
| `--version` | 否 | 指定版本号（默认使用 current_version_no） |
| `--output`, `-o` | 否 | 输出文件路径（默认 `configs/agent_{id}_v{version}.yaml`） |

## 使用示例

### 按 agent_id 导出

```bash
backend/.venv/bin/python sdk/benchmark/generic/tools/export_agent_config.py --agent-id 7 --output sdk/benchmark/generic/configs/agent_7.yaml
```

### 按名称导出

```bash
backend/.venv/bin/python sdk/benchmark/generic/tools/export_agent_config.py --name "数学解答助手" --output sdk/benchmark/generic/configs/math_assistant.yaml
```

### 导出特定版本

```bash
backend/.venv/bin/python sdk/benchmark/generic/tools/export_agent_config.py --agent-id 7 --version 1 --output sdk/benchmark/generic/configs/agent_7_v1.yaml
```

### 使用默认输出路径

```bash
backend/.venv/bin/python sdk/benchmark/generic/tools/export_agent_config.py --agent-id 5
# → 输出到 configs/agent_5_v4.yaml
```

## 导出的 YAML 结构

```yaml
agent_info:
  agent_id: 7
  name: gsm8k_solver_assistant
  display_name: 数学解答助手
  description: 你是一个数学解答助手，擅长解答GSM8K等数学问题...
  greeting_message: 你好！我是数学解答助手...
  example_questions:
    - 小明买了3个2元的苹果和2个1元的香蕉，一共花了多少钱？
    - 一辆车每小时行驶60公里，3小时能行驶多远？

agent_config:
  max_steps: 15
  enable_context_manager: true
  provide_run_summary: false
  prompt_template_id: 0
  version_no: 1
  verification_config:
    enabled: false
    pass_score: 0.75
    strictness: balanced
    fail_policy: repair_then_controlled_summary
    critical_events:
      - tool_precheck
      - tool_result
      - retrieval
      - code_execution
      - handoff
      - final_answer
    max_final_rounds: 2
    llm_verification_enabled: true
    step_verification_enabled: true
    final_verification_enabled: true

prompts:
  duty_prompt: |
    你是一个专业的数学解题助手，负责解答各类数学计算问题。你具备出色的逻辑推理与数值计算能力...
  constraint_prompt: ''
  few_shots_prompt: ''

tools: []
sub_agents: []
skills: []
```

## 查询数据库中的 Agent

### 列出所有 Agent

```bash
docker exec nexent-postgresql psql -U root -d nexent -c "
SET search_path TO nexent;
SELECT agent_id, display_name, current_version_no
FROM ag_tenant_agent_t
WHERE delete_flag = 'N' AND version_no = 0
ORDER BY agent_id;
"
```

### 查看特定 Agent 的详细信息

```bash
docker exec nexent-postgresql psql -U root -d nexent -c "
SET search_path TO nexent;
SELECT agent_id, display_name, description, duty_prompt, max_steps,
       enable_context_manager, current_version_no
FROM ag_tenant_agent_t
WHERE agent_id = 7 AND version_no = 0;
"
```

## 注意事项

1. **版本选择**：
   - `version_no = 0` 表示草稿版本
   - `current_version_no` 表示当前发布的版本
   - 默认导出 `current_version_no`，如果为 NULL 则导出 `version_no = 0`

2. **工具配置**：
   - 导出的工具配置包含工具名称、类名、来源、类别、描述和参数
   - 工具的实际实现需要在 Nexent SDK 中注册

3. **Prompt 模板**：
   - 导出的配置不包含 prompt_template 的完整内容
   - `run_benchmark.py` 使用 SDK 内置的模板引擎

4. **数据库连接**：
   - 确保 Nexent PostgreSQL 容器正在运行
   - 如果使用 Docker，默认端口是 5434（映射到容器的 5432）

## 故障排除

### 连接被拒绝

```bash
# 检查 PostgreSQL 容器状态
docker ps | grep postgres

# 检查端口映射
docker port nexent-postgresql
```

### Agent 不存在

```bash
# 确认 agent_id 或 display_name 正确
docker exec nexent-postgresql psql -U root -d nexent -c "
SET search_path TO nexent;
SELECT agent_id, display_name FROM ag_tenant_agent_t WHERE delete_flag = 'N';
"
```

### 版本不存在

```bash
# 查看 Agent 的所有版本
docker exec nexent-postgresql psql -U root -d nexent -c "
SET search_path TO nexent;
SELECT version_no, create_time FROM ag_tenant_agent_t
WHERE agent_id = 7 ORDER BY version_no;
"
```
