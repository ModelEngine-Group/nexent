# AI 资讯速递 Agent 端到端修复总结

> 日期：2026-07-29
> 状态：✅ 端到端验证通过

## 问题回顾

Agent 38 (ai_news_hot) 运行时遇到三个串联问题：

1. `read_skill_md("aihot")` 返回 "Skill not found" → ContextVar 修复（已完成）
2. `terminal` 工具 SSH 认证失败 → 改用 `run_skill_script` 替代
3. smolagents 限制 `import urllib.request` → 用 `run_skill_script` 执行外部 Python 脚本绕过
4. LLM Connection error → tenant_config 缺少 LLM_ID 配置

## 修复方案

### 方案核心：terminal → run_skill_script

参照 WorkBuddy 的本地方案，不使用 SSH/terminal，改为：

- 创建 `scripts/fetch_aihot.py`：用 stdlib `urllib.request` 调 aihot.virxact.com API
- SKILL.md 全量改写：所有 `curl` 命令改为 `run_skill_script("aihot", "scripts/fetch_aihot.py", ...)` 调用
- `run_skill_script` 通过 `subprocess.run` 执行脚本，不受 smolagents import 限制

### 文件变更

| 文件 | 变更 |
|------|------|
| `skills/aihot/scripts/fetch_aihot.py` | 新建：urllib-based API 调用脚本 |
| `skills/aihot/SKILL.md` | 全量改写：curl → run_skill_script |
| `agents/ai_news_hot.md` | tools: terminal → run_skill_script |

### 数据库变更

| 操作 | 表 | 说明 |
|------|----|------|
| 软删除 | ag_agent_repository_t (id=13) | 旧模板（tools=terminal） |
| 新建 | ag_agent_repository_t (id=14) | 新模板（tools=run_skill_script） |
| 更新 | ag_tool_instance_t (id=95) | tool_id: 23(terminal) → 150(run_skill_script) |
| 新建 | model_record_t (id=57) | qwen3.7-max 复制到 tenant_id 下 |
| 新建 | tenant_config_t | LLM_ID=57 配置 |

### 容器变更

| 容器 | 变更 |
|------|------|
| nexent-config | 复制 solution 文件 + 重启触发 seeder |
| nexent-runtime | 复制 SKILL.md + fetch_aihot.py + 重启 |

## 端到端验证结果

```
用户: "today AI news"
↓
Agent 步骤1: read_skill_md("aihot") → 9288 字符 SKILL.md ✓
↓
Agent 步骤2: run_skill_script("aihot", "scripts/fetch_aihot.py", 
           "--endpoint items --mode selected --hours-ago 24 --take 50")
           → 17 条 AI 资讯 JSON ✓
↓
Agent 步骤3: create_file → 生成 HTML 简报 ✓
↓
最终输出: 格式化 AI 资讯简报（头条焦点 + 五大版块 + 条目详情）✓
```

### 返回的 AI 资讯示例（17 条）

1. 在 M1 Max 上运行 2.8T 参数的 Kimi K3
2. 1100+ AI 员工联名呼吁控制 AI 发展速度
3. 我的 Claude 账号被封了
4. OpenRouter 推出 LangChain 集成包
5. OpenAI 发布 Codex 安全 CLI 与 SDK
...（共 17 条）

## 技术要点

### smolagents import 限制
- smolagents 的 Python 代码执行环境限制可导入模块（json, re, math 等）
- `urllib`, `subprocess`, `requests` 不在白名单
- `run_skill_script` 通过 `subprocess.run` 在 smolagents 外执行，有完整 stdlib 访问权限

### ContextVar 工具实例隔离
- 旧单例模式：首次调用参数为空 → 永远返回空参数实例
- ContextVar 模式：有参数时创建新实例存入 ContextVar，无参数时先查 ContextVar
- `copy_context().run()` 在 agent 执行线程中传播上下文

### tenant_config 模型配置链
```
tenant_config_t.LLM_ID → model_id
→ get_model_by_model_id(model_id, tenant_id) 
→ ModelConfig(api_key, base_url, model_factory)
→ OpenAIModel(model_id, api_base, api_key)
→ smolagents agent
```
