# Agent 计划功能设计方案

> 文档版本：v1.2
> 日期：2026-06-11
> 状态：**待开发**

---

## 一、背景与目标

当前智能体（Agent）的执行模式为纯 ReAct 循环：接收任务后直接进入"思考 - 代码执行 - 观察"循环，直至得出最终答案。这种模式在简单任务上效率很高，但存在以下问题：

- **缺乏全局视角**：Agent 每一步都只看到当前状态，无法预判后续步骤，容易做重复工作或遗漏关键步骤。
- **用户不可见**：Agent 的执行过程对用户黑盒，用户无法预知任务会被分解为哪些步骤，任务复杂时体验不佳。

引入**计划（Planning）**机制：Agent 在正式执行前，先对任务进行分解，生成结构化的任务计划并展示给用户（只读），然后按计划逐步执行。

---

## 二、设计决策

| 决策项 | 选项 | 选择 | 理由 |
|--------|------|------|------|
| 触发方式 | 每次任务 / 自动检测复杂度 / 用户按钮触发 | **用户按钮触发** | 避免对简单任务增加不必要的延迟；默认关闭，用户主动开启 |
| 计划可见性 | 隐藏（仅 Agent 内部）/ 只读展示 / 可编辑 | **只读展示** | 用户可见但不能随意修改，保证执行方向可控 |
| 步骤粒度 | 纯文本步骤列表 / 带有状态的富结构 | **带状态的富结构** | 需要支持"pending / in_progress / completed / skipped"等状态更新 |
| 执行顺序 | 严格顺序 / 自适应（可跳过/重排） | **自适应** | Agent 可根据实际执行上下文调整，跳过不必要的步骤 |
| 计划范围 | 主 Agent 循环 / 覆盖子 Agent | **仅主 Agent 循环** | 子 Agent 由主 Agent 调用，计划覆盖会增加复杂度 |
| 多轮对话 | 每轮重新生成 / 仅第一轮生成 | **每轮重新生成** | 每次用户消息都独立生成新计划，执行上下文干净 |
| PlanRepo 集成方式 | 方案 A（CoreAgent 内部创建）/ 方案 B（通过 AgentRunInfo 传入） | **方案 B** | SDK 层保持纯净，不引入基础设施依赖；符合现有 observer / stop_event 的透传模式 |
| 实时存储 | Redis / PostgreSQL | **Redis** | `update_step` 是高频热路径操作（每步执行完调用），Redis 亚毫秒级延迟优于 PG |
| 审计存储 | 不做 / 内嵌到 PlanRepo / 独立异步写入 PG | **暂不做** | 可在 Redis TTL 到期后补充 PG 归档层 |
| 计划删除时机 | FINAL_ANSWER 后删除 / stop_event 时也删除 | **仅 FINAL_ANSWER 后删除** | 用户中断时由 Redis TTL 自动过期兜底，不需要主动删除 |

---

## 三、数据模型

### 3.1 Python 端（Pydantic）

```python
# sdk/nexent/core/agents/agent_model.py

class PlanStep(BaseModel):
    id: str = Field(description="唯一步骤 ID，如 'step-1'")
    title: str = Field(description="简短步骤标题")
    description: str = Field(description="步骤详细描述")
    status: Literal["pending", "in_progress", "completed", "skipped"] = "pending"


class AgentPlan(BaseModel):
    plan_id: str = Field(description="计划唯一 ID")
    title: str = Field(description="从任务中提取的计划标题")
    steps: List[PlanStep] = Field(description="有序步骤列表")
    current_step_index: int = 0
```

### 3.2 TypeScript 端

```typescript
// frontend/app/[locale]/chat/types/chat.ts

interface PlanStep {
  id: string;
  title: string;
  description: string;
  status: 'pending' | 'in_progress' | 'completed' | 'skipped';
}

interface AgentPlan {
  plan_id: string;
  title: string;
  steps: PlanStep[];
  current_step_index: number;
}
```

### 3.3 Redis 数据结构

- **Key 格式**：`plan:{conversation_id}:{user_id}`
- **Value**：JSON 序列化的 `AgentPlan` 对象
- **TTL**：`PLAN_TTL_SECONDS`（默认 24 小时，与 conversation 生命周期对齐）

---

## 四、整体架构

### 4.1 组件关系图

```
┌──────────────────────────────────────────────────────────────┐
│                         前端 (Frontend)                       │
│  ┌──────────────┐   ┌──────────────────┐   ┌─────────────┐  │
│  │  ChatInput   │   │ chatStreamHandler│   │PlanPanel   │  │
│  │  计划开关按钮 │──▶│    SSE 事件处理   │──▶│ 只读展示     │  │
│  └──────────────┘   └──────────────────┘   └─────────────┘  │
└──────────────────────────────────────────────────────────────┘
                              │
                              │ POST /agent/run (enable_plan)
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                         后端 (Backend)                        │
│  ┌─────────────────┐   ┌──────────────────┐   ┌──────────┐  │
│  │ agent_app.py    │──▶│ agent_service.py │──▶│ PlanRepo │  │
│  │   /agent/run    │   │prepare_agent_run │   │  Redis   │  │
│  └─────────────────┘   └──────────────────┘   └──────────┘  │
│                                  │                            │
│                                  │ create_agent_run_info      │
│                                  ▼                            │
│                          ┌──────────────────┐                │
│                          │ create_agent_info │                │
│                          └──────────────────┘                │
└──────────────────────────────────────────────────────────────┘
                              │
                              │ AgentRunInfo
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                          SDK                                  │
│  ┌─────────────────┐   ┌──────────────┐   ┌─────────────┐  │
│  │  run_agent.py   │──▶│ NexentAgent  │──▶│ CoreAgent   │  │
│  │agent_run_thread │   │              │   │  _run_stream │  │
│  └─────────────────┘   └──────────────┘   └─────────────┘  │
│                                                 │            │
│                                          save/load/update   │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │      Redis       │
                    │  (实时计划存储)   │
                    └──────────────────┘
```

> **数据流**：前端触发 → 后端注入 PlanRepo → SDK 执行 → Redis 持久化 → 前端 SSE 展示

### 4.2 执行流程（序列图）

```
用户 ───▶ 前端 ChatInput
          点击"开启计划"按钮

前端 ───▶ POST /agent/run (enable_plan: true)
          AgentRequest.enable_plan = true

后端 agent_service.prepare_agent_run
          │
          ├─ create_agent_run_info(...)
          │
          ├─ PlanRepo(redis_client=...)
          │
          ├─ agent_run_info.enable_planning = true
          │
          └─ agent_run_info.plan_repo = PlanRepo

后端 ───▶ SDK CoreAgent (AgentRunInfo)
          │
          ▼
    【阶段 1：规划】
          │
          ├─▶ LLM: Planning prompt (JSON 输出)
          │◀── LLM 返回: 结构化计划 JSON
          │
          ├─▶ PlanRepo.save(plan)
          │
          └─▶ 前端 PlanPanel
               发送 PLAN SSE event
               → 渲染只读计划面板

    【阶段 2：执行循环】
          │
          loop 自适应执行（每步）
          │
          ├─▶ 前端: STEP_COUNT event
          │
          ├─▶ LLM: ReAct think + code
          │◀── LLM 返回: code blob
          │
          ├─▶ 执行代码
          │
          ├─▶ PlanRepo.update_step_status
          │
          ├─▶ 前端: PLAN_STEP_UPDATE event
          │     → 更新步骤状态图标
          │
          └─▶ 前端: execution_logs / token_count
          end

SDK ──────▶ 前端: FINAL_ANSWER event
SDK ──────▶ PlanRepo.delete(plan)
            → Redis TTL 自动过期兜底，不阻塞主流程
```

### 4.3 任务数据流转图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                   INPUT                                     │
│   用户 query  ──┐                                                           │
│   MinIO 文件  ──┼──▶ AgentRequest                                           │
│   对话历史   ──┘                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             BACKEND (后端)                                   │
│                                                                              │
│   AgentRequest ──▶ prepare_agent_run                                         │
│                              │                                               │
│                              ├──▶ create_agent_run_info                      │
│                              │                                               │
│                              ├──▶ PlanRepo(redis_client=...)                 │
│                              │                                               │
│                              ├──▶ agent_run_info.enable_planning = true      │
│                              │                                               │
│                              └──▶ agent_run_info.plan_repo = PlanRepo        │
│                                                                              │
│   输出: AgentRunInfo(plan_repo, enable_planning)                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SDK (CoreAgent)                                 │
│                                                                              │
│   【规划阶段】                                                               │
│     LLM 生成计划 (JSON)                                                      │
│         │                                                                   │
│         ├──▶ PlanRepo.save(plan) ──▶ Redis                                  │
│         │                                                                   │
│         └──▶ [PLAN event] ───────────────────┐                              │
│                                               │ (SSE 事件流)                 │
│   【执行循环】                                   ▼                              │
│     每步:                                                           ┌──────┐│
│         ├──▶ PlanRepo.update_step ──▶ Redis                          │FE 前端││
│         │                                                           │      ││
│         ├──▶ [PLAN_STEP_UPDATE event] ───────────────────────────────▶ PlanPanel│
│         │                                                           └──────┘│
│         ├──▶ [execution_logs] ───────────────────────────────────────────▶ │
│         └──▶ ... (循环直到完成)                                            │
│                                                                              │
│   【结束】                                                                   │
│         ├──▶ [FINAL_ANSWER event] ────────────────────────────────────▶   │
│         └──▶ PlanRepo.delete ──▶ Redis (TTL 过期兜底)                        │
└─────────────────────────────────────────────────────────────────────────────┘

图例:
  ──▶ 数据/控制流
  ══▶ SSE 事件流（前端展示）
  PlanRepo 在后端初始化，全程不泄漏 Redis 细节到 SDK
```

---

## 四、设计原则

### 4.1 计划生成时机

**每轮独立生成** — 每次用户输入都会触发一次完整的计划生成流程。Agent 不会复用上一轮的计划，每轮都是基于当前上下文重新规划。

### 4.2 跨轮次连续性

通过**上下文压缩机制**（context_compress）实现连续性：

- 上下文压缩器在压缩对话历史时，如果检测到存在进行中的任务，会将当前计划的 `plan_id`、`title`、未完成步骤列表作为摘要的一部分输出
- 计划生成 prompt 中传入压缩后的上下文摘要，让 LLM 了解全局目标
- 当用户说"继续"时，压缩后的上下文会包含上一个未完成计划的摘要，LLM 可以据此决定是追加步骤还是重新规划

### 4.3 执行约束机制

**System prompt 软约束** — 不采用硬校验（工具白名单），而是通过 system prompt 约束 LLM 自主按计划执行：

- 在 `_step_stream` 每次迭代时，将当前步骤的 `title`、`description`、剩余步骤列表注入到 messages 中
- LLM 根据步骤描述自主选择工具，在 prompt 约束下自行判断是否符合计划
- 步骤切换时机：当前步骤描述的完整功能块执行完毕（通过判断 `_step_stream` 的 `code_output` 是否标志功能块结束）后，更新步骤状态为 `completed`，进入下一步骤

### 4.4 步骤粒度

**功能块粒度** — 每个 `PlanStep` 对应一个完整的功能块，而非单次工具调用：

- 一个步骤可能包含多次 LLM 推理和多次工具调用
- 步骤状态更新时机：功能块执行完毕（由 `_step_stream` 的循环自然界定）后标记为 `completed`
- 步骤状态枚举：`pending` / `in_progress` / `completed` / `skipped`

### 4.5 上下文传递链路

```
用户输入 + 对话历史
        │
        ▼
上下文压缩（context_compress）
  │
  ├── 压缩后的对话摘要
  └── 进行中的计划摘要（plan_id + title + pending_steps）── 若存在
        │
        ▼
计划生成 prompt（包含压缩后的上下文）
        │
        ▼
LLM 生成结构化计划
```

---

### 4.6 完整交互示例

#### 示例场景

用户开启计划模式后输入："帮我分析当前项目中的代码质量问题，并生成一份改进建议"

#### 第一阶段：请求发起

**前端 → 后端**

```http
POST /agent/run
Content-Type: application/json
Authorization: Bearer <token>

{
  "query": "帮我分析当前项目中的代码质量问题，并生成一份改进建议",
  "conversation_id": 42,
  "history": [
    {"role": "user", "content": "请介绍一下这个项目"},
    {"role": "assistant", "content": "这是一个基于 Agent 的智能助手项目..."}
  ],
  "agent_id": 1,
  "model_id": 3,
  "enable_plan": true
}
```

#### 第二阶段：构造 AgentRunInfo

**后端** 先通过 `prepare_agent_run` 创建 `agent_run_info`：

```python
agent_run_info, memory_context = await prepare_agent_run(
    agent_request=agent_request,
    user_id=user_id,
    tenant_id=tenant_id,
    language=language,
    allow_memory_search=True,
)
```

这一步构建了 `agent_config`、`model_config_list`、`observer` 等所有核心字段。

#### 第三阶段：上下文压缩

**后端** 在 `agent_run_info` 创建之后，对历史对话执行压缩：

```python
def _compress_context(history, task):
    recent = history[-5:]
    summary_parts = [f"当前任务：{task}"]
    for item in recent:
        role = "用户" if item.role == "user" else "助手"
        content = item.content[:100] if len(item.content) > 100 else item.content
        summary_parts.append(f"- {role}：{content}")
    return "\n".join(summary_parts)

context_summary = _compress_context(agent_request.history, agent_request.query)
```

#### 第四阶段：注入计划字段

```python
agent_run_info.enable_planning = True
agent_run_info.plan_repo = PlanRepo(redis_client=redis_client)
agent_run_info.context_summary = context_summary
```

注入完成后，`agent_run_info` 被传给 `_stream_agent_chunks`，随后进入新线程，由 `NexentAgent` 接收并透传到 `CoreAgent`。

#### 第五阶段：规划阶段（SDK → SSE）

**SDK CoreAgent._generate_plan** 调用 LLM，传入压缩后的上下文，prompt 如下：

```
User:
[对话上下文摘要]
当前任务：帮我分析当前项目中的代码质量问题，并生成一份改进建议
- 用户：请介绍一下这个项目
- 助手：这是一个基于 Agent 的智能助手项目...

你是一个任务规划助手。请将以下用户任务分解为 3-8 个逻辑清晰的功能块步骤。
用户任务：帮我分析当前项目中的代码质量问题，并生成一份改进建议

请按以下 JSON 格式输出计划：
{"plan_id": "auto-uuid", "title": "简短计划标题", "steps": [
{"id": "step-1", "title": "步骤1标题", "description": "详细描述", "status": "pending"}, ...]}

要求：分解为 3-8 个独立可执行的功能块，描述要具体
```

**SDK → 前端（SSE 第一批事件）**

```json
data: {"type": "plan", "content": "{\"plan_id\": \"a1b2c3d4\", \"title\": \"代码质量分析计划\", \"steps\": [{\"id\": \"step-1\", \"title\": \"扫描项目代码结构\", \"description\": \"使用文件遍历工具扫描项目目录，获取所有源代码文件列表\", \"status\": \"pending\"}, {\"id\": \"step-2\", \"title\": \"静态代码分析\", \"description\": \"对代码文件进行静态分析，检测复杂度、重复代码、命名规范等问题\", \"status\": \"pending\"}, {\"id\": \"step-3\", \"title\": \"生成改进建议报告\", \"description\": \"根据分析结果生成结构化的改进建议报告\", \"status\": \"pending\"}]}"}

data: {"type": "plan_step_update", "content": "{\"step_id\": \"step-1\", \"status\": \"in_progress\"}"}
```

#### 第六阶段：执行循环（步骤约束注入）

**SDK CoreAgent._step_stream** 每次迭代前，通过 `_inject_step_constraint` 将约束注入 messages：

```
User (约束注入):
[计划约束] 当前正在执行计划「代码质量分析计划」，步骤 step-1: 扫描项目代码结构
步骤描述：使用文件遍历工具扫描项目目录，获取所有源代码文件列表
剩余步骤：
- step-2: 静态代码分析 — 对代码文件进行静态分析，检测复杂度、重复代码等问题
- step-3: 生成改进建议报告 — 根据分析结果生成结构化的改进建议报告
要求：严格按照计划步骤执行。当前步骤完成后，在输出末尾添加 __STEP_COMPLETE__ 标记。
```

**SDK → 前端（SSE 执行事件流）**

```json
data: {"type": "model_output", "content": "我将按照计划执行。首先扫描项目代码结构..."}
data: {"type": "model_output_code", "content": "for root, dirs, files in os.walk(project_path):\n    for f in files:\n        if f.endswith('.py'):\n            ..."}
data: {"type": "execution", "content": "扫描完成，共发现 128 个 Python 文件"}
data: {"type": "plan_step_update", "content": "{\"step_id\": \"step-1\", \"status\": \"completed\"}"}
data: {"type": "plan_step_update", "content": "{\"step_id\": \"step-2\", \"status\": \"in_progress\"}"}
data: {"type": "step_count", "content": "Step 2"}
data: {"type": "token_count", "content": "{\"step_number\": 2, \"input_tokens\": 2048, \"output_tokens\": 512}"}
data: {"type": "plan_step_update", "content": "{\"step_id\": \"step-2\", \"status\": \"completed\"}"}
data: {"type": "plan_step_update", "content": "{\"step_id\": \"step-3\", \"status\": \"in_progress\"}"}
...
```

#### 第七阶段：最终答案

```json
data: {"type": "final_answer", "content": "## 代码质量分析报告\n\n### 发现的问题\n1. **圈复杂度过高**：...\n\n### 改进建议\n1. 重构高复杂度函数\n2. 提取公共方法减少重复代码\n..."}
```

#### 前端 PlanPanel 状态演进

| 阶段 | step-1 | step-2 | step-3 |
|------|--------|--------|--------|
| 规划阶段 | pending | pending | pending |
| 执行 step-1 | **in_progress** | pending | pending |
| step-1 完成 | **completed** | pending | pending |
| step-2 开始 | completed | **in_progress** | pending |
| step-2 完成 | completed | **completed** | pending |
| step-3 开始 | completed | completed | **in_progress** |
| 最终答案 | completed | completed | **completed** |

前端 `PlanPanel` 组件在收到 `plan` 事件时初始化计划面板，在收到 `plan_step_update` 事件时更新对应步骤的 `status` 状态，驱动 UI 状态图标变化（pending → in_progress → completed/skipped）。

---

## 五、详细设计

### 5.1 后端 —— `AgentRequest` 增加字段

**文件：** `backend/consts/model.py`

在 `AgentRequest` 中增加 `enable_plan` 和 `plan_prompt_template_id` 字段（可选，默认为 `false` / `None`）：

```python
class AgentRequest(BaseModel):
    query: str
    conversation_id: Optional[int] = None
    history: Optional[List[HistoryItem]] = None
    minio_files: Optional[List[Dict[str, Any]]] = None
    agent_id: Optional[int] = None
    model_id: Optional[int] = None
    version_no: Optional[int] = None
    is_debug: Optional[bool] = False
    enable_plan: Optional[bool] = Field(
        default=False,
        description="Whether to enable the planning phase before execution"
    )
    plan_prompt_template_id: Optional[int] = Field(
        default=None,
        description=(
            "Optional prompt template ID (from /prompt_templates) used for "
            "the plan generation prompt. Falls back to system default when None."
        )
    )
```

### 5.1.1 后端 —— 复用现有提示词管理机制

计划提示词 **不新增独立的模板类型**，而是复用现有 `agent_generate` 模板的同一张数据库表与同一套加载/合并逻辑（`utils/prompt_template_utils.py` + `services/prompt_template_service.py`），理由如下：

- 现有机制已支持：①YAML 系统默认，②数据库中的租户/用户自定义模板（`prompt_template` 表，`template_type = 'agent_generate'`），③`merge_prompt_generate_templates` 的"自定义优先 + 系统兜底"合并策略。
- 计划 prompt 实质上仍是"LLM 根据上下文生成结构化 JSON"，与 `agent_generate` 模板使用同一套 Jinja2 渲染和字段归一化逻辑。
- 避免引入新的 `template_type` 枚举值、新的 DB schema 字段和新的管理端 UI 入口。

**关键设计：计划 prompt 直接存入 `agent_config.prompt_templates["plan_prompt"]`**

现有 `AgentConfig` 中已有 `prompt_templates: Dict[str, Any]` 字段，用于存放所有提示词内容。后端只需在启用计划时，往这个 dict 中追加一个 `"plan_prompt"` 键即可，SDK 直接从中取值——不需要新增 `AgentRunInfo` 字段，也不需要让 SDK 接触 YAML 或数据库。

**后端集成（`agent_service.py`）：**

```python
from services.prompt_template_service import resolve_prompt_generate_template

async def generate_stream_with_memory(agent_request, user_id, tenant_id, language="zh"):
    # 1. prepare_agent_run：创建 agent_run_info（内部已构建 agent_config.prompt_templates）
    agent_run_info, memory_context = await prepare_agent_run(...)

    # 2. 上下文压缩
    context_summary = None
    if agent_request.enable_plan and agent_request.history:
        context_summary = _compress_context(
            history=agent_request.history,
            task=agent_request.query
        )

    # 3. 注入计划相关字段
    if agent_request.enable_plan:
        # 复用 resolve_prompt_generate_template：相同合并逻辑（自定义优先 + 系统兜底）
        merged_prompts = resolve_prompt_generate_template(
            tenant_id=tenant_id,
            user_id=user_id,
            language=language,
            prompt_template_id=agent_request.plan_prompt_template_id,
        )
        agent_run_info.enable_planning = True
        agent_run_info.plan_repo = PlanRepo(redis_client=redis_client)
        agent_run_info.context_summary = context_summary
        # 直接写入 agent_config.prompt_templates，SDK 从此处读取
        if agent_run_info.agent_config.prompt_templates is None:
            agent_run_info.agent_config.prompt_templates = {}
        agent_run_info.agent_config.prompt_templates["plan_prompt"] = merged_prompts

    # 4. 传给 SDK
    async for data_chunk in _stream_agent_chunks(
        agent_request=agent_request,
        user_id=user_id,
        tenant_id=tenant_id,
        agent_run_info=agent_run_info,
        memory_ctx=memory_context,
    ):
        yield data_chunk
```

**SDK 取用（`CoreAgent._generate_plan`）：**

```python
# plan_prompt 直接来自 agent_config.prompt_templates["plan_prompt"]
# 无需读 YAML、无需查 DB、无需新增 AgentRunInfo 字段
plan_prompt_templates = self.agent_config.prompt_templates.get("plan_prompt", {})
plan_role = plan_prompt_templates.get("duty_system_prompt", "你是一个任务规划助手。")
plan_user = plan_prompt_templates.get("user_prompt", "").format(
    context_summary=self.context_summary or "",
    task=self.query
)
```

**关键约束：**

- `AgentRunInfo` 不新增 `plan_prompt_templates` 字段；所有提示词内容统一进入 `agent_config.prompt_templates`。
- SDK 不新增 `template_type`、不读环境变量、不查 DB；模板内容完全由后端在调用前注入。
- 若用户未传 `plan_prompt_template_id`，`resolve_prompt_generate_template` 等价于"使用系统默认"，与 `prompt_service.generate_system_prompt` 中 `prompt_template_id=None` 的行为完全一致。
- 管理员仍可在现有的"提示词模板管理"页（`/prompt_templates`）中创建/编辑 `agent_generate` 类型模板，无需额外入口。

### 5.2 后端 —— `create_agent_run_info` 保持签名不变

**文件：** `backend/agents/create_agent_info.py`

`create_agent_run_info` 保持现有签名不变。`enable_planning`、`plan_repo` 和 `context_summary` 在调用方（`prepare_agent_run`）中直接赋值到返回的 `AgentRunInfo` 对象。

### 5.2.1 后端 —— 上下文压缩集成

**文件：** `backend/services/agent_service.py`

上下文压缩在 `generate_stream_with_memory` / `generate_stream_no_memory` 中调用，紧贴在 `prepare_agent_run` **之后**、`_stream_agent_chunks` **之前**：

```python
async def generate_stream_with_memory(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
):
    # 1. prepare_agent_run：创建 agent_run_info（内部会构建 agent_config、model 等）
    agent_run_info, memory_context = await prepare_agent_run(
        agent_request=agent_request,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
        allow_memory_search=True,
    )

    # 2. 上下文压缩：在 agent_run_info 创建之后、执行之前
    context_summary = None
    if agent_request.enable_plan and agent_request.history:
        context_summary = _compress_context(
            history=agent_request.history,
            task=agent_request.query
        )

    # 3. 将计划相关字段注入到 agent_run_info（供 SDK 使用）
    if agent_request.enable_plan:
        agent_run_info.enable_planning = True
        agent_run_info.plan_repo = PlanRepo(redis_client=redis_client)
        agent_run_info.context_summary = context_summary

    # 4. 传给 SDK，通过新线程中的 agent_run_thread → NexentAgent → CoreAgent 执行
    async for data_chunk in _stream_agent_chunks(
        agent_request=agent_request,
        user_id=user_id,
        tenant_id=tenant_id,
        agent_run_info=agent_run_info,
        memory_ctx=memory_context,
    ):
        yield data_chunk
```

同理 `generate_stream_no_memory` 也做相同处理。注入发生在 `prepare_agent_run` 返回 `agent_run_info` 之后、`_stream_agent_chunks` 之前，确保 Redis 细节（PlanRepo）不出现在 SDK 层。

其中 `_compress_context` 从对话历史中提取上下文摘要。如果已有上下文压缩服务，直接调用；否则使用轻量降级实现：

```python
def _compress_context(history: List[HistoryItem], task: str) -> str:
    """从对话历史中提取上下文摘要，包含进行中的计划信息。"""
    recent = history[-5:] if len(history) > 5 else history
    summary_parts = [f"当前任务：{task}"]
    for item in recent:
        role = "用户" if item.role == "user" else "助手"
        content = item.content[:100] if len(item.content) > 100 else item.content
        summary_parts.append(f"- {role}：{content}")
    return "\n".join(summary_parts)
```

### 5.3 SDK —— `AgentRunInfo` 增加字段

**文件：** `sdk/nexent/core/agents/agent_model.py`

在 `AgentRunInfo` 中增加 `enable_planning` 和 `plan_repo` 字段：

```python
class AgentRunInfo(BaseModel):
    query: str = Field(description="User query")
    model_config_list: List[ModelConfig] = Field(description="List of model configurations")
    observer: MessageObserver = Field(description="Return data")
    agent_config: AgentConfig = Field(description="Detailed Agent configuration")
    mcp_host: Optional[List[Union[str, Dict[str, Any]]]] = Field(default=None)
    history: Optional[List[AgentHistory]] = Field(default=None)
    stop_event: Event = Field(description="Stop event control")
    context_manager: Optional[Any] = Field(default=None)
    enable_planning: bool = Field(
        description="Whether to enable the planning phase before execution",
        default=False
    )
    plan_repo: Optional[Any] = Field(
        description="PlanRepo instance for plan persistence",
        default=None
    )
    context_summary: Optional[str] = Field(
        description="Compressed context summary from context_compress for plan generation",
        default=None
    )

    class Config:
        arbitrary_types_allowed = True
```

### 5.4 SDK —— `NexentAgent` 增加参数

**文件：** `sdk/nexent/core/agents/nexent_agent.py`

在 `NexentAgent.__init__` 中增加 `enable_planning`、`plan_repo` 和 `context_summary` 参数，并透传到 `CoreAgent`：

```python
class NexentAgent:
    def __init__(self, observer: MessageObserver,
                 model_config_list: List[ModelConfig],
                 stop_event: Event,
                 mcp_tool_collection=None,
                 enable_planning: bool = False,   # 新增
                 plan_repo=None,                  # 新增
                 context_summary=None):           # 新增
        self.observer = observer
        self.model_config_list = model_config_list
        self.stop_event = stop_event
        self.mcp_tool_collection = mcp_tool_collection
        self.enable_planning = enable_planning
        self.plan_repo = plan_repo
        self.context_summary = context_summary  # 新增
        self.agent = None
```

在 `create_single_agent` 中传递给 `CoreAgent`：

```python
agent = CoreAgent(
    ...,
    enable_planning=effective_planning,
    plan_repo=self.plan_repo,
    context_summary=self.context_summary,  # 新增
)
```

### 5.5 SDK —— `CoreAgent` 核心改动

**文件：** `sdk/nexent/core/agents/core_agent.py`

#### 5.5.1 `__init__` 增加字段

```python
class CoreAgent(CodeAgent):
    def __init__(self, observer, prompt_templates=None,
                 enable_planning: bool = False,   # 新增
                 plan_repo=None,                  # 新增
                 context_summary=None,             # 新增
                 *args, **kwargs):
        super().__init__(prompt_templates=prompt_templates, *args, **kwargs)
        self.observer = observer
        self.stop_event = threading.Event()
        self.context_manager = None
        self.step_metrics = []
        self.code_block_tags = ["", ""]
        self.enable_planning = enable_planning      # 新增
        self.plan_repo = plan_repo                  # 新增
        self.context_summary = context_summary      # 新增
        self.current_plan: Optional[AgentPlan] = None
        self.current_step_index: int = 0            # 功能块粒度步骤索引
        self.lang = getattr(self, 'lang', 'en')
```

#### 5.5.2 `_run_stream` 插入规划阶段

```python
def _run_stream(self, task: str, max_steps: int, images=None):
    context_summary = self.context_summary  # 从实例属性获取
    if self.enable_planning:
        plan = self._generate_plan(task, context_summary)
        self.current_plan = plan
        self.current_step_index = 0  # 当前步骤索引（功能块粒度）
        plan_json = json.dumps({
            "plan_id": plan.plan_id,
            "title": plan.title,
            "steps": [s.model_dump() for s in plan.steps]
        }, ensure_ascii=False)
        self.observer.add_message(self.agent_name, ProcessType.PLAN, plan_json)

        # 持久化到 Redis
        if self.plan_repo:
            conv_id = self._get_conversation_id()
            user_id = self._get_user_id()
            self.plan_repo.save(
                plan.model_dump(),
                conversation_id=conv_id,
                user_id=user_id
            )

    # 原有执行循环逻辑不变...
```

#### 5.5.3 步骤状态更新（功能块粒度）

当前步骤索引 `current_step_index` 与功能块执行完毕时机绑定。一个功能块可能包含多次工具调用，步骤状态的切换由 `_step_stream` 的主循环控制，而非单次 `code_output` 触发。

```python
def _step_stream(self, task: str, ...):
    # 功能块粒度：每完成一个功能块，更新一次步骤状态
    while self.step_count < self.max_steps:
        # 将当前步骤约束注入到 prompt messages 中
        if self.current_plan and self.current_step_index < len(self.current_plan.steps):
            messages = self._inject_step_constraint(messages, self.current_plan, self.current_step_index)

        # 原有 LLM 推理 + 工具执行逻辑不变...

        # 功能块执行完毕判定（由 Agent 内部循环自然界定）
        if self._is_functional_block_complete(code_output):
            self._advance_to_next_step()

        yield code_output
```

其中 `_advance_to_next_step` 方法负责推进步骤：

```python
def _advance_to_next_step(self) -> None:
    """推进到下一个计划步骤，标记当前步骤为 completed。"""
    if not self.current_plan or self.current_step_index >= len(self.current_plan.steps):
        return

    current_step = self.current_plan.steps[self.current_step_index]
    current_step.status = "completed"

    # 发送步骤完成事件
    self.observer.add_message(
        self.agent_name, ProcessType.PLAN_STEP_UPDATE,
        json.dumps({"step_id": current_step.id, "status": "completed"}, ensure_ascii=False)
    )

    # 推进索引
    self.current_step_index += 1

    # 标记下一步为 in_progress（若存在）
    if self.current_step_index < len(self.current_plan.steps):
        next_step = self.current_plan.steps[self.current_step_index]
        next_step.status = "in_progress"
        self.observer.add_message(
            self.agent_name, ProcessType.PLAN_STEP_UPDATE,
            json.dumps({"step_id": next_step.id, "status": "in_progress"}, ensure_ascii=False)
        )

    # 持久化步骤状态
    if self.plan_repo:
        conv_id = self._get_conversation_id()
        user_id = self._get_user_id()
        self.plan_repo.update_step(
            conversation_id=conv_id,
            user_id=user_id,
            step_id=current_step.id,
            status="completed"
        )


def _is_functional_block_complete(self, code_output) -> bool:
    """判断当前功能块是否执行完毕。"""
    output_str = str(getattr(code_output, 'output', ''))
    # 通过特殊标记判断（由 Agent 在功能块末尾输出）
    return "__STEP_COMPLETE__" in output_str


def _inject_step_constraint(self, messages: list, plan: AgentPlan, step_index: int) -> list:
    """将当前步骤约束注入到 messages 中，引导 LLM 按计划执行。"""
    current_step = plan.steps[step_index]
    remaining_steps = plan.steps[step_index + 1:]
    remaining_str = "\n".join(
        f"- {s.id}: {s.title} — {s.description}" for s in remaining_steps
    ) if remaining_steps else "无"

    constraint_prompt = (
        f"[计划约束] 当前正在执行计划「{plan.title}」，步骤 {current_step.id}: {current_step.title}\n"
        f"步骤描述：{current_step.description}\n"
        f"剩余步骤：\n{remaining_str}\n"
        f"要求：严格按照计划步骤执行。当前步骤完成后，在输出末尾添加 __STEP_COMPLETE__ 标记。"
    )

    # 追加到首条系统消息或注入为新的 user 约束消息
    constrained_messages = messages.copy()
    constrained_messages.append(
        ChatMessage(role=MessageRole.USER, content=constraint_prompt)
    )
    return constrained_messages
```

#### 5.5.4 规划方法（含上下文）

```python
def _generate_plan(self, task: str, context_summary: str = None) -> AgentPlan:
    """使用 LLM 生成结构化任务计划。"""
    planning_prompt = self._build_planning_prompt(task, context_summary)
    messages = [ChatMessage(role=MessageRole.USER, content=planning_prompt)]
    try:
        response = self.model(messages)
        model_output = response.content if hasattr(response, 'content') else str(response)
    except Exception as e:
        self.logger.log(f"Plan generation failed: {e}", level=LogLevel.WARN)
        return self._fallback_plan(task)
    return self._parse_plan_response(model_output, task)


def _build_planning_prompt(self, task: str, context_summary: str = None) -> str:
    """构建计划生成提示词（支持中英文），包含压缩后的上下文摘要。"""
    context_section = ""
    if context_summary:
        context_section = f"\n\n[对话上下文摘要]\n{context_summary}\n" if self.lang == 'zh' else f"\n\n[Conversation Context Summary]\n{context_summary}\n"

    if self.lang == 'zh':
        return (
            f"{context_section}"
            f"你是一个任务规划助手。请将以下用户任务分解为 3-8 个逻辑清晰的功能块步骤。\n"
            f"用户任务：{task}\n\n"
            f"请按以下 JSON 格式输出计划：\n"
            f'{{"plan_id": "auto-uuid", "title": "简短计划标题", "steps": ['
            f'{{"id": "step-1", "title": "步骤1标题", "description": "详细描述", "status": "pending"}}, ...]}}\n\n'
            f"要求：分解为 3-8 个独立可执行的功能块，描述要具体"
        )
    else:
        return (
            f"{context_section}"
            f"You are a task planning assistant. Decompose the following user task into 3-8 logical functional steps.\n"
            f"User task: {task}\n\n"
            f"Please output the plan in the following JSON format:\n"
            f'{{"plan_id": "auto-uuid", "title": "short plan title", "steps": ['
            f'{{"id": "step-1", "title": "Step 1 title", "description": "Detailed description", "status": "pending"}}, ...]}}\n\n'
            f"Requirements: Decompose into 3-8 independently executable functional blocks, be specific"
        )


def _parse_plan_response(self, content: str, task: str) -> AgentPlan:
    """解析 LLM 输出为 AgentPlan，解析失败时降级为单步计划。"""
    import re, uuid
    try:
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        data = json.loads(json_match.group()) if json_match else json.loads(content)
        return AgentPlan(**data)
    except Exception:
        return self._fallback_plan(task)


def _fallback_plan(self, task: str) -> AgentPlan:
    """创建单步降级计划。"""
    import uuid
    return AgentPlan(
        plan_id=str(uuid.uuid4()),
        title=task[:50] if len(task) > 50 else task,
        steps=[PlanStep(
            id="step-1",
            title="Execute task" if self.lang != 'zh' else "执行任务",
            description=task,
            status="pending"
        )]
    )


def _get_conversation_id(self) -> int:
    """从 context_manager 中提取 conversation_id。"""
    if self.context_manager and hasattr(self.context_manager, 'conversation_id'):
        return self.context_manager.conversation_id
    return 0


def _get_user_id(self) -> str:
    """从 context_manager 中提取 user_id。"""
    if self.context_manager and hasattr(self.context_manager, 'user_id'):
        return str(self.context_manager.user_id)
    return "anonymous"
```

#### 5.5.5 计划删除

在 `FINAL_ANSWER` 事件发送后调用：

```python
def _cleanup_plan(self) -> None:
    """删除 Redis 中的计划。"""
    if self.plan_repo and self.enable_planning:
        conv_id = self._get_conversation_id()
        user_id = self._get_user_id()
        try:
            self.plan_repo.delete(conversation_id=conv_id, user_id=user_id)
        except Exception as e:
            self.logger.log(f"Plan cleanup failed: {e}", level=LogLevel.WARN)
```

> 注意：用户中断（stop_event set）时不主动删除，由 Redis TTL 自动过期。

### 5.6 SDK —— `PlanRepo` 设计（方案 B）

**文件：** `sdk/nexent/core/agents/plan_repo.py`（新建）

```python
"""
Plan persistence layer: Redis primary + local memory fallback.
"""

Usage:
    # 后端层：创建实例
    from backend.services.redis_service import get_redis_service
    redis_client = get_redis_service().client
    plan_repo = PlanRepo(redis_client=redis_client)

    # 通过 AgentRunInfo 传入 SDK
    AgentRunInfo(..., plan_repo=plan_repo)
"""
import json
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class PlanRepo:
    """
    Stores agent plans in Redis with local memory fallback.
    """

    PLAN_KEY_PREFIX = "plan"
    DEFAULT_TTL_SECONDS = 86400  # 24 hours

    def __init__(self,
                 redis_client=None,
                 ttl_seconds: int = DEFAULT_TTL_SECONDS):
        """
        Args:
            redis_client: redis.Redis instance. If None, uses local memory only.
            ttl_seconds: TTL for plan keys in Redis.
        """
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._local: dict[str, dict] = {}
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def save(self,
             plan_dict: dict,
             conversation_id: int,
             user_id: str,
             status: str = "active") -> None:
        """
        Persist a plan. Writes to Redis if available, otherwise local memory.

        Args:
            plan_dict: Serialized AgentPlan dict
            conversation_id: Conversation ID
            user_id: User ID
            status: Audit status string (e.g. "active", "completed", "interrupted")
        """
        key = self._make_key(conversation_id, user_id)
        with self._lock:
            self._local[key] = plan_dict

        if self._redis is not None:
            try:
                self._redis.setex(
                    self._make_redis_key(conversation_id, user_id),
                    self._ttl,
                    json.dumps(plan_dict, ensure_ascii=False)
                )
            except Exception as e:
                logger.warning(f"Redis save failed, using local memory: {e}")

    def load(self, conversation_id: int, user_id: str) -> Optional[dict]:
        """
        Load a plan. Tries Redis first, falls back to local memory.

        Returns:
            Plan dict or None if not found.
        """
        key = self._make_key(conversation_id, user_id)

        if self._redis is not None:
            try:
                data = self._redis.get(self._make_redis_key(conversation_id, user_id))
                if data:
                    plan = json.loads(data)
                    with self._lock:
                        self._local[key] = plan
                    return plan
            except Exception as e:
                logger.warning(f"Redis load failed, falling back to local memory: {e}")

        with self._lock:
            return self._local.get(key)

    def delete(self, conversation_id: int, user_id: str,
               status: str = "completed") -> None:
        """
        Delete a plan from both Redis and local memory.
        """
        key = self._make_key(conversation_id, user_id)

        with self._lock:
            self._local.pop(key, None)

        if self._redis is not None:
            try:
                self._redis.delete(self._make_redis_key(conversation_id, user_id))
            except Exception as e:
                logger.warning(f"Redis delete failed: {e}")

    def update_step(self,
                    conversation_id: int,
                    user_id: str,
                    step_id: str,
                    status: str) -> None:
        """
        Update a single step's status within a stored plan.
        """
        plan = self.load(conversation_id, user_id)
        if plan is None:
            return
        for step in plan.get("steps", []):
            if step.get("id") == step_id:
                step["status"] = status
                break
        self.save(plan, conversation_id, user_id, status="active")

    # -------------------------------------------------------------------------
    # Key helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _make_key(conversation_id: int, user_id: str) -> str:
        return f"{conversation_id}:{user_id}"

    @staticmethod
    def _make_redis_key(conversation_id: int, user_id: str) -> str:
        return f"plan:{conversation_id}:{user_id}"
```

### 5.7 SDK —— `run_agent.py` 透传参数

**文件：** `sdk/nexent/core/agents/run_agent.py`

在两处 `NexentAgent` 实例化处传入 `enable_planning` 和 `plan_repo`：

```python
def agent_run_thread(agent_run_info: AgentRunInfo):
    # ... 两处 NexentAgent 实例化均需添加：
    nexent = NexentAgent(
        observer=agent_run_info.observer,
        model_config_list=agent_run_info.model_config_list,
        stop_event=agent_run_info.stop_event,
        enable_planning=getattr(agent_run_info, 'enable_planning', False),
        plan_repo=getattr(agent_run_info, 'plan_repo', None),
        # ... 其他参数 ...
    )
```

### 5.8 SDK —— `observer.py` 新增事件类型

**文件：** `sdk/nexent/core/utils/observer.py`

```python
class ProcessType(Enum):
    # ... 现有类型 ...
    MEMORY_SEARCH = "memory_search"
    MAX_STEPS_REACHED = "max_steps_reached"
    PLAN = "plan"                        # 新增：结构化计划 JSON
    PLAN_STEP_UPDATE = "plan_step_update"  # 新增：单个计划步骤状态更新
```

在 `_init_message_transformers` 中注册（使用 `DefaultTransformer`）：

```python
self.transformers = {
    # ... 现有映射 ...
    ProcessType.MEMORY_SEARCH: default_transformer,
    ProcessType.MAX_STEPS_REACHED: default_transformer,
    ProcessType.PLAN: default_transformer,              # 新增
    ProcessType.PLAN_STEP_UPDATE: default_transformer,  # 新增
}
```

### 5.9 后端 —— `agent_service.py` 集成 PlanRepo

**文件：** `backend/services/agent_service.py`

在 `prepare_agent_run` 函数中初始化 `PlanRepo`，在 `create_agent_run_info` 返回后直接赋值到 `AgentRunInfo`：

```python
async def prepare_agent_run(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
    allow_memory_search: bool = True,
):
    """
    Prepare for an agent run by creating context and run info, and registering the run.
    """

    memory_context = build_memory_context(
        user_id, tenant_id, agent_request.agent_id, skip_query=not allow_memory_search)

    agent_run_info = await create_agent_run_info(
        agent_id=agent_request.agent_id,
        minio_files=agent_request.minio_files,
        query=agent_request.query,
        history=agent_request.history,
        tenant_id=tenant_id,
        user_id=user_id,
        language=language,
        allow_memory_search=allow_memory_search,
        is_debug=agent_request.is_debug,
        override_version_no=agent_request.version_no,
        override_model_id=agent_request.model_id,
    )

    # 初始化 PlanRepo 并注入（方案 B）
    from backend.services.redis_service import get_redis_service
    from sdk.nexent.core.agents.plan_repo import PlanRepo

    try:
        redis_client = get_redis_service().client
    except Exception:
        redis_client = None

    plan_repo = PlanRepo(redis_client=redis_client)
    agent_run_info.enable_planning = agent_request.enable_plan  # 直接赋值
    agent_run_info.plan_repo = plan_repo                        # 直接赋值

    # Mount conversation-level reusable ContextManager if enabled
    cm_config = getattr(agent_run_info.agent_config,
                        'context_manager_config', None)
    if cm_config and cm_config.enabled:
        cm = agent_run_manager.get_or_create_context_manager(
            conversation_id=str(agent_request.conversation_id),
            config=cm_config,
            max_steps=agent_run_info.agent_config.max_steps
        )
        agent_run_info.context_manager = cm

    agent_run_manager.register_agent_run(
        agent_request.conversation_id, agent_run_info, user_id)
    # ...
```

> **透传方式**：不修改 `create_agent_run_info` 签名。在其返回 `AgentRunInfo` 后，由调用方直接赋值 `enable_planning` 和 `plan_repo` 属性，语义清晰且无需清理残留。

### 5.10 前端 —— ChatInput 增加计划开关

**文件：** `frontend/app/[locale]/chat/components/chatInput.tsx`

在输入框底部栏（现有工具按钮区域）增加一个切换开关：

```tsx
// Props 接口扩展
interface ChatInputProps {
  // ... 现有字段 ...
  enablePlan?: boolean;              // 新增
  onEnablePlanChange?: (v: boolean) => void;  // 新增
}

// 内部状态
const [enablePlan, setEnablePlan] = useState(false);

// 底部工具栏渲染
<div className="flex items-center gap-2">
  {/* 现有按钮... */}

  {/* 计划开关（默认关闭） */}
  <Tooltip title={t('plan.enablePlanning')}>
    <Button
      type={enablePlan ? 'primary' : 'text'}
      size="small"
      icon={<ListTodo className="w-4 h-4" />}
      onClick={() => setEnablePlan(!enablePlan)}
    />
  </Tooltip>
</div>
```

在调用 `runAgent` 时透传：

```tsx
const result = await runAgent({
  query: input,
  conversation_id: currentConversationId,
  // ... 现有参数
  enable_plan: enablePlan,  // 新增
}, abortController.signal);
```

### 5.11 前端 —— `conversationService` 透传字段

**文件：** `frontend/services/conversationService.ts`

```typescript
async runAgent(params: {
  // ... 现有字段 ...
  enable_plan?: boolean;  // 新增
}, signal?: AbortSignal) {
  const requestParams: any = {
    query: params.query,
    conversation_id: params.conversation_id,
    history: params.history,
    minio_files: params.minio_files || null,
    is_debug: params.is_debug || false,
    enable_plan: params.enable_plan || false,  // 新增
  };
  // ...
}
```

### 5.12 前端 —— 消息配置

**文件：** `frontend/const/chatConfig.ts`

```typescript
messageTypes: {
  // ... 现有类型 ...
  PLAN: 'plan',                  // 新增
  PLAN_STEP_UPDATE: 'plan_step_update',  // 新增
},
```

### 5.13 前端 —— SSE 事件处理

**文件：** `frontend/app/[locale]/chat/streaming/chatStreamHandler.tsx`

在 `handleStreamResponse` 的 `switch` 语句中新增两个 `case`：

```typescript
case chatConfig.messageTypes.PLAN:
  try {
    const planData = JSON.parse(messageContent);
    updatedMsg.plan = planData;
    updatedMsg.planVisible = true;
  } catch {
    // 解析失败，静默忽略
  }
  break;

case chatConfig.messageTypes.PLAN_STEP_UPDATE:
  try {
    const stepUpdate = JSON.parse(messageContent);
    if (updatedMsg.plan?.steps) {
      const step = updatedMsg.plan.steps.find(
        (s: PlanStep) => s.id === stepUpdate.step_id
      );
      if (step) {
        step.status = stepUpdate.status;
      }
    }
  } catch {
    // 解析失败，静默忽略
  }
  break;
```

### 5.14 前端 —— 计划面板组件

**文件：** `frontend/app/[locale]/chat/components/PlanPanel.tsx`（新建）
**UI 位置：** 作为 `ChatStreamMain` 中 assistant 消息的兄弟节点渲染，位置在 `ChatStreamFinalMessage` 之前（步骤列表上方）。

功能需求：
- 显示计划标题
- 列出所有步骤，每个步骤显示：序号、图标（按状态区分）、标题、描述
- 顶部进度条（已完成步骤 / 总步骤）
- 状态图标：
  - `pending`：空心圆（灰色）
  - `in_progress`：旋转加载图标（蓝色）
  - `completed`：绿色勾选圆圈
  - `skipped`：灰色跳过箭头
- 只读，不可编辑

### 5.15 前端 —— 集成到消息渲染

**文件：** `frontend/app/[locale]/chat/streaming/chatStreamMain.tsx`

在 `finalMessages.map` 中，assistant 消息的 `<ChatStreamFinalMessage />` 之前作为兄弟节点渲染计划面板：

```tsx
{processedMessages.finalMessages.map((message, index) => (
  <div key={message.id || index} className="flex flex-col gap-2">
    {/* 计划面板（只读）- 独立兄弟节点 */}
    {message.role === MESSAGE_ROLES.ASSISTANT && message.plan && message.planVisible && (
      <PlanPanel plan={message.plan} />
    )}
    <ChatStreamFinalMessage
      message={message}
      onSelectMessage={onSelectMessage}
      isSelected={message.id === selectedMessageId}
      searchResultsCount={message?.searchResults?.length || 0}
      imagesCount={message?.images?.length || 0}
      onImageClick={onImageClick}
      onOpinionChange={onOpinionChange}
      index={index}
      currentConversationId={currentConversationId}
      onCitationHover={onCitationHover}
    />
    {message.role === MESSAGE_ROLES.USER &&
      processedMessages.conversationGroups.has(message.id!) && (
        <div className="transition-all duration-500 opacity-0 translate-y-4 animate-task-window">
          <TaskWindow ... />
        </div>
      )}
  </div>
))}
```

> **注意：** `PlanPanel` 渲染在 `ChatStreamFinalMessage` 之前，因此用户可以在 agent 执行步骤过程中实时看到计划进度，不受最终消息渲染时机影响。

---

## 六、文件变更清单

### SDK 层

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `sdk/nexent/core/utils/observer.py` | 修改 | 新增 `PLAN` 和 `PLAN_STEP_UPDATE` 枚举值及 transformer 注册 |
| `sdk/nexent/core/agents/agent_model.py` | 修改 | 新增 `PlanStep`、`AgentPlan` 模型；在 `AgentRunInfo` 中增加 `enable_planning`、`plan_repo` 字段 |
| `sdk/nexent/core/agents/core_agent.py` | 修改 | `__init__` 增加 `enable_planning`、`plan_repo`、`current_plan`；`_run_stream` 插入规划阶段；新增 `_generate_plan`、`_build_planning_prompt`、`_parse_plan_response`、`_fallback_plan`、`_update_plan_step_status`、`_get_conversation_id`、`_get_user_id`、`_cleanup_plan` |
| `sdk/nexent/core/agents/nexent_agent.py` | 修改 | `__init__` 增加 `enable_planning`、`plan_repo`；`create_single_agent` 透传到 `CoreAgent` |
| `sdk/nexent/core/agents/run_agent.py` | 修改 | 两处 `NexentAgent` 实例化均传入 `enable_planning` 和 `plan_repo` |
| `sdk/nexent/core/agents/plan_repo.py` | **新建** | 计划持久化层：Redis + 本地内存兜底 |

### 后端层

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `backend/consts/model.py` | 修改 | `AgentRequest` 增加 `enable_plan` 和 `plan_prompt_template_id` 字段 |
| `backend/agents/create_agent_info.py` | 无需修改 | 签名不变，`enable_planning`、`plan_repo` 和 `context_summary` 在调用方直接赋值 |
| `backend/services/agent_service.py` | 修改 | `prepare_agent_run` 中初始化 `PlanRepo` 并赋值到 `AgentRunInfo`；启用 plan 时通过 `resolve_prompt_generate_template` 解析模板后注入 |

### 前端层

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `frontend/const/chatConfig.ts` | 修改 | 新增 `PLAN` 和 `PLAN_STEP_UPDATE` 消息类型 |
| `frontend/app/[locale]/chat/types/chat.ts` | 修改 | 新增 `PlanStep`、`AgentPlan` 类型；扩展 `ChatMessageType` |
| `frontend/services/conversationService.ts` | 修改 | `runAgent` 增加 `enable_plan` 参数透传 |
| `frontend/app/[locale]/chat/streaming/chatStreamHandler.tsx` | 修改 | 处理 `PLAN` 和 `PLAN_STEP_UPDATE` SSE 事件 |
| `frontend/app/[locale]/chat/components/chatInput.tsx` | 修改 | 底部栏增加计划开关按钮（默认关闭） |
| `frontend/app/[locale]/chat/components/PlanPanel.tsx` | **新建** | 计划面板组件（状态图标 + 进度条） |
| `frontend/app/[locale]/chat/streaming/chatStreamMain.tsx` | 修改 | 渲染 `PlanPanel` 作为 assistant 消息的兄弟节点 |
| `frontend/app/[locale]/chat/streaming/chatStreamFinalMessage.tsx` | 修改 | 移除 `PlanPanel` 渲染逻辑（改由 `ChatStreamMain` 负责） |

### 提示词层（复用现有机制，无新增）

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `backend/prompts/utils/prompt_generate_zh.yaml` | 不修改 | 复用现有 `duty_system_prompt` / `user_prompt` 字段承载计划 prompt；YAML 中已含"任务规划助手"段落 |
| `backend/prompts/utils/prompt_generate_en.yaml` | 不修改 | 同上英文版本 |
| `backend/utils/prompt_template_utils.py` | 不修改 | 复用 `get_prompt_template` / `merge_prompt_generate_templates` |
| `backend/services/prompt_template_service.py` | 不修改 | 复用 `resolve_prompt_generate_template(tenant_id, user_id, language, prompt_template_id)` |
| `backend/consts/prompt_template.py` | 不修改 | 复用现有 `PROMPT_GENERATE_TEMPLATE_FIELD_ALIAS_MAP` |

---

## 七、关键设计要点

### 7.1 自适应执行

Agent 可通过在代码输出中包含特殊标记 `__SKIP_STEP__` 来跳过当前步骤：

```python
# Agent 代码示例
print(__SKIP_STEP__)  # 标记当前步骤为跳过
# 或者输出中包含 __SKIP_STEP__ 字符串
```

`_update_plan_step_status` 检测该标记并将步骤状态设为 `skipped`。

### 7.2 降级策略

| 失败场景 | 处理方式 |
|----------|----------|
| LLM 无法生成有效 JSON | 降级为单步计划，继续执行 |
| 前端解析 PLAN 事件失败 | 静默忽略，不阻塞执行循环 |
| Redis 不可用 | 自动降级到本地内存（`PlanRepo` 内部处理） |
| 计划持久化全部失败 | 不阻塞 agent 运行，计划丢失但执行继续 |

### 7.3 性能考量

- **规划阶段额外增加 1 次 LLM 调用**，延迟取决于模型推理速度（通常 0.5-2 秒）。通过用户主动触发控制，避免所有任务都增加开销。
- **计划 JSON 通常 < 2KB**，SSE 传输无额外压力。
- **Redis 操作在关键路径之外**（save/load/update 不阻塞 agent 执行），仅用于多实例共享和会话恢复。

### 7.4 兼容性

- `enable_plan` 默认为 `false`，现有调用链完全不受影响。
- 现有的 `STEP_COUNT`、`execution_logs`、`token_count` 等 SSE 事件不受影响。
- 不开启计划功能时，`CoreAgent._run_stream` 执行路径与之前完全一致。

### 7.5 多实例部署

- Redis 作为共享存储，保证多实例间计划一致性。
- `PlanRepo` 本地内存作为缓存，减少 Redis 访问频率。
- 用户中断（stop_event）时，计划不主动删除，由 Redis TTL（24h）自动过期兜底。

---

## 八、待开发确认事项

以下事项在开发过程中可能需要进一步对齐：

1. **i18n 文案**：前端 `PlanPanel` 中的"进行中"、"步骤完成"等中文文案需要支持多语言。
2. **现有测试兼容**：`NexentAgent` 构造函数签名变更（增加 `enable_planning`、`plan_repo` 参数），需更新相关单元测试。

---

## 九、开发计划

### 9.1 整体策略

将计划功能拆分为 **5 个独立模块**，每个模块可独立开发、独立合入 PR。合入顺序满足依赖关系，任意模块合入后不影响现有功能（所有新字段均带默认值，开关默认关闭）。

```
Module A ──→ Module B      （无依赖，可并行）
                  │
                  ▼
              Module C
                  │
                  ▼
              Module D
                  │
                  ▼
              Module E
```

---

### 9.2 模块 A — SDK 数据层（Observer + 模型）

**合入优先级：P0（最先）**
**目标文件：** `sdk/nexent/core/agents/agent_model.py`、`sdk/nexent/core/utils/observer.py`

| 改动 | 说明 |
|------|------|
| 新增 `PlanStep` 模型 | 描述单个计划步骤：`step_no`、`title`、`status`（pending/in_progress/completed/skipped）、`description` |
| 新增 `AgentPlan` 模型 | 包含 `plan_id`、`steps: List[PlanStep]`、`status`、`total_steps` |
| `AgentRunInfo` 增加字段 | `enable_planning: bool = False`、`plan_repo: Optional[Any] = None`、`context_summary: Optional[str] = None`，均有默认值，向后兼容 |
| Observer 新增枚举 | `PLAN`、`PLAN_STEP_UPDATE`，仅增加两个可选事件类型，不影响现有事件流转 |

**回归风险：零。** 新字段全带 `default=`，Observer 枚举只是多两个值。

**依赖：** 无，可与其他模块并行开发。

---

### 9.3 模块 B — 后端集成（PlanRepo + 提示词解析）

**合入优先级：P0（可与模块 A 并行）**
**目标文件：** `backend/consts/model.py`、`backend/agents/plan_repo.py`、`backend/services/agent_service.py`

| 改动 | 说明 |
|------|------|
| `AgentRequest` 增加字段 | `enable_plan: bool = False`、`plan_prompt_template_id: Optional[int] = None` |
| 新建 `plan_repo.py` | Redis 存储 + 本地内存兜底的计划持久化层，接口：`save_plan`、`get_plan`、`update_step`、`delete_plan`、`get_conversation_plan` |
| `agent_service.py` 集成 | 在 `generate_stream_with_memory` / `generate_stream_no_memory` 中，`prepare_agent_run` 之后、`_stream_agent_chunks` 之前：① 调用 `_compress_context` 生成上下文摘要（可选降级）；② 调用 `resolve_prompt_generate_template` 解析计划提示词模板；③ 将结果写入 `agent_run_info.agent_config.prompt_templates["plan_prompt"]`；④ 赋值 `enable_planning`、`plan_repo`、`context_summary` |

**回归风险：零。** 后端只做"赋值"操作，SDK 此时尚未读取新字段，功能上无感知。`_compress_context` 有轻量降级实现。

**依赖：** 无，可与模块 A 并行。

---

### 9.4 模块 C — CoreAgent 规划阶段

**合入优先级：P1（依赖模块 A）**
**目标文件：** `sdk/nexent/core/agents/core_agent.py`

| 改动 | 说明 |
|------|------|
| `__init__` 接收新参数 | `enable_planning`、`plan_repo`、`context_summary`，存入实例属性 |
| `_run_stream` 插入规划阶段 | 在执行循环之前，若 `enable_planning=True` 且有活跃 plan，则调用 `_generate_plan`；完成后通过 Observer 发出 `PLAN` 事件 |
| 新增 `_generate_plan` | 从 `agent_config.prompt_templates["plan_prompt"]` 取模板（详见 5.1.1 节），渲染 system/user prompt，调用 LLM，解析结构化 JSON |
| 新增 `_build_planning_prompt` | 组装计划生成 prompt：role 来自 `duty_system_prompt`，user 来自 `user_prompt` + 上下文摘要 + 当前任务 |
| 新增 `_parse_plan_response` | 解析 LLM 返回的 JSON，提取步骤列表，存入 PlanRepo |
| 新增 `_fallback_plan` | LLM 解析失败时，生成最小可用计划（单步骤），保证流程不中断 |

**回归风险：零。** 规划阶段是 `_run_stream` 的前置步骤，`enable_planning=False` 时完整跳过，原有执行循环不受任何影响。

**依赖：** 模块 A（`AgentPlan`/`PlanStep` 模型 + Observer 枚举）。

---

### 9.5 模块 D — 执行循环计划集成

**合入优先级：P2（依赖模块 A + C）**
**目标文件：** `sdk/nexent/core/agents/nexent_agent.py`、`sdk/nexent/core/agents/run_agent.py`、`sdk/nexent/core/agents/core_agent.py`

| 改动 | 说明 |
|------|------|
| `nexent_agent.py` | `__init__` 接收 `enable_planning`/`plan_repo`/`context_summary`，`create_single_agent` 透传到 `CoreAgent` |
| `run_agent.py` | 两处 `NexentAgent` 实例化均传入新参数 |
| `core_agent.py` — `_step_stream` | 每次迭代前调用 `_inject_step_constraint`：若当前有活跃计划，在 system prompt 中追加"请执行第 N 步：{step.title}"约束 |
| 新增 `_update_plan_step_status` | 检测 Agent 输出中的 `__SKIP_STEP__` 标记，将步骤状态设为 `skipped`；执行成功后设为 `completed`，通过 Observer 发出 `PLAN_STEP_UPDATE` 事件 |
| 新增 `_cleanup_plan` | 任务结束后（无论成功/失败/中断）将计划状态标记为 `completed`，不主动删除（Redis TTL 24h 兜底） |

**回归风险：极低。** `_step_stream` 仅在 `enable_planning=True` 且有活跃计划时才注入额外 message，否则行为与之前完全一致。

**依赖：** 模块 A（模型）、模块 C（规划阶段 + `_generate_plan`）。

---

### 9.6 模块 E — 前端（SSE 处理 + PlanPanel 组件）

**合入优先级：P3（依赖模块 C + D）**
**目标文件：** `frontend/const/chatConfig.ts`、`frontend/app/[locale]/chat/streaming/chatStreamHandler.tsx`、`frontend/services/conversationService.ts`、`frontend/app/[locale]/chat/components/chatInput.tsx`、`frontend/app/[locale]/chat/components/PlanPanel.tsx`（新建）、`frontend/app/[locale]/chat/streaming/chatStreamMain.tsx`

| 改动 | 说明 |
|------|------|
| `chatConfig.ts` | 新增 `PLAN`、`PLAN_STEP_UPDATE` 消息类型 |
| `conversationService.ts` | `runAgent` 增加 `enable_plan` 参数透传 |
| `chatStreamHandler.tsx` | 处理 `PLAN` 事件（解析 plan JSON，更新 message.plan）和 `PLAN_STEP_UPDATE` 事件（更新对应步骤状态） |
| `chatInput.tsx` | 底部工具栏增加计划开关按钮（默认关闭） |
| 新建 `PlanPanel.tsx` | 计划面板组件：步骤列表 + 状态图标（pending/in_progress/completed/skipped）+ 进度条 |
| `chatStreamMain.tsx` | 在 assistant 消息之前渲染 `PlanPanel`（如果消息有 plan 数据） |

**回归风险：零。** 前端开关默认 `false`，后端默认不启用规划，即使前后端各合一半，用户看到的也是完全正常的行为。

**依赖：** 模块 C（`PLAN` SSE 事件格式）、模块 D（`PLAN_STEP_UPDATE` SSE 事件格式）。

---

### 9.7 各模块合入检查清单

每个模块合入前确认：

- [ ] 所有新增字段带 `default=`，无破坏性变更
- [ ] 所有新函数/类有 fallback 路径（Redis 不可用时降级到内存）
- [ ] 现有单元测试全部通过（不新增测试也可以先合入）
- [ ] 开关默认为关闭/None，不影响现有用户

**推荐合入顺序：**

| PR | 模块 | 合入时机 | 并行度 |
|----|------|----------|--------|
| PR 1 | A — SDK 数据层 | 最早 | 可与 PR 2 并行 |
| PR 2 | B — 后端集成 | 最早 | 可与 PR 1 并行 |
| PR 3 | C — CoreAgent 规划阶段 | 合入 PR 1 后 | 独立 |
| PR 4 | D — 执行循环集成 | 合入 PR 1 + 3 后 | 独立 |
| PR 5 | E — 前端 | 合入 PR 3 + 4 后（或合入 PR 1 后即可开始前端开发） | 独立 |
