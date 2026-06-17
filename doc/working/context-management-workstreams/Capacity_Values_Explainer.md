# 容量值全景：从 UI 到 dispatch 的每一个数字到底在算什么

> 受众：模型管理员、Agent 作者、参与 W1/W2/W3 评审的工程师
> 目标：用一篇文档说清楚 Nexent 上下文管理里所有"容量类"数字的物理意义、出处、计算关系
> 关联：W1（容量解析）、W2（输出/安全预算）、W3（dispatch 保障）

---

## 一句话总结

> **上下文窗口 = 输入区 + 输出区**。
> Nexent 在"输入区"上画了两条线：**软线（soft，开始压缩）** 和 **硬线（hard，绝不可越）**。"输出区"由 agent 显式预留，从输入区里"切"出来。所有这些数字都由一条 *override 链* 决定，从模型默认 → 租户 → agent → 单次请求，越靠近请求优先级越高。

---

## 1. 全景图（先看一眼，下面分章节展开）

```
模型上下文窗口 (context_window_tokens)
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│  ┌─────────────────────────────────── ┐  ┌──────────────────────────┐   │
│  │                                    │  │                          │   │
│  │       输入区 = provider_input_limit │  │  输出区 = requested      │   │
│  │       (W1 算出)                    │  │  _output_tokens          │   │
│  │                                    │  │  (W2 决定本轮预留多少)    │   │
│  │  ┌──────────────────────────────┐  │  │                          │   │
│  │  │  uncertainty_reserve         │  │  │  ≤ max_output_tokens     │   │
│  │  │  (CM-016：不确定时多留一笔)    │  │  │   (模型一次回复硬上限)    │   │
│  │  └──────────────────────────────┘  │  │                          │   │
│  │  ┌──────────────────────────────┐  │  │                          │   │
│  │  │ hard_input_budget (W2 红线)   │  │  │                          │   │
│  │  │  ┌──────────────────────────┐ │  │  │                          │   │
│  │  │  │ soft_input_budget (黄线)  │ │  │  │                          │   │
│  │  │  │ = hard × soft_limit_ratio│ │  │  │                          │   │
│  │  │  └──────────────────────────┘ │  │  │                          │   │
│  │  └──────────────────────────────┘  │  │                          │   │
│  └────────────────────────────────────┘  └──────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 来源分类：哪些值在哪里设置 / 算出

### 2.1 模型管理 UI（管理员配置）→ `model_record_t` 列

| UI 标签 | DB 列 | 含义 | 谁负责设 |
|---------|-------|------|---------|
| 上下文窗口 tokens | `context_window_tokens` | 模型一次调用允许的总 token 数（input + output 合计上限） | 模型管理员，从 provider 文档抄 |
| 最大输出 tokens | `max_output_tokens` | 模型一次回复最多输出多少 token（provider 硬上限） | 模型管理员，从 provider 文档抄 |
| 默认输出预留 | `default_output_reserve_tokens` | 当 agent 没配 "输出预留" 时，本模型本轮预留多少 | 模型管理员（可空，留空走 SDK 默认 4096） |
| 最大输入 tokens | `max_input_tokens` | 部分 provider 显式给的 input-only 硬上限（多数模型未公开，留空即可）；如果填了，会再做 `min(max_input, context_window − requested_output)` | 模型管理员（一般留空） |

> **UI 入口可见性**：`maxInputTokens`、`maxOutputTokens` 在 Add / Edit 两种模式都可见；`defaultOutputReserveTokens` **当前只在 Edit 模式渲染**（`ModelCapacityFields.tsx:277` 的 `isAddMode` 分支）。所以新加模型这一列默认 NULL，runtime 走 SDK 4096 默认；要按模型精调，必须先 Add，再 Edit 进去补这一列。这是当前的 UX 折中，W17 会进一步在 catalog 命中时自动 prefill 这个值。

### 2.2 Agent 编辑 UI（Agent 作者配置）→ `agent_t` 列

| UI 标签 | DB 列 | 含义 |
|---------|-------|------|
| 输出预留 | `requested_output_tokens` | 本 agent 每次调用模型时，从上下文窗口里切多少给输出 |

留空 → fallback 到模型的 `default_output_reserve_tokens` → 再 fallback 到 SDK 默认 4096。Form.Item 有条件性 max rule（max = 当前所选模型的 `max_output_tokens`），保存时拦截超限；切换模型时立刻重新校验已填值。

### 2.3 API 请求 body（单次请求覆盖）

调用 `/agent/run` 时 body 可以传 `request_requested_output_tokens` 临时覆盖**这一次**请求的预留。一般给"这次我要个长篇大论"或者"这次只要一句"的临时调整用。

### 2.4 租户配置 → `tenant_config_t`

| 字段 | 含义 |
|------|------|
| `soft_limit_ratio` | 软线占硬线的比例。默认 0.8（CM-027）。调到 0.9 = 留更多输入，压缩更晚触发；调到 0.7 = 提早压缩，更安全 |

### 2.5 W1 ModelCapacityResolver 算出 → `ModelCapacitySnapshot`

| 字段 | 公式 | 含义 |
|------|------|------|
| `provider_input_limit_tokens` | `min(max_input_tokens, context_window − requested_output_tokens)` | 这一次调用允许的输入上限。所有压缩 / 预算都以这个为根 |
| `fingerprint` | SHA-256 over canonical JSON | 整套 W1 状态的指纹，下游 W2/W3 用来检测"被偷偷改了" |

### 2.6 W2 SafeInputBudgetCalculator 算出 → `SafeInputBudgetSnapshot`

| 字段 | 公式 | 含义 |
|------|------|------|
| `uncertainty_reserve_tokens` | 当某些 capability "unknown" 时，按 `provider_input_limit × 10%`（CM-016） | 给"不确定的事情"留的应急空间，避免溢出 |
| `hard_input_budget_tokens` | `provider_input_limit − uncertainty_reserve` | **绝对红线**。超过这里 → provider 报 token overflow |
| `soft_input_budget_tokens` | `floor(hard × soft_limit_ratio)` | **黄色警戒**。到这里 W3 / 上下文管理器开始**主动压缩** |
| `requested_output_tokens` | 来自 override 链（见 §3） | 本轮预留给输出的 token 数 |
| `fingerprint` | SHA-256 包含 `w1_fingerprint` | 整套 W2 状态的指纹；dispatch 时和 W1 配对验证 |

---

## 3. Override 链：`requested_output_tokens` 怎么决定（CM-028）

每次请求只有**一个**最终 `requested_output_tokens` 进入 W2 计算。从高到低：

```
1. 单次请求 body (request_requested_output_tokens)
       ↓ 没传则
2. Agent 列 (agent_t.requested_output_tokens) ← UI "输出预留"
       ↓ 没填则
3. 模型列 (model_record_t.default_output_reserve_tokens)
       ↓ 没填则
4. SDK 默认 (_DEFAULT_REQUESTED_OUTPUT_TOKENS = 4096)
```

**关于 SDK 默认 4096**：早期版本是 1024，太小 —— tool-use agent 一步常常写几百 token 的 JSON tool call 加几百 token 的 thought，1024 经常在 JSON 中间被截断，错误暴露为"工具调用失败"，让运维很难追到根因。4096 覆盖大多数单轮输出；不够再用上面三层 override 覆盖。

**关于 model_record_t.default_output_reserve_tokens（第 3 层）的 UI 入口**：
- **Add 模式**：当前**不渲染**该字段，新加模型这一列会是 NULL，runtime 会一路 fallback 到第 4 层（4096）
- **Edit 模式**：渲染该字段；管理员可手填具体值
- 后果：新加的模型如果不再回 edit 面板补一刀，永远走 4096 默认；这对多数场景够用，但写报告 / 长代码 / 复杂表格类 agent 仍可能截断 —— 建议管理员在 edit 模式按模型实际 max_output_tokens 配一个合适值（一般取 `max_output / 2` 或 `max_output` 本身）

**校验**：最终值必须满足 `0 < requested ≤ max_output_tokens`。超过 → 抛 `RequestedOutputExceedsCap`，dispatch 失败。

**UI 防线**（两端都有）：
- Agent 编辑面板的"输出预留" Form.Item 启用条件性 max rule（max = 当前所选模型的 `max_output_tokens`），保存时拦截违例；切换模型时立即重新校验已填值
- 后端 `_validate_requested_output_tokens_for_agent` 在 API 保存 agent 时也独立校验，作为 defense-in-depth

`soft_limit_ratio` 也有类似 override 链：单次请求 body > tenant_config_t > 默认 0.8。

---

## 4. 端到端三个例子

### 例 1：标准配置，无 agent override

**模型**（glm-5）：context_window=128000, max_output=8192, default_reserve=8192
**Agent**："输出预留" 留空
**Tenant**：默认 soft_limit_ratio=0.8
**单次请求**：没传 override

```
requested_output_tokens = 8192     ← 模型 default_reserve
provider_input_limit    = 128000 − 8192 = 119808
uncertainty_reserve     = 119808 × 10% = 11980 ≈ 12800（向上对齐到 256 倍数，举例）
hard_input_budget       = 119808 − 12800 = 107008
soft_input_budget       = floor(107008 × 0.8) = 85606
```

观察：上下文累积到 ~85K → 开始压缩；硬线 107K；模型每次回最多 8K。

### 例 2：Agent 想要长回复

**模型**（gpt-4.1）：context_window=1000000, max_output=32768, default_reserve=8192
**Agent**："输出预留" 填 16384
**Tenant**：默认 soft_limit_ratio=0.8

```
requested_output_tokens = 16384    ← agent override 拿到，且 ≤ max_output(32768) ✓
provider_input_limit    = 1000000 − 16384 = 983616
uncertainty_reserve     = 0（这个模型 capability 全已知，CM-016 不触发）
hard_input_budget       = 983616
soft_input_budget       = floor(983616 × 0.8) = 786892
```

观察：模型可以写到 16K 长回复；输入到 786K 才开始压；hard 几乎拉满。

### 例 3：Agent 配置超限（UI 保存时拦下）

**模型**（glm-5）：context_window=128000, max_output=8192
**Agent**："输出预留" 填 16384（**超过模型 8K 上限**）

```
点保存
  → Form.Item 条件性 max rule 触发（max=8192）
  → InputNumber max=8192 同步拦截
  → 显示 i18n 错误："输出预留不能超过该模型的最大输出 tokens（8192）"
  → 表单不提交，agent 不会保存进入运行
```

修法：把 agent "输出预留" 调回 ≤ 8192；如确实需要长回复，管理员去模型管理把 `max_output_tokens` 调大（前提是 provider 实际支持）。

> 历史背景：早期版本 UI 不做这条校验，违例 row 能保存到 DB，runtime 才在 `capacity_resolver.py:280` 抛 `RequestedOutputExceedsCap` —— 表现为"agent 莫名其妙不回话"。当前版本前端 + 后端 `_validate_requested_output_tokens_for_agent` 双重防护，已不会出现这种隐蔽失败。

### 例 4：裸模型 fallback

**模型**（某裸 row）：context_window=NULL, max_output=NULL
**Agent**：任意配置

```
resolve_capacity() → ProviderCapabilityUnknown
W1 ModelCapacitySnapshot = None
W2 SafeInputBudgetSnapshot = None
context manager 使用 _TOKEN_THRESHOLD_LEGACY_FALLBACK = 32768 作为压缩阈值近似
dispatch 时 CM-030 不生效（没有 W2 snapshot 强制 max_tokens）
后端日志输出一条 operator-friendly WARNING（每进程每模型一次）
```

修法：模型管理 UI 给这个模型补 capacity；W17 会用 badge 让这种 row 可见。

---

## 5. 边界与陷阱速查

| 现象 | 原因 | 解法 |
|------|------|------|
| Agent 编辑 UI："输出预留不能超过该模型的最大输出 tokens（X）" | 当前所选模型 `max_output_tokens` < 你填的值 | 调小预留；或换模型；或管理员调大模型的 max_output |
| 模型管理 UI："最大输入 Token 数不能超过上下文窗口" | `max_input_tokens > context_window_tokens` 时静默被 min() 钳掉，且管理员的 override 不生效 | 把 max_input 调到 ≤ context_window；多数模型留空即可 |
| 模型管理 UI："最大输出 Token 数不能超过上下文窗口" / "输出预留 Token 数不能超过最大输出 Token 数" | 字段之间存在不一致 | 按提示调整对应字段 |
| `W2 uncertainty reserve active` WARNING 持续出现 | 模型 capability 某些字段标记 unknown（典型：`max_input_tokens`、tokenizer_family 缺失） | 不必处理；CM-016 设计：宁愿保守也不溢出 |
| 后端日志：`Output token cap ... not enforced for model 'X'` | 模型 row 是裸 capacity（NULL） | UI 编辑该模型填上下文窗口 + 最大输出 |
| 前端 indicator 显示 `XX/32k*`，星号 | 后端没发 `token_threshold`（snapshot 路径不通） | 同上：补 capacity；或确认 W2 链路 |
| `soft_input_budget` 看起来比想象的低 | `soft_limit_ratio` 被租户调低（< 0.8） | 看 `tenant_config_t.soft_limit_ratio`；想激进就拉到 0.9 |
| 模型回复总是被截断（输出半句话 / JSON 半截） | `requested_output_tokens` 太小（fallback 到 4096、或 model default 配小了、或 agent 显式设了小值） | 优先：agent 编辑设大"输出预留"；其次：管理员去模型 edit 给 `default_output_reserve_tokens` 填合理值；单次需要长输出可以 API body 临时覆盖 |
| 新加模型的 agent 输出经常 4K 截断 | Add 模式不渲染 `defaultOutputReserveTokens` → DB 这一列 NULL → fallback 到 4096 | 去模型 edit 模式补 `default_output_reserve_tokens`；或等 W17 catalog 自动 prefill |
| 上下文还有很多空间但已开始压缩 | `hard - soft` 间距 = 20%（默认）正在工作 | 这是设计；不想压可调高 ratio |

---

## 6. 名词缩写对照

| 缩写 | 全名 | 含义 |
|------|------|------|
| W1 | Workstream 1 | 模型容量解析，输出 `ModelCapacitySnapshot` |
| W2 | Workstream 2 | 输出 + 安全输入预算，输出 `SafeInputBudgetSnapshot` |
| W3 | Workstream 3 | dispatch 时强制按 W2 snapshot 调用 LLM |
| CM-013 | Context-Management Finding 013 | 可信 dispatch 边界：缺失 / 过期 / 篡改 → fail closed |
| CM-016 | Context-Management Finding 016 | capability 不全时按 10% 预留 uncertainty buffer |
| CM-027 | Context-Management Finding 027 | `soft_limit_ratio` 默认 0.8，租户可覆盖 |
| CM-028 | Context-Management Finding 028 | 输出预留两层 override（agent 列 + 请求 body） |
| CM-029 | Context-Management Finding 029 | 每个模型一份 W1→W2 snapshot 链（不可跨模型借用） |
| CM-030 | Context-Management Finding 030 | dispatch 把 W2 `requested_output_tokens` 作为 `max_tokens` 的唯一来源 |
| CM-031 | Context-Management Finding 031 | `model_factory='OpenAI-API-Compatible'` 是默认值，catalog 命中率低 |

---

## 7. 一图记住整条链

```
   provider 文档                    租户配置                    Agent 配置                  本次请求
        │                              │                              │                          │
        ▼                              ▼                              ▼                          ▼
context_window_tokens            soft_limit_ratio          requested_output_tokens     request body override
max_output_tokens                                            (UI: "输出预留")           (CM-028 顶层)
default_output_reserve_tokens                                                               
        │                              │                              │                          │
        └────────────► W1 resolve_capacity ────────────► ModelCapacitySnapshot              │
                                       │                              │                          │
                                       ▼                              ▼                          ▼
                                       └────────► W2 SafeInputBudgetCalculator ◄────────────────┘
                                                                      │
                                                                      ▼
                                                          SafeInputBudgetSnapshot
                                                          (hard / soft / requested_output / fingerprint)
                                                                      │
                                                                      ▼
                                                            W3 dispatch
                                                          (CM-030 强制 max_tokens = requested_output)
                                                          (CM-013 验证 fingerprint 链)
```
