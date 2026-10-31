# PR #4151 代码评审 — nl2skills 工作台缺陷修复

- **PR**: [ModelEngine-Group/nexent#4151](https://github.com/ModelEngine-Group/nexent/pull/4151) `🐛 Bugfix: Fix issues with the nl2skills feature in the Agent Workbench`
- **作者**: YehongPan · 2 commits · 13 files · **+453/−38**
- **基准**: merge-base `872fe972d` · head `2af656eb0`
- **⚠️ 状态**: **已合入 develop**（squash 提交 `377fe37a2`），因此本报告按「已上线代码的缺陷弹」来处理

---

## 0. 先说结论

| 项 | 结论 |
| --- | --- |
| 三个声称的修复 | 两个真正修好（按钮、历史进入上下文），第三个（英文提示词）修得对但**未覆盖中文场景下的同类问题** |
| 🔴 严重 | **1 条**：历史中的空 user/assistant 会生成空消息直送模型，且仓库已有 `_UNANSWERED_CONTEXT_NOTE` 约定未被沿用（见 B1） |
| 🟡 建议 | 4 条（locale 孤儿 key、测试断言过严、`_skill_history_turns` 边界、`_decorate_event` 存量缺陷） |
| 💭 轻微 | 2 条 |
| 合入判断 | 已合入。**B1 建议尽快跟进修复**（改动小、影响实际请求） |

### 三个修复的实际完成度

| 声称的修复 | 实际 | 说明 |
| --- | --- | --- |
| 移除无效的“确定/运行”按钮 | ✅ 完成 | 两按钮原本都恒 `disabled`，删除是唯一正确选择 |
| 修复历史未进模型上下文 | ⚠️ **主链路修好，但引入空消息缺陷** | 见 B1。`context_input` 注入思路正确，但空回复处理没对齐仓库既有约定 |
| 修复大量英文提示词 | ✅ en 修好，zh 侧表述同步 | 根因是 `prompt_templates=None` 触发 smolagents 默认英文模板，定位准确 |

---

## 1. 三个修复的实质

### 修复 1：移除文件预览的无效按钮 — ✅ 修对了

**位置**：`frontend/app/[locale]/newchat/ui/skill-file-card.tsx`

删除了 `SkillFileCard` 底部整块 footer：`PlayIcon`（运行，恒 disabled）+ `CheckIcon`（确定，恒 disabled）。原实现两个按钮**都写死 `disabled`**，等于永远点不动的假控件，删除是唯一正确选择（而不是把它启用）。

同步清理：`Button`、`useTranslation`、`CheckIcon`、`PlayIcon` 四个 import 一并删掉，`isCode` 仍被 `FileIcon` 使用而保留 —— 没有留下未使用变量。✅

新增测试 `SkillFileCard.test.tsx` 断言“展开后不存在确定按钮”，并用 `getAllByRole("button")` 等于仅 trigger 一条来锁死“预览里没有任何可交互按钮”。

### 修复 2：历史进入模型上下文 — ✅ 修对了，但渲染层有漏（见 B1）

**根因准确**：`build_nl2skill_run_info` 构造 `AgentRunInfo` 时把 `history` 塞进了 `AgentRunInfo.history`，而 SDK 的 `run_agent._get_authorized_history()`（`run_agent.py` L196-202）在 `context_input` 存在时会**返回 `[]`** —— 即历史被显式丢弃。所以“原失败会话输入继续后能生成”确实只能靠把历史搬进 `context_input` 才能修好。

**实现方式**：新增 `_skill_history_turns()` 把 `AgentHistory` 列表转成 `conversation_turn` 项的 `{user_message, assistant_final_answer, attachments, user_message_id, assistant_message_id}` 结构，再经 `build_authorized_context_input(run_info, historical_context=...)` 冻结成 context 快照。

这个思路是对的：走官方已存在的授权上下文通道，而不是重新打开 `AgentMemory` 旁路。`_get_authorized_history(info) == []` 的断言（test L47）也确认了“不会双写”。

**`_skill_history_turns` 的合并策略**（`backend/services/nl2skill_service.py` L87-104）：

```python
if entry.role == "assistant" and pending_user:
    turns[-1]["assistant_final_answer"] = entry.content
    pending_user = False
    continue
```

即“user 开一条 turn，紧随其后的 assistant 回填进同一条”。这个策略对三种关键场景都成立：
- user + 空 assistant（失败会话）→ 1 条 turn，`assistant=""` ✅
- user 后面没有 assistant（未回答）→ 1 条 turn，`assistant=""` ✅
- 正常多轮 → n 条 turn ✅

### 修复 3：英文提示词过多 — ✅ en 修对了，但 zh 侧同类表述只改了一半

**en 侧**（`sdk/nexent/core/prompts/en/meta/nl2skill.yaml`）：
- 新增 “Language and response boundaries” 段，明确“默认英文，用户显式指定时跟随用户”
- 删掉 `- **Do not** use "Thought:", "Thinking:", or any English thinking tags - the Agent must use Chinese format.` —— 这条对英文用户完全错乱（要求英文 agent 用中文思考），改成语言中立的 “do not output reasoning labels or execution traces in any language”
- `description` 字段从“必须英文”放宽为“默认英文，用户指定则跟随”

**zh 侧**对称改动，但这里有个细节值得指出：

`zh` 的 `description` 从 `简短的中文描述` 改为 `默认使用中文的简短描述…用户明确指定产物语言时使用该语言`，而**技能 `name` 仍然是强制英文或拼音**（`使用英文或拼音，字母小写`）。这是有意的（文件系统/路径约束），但两侧都没在 prompt 里解释“为什么 name 必须拉丁化”，中文用户第一次看到可能困惑。💭

**同时修复的实质问题**：原 `nl2skill_agent.py` 用 `instructions=system_prompt` + `prompt_templates=None`，导致 smolagents 会把**默认英文 CodeAgent 模板**（"You are an expert assistant who can solve any task using code blobs…"）和 `instructions` 拼接。这才是“英文提示词大量出现”的真正来源。改成：

1. `prompt_templates` 传非空 mapping（关闭默认模板加载）
2. 真正的 prompt 走 `context_items` 的 `SYSTEM` 项
3. `instructions` 不传

**为什么第 2 步是必要的**（这点作者注释写对了）：`prompt_templates["system_prompt"]` 会被 Jinja 渲染，而用户 draft 里可能有字面量 `{{ customer_name }}` 或 `{% if enabled %}`，直接放模板会被误渲染。走 `context_items` 的 `content={"text": ...}` 则完全绕过模板引擎。测试 `test_nl2skill_prompt.py` L24 专门用这个 draft 验证了 `{{ customer_name }}` 字面量存活 —— 这是个很好的用例。

---

## 2. 🔴 B1（严重）：历史空 content 会生成空消息直送模型

### 问题

`_render_turn` 对每个 `conversation_turn` **无条件**产出 user + assistant 两条消息，不判断内容是否为空：

**位置**：`sdk/nexent/core/agents/context/rendering.py` **L85-89**

```python
def _render_turn(item: ContextItem) -> list[dict[str, Any]]:
    return [
        _text_message("user", str(item.content["user_message"])),
        _text_message("assistant", str(item.content["assistant_final_answer"])),
    ]
```

而 `_text_message`（同文件 L27-28）不做任何空判断：

```python
def _text_message(role: str, text: str) -> dict[str, Any]:
    return {"role": role, "content": [{"type": "text", "text": text}]}
```

对比同文件的 `_render_text`（L42-43）**是有空过滤的**：

```python
if not text:
    return []
```

所以 `conversation_turn` 是唯一一条没有空过滤的渲染路径。

### 触发条件（用 PR 自己的测试用例就能复现）

我复现了 `_skill_history_turns` 的纯逻辑，四种真实场景都会产出空消息：

| 输入 history | 产出 turn | 空消息 |
| --- | --- | --- |
| `[user:"A", assistant:""]`（**本 PR 要修的核心场景**） | 1 条，`assistant=""` | **空 assistant** |
| `[user:"A"]`（未回答） | 1 条，`assistant=""` | **空 assistant** |
| `[user:"A", user:"B"]`（前端连续两次发送） | 2 条，两条 `assistant=""` | **2 条空 assistant** |
| `[assistant:"X", user:"A"]`（会话首条是 assistant） | 2 条，第 1 条 `user=""` | **空 user** |
| `[user:"A", assistant:"R1", assistant:"R2"]` | 2 条，第 2 条 `user=""` | **空 user** |

注意第一行：**这正是 PR 描述里说“原失败会话输入继续后可成功生成”的那个场景** —— 失败会话的 assistant content 就是空字符串。也就是说，这个 PR 为修复它而引入的历史回放，恰好会往请求里塞一条 `content: [{"type":"text","text":""}]` 的 assistant 消息。

### 影响

1. **provider 兼容性**：OpenAI 规范里 assistant message 的 `content` 不允许是空字符串；部分实现（Azure、部分国产兼容网关）会直接 400 `content must not be empty`。nexent 的 `openai_llm.py` 里我搜过，**没有任何消息级空 content 剔除逻辑**（只有 `model_output.strip()` 相关的空输出判断，L801/L824，那是响应侧）。
2. **即使 provider 容忍**：空 assistant 消息在语义上是“模型已经回答了一个空答案”，会占据对话结构位，对小模型的后续生成有轻微误导。
3. **空 user 消息**更糟：连续两条 user 或首条 assistant 的场景会产生 `user: ""`，这在多数 provider 上属于非法交替序列。

### 为什么测试没抓到

`test_nl2skill_continuation.py` L43-45：

```python
visible_history = [(role, text) for role, text in actual if role != "system" and text]
expected = [(m["role"], m["content"]) for m in history if m["role"] in {"user", "assistant"} and m["content"]]
assert visible_history == expected
```

**两边都带 `and text` 过滤**。测试把空消息主动滤掉后再比较，因此“空 assistant 被发出去”这件事永远断言不到。这属于测试与实现共享了同一个错误假设 —— 断言的是“非空内容一致”，而不是“模型实际收到的消息序列正确”。

### 关键旁证：仓库里已有正确做法，本 PR 没有跟随

我对比了另外两条同样走 `conversation_turn` 的路径，它们**都不会产出空消息**：

| 路径 | 入口 | 未回答/空回复的处理 |
| --- | --- | --- |
| 主 Agent 聊天 | `run.py` L231-237 → `load_historical_context` → `get_historical_context` | **填占位说明** `_UNANSWERED_CONTEXT_NOTE = "该轮未生成有效回复。"`（`conversation_db.py` L2419），L2552/L2562 显式使用 |
| nl2agent | `nl2agent_service.py` L1436 → `build_authorized_context_input(run_info)`（不带 `historical_context`） | 走 `context.py` L26-44 的 `fallback_turns`，**只在 user+assistant 成对时才 append**，未回答的 user 被直接跳过 |
| **nl2skill（本 PR）** | `nl2skill_service.py` L272-274 → 自建 `_skill_history_turns` | **空字符串原样保留** ← 唯一例外 |

也就是说，仓库对“失败的轮次怎么表达”已经有一个明确约定（`_UNANSWERED_CONTEXT_NOTE`），而本 PR 新写的 `_skill_history_turns` 既没复用它、也没做渲染层过滤，形成了第三套不一致的语义。

### 建议修复（推荐方案 b）

**方案 a（渲染层防御）**：在 `rendering.py` 的 `_render_turn` 对齐 `_render_text` 的空判断：

```python
def _render_turn(item: ContextItem) -> list[dict[str, Any]]:
    messages = []
    user_text = str(item.content.get("user_message") or "")
    assistant_text = str(item.content.get("assistant_final_answer") or "")
    if user_text:
        messages.append(_text_message("user", user_text))
    if assistant_text:
        messages.append(_text_message("assistant", assistant_text))
    return messages
```

**方案 b（对齐既有约定，更推荐）**：在 `_skill_history_turns` 里就对空回复填占位说明，与主流程语义一致：

```python
# backend/services/nl2skill_service.py
from database.conversation_db import _UNANSWERED_CONTEXT_NOTE   # 或提到公共 consts

...
turns.append({
    "user_message": entry.content if entry.role == "user" else "",
    "assistant_final_answer": (
        entry.content or _UNANSWERED_CONTEXT_NOTE   # ← 空回复也告知模型"这轮失败了"
    ) if entry.role == "assistant" else "",
    ...
})
```

理由：本 PR 的业务目标恰恰是“让模型知道上一轮失败了，所以用户说继续”。给一条空 assistant 既不合法也不传达信息；填 `"该轮未生成有效回复。"` 既避免空消息，又真正实现 PR 想达成的效果。**同时 renderer 侧的空防御（方案 a）仍建议一并加上**，作为 SDK 公共层的兜底。

**测试同步修**：把 `test_nl2skill_continuation.py` L43 的 `and text` 从 **actual 侧**去掉（只保留 expected 侧的过滤），断言变成“模型收到的消息序列 == 期望序列”，空消息一旦发出去就红。

⚠️ 方案 a 在 `sdk/` 公共渲染层，会影响所有 agent。改前跑 `test/sdk/core/agents/` 全量，确认没有用例依赖“空 turn 也产生两条消息”。

---

## 3. 🟡 建议级

### S1. 删除按钮后 locale key 变孤儿

**位置**：`frontend/public/locales/en/common.json` **L4664**、`zh/common.json` **L4605**

```json
"skillManagement.fileCard.run": "Run",     // 已无任何消费者
"skillManagement.fileCard.run": "运行",
```

`git grep` 确认 `frontend/app` / `frontend/components` / `frontend/features` 下 **0 处引用**。PR 删了“运行”按钮却没删它的文案 key。（`.confirm` 走的是 `common.confirm`，不能删。）

**建议**：删掉 en/zh 各一条。

### S2. 新测试的按钮断言过严

**位置**：`frontend/tests/workbench/SkillFileCard.test.tsx` L50

```ts
expect(screen.getAllByRole("button")).toEqual([trigger]);
```

断言“整个卡片只有一个 button”。将来任何人往卡片里加一个合法的按钮（比如“复制路径”“下载文件”），这条测试都会红 —— 而那时的改动是正确的。

**建议**：改成反向断言，锁住真正要防的回归：

```ts
expect(screen.queryByRole("button", { name: /^(确定|Confirm|Run|运行)$/ })).not.toBeInTheDocument();
```

### S3. `_skill_history_turns` 未做防御性收敛

**位置**：`backend/services/nl2skill_service.py` L87-104

三点可加固（都不影响当前正确性）：

1. **未过滤空 content 的条目**：空 assistant 保留是**有意**的（要表达“这轮失败了”），但如果转为 B1 的方案（渲染层过滤），这里的行为就一致了。若保持现状，建议加注释说明“保留空 assistant 是有意的，由渲染层决定是否发出”。
2. **连续同 role 会产生空占位 turn**（见上表第 3、5 行）。虽然 `_convert_history` 已过滤非 user/assistant 角色（L79-84），不会注入 system 指令，但连续 user 仍会造出 `user_message=""` 的 turn。
3. **`user_message_id`/`assistant_message_id` 用负数索引**（`-(index*2+1)`）避免与真实消息 ID 冲突 —— 这个设计是对的，但两个 role 交错的 turn（第 5 行）会出现 ID 不连续，`conversation_turn:{u}:{a}` 的 item id 仍唯一，无碰撞风险。✅

**建议**：至少补一行注释，说明“空内容保留是契约的一部分，不是遗漏”。

### S4. `_decorate_event` 未被本 PR 触及

PR 没改它，但既然在看这条链路：`_decorate_event` 用 `event.get("path", "")` 拼 `block_id`，若 parser 产出缺 path 的 `file_content`，会得到 `block_id="file:"` 这种歧义 ID。属于存量问题，顺便提一句。

---

## 4. 💭 轻微

### M1. `prompt_templates` 的空字符串裸奔

**位置**：`backend/agents/nl2skill_agent.py` L27-34

```python
prompt_templates={
    "system_prompt": "",
    "planning": {"initial_plan": "", "update_plan_pre_messages": "", "update_plan_post_messages": ""},
    "managed_agent": {"task": "", "report": ""},
    "final_answer": {"pre_messages": "", "post_messages": "{{task}}"},
},
```

我核对了这里**不会**踩 `system_sections` 空字典的 KeyError：`AgentPromptBundle._from_compatibility_mapping`（`bundle.py` L77-88）会把 `system_sections` 置为空 `MappingProxyType({})`，而 `render_system_section`（`composer.py` L48-50）会按下标取。但 nl2skill 路径只经过 `_purpose_messages`（`manager.py` L570-591），那里只用 `render_final_answer_pre_message()` / `render_final_answer_post_message()`，**不会**调 `render_system_section`。✅

但 `managed_agent: {"task": "", "report": ""}` 意味着若将来 nl2skill 被用作 managed agent，任务和报告都会被渲染成空串。建议加注释标明“零值模板是有意的：本 agent 从不委派”。

### M2. `{{task}}` 会让 final answer 阶段重复注入完整任务

`final_answer.post_messages = "{{task}}"` 会在生成 final answer 时把完整 task（即渲染后的整个 user_prompt）再作为 user message 发一遍。虽然符合 `schema.py` 的合法变量集（L22 `post_messages: frozenset({"task"})`），但 nl2skill 的 user_prompt 本身就包含完整需求描述，重复一遍会多消耗 token。

对比其他 agent 的 final_answer 模板通常带指导语（“Please provide your final answer…”），这里是裸 `{{task}}`。**如果这是刻意的（避免 final answer 阶段被额外指令干扰输出格式），建议在注释里写明**；否则改成带简短指令的模板更省 token。

---

## 5. 做得好的地方

1. **根因定位准**：三个问题都找到了真正的成因，而不是打补丁。特别是“英文提示词”定位到 `prompt_templates=None` 导致 smolagents 加载默认英文模板，而不是去修 prompt 文本。
2. **模板注入防御想得细**：`instructions`（会被 Jinja 渲染）→ `context_items`（纯文本）的迁移，用测试锁住 `{{ customer_name }}` 字面量存活。这个坑很多人会踩。
3. **`_get_authorized_history(info) == []` 有断言**：防止历史被双写进 `AgentMemory` 和 `context_input`。
4. **`create_nl2skill_agent_config` 加了 fail-fast**：`if not system_prompt.strip(): raise ValueError`，并有参数化测试覆盖 `""` 和 `" \n\t"`。空 prompt 在旧实现下会静默生成一个只有默认英文模板的 agent，现在直接失败 —— 正确的 fail-closed。
5. **prompt hash 基线同步且正确**：我实测了 `sha256sum`，en/zh 两侧的 hash 与 `test/assets/sdk_prompt_migration_hashes.json` 完全一致（`5db65d65...` / `ae963e7e...`），没有出现“改了 prompt 忘了更新 hash”的常见疏漏。
6. **locale key 增删 en/zh 完全对齐**，未出现单侧漏改（这是历史上反复出问题的点）。
7. **commit 拆分清晰**：功能提交 + `fix(skill): align prompt wording and reviewed resource hashes` 单独收尾，第二个提交专门处理 prompt 措辞和 hash，便于 review。

---

## 6. 测试充分性评估

| 测试 | 覆盖 | 评价 |
| --- | --- | --- |
| `test_nl2skill_continuation.py`（新增，48 行） | 9 种 history 形态参数化 + 断言 context 渲染结果 + `_get_authorized_history == []` + system 注入防护 | **思路好，但有过滤漏洞**（见 B1 的“为什么测试没抓到”） |
| `test_nl2skill_prompt.py`（新增，121 行） | zh/en × targeted/full 四象限；用 `importlib.resources.files` 打桩断言“默认模板未被加载”；空 prompt fail-fast；输出契约标签一致性 | **质量很高**。特别是 `default_resources.assert_not_called()` 直接证明了“没有英文默认模板”这个核心主张 |
| `test_nl2skill_service.py`（改 3 行） | `instructions is None` + `context_items[0].content["text"]` | 精准跟随实现变更 |
| `SkillFileCard.test.tsx`（新增，54 行） | md/code × streaming 展开折叠 + 无确定按钮 | 覆盖到位，但有一条断言过严（S2） |
| `SkillCreationReasoningStream.test.ts`（改 32 行） | 新增“失败后继续”用例，断言 `query="继续"` + `history` 只含前两轮 | **这条测试揭示了一个重要契约**：`history` 不包含当前轮的“继续” |

两点观察：

1. **`test_nl2skill_prompt.py` 用真实 `CodeAgent` + 真实 `ContextManager` 而不是 mock**，这让“默认英文模板未加载”这个断言有了实际约束力。这个选择值得推广。
2. **两个 change 记录的 `coverage_gap.description` 写得诚实**：“Existing service UT checks `run_info.history` but not the assembled model messages” —— 准确描述了漏洞位置。但恰恰是这个“assembled model messages”的断言带了 `and text` 过滤，形式上覆盖了、实质上没覆盖。这正是 B1 能逃过 CI 的原因。

---

## 7. 关于“已合入”的处理建议

该 PR 已 squash 进 develop（`377fe37a2`），我的建议是：

1. **B1 单独提 hotfix PR**。优先用方案 b（`_skill_history_turns` 补占位说明），因为它不改 SDK 公共层、风险最低，且与主流程语义统一；方案 a（renderer 空防御）可作为 SDK 侧的独立加固 PR。
2. **B1 的影响范围要先确认**：`conversation_turn` 是公共 ContextItemType，但实际生产者只有三处 —— 主 Agent 聊天（`conversation_db.get_historical_context`，已有占位说明 ✅）、nl2agent（`context.py` fallback，跳过未回答 ✅）、nl2skill（本 PR，**唯一漏洞** ✅ 待修）。所以修复面可控，主要就是 nl2skill 这一条。
3. **S1/S2 可以顺手在同一个 hotfix 里带上**（删两条 locale key、改一条测试断言），成本极低。
4. **S3/M1/M2 留作 follow-up**，不阻塞。
