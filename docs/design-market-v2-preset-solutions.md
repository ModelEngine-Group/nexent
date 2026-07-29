# 方案市场（Market v2）设计文档

> **版本**：v1.0  
> **日期**：2026-07-27  
> **作者**：Nexent Team  
> **状态**：已实现，持续迭代

---

## 目录

1. [设计目标](#1-设计目标)
2. [核心概念](#2-核心概念)
3. [页面架构](#3-页面架构)
4. [方案目录设计](#4-方案目录设计)
5. [预制 Agent 自动 Seed 机制](#5-预制-agent-自动-seed-机制)
6. [方案匹配引擎](#6-方案匹配引擎)
7. [点击即聊交互流程](#7-点击即聊交互流程)
8. [数据流与 API 约定](#8-数据流与-api-约定)
9. [文件清单](#9-文件清单)
10. [已知限制与未来迭代](#10-已知限制与未来迭代)

---

## 1. 设计目标

### 问题背景

旧版 `/market` 页面是一个**远程模板下载器**：
- 数据来源是 `market.nexent.tech`（远程云市场 API）
- 用户浏览 agent 模板（Deep Researcher / Code Reviewer 等），点击"下载"
- 弹出 `AgentImportWizard` 安装向导，走 3 步（agent → skill → mcp）导入流程
- 导入完成后用户还要去 agent 配置页手动调整才能用

这导致两个问题：
1. **远程依赖**：云市场不可达（502）时页面空壳，数据全部丢失
2. **流程太重**：用户只想用一个 agent，却要走完安装向导的 3 步确认

### 新版目标

`/market-v2` 页面改为 **"方案市场 + 点击即聊"** 模式：
1. **零远程依赖**：所有方案和 agent 都是本地预制的，不依赖云市场
2. **点击即聊**：用户看到方案 → 点击 → 直接进对话页开聊，不走安装向导
3. **四 Tab 统一**：Solutions / Agents / Skills / MCPs 四个维度一页看完
4. **自动预制**：新租户注册时后端自动 seed 7 个预制 agent，老租户首次访问时懒加载 seed

---

## 2. 核心概念

### 2.1 Solution（方案）

方案是用户看到的最小消费单元。一条 Solution = 一个可以直接点击开聊的场景入口。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | number | 方案唯一 ID（101-108） |
| `name` | string | 逻辑名（如 `kb-qa-assistant`） |
| `display_name` | string | 展示名（如"知识库问答助手"） |
| `description` | string | 一句话描述 |
| `solution_type` | `"single" \| "team"` | single = 单 agent 方案，team = 多角色协作方案 |
| `tool_keywords` | string[] | 关键词列表，用于匹配 published agent |
| `agent_id` | number? | 匹配到的 agent ID（运行时由 resolveSolutions 填入） |
| `resolved` | boolean? | 是否已匹配到可用 agent（运行时填入） |

### 2.2 两种方案类型

```
┌─────────────────────────────────────────────┐
│  solution_type: "single"                    │
│  展示：构成徽章（1A + 2S + 1M）              │
│  匹配：按 tool_keywords 找 published agent   │
│  点击 → 直跳 /newchat 对话页                 │
├─────────────────────────────────────────────┤
│  solution_type: "team"                      │
│  展示：角色成员列表（主理人/研究员/...）     │
│  匹配：按 tool_keywords 找 + fallback        │
│  点击 → 直跳 /newchat 对话页                 │
└─────────────────────────────────────────────┘
```

### 2.3 与旧版 Recipe / Expert 的关系

旧版有 Recipe（单 agent 组合）和 Expert（多角色团队）两个概念，已合并为统一的 Solution 类型，用 `solution_type` 区分子类型。这是为了简化用户认知——"你看到的就是能用的"。

---

## 3. 页面架构

### 3.1 路由

| 路由 | 说明 |
|------|------|
| `/market` | 旧版页面，**已改为重定向** → `/{locale}/market-v2` |
| `/{locale}/market-v2` | 新版方案市场页面 |
| `/{locale}/newchat` | 对话页（方案点击后跳转目标） |

### 3.2 页面布局

```
┌─────────────────────────────────────────────────────────┐
│  🛒 方案市场                              [搜索框]       │
│  发现一键即用的完整方案，或浏览组成零件自行组装           │
├─────────────────────────────────────────────────────────┤
│  [Solutions 8] [Agents 2] [Skills 2] [MCPs 1]           │
├─────────────────────────────────────────────────────────┤
│  ⭐ 推荐方案 · 点击直接开聊                               │
│  知识库问答助手 — 点击右侧按钮直接进入对话  [开始对话 →]  │
├─────────────────────────────────────────────────────────┤
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐      │
│  │方案卡片1│ │方案卡片2│ │方案卡片3│ │方案卡片4│      │
│  │图标     │ │图标     │ │图标    │ │图标     │      │
│  │标题     │ │标题     │ │标题     │ │标题     │      │
│  │描述     │ │描述     │ │描述     │ │描述     │      │
│  │[开始对话]│ │[开始对话]│ │[即将上线]│ │[开始对话]│      │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘      │
└─────────────────────────────────────────────────────────┘
```

### 3.3 四个 Tab

| Tab | 数据来源 | 卡片组件 | 操作 |
|-----|---------|---------|------|
| Solutions | 前端 BUILTIN_SOLUTIONS + 后端 published agent 匹配 | `SolutionMarketCard` | 点击直跳对话 |
| Agents | 后端 `/api/market/agent/list`（远程） | `AgentMarketCard` | 下载 |
| Skills | 后端 `/api/skill/repository/listings` | `SkillMarketCard` | 下载 |
| MCPs | 后端 `/api/mcp/community/list` | `McpMarketCard` | 下载 |

只有 Solutions Tab 走"点击即聊"模式，其他三个 Tab 保留原有的"浏览 + 下载"模式（给进阶用户自行组装零件）。

---

## 4. 方案目录设计

### 4.1 内置方案列表（BUILTIN_SOLUTIONS）

共 8 个方案，ID 101-108：

| ID | 名称 | 类型 | 关键词 | 匹配工具 |
|----|------|------|--------|---------|
| 101 | 知识库问答助手 | single | 知识库/knowledge/rag/问答/kb | `knowledge_base_search` |
| 102 | 网络调研助手 | single | 调研/research/search/搜索/网络/tavily | `tavily_search`, `exa_search`, `linkup_search` |
| 103 | 文档分析助手 | single | 文档/document/file/文件/分析/analyze | `read_file`, `analyze_text_file` |
| 104 | 多模态分析助手 | single | 多模态/multimodal/image/audio/video | `analyze_image`, `analyze_audio`, `analyze_video` |
| 105 | 数据分析助手 | single | 数据/data/sql/database/数据库 | `mysql_database`, `postgres_database`, `mssql_database` |
| 106 | 文件管理助手 | single | 文件/file/目录/directory/管理 | `create_file`, `read_file`, `delete_file`, `list_directory` 等 |
| 107 | 邮件助手 | single | 邮件/email/mail/imap/smtp | `get_email`, `send_email` |
| 108 | 深度研究团队 | team | 研究/research/调研/report/深度/deep | （fallback 到第一个可用 agent） |

### 4.2 方案卡片状态

```
┌──────────────────────────────┐
│  resolved = true             │
│  agent_id = 42               │
│  ┌────────────────────────┐  │
│  │   💬 开始对话           │  │ ← 蓝色按钮，可点击
│  └────────────────────────┘  │
└──────────────────────────────┘

┌──────────────────────────────┐
│  resolved = false            │
│  agent_id = undefined        │
│  ┌────────────────────────┐  │
│  │   ⏳ 即将上线           │  │ ← 灰色禁用，不可点击
│  └────────────────────────┘  │
└──────────────────────────────┘
```

只有当后端**完全没有**已发布 agent 时，卡片才显示"即将上线"。只要有一个 agent，所有方案都能点击开聊。

---

## 5. 预制 Agent 自动 Seed 机制

### 5.1 为什么需要 Seed

方案卡片要能点击，必须有 `agent_id`；`agent_id` 来自 `usePublishedAgentList()` 返回的 published agent 列表。如果租户没有任何 agent，方案卡片永远显示"即将上线"。

旧方案是前端加一个"一键初始化"按钮让用户手动创建——但用户的反馈是："不用一键初始化吧，我想预制"。所以改为后端自动 seed。

### 5.2 Seed 触发时机（三处注册入口 + 懒加载）

```
新租户注册 ──┬── user_management_service.py（普通注册）
            ├── cas_service.py（CAS 登录新租户）
            └── oauth_service.py（OAuth 注册新租户）
                        │
                        ▼
              init_tool_list_for_tenant()   ← 已有
              init_skill_list_for_tenant()  ← 已有
              init_preset_agents_for_tenant() ← 新增

老租户首次访问 ──── list_all_agent_info_impl() / list_published_agents_impl()
                        │
                        ▼
              检测到零 enabled agent → 自动 seed（懒加载兜底）
```

### 5.3 Seed 流程（`init_preset_agents_for_tenant`）

```
1. 幂等检查：query_all_agent_info_by_tenant_id()
   └─ 有 enabled agent → return（跳过）

2. 解析工具映射：query_all_tools(tenant_id)
   └─ tool.name → tool_id（租户级自增，不能硬编码）

3. 解析默认模型：get_model_records({"model_type":"llm"}, tenant_id)
   └─ 取第一个可用 LLM model_id

4. 解析用户 group：query_group_ids_by_user(user_id)

5. 对每个模板（7 个）：
   ├─ create_agent(agent_info={name, display_name, ...}) → 拿到 agent_id
   ├─ 对每个 tool_name：
   │   └─ create_or_update_tool_by_tool_info(tool_id, agent_id, enabled=True)
   └─ publish_version_impl(agent_id) → 发布版本 1（让 agent 出现在 published_list）

6. 完成：7 个 agent 已创建 + 发布
```

### 5.4 预制 Agent 模板

| Agent name | Display name | Tools | Duty Prompt |
|-----------|-------------|-------|-------------|
| `kb-qa-assistant` | 知识库问答助手 | `knowledge_base_search` | 优先用知识库检索回答 |
| `web-research-assistant` | 网络调研助手 | `tavily_search`, `exa_search`, `linkup_search` | 多轮检索+归纳要点 |
| `document-analysis-assistant` | 文档分析助手 | `read_file`, `analyze_text_file` | 读取文件+提取信息 |
| `multimodal-analysis-assistant` | 多模态分析助手 | `analyze_image`, `analyze_audio`, `analyze_video` | 图片/音频/视频识别 |
| `data-analyst-assistant` | 数据分析助手 | `mysql_database`, `postgres_database`, `mssql_database` | NL→SQL+数据分析 |
| `file-manager-assistant` | 文件管理助手 | `create_file`, `read_file`, `delete_file`, `create_directory`, `delete_directory`, `move_item`, `list_directory` | 文件/目录操作 |
| `email-assistant` | 邮件助手 | `get_email`, `send_email` | 读取+发送邮件 |

> **注**：solution 108"深度研究团队"是 team 类型，**不创建单独 agent**。它通过 `tool_keywords` 匹配到"网络调研助手"等 research 类 agent，或 fallback 到第一个可用 agent。

### 5.5 发布机制

创建 agent 后只会在 `/api/agent/list`（draft 列表）中出现，但 `/api/agent/published_list` 需要 `current_version_no > 0`。所以 seed 流程的最后一步对每个 agent 调用 `publish_version_impl()`，创建版本 1 快照，让 agent 出现在 published list 中。

---

## 6. 方案匹配引擎

### 6.1 resolveSolutions 函数

```typescript
function resolveSolutions(solutions: SolutionCardData[], agents: Agent[]): SolutionCardData[]
```

对每个方案按以下优先级匹配：

```
┌─────────────────────────────────────────────┐
│ Step 1: 关键词匹配                           │
│   在 availableAgents 中找 name/display_name/  │
│   description 包含任意 keyword 的 agent       │
│   └─ 匹配成功 → set agent_id, resolved=true  │
├─────────────────────────────────────────────┤
│ Step 2: Fallback 到第一个可用 agent           │
│   └─ 有 agent → set agent_id, resolved=true  │
├─────────────────────────────────────────────┤
│ Step 3: 无 agent                             │
│   └─ resolved=false（显示"即将上线"）         │
└─────────────────────────────────────────────┘
```

### 6.2 team 类型处理

team 类型（solution 108）原来直接 `resolved=true` 但不设 `agent_id`，导致点击报"无法启动对话"。修复后 team 类型也走关键词匹配 + fallback 逻辑，保证只要有 agent 就能点进去。

### 6.3 agentMatchesKeywords 函数

```typescript
function agentMatchesKeywords(agent: Agent, keywords: string[]): boolean
```

将 agent 的 `name` + `display_name` + `description` 拼成一个 haystack（小写），检查 keywords 中是否有任意一个包含在 haystack 中。

> **注**：published agent list API 不返回 `tools` 字段（精简数据），所以不能按工具匹配，只能按 agent 名称/描述匹配。这也是为什么 `tool_keywords` 用业务词汇（"知识库""调研"）而非工具 class_name。

---

## 7. 点击即聊交互流程

### 7.1 用户操作流程

```
用户打开 /market-v2
  │
  ▼
看到 Solutions Tab，8 个方案卡片
  │
  ▼
点击方案卡片"开始对话"按钮
  │
  ▼
handleStartChat(solution)
  ├─ solution.agent_id 存在？
  │   ├─ 是 → sessionStorage.setItem("nexent_last_used_agent_id", agent_id)
  │   │        router.push("/newchat")
  │   └─ 否 → message.warning("该方案无法直接启动对话")
  │
  ▼
/newchat 页面加载
  ├─ 读取 sessionStorage("nexent_last_used_agent_id")
  ├─ 预选该 agent
  └─ 用户直接开始对话
```

### 7.2 sessionStorage 机制

key: `"nexent_last_used_agent_id"`  
value: agent_id（字符串）

这与 agent-landing 页面（`/agents/landing`）使用的是同一套机制，`/newchat` 页面已经支持读取这个 key 来预选 agent。

---

## 8. 数据流与 API 约定

### 8.1 前端调用的 API

| 用途 | API | 方法 |
|------|-----|------|
| 获取已发布 agent 列表 | `/api/agent/published_list` | GET |
| 获取工具列表（seed 用） | `/api/tool/list` | GET |
| 获取模型列表（seed 用） | `/api/model/list` | GET |
| 创建空白 agent（seed 用） | `/api/agent/get_creating_sub_agent_id` | GET |
| 更新 agent 配置（seed 用） | `/api/agent/update` | POST |

### 8.2 后端 Seed 调用链

```
注册入口（user_management / cas / oauth）
  │
  ├─ await init_tool_list_for_tenant(tenant_id, user_id)
  ├─ await init_skill_list_for_tenant(tenant_id, user_id)
  └─ init_preset_agents_for_tenant(tenant_id, user_id)  ← 新增
       │
       ├─ query_all_agent_info_by_tenant_id()  ← 幂等检查
       ├─ query_all_tools(tenant_id)            ← 工具映射
       ├─ get_model_records({"model_type":"llm"}, tenant_id)  ← 默认模型
       ├─ query_group_ids_by_user(user_id)      ← 用户 group
       │
       └─ 对每个模板：
           ├─ create_agent({...})               ← 创建 draft agent
           ├─ create_or_update_tool_by_tool_info() ← 绑定工具
           └─ publish_version_impl(agent_id)     ← 发布版本 1
```

### 8.3 懒加载兜底

在 `agent_service.py` 的 `list_all_agent_info_impl` 和 `agent_version_service.py` 的 `list_published_agents_impl` 中加入懒加载检查：

```python
agent_list = query_all_agent_info_by_tenant_id(tenant_id=tenant_id)

# Lazy seed: if the tenant has zero enabled agents, auto-create
if not any(a.get("enabled") for a in agent_list):
    try:
        from services.preset_agent_service import init_preset_agents_for_tenant
        init_preset_agents_for_tenant(tenant_id, user_id)
        agent_list = query_all_agent_info_by_tenant_id(tenant_id=tenant_id)
    except Exception as e:
        logger.warning(f"Lazy preset agent seed failed: {str(e)}")
```

这覆盖了"租户已存在但没 agent"的老用户场景。

---

## 9. 文件清单

### 9.1 新增文件

| 文件 | 说明 |
|------|------|
| `backend/services/preset_agent_service.py` | 后端预制 agent seed 服务 |
| `docs/design-market-v2-preset-solutions.md` | 本设计文档 |

### 9.2 修改文件

| 文件 | 改动 |
|------|------|
| `frontend/app/[locale]/market-v2/page.tsx` | 主页面：BUILTIN_SOLUTIONS + resolveSolutions + handleStartChat |
| `frontend/app/[locale]/market/page.tsx` | 旧版页面改为重定向到 /market-v2 |
| `frontend/components/market/SolutionMarketCard.tsx` | 方案卡片：MessageCircle 图标 + "开始对话"/"即将上线"按钮 |
| `backend/services/user_management_service.py` | 注册流程加 `init_preset_agents_for_tenant` |
| `backend/services/cas_service.py` | CAS 登录新租户加 seed |
| `backend/services/oauth_service.py` | OAuth 注册新租户加 seed |
| `backend/services/agent_service.py` | `list_all_agent_info_impl` 加懒加载 seed |
| `backend/services/agent_version_service.py` | `list_published_agents_impl` 加懒加载 seed |

### 9.3 删除文件

| 文件 | 原因 |
|------|------|
| `frontend/components/market/SolutionInstallWizard.tsx` | 不再走安装向导 |
| `frontend/services/presetAgentService.ts` | 前端 seed 服务已移到后端 |

---

## 10. 已知限制与未来迭代

### 10.1 当前限制

1. **方案 → Agent 映射不够精准**：`agentMatchesKeywords` 只能按名称/描述模糊匹配，无法按实际绑定的工具匹配（published list API 不返回 tools 字段）。如果两个 agent 名称相似，可能匹配错。

2. **team 类型方案的 agent_id 是假绑定**：深度研究团队点进去实际用的是"网络调研助手"的 agent，而不是一个真正的多角色协作 agent。后续需要实现真正的 team agent 架构。

3. **预制 agent 的 duty_prompt 较简单**：目前每个 agent 只有一句 duty_prompt，没有 constraint_prompt 和 few_shots_prompt。后续可以增强。

4. **模型依赖**：seed 前提是租户已配置至少一个 LLM 模型。如果模型未配置，agent 会创建成功但没有 model_id，运行时可能报错。

5. **工具依赖**：seed 前提是租户已扫描工具列表（`init_tool_list_for_tenant` 已在 seed 前执行）。如果工具未扫描，agent 会创建成功但没有绑定工具。

### 10.2 未来迭代方向

1. **方案自定义**：允许用户从"Agents + Skills + MCPs"三个 Tab 选配零件，组装成自定义 Solution，保存到"我的方案"。

2. **方案分享**：用户可以将自己组装的方案分享到社区，其他用户可以一键安装。

3. **真实 team agent**：为深度研究团队等 team 方案创建真正的多角色协作 agent（主 agent + sub agents），而非 fallback 到单个 agent。

4. **方案评分与反馈**：用户用完方案后可以评分，反馈数据用于优化方案推荐。

5. **方案版本管理**：预制方案可以迭代版本，用户可以选择使用最新版或锁定特定版本。

6. **按需 seed**：不一次性创建 7 个 agent，而是用户首次点击某个方案时才创建对应 agent（更轻量）。

---

> **文档维护**：本设计文档随实现同步更新。如有架构变更，请更新对应章节并标注日期。
