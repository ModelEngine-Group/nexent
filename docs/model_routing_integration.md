# Nexent 多模型任务路由组件 — 技术总结与生产集成指南

> 版本：v2.0（收敛版）｜ 日期：2026-11-11 ｜ 基线：nexent develop 分支（0f3a813）
> 参考实现：openjiuwen `intelli_router`（Deployment/TagBasedStrategy/ReliableRouter 分层模式）
> v2.0 变更：按社区贡献审查意见收敛 —— 显式启用开关、医疗词表外置为示例配置、
> DEFAULT 语义修正（无信号保持原选择）、fallback_from 审计、输入容量口径修正、
> 移除被证伪的 context_policy 载体（其 extra="forbid" 不接受额外键）。

---

## 1. 功能概述

为 nexent Agent 平台新增**按任务意图自动分流的多模型路由能力**。每次 Agent 运行时，根据用户查询内容与 Agent 声明的任务标签，将请求自动路由到该 Agent 模型池中最合适的一个模型。

支撑三类服务分层（可映射到异构算力部署）：

| 分层 | RouteTier | 典型场景 | 模型示例 |
|---|---|---|---|
| 快问服务 | `quick_qa` | 指标查询、术语翻译、简短事实问答 | Qwen3-30B（非思考） |
| 长文服务 | `long_context` | 病历归纳、出院小结处理、长文献分析 | Qwen3.6-35B（长窗口） |
| 深度推理 | `deep_reasoning` | 鉴别诊断、MDT 多学科会诊、方案比较 | DeepSeek-R1 |

附加治理能力：

- **风险优先**：命中高风险医疗词汇（手术/化疗/剂量…）且需要分析时，强制升级到最强推理层，并打 `review_required` 标记供下游临床复核流程使用
- **全程可追溯**：每次决策输出结构化审计日志（分层来源、命中规则、候选评分、所选模型）
- **零配置分层**：直接复用 `model_record_t` 已有能力字段判定模型分层，无需运维额外维护映射表
- **权限不越界**：路由严格限定在 Agent 自己配置的 `model_ids` 池内，显式指定的 model_id 永远优先于路由

---

## 2. 修改文件清单

| # | 文件 | 状态 | 说明 |
|---|---|---|---|
| 1 | [backend/management/services/model/routing.py](../backend/management/services/model/routing.py) | **新增** | 通用路由引擎：规则加载 + 分类 + 评分 + 降级 + 审计（领域无关，词表全部来自配置） |
| 2 | [backend/configs/model_routing_rules.json](../backend/configs/model_routing_rules.json) | **新增** | 路由规则示例配置（当前为医疗词表，可整体替换为其他领域） |
| 3 | [backend/management/services/agent/preparation/compiler.py](../backend/management/services/agent/preparation/compiler.py) | **修改** | 接线：`MODEL_ROUTING_ENABLED` 门控 + `_route_agent_model`；`create_agent_config` 新增 `run_history_length`/`run_has_attachments` 可选参数 |
| 4 | [backend/management/services/agent/preparation/run.py](../backend/management/services/agent/preparation/run.py) | **修改** | +2 行：传递真实 history 轮数与附件标记 |
| 5 | [backend/contracts/constants/environment.py](../backend/contracts/constants/environment.py) | **修改** | +5 行：`MODEL_ROUTING_ENABLED`（默认 false）与规则文件路径常量 |
| 6 | [test/backend/services/test_model_task_routing.py](../test/backend/services/test_model_task_routing.py) | **新增** | 43 个单元测试（规则加载/分类/评分/降级/审计/契约锁定） |
| 7 | [test/backend/agents/test_create_agent_info.py](../test/backend/agents/test_create_agent_info.py) | **修改** | 4 处精确调用断言补充新 kwargs |
| 8 | [test/backend/management/test_service_directory_architecture.py](../test/backend/management/test_service_directory_architecture.py) | **修改** | +1 行：架构守护白名单登记 `model/routing.py` |

无数据库迁移、无前端改动、无 SDK（sdk/nexent）改动、无既有 HTTP 契约变更。

---

## 3. 核心逻辑解读

### 3.0 行为契约（v2.0 收敛定稿）

1. **显式选择永远赢**：请求带 `model_id` 时路由不介入，选中模型与 v1 之前完全一致
2. **默认关闭**：`MODEL_ROUTING_ENABLED=false`（默认）时路由代码路径整体跳过，行为与未引入路由的版本逐字节一致
3. **池内选择**：只在 Agent 已配置且租户可用（`connect_status=Available`）的模型中选择
4. **无信号不换模**：分类结果为 DEFAULT（无任何规则命中）时返回 None，保持原选择 —— 路由永远不因"猜测"而改变模型
5. **无候选不失败**：目标分层无可用模型且降级穷尽时返回 None，保持原选择 —— 路由永远不让运行失败
6. **回退可追踪**：发生分层降级时 `fallback_from` 记录原目标层，`matched_rules` 追加 `relax:<tier>`
7. **同分稳定**：评分相同的候选按输入顺序稳定排序（Python sort 稳定性），同池同配置下决策可复现

### 3.1 数据流总览

```
AgentRequest（query, model_id?, history, minio_files…）
        │
        ▼
create_agent_run_info (run.py)
        │  model_list = create_model_config_list(tenant_id)   ← 租户全量 LLM
        │  create_config_kwargs += run_history_length / run_has_attachments
        ▼
create_agent_config (compiler.py)
        │
        │  ① _select_agent_model_id(agent_model_ids, override_model_id, tenant_id)
        │       ├─ override_model_id 非 None → 直接用它（显式选择，路由不介入）
        │       └─ 否则 → Agent.model_ids 中第一个可用模型（既有逻辑，保底）
        │
        │  ② MODEL_ROUTING_ENABLED ∧ override 缺省 时 → _route_agent_model(...)  ← 新增
        │       ├─ 收集 Agent.model_ids 池内可用记录（is_model_available 过滤）
        │       └─ route_model_selection(候选记录, query, history_length, has_attachments)
        │               ├─ load_rules()        ← configs/model_routing_rules.json
        │               ├─ classify_run()      → ClassificationResult
        │               ├─ DEFAULT 来源 → 返回 None（契约 4）
        │               ├─ rank_candidates()   → ([(record, score)], fallback_from)
        │               └─ 空 → 返回 None（契约 5）；否则 (最佳记录, RoutingDecision)
        │
        ▼
AgentConfig.model_name = 选中模型的 display_name
        │                        （SDK 按 cite_name 取用，零改动）
        ▼
NexentAgent.create_model → OpenAIModel(api_base, api_key, …)
```

关键性质：
- **路由只在"开关开启 ∧ 未显式指定模型"时介入**（[compiler.py:608-621](../backend/management/services/agent/preparation/compiler.py#L608)）
- **候选池 = Agent 自己的 model_ids**，与现有权限校验 `validate_agent_model_selection` 的边界一致
- 开关关闭 / 单模型池 / 无信号 / 无候选四种情况下自动回退原行为，**对存量 Agent 零影响**

### 3.2 分类规则引擎（classify_run）— 领域无关

判定优先级（高→低）：

```
1. 显式任务标签   task_tag 命中规则文件 task_tags 映射 → 直接定层（来源=explicit_tag）
2. 风险升级       高风险词汇 ∧ 分析词汇 → deep_reasoning + review_required=True
3. 长上下文       估算 token ≥ 阈值 或 字符数 ≥ 阈值 或命中长文词汇
                  （长文优先于推理：截断是比弱推理更硬的失败）
4. 深度推理       命中分析/推理词汇
5. 快问           命中查询词汇 或（非空且 ≤ char_limit）
6. 兜底           无任何信号 → DEFAULT 来源 → 调用方保持原选择
```

**词表、阈值、标签映射全部来自 `configs/model_routing_rules.json`**（`MODEL_ROUTING_RULES_JSON_PATH` 可覆盖路径）；文件缺失/损坏时降级为空词表默认值 —— 引擎本身不含任何医疗词汇，换领域只需换配置文件。

token 估算：CJK ≈1 token/字、其他 ≈4 字符/token；history 按配置每轮加成（默认 200）、附件按配置加成（默认 800）。

### 3.3 模型分层判定（record_tier）— 零配置设计

复用 `model_record_t` 运维已验证的字段，判定优先级：

```
reasoning_supported == true 或 enable_thinking == true   → deep_reasoning
输入容量 ≥ 48000（先 max_input_tokens，后 context_window_tokens）→ long_context
名称启发式：reason / think / -r1 / o1 / o3               → deep_reasoning
           long / long-context                           → long_context
其余                                                      → quick_qa
```

容量口径（v2.0 修正）：路由守护**输入侧**，优先用 `max_input_tokens`（provider 硬输入上限），其次合并窗口；输出预留由既有 context budget 模块负责，不重复计算。

### 3.4 候选评分与降级（score_candidate / rank_candidates）

同层候选打分：

```
score = 1.0
      + min(容量余量/8, 0.5)      # headroom = 容量/估算token，越大越好
      + 0.2                       # deep 层且 enable_thinking=true
```

硬性排除（score = -1）：
- 分层不匹配的候选
- 已知输入容量 < 估算 token 的候选 —— **保证路由永不选中会截断请求的模型**

降级链（某层无可用模型时）：

```
quick_qa → long_context → deep_reasoning
（fallback_from 记录原目标层；穷尽后返回 None 保持原选择）
```

### 3.5 审计与可追溯（RoutingDecision）

每次实际发生的路由输出一条结构化日志（`logger.info("Model routing decision: %s", …)`）：

```json
{
  "agent_id": 42,
  "tier": "deep_reasoning",            // 目标分层
  "source": "rule",                    // explicit_tag | rule（default 不产生决策）
  "risk": "high",
  "review_required": true,             // 下游复核流程的输入标记
  "est_tokens": 1834,
  "matched_rules": ["deep:鉴别诊断", "risk:escalate_deep"],
  "selected_model_id": 12,
  "selected_display_name": "DeepSeek-R1",
  "candidates": [{"model_id": 12, "tier": "deep_reasoning", "score": 1.2}],
  "fallback_from": null,               // 降级时为原目标层，如 "quick_qa"
  "reason": "tier=deep_reasoning source=rule"
}
```

### 3.6 接线点详解（compiler.py / run.py 改动）

- [compiler.py:598-621](../backend/management/services/agent/preparation/compiler.py#L598)：选择流程改为「显式覆盖 →（开关开启时）路由 → 保底」；路由结果复用记录容量字段，无二次 DB 查询
- [compiler.py:797-835](../backend/management/services/agent/preparation/compiler.py#L797)：`_route_agent_model` —— 池内候选收集 + 调用路由服务；延迟 import 遵循仓库惯例
- [compiler.py:71-96](../backend/management/services/agent/preparation/compiler.py#L71)：`create_agent_config` 新增 `run_history_length=0` / `run_has_attachments=False` 可选参数（默认值向后兼容，两处子 Agent 递归调用透传）
- [run.py:210-214](../backend/management/services/agent/preparation/run.py#L210)：传递真实 history 轮数与附件标记
- `route_model_selection` 返回 `(record, decision)` 元组，**不污染输入 record**（测试锁定）

---

## 4. 测试用例解读

[test_model_task_routing.py](../test/backend/services/test_model_task_routing.py) — 43 个用例，7 组：

| 组 | 用例数 | 覆盖点 |
|---|---|---|
| `TestRulesLoading` | 5 | 文件缺失降级空词表、示例配置可加载、损坏 JSON 降级、缓存重置后重读 |
| `TestEstimateTokens` | 4 | 空文本、CJK 1:1、ASCII 4:1、history/附件加成 |
| `TestClassifyRun` | 13 | 显式标签最高优先、未知标签落规则引擎、风险升级+强制复核、高风险无分析不升层、按体量判长文、长文压过推理、推理/快问关键词、短问兜底、**无信号 DEFAULT**、**空词表 DEFAULT**、空查询安全、非法标签映射忽略 |
| `TestRecordTier` | 5 | reasoning 标志、**输入上限优先于合并窗口**、容量阈值、名称启发式、reasoning 压过容量 |
| `TestScoreAndRank` | 6 | 异层不可选、同层余量优先、容量不足硬拒绝、降序+无降级标记、**降级记录 fallback_from**、穷尽降级返回空 |
| `TestRouteModelSelection` | 7 | 决策元组完整、空池 None、**DEFAULT 保持原选择（向后兼容契约锁定）**、短问正常路由、穷尽降级 None、**快问→长文降级审计**、不污染输入 |
| `test_task_tag_mapping`(参数化) | 4 | 代表标签到分层映射 |

设计要点：
- **契约锁定**：`test_default_source_keeps_existing_selection` 与 `test_fallback_from_is_audited` 把 §3.0 契约 4/5 固化为回归 —— 这两条是社区审查最关心的向后兼容语义
- **通用性证明**：`test_empty_vocabularies_fall_to_default` 证明引擎在零词表下正确退化为"永不路由"，医疗词表确实只是配置
- 测试数据 `_record()` 工厂模拟 `model_record_t` 行结构，无需 DB fixture；`_isolated_rules` fixture 保证规则缓存测试隔离

### 集成测试

- `test_create_agent_info.py`（253 用例）：`create_agent_config` 全链路，4 处精确调用断言已补新 kwargs，全绿
- 基线 diff 对比（stash 前后同测试集）：失败集合与基线**完全一致**，零新增失败
- 架构守护 + contracts 守护：14 passed
- 版权头检查 6 文件：OK

---

## 5. 生产环境集成步骤

### 阶段一：部署前确认（运维）

1. **版本基线**：确认部署的 nexent 代码包含本变更（文件清单见 §2）
2. **无需数据库迁移**：所有判定复用 `model_record_t` 既有列；若列值为 NULL，`record_tier` 自动落到名称启发式
3. **路由默认关闭**：部署后行为与升级前完全一致；确认 `MODEL_ROUTING_ENABLED` 未设置（或为 false）
4. **规则文件**：确认 `backend/configs/model_routing_rules.json` 随镜像发布（缺失时引擎降级为空词表 = 永不路由，安全但无功能）；医疗以外领域替换该文件内容即可

### 阶段二：模型池配置（管理员，管理界面操作）

为需要路由的 Agent 配置**多模型池**（Agent 编辑页 → 模型选择，最多 5 个）：

1. 确保租户模型列表中各分层模型已配置且**连通性检测为 Available**（`connect_status` 驱动 `is_model_available`，不可用模型自动退出候选）
2. 建议按能力如实填写模型记录字段（添加/编辑模型时）：
   - 推理模型：`reasoning_supported = true`（或 `enable_thinking = true`）
   - 长文模型：`context_window_tokens`（或 `max_input_tokens`）填真实值 ≥ 48000
   - 这些字段同时被容量预算模块（run_budget）使用，填写准确一举两得
3. 为目标 Agent 勾选池内多个模型（如：快问模型 + 长文模型 + 推理模型）
4. （可选）领域任务标签：在**规则文件**的 `task_tags` 节维护 `标签 → 分层` 映射（当前示例含 `mdt`/`summary`/`quality_check` 等通用标签）；per-Agent 的显式标签载体（Agent 配置界面/字段）需先与社区确认配置契约，见 §6.2

> 未配置多模型的 Agent 行为不变：单模型池无路由空间；开关关闭时一切如旧。

### 阶段三：验证（灰度）

1. **单元回归**（部署机或 CI）：
   ```bash
   pytest test/backend/services/test_model_task_routing.py -v
   pytest test/backend/management/test_service_directory_architecture.py -v
   ```
2. **冒烟验证**（管理服务启动后）：
   - 用配置了多模型的 Agent 发送三类查询，观察 management 服务日志中的 `Model routing decision` 行：
     - 短查询（如 "CRP 的正常值"）→ `tier=quick_qa`
     - 粘贴长病历并要求归纳 → `tier=long_context`
     - "请分析该患者的鉴别诊断" → `tier=deep_reasoning`
   - 核对 `selected_model_id` 与 `candidates` 评分符合预期
   - 在前端会话里确认实际回答的模型行为一致（可在模型服务侧看请求落点）
3. **显式选择优先级**：请求带 `model_id` 时确认日志**无** `Model routing decision`（路由未介入）

### 阶段四：监控与审计接入

- **路由审计**：采集 management 服务中 `Model routing decision` 结构化日志，接入现有日志平台（如 ELK）。关键字段告警建议：
  - `review_required=true` 的高风险运行量（供临床质控报表）
  - `fallback_from` 或 `matched_rules` 含 `relax:` 的比例 —— 持续偏高说明某分层容量不足，需扩池
- **容量阈值**：`est_tokens` 接近所选模型容量的运行占比（容量规划输入）

### 回滚方案

改动为纯增量逻辑：删除/回退 2 个 backend 文件改动即恢复原行为（`_select_agent_model_id` 原路径完整保留）。路由不写库、不改请求契约、无缓存状态，回滚无副作用。

---

## 6. 已知边界与后续扩展点

### 6.1 可调参数

| 参数 | 位置 | 默认值 | 含义 |
|---|---|---|---|
| `MODEL_ROUTING_ENABLED` | 环境变量 | `false` | 路由总开关（默认关闭，行为与历史版本一致） |
| `MODEL_ROUTING_RULES_JSON_PATH` | 环境变量 | `configs/model_routing_rules.json` | 规则文件路径 |
| `long_context.token_threshold` | 规则文件 | 24000 | 估算 token 判长文阈值 |
| `long_context.char_threshold` | 规则文件 | 8000 | 字符数判长文阈值 |
| `quick_qa.char_limit` | 规则文件 | 120 | 短查询判快问上限 |
| 各层 `terms` / `risk.*_terms` / `task_tags` | 规则文件 | 医疗示例 | 领域词表与标签映射 |
| `history_tokens_per_turn` / `attachment_tokens` | 规则文件 | 200 / 800 | 估算加成 |
| 评分权重（headroom/8 封顶 0.5、thinking +0.2） | routing.py 常量 | — | 同层候选偏好（代码内，改动需发版） |

### 6.2 后续扩展方向（按社区贡献路径推进）

1. **Feature Issue 先行**：以通用问题表述（"Agent 配置多模型后按任务与输入规模选择合适模型，保留显式指定优先级"）发起方向讨论，附前后行为示例；确认配置位置（per-Agent 标签的载体）、启用方式（现环境变量，可讨论租户/Agent 级开关）、扩展接口
2. **per-Agent 任务标签**：`context_policy` 被 `PolicyLayers(extra="forbid")` 校验（sdk policy.py:23），不能承载 task_tag；需在 Issue 中定载体（候选：Agent 表新列 / metadata 字段 / 标签实体）
3. **能力组合而非互斥分层**：现版 tier 互斥（推理模型兼任长文时被排除）；演进方向是"先过滤容量/模态硬条件，再按任务偏好评分"——已被审查标识为 v1 设计约束
4. **review_required 贯通前端**：decision 挂 run 元数据，会话接口透出复核标记（当前仅审计日志）
5. **RPM/并发感知**：`concurrency_limit` 列已存在，可加实时余量权重（参考 openjiuwen AdaptiveStrategy）
6. **失败冷却**：叠加 openjiuwen ReliableRouter 式冷却状态（nexent SDK retry.py 已有错误分类）
7. **LLM 辅助分类**：规则未命中时小模型兜底分类（参考 automation/intent.py 的工厂模式）

### 6.3 环境已知问题（非本变更引入，基线复现）

- `test_run_model_control_boundaries.py` 与 `test_agent_run_model_controls.py` 同跑时 3 例因 import 污染失败（单跑通过）
- `test_create_agent_info_workbench_coverage.py` 7 例失败（基线一致）
- `test/backend/agents/` 下 6 个文件 collection error：本地 `uv sync` 安装的 nexent 包与仓库 sdk/ 版本不匹配；以可编辑方式安装 `sdk/` 可解决
- 以上均已用 `git stash` 基线对比确认与本变更无关

---

## 7. 快速参考

```bash
# 跑路由单元测试
pytest test/backend/services/test_model_task_routing.py -v

# 冒烟观察路由决策
# （management 服务日志）
grep "Model routing decision" <management-service.log>

# 为 Agent 声明任务标签（DB 或管理界面，context_policy JSONB）
{"task_tag": "medical_summary"}
```

核心文件入口：
- 路由服务：`backend/management/services/model/routing.py`（`classify_run` / `rank_candidates` / `route_model_selection`）
- 接线点：`backend/management/services/agent/preparation/compiler.py` → `_route_agent_model`
