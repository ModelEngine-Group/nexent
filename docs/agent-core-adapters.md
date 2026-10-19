# 可选 Agent Core：接入与验证说明

## 2026-10-16 当前接入方式（M6）

Nexent 继续保存智能体配置，Factory 选择 Jiuwen Adapter，Jiuwen Runner 负责推理循环。模型统一经 ModelService 发送；原生工具调用和受控文本协议共用授权资源入口，不运行 CodeAgent 循环。

- 依赖固定 `openjiuwen==0.1.19`；SDK 安装 `nexent[jiuwen]`。公共模型服务集成至固定 6dc5ed0bb 基线的必要增量，不表示重新核验了 Jiuwen 最新发布。
- 原生/text 均支持已授权工具、MCP、Skills 和显式 parallel；文本执行使用现有 Python/沙箱及远端回调上下文。MCP 的保存参数、隐藏身份、超时/会话所有权沿用 Nexent；Skills 按 root+name 白名单读取，脚本运行在配置指定的后端。
- 页面切换 Core 只修改 core，保留工具、MCP、Skills、协作绑定、模型和所有策略值。Jiuwen 不支持的选项仍禁用编辑并在运行前明确拒绝；需要先在 smolagents 下关闭尚未支持的能力，再运行 Jiuwen。
- 子智能体逐调用经工厂选择自身 Core，按自身版本绑定模型出口/参数；Jiuwen↔smolagents 和 Jiuwen→Jiuwen 已验证。A2A 复用现有代理，每调用独立客户端并传递可信身份，远端自行选择其 Core/模型。页面允许 Jiuwen 编辑协作绑定。
- CM 复用现有 ContextManager，遵循保存开关与预算；配置页变更 Core 并按既有发布流程生效后，原会话可重开续聊，历史工具/附件作为只读事实，已有摘要仍可加载。仍未支持 Planning、运行总结、协议修复、校验/护栏及 provider prompt-cache 策略；公共 StepObservation/RunResult 已接入实时与历史展示，工具/结果、显式推理、子调用分组和失败/停止保留真实状态；终答仅由明确终态确认。保留绑定不表示已实现执行，不静默切回其他 Core。
- 完整可信 `ResolvedModelProfile` 在管理侧保存，运行时恢复、验证并按请求预算生成独立快照；不按别名猜出口，不在运行时重新读 catalog，不走原生 HTTP。凭据只按 tenant/出口引用捕获，不进入模型资源视图。

M5 本地验证：515 项 Python UT、16 项前端组件、8 个正式 Case / 54 项检查通过。复用 SSE 与数据库执行单元，刷新后不按当前 Core 猜测旧输出；失败/停止保留过程，A2A 不虚构远端步骤。实际框架/资源/隔离数据库和受控 API 浏览器分别证明执行与展示，不等同于已部署的商业模型验收。证据见原 SPEC task.md 的 M5 历史记录；当时待实施的 AC-018 已在下述 M6 完成。

M6 已部署并通过选定真实出口：DeepSeek 原生工具协议、Qwen 受控文本协议，工具/MCP/Skills、两种子 Core 与 A2A 均完成实际执行桥验证。固定参数纠正每步骤 1 次/每轮 3 次（含已知 code 参数错误），空/仅推理/length 每轮 1 次；物理重试仍归 ModelService。原 Code 协议修复开关继续按 Jiuwen 能力校验。失败不切模型/Core，坏块不执行，历史任务不重放。

数据库在事务锁中分配用户/助手序号，空客户端历史也能从原会话续聊；私有运行边界不改变 HTTP schema。M6 862 项 Python UT、16 项前端组件和 10 个正式 Case / 72 项检查通过；真实模型与受控资源、浏览器受控 API 的边界详见原 SPEC task.md。应用访问 `http://localhost:3000`，镜像使用 `jiuwen-m6-20261016` 标签。全局正式资产门禁仍被既有 F-111-RULE-02 引用阻塞。

### 统一输出与原有会话页面（2026-10-16）

不同Core输出在 `frontend/lib/nexentOutputAdapter.ts` 统一转换为原有Nexent事件，然后进入原有实时/历史解析器。页面使用同一套Reasoning、ToolFallback、Markdown和SubAgentContainer，不按Core选择渲染器；已移除M5的runtime-output专用路径。历史记录按自身保存的协议解析，智能体切换Core后仍可加载旧记录。

工具/MCP/Skills映射原工具卡，子智能体/A2A沿用原分组；只有封口后的成功终态生成终答，失败/停止保留partial。token用量绑定本条消息，未知显示未知，不借用其他轮计数。新Core需在执行端满足公共事实合同；其注册与配置校验仍独立适配。

本轮Web已部署 `nexent/nexent-web:jiuwen-unified-ui-20261016`，后端保持jiuwen-image-20261016。63项前端UT、TypeScript及定向lint通过，既有D3/D5回归和最终部署上的固定浏览器旅程通过；真实后端旧历史加载/刷新通过，未触发新Agent运行。标准prepared入口/全局资产门禁仍被既有F-111-RULE-02缺失引用阻塞，不声明完整发布门禁通过。完整证据见原SPEC新增UO记录。

### 共享容量展示补齐（2026-10-19）

Jiuwen公共StepObservation.context_capacity现从已有ContextManager读取容量、阈值、有效输入上限和处理模式，经Observer及共用输出Adapter映射到原token_count。CM关闭仍保留容量，原用量百分比/详情组件无需Core分支。旧历史缺字段时保留未知，不用当前模型值回填。

main/Web已部署jiuwen-capacity-20261019。108项Python UT、43项前端UT及既有D3/D5回归通过；文件解析助手8轮真实业务验证覆盖两Core、CM开关和刷新，窗口/阈值与用量形式一致。正式D4仍因AIDP列表502为FAIL，prepared入口仍有F-111引用阻塞；详见原SPEC容量补齐记录，不宣称完整发布通过。

### 升级与存量出口回填

1. 核对现有 Core 字段迁移记录；已应用的 v2.7.2_1010 不重复执行，不改旧 SQL。
2. 部署代码前应用新增 [模型快照迁移](../deploy/sql/migrations/v2.7.2_1015_runtime_outlet_snapshot.sql)。它只加过渡 JSONB 字段，保留旧模型 API/列。
3. 在配置好后端数据库连接的部署环境使用 Python 3.11 执行 `backend/scripts/migrate_runtime_outlets.py --tenant-id <tenant>`，默认 dry run；确认结果后加 `--apply` 写入。失败项不能作为可运行的 Jiuwen 出口；重复 apply 对未变化档案幂等。
4. 后续模型管理保存、健康检查和租户默认模型写入会在同一事务维护快照。普通修改按冻结声明校验、行锁合并和递增 revision。旁路修改旧列使档案陈旧时，Jiuwen 提前拒绝，需要通过管理保存或迁移修复。

M4 本地验证：753 项 Python UT、4 项前端组件、10 个正式 Case / 54 项测试通过；包含真实隔离 PostgreSQL 的双向配置 Core 变更、长历史摘要、CM 开关、故障/取消恢复和浏览器旧会话续聊。完整发布工作流及商业模型验证不在本轮证明范围；显式版本绑定不改写，未部署。证据见原 SPEC task.md 的 M4 记录。

上轮已在隔离 PostgreSQL 验证迁移、回填、并发和回滚。本轮完成 853 项 Python UT、4 项前端组件回归和 7 个正式 Case / 39 项检查，含混合 Core、子工具授权隔离、A2A、取消/超时/容量耗尽恢复与页面协作编辑。文本父子同时执行需要相应 sandbox worker 容量；协作排队和执行受有限总 deadline 控制。未修改现有应用数据库、未重建部署容器；具体证据与边界详见原 SPEC task.md。全局资产门禁仍被既有 F-111-RULE-02 引用阻塞；不声明全局通过或真实商业模型验收完成。

---

## 以下为首版历史说明（不作为当前启用操作）

## 本次实现

Nexent 继续保存智能体、模型、工具、MCP 和 Skills 配置。执行时，`AgentCoreFactory` 根据 `agent_core` 创建 Adapter，由 Adapter 编译配置并执行所选 Core。

```text
Nexent 配置 → AgentCoreFactory → AgentCoreAdapter
                                ├─ SmolagentsAdapter → 现有执行链路
                                └─ JiuwenAdapter → create_deep_agent → Runner.run_agent_streaming
```

Jiuwen 路径使用原生模型客户端、LocalFunction、MCPTool 和 SkillUseRail。Nexent 原有工具的业务函数及沙箱设施继续复用；Jiuwen 负责模型循环、工具选择和调用。不会在该路径创建 smolagents Agent。

## 如何启用

1. 先执行新增迁移 `deploy/sql/migrations/v2.6.0_1010_agent_core_factory.sql`。迁移为每个智能体版本添加 `agent_core`，存量数据默认 `smolagents`。
2. 后端依赖固定为 `openjiuwen==0.1.18`；单独使用 SDK 时安装 `nexent[jiuwen]`。
3. 通过现有 `POST /agent/update` 接口，在原请求中增加以下字段，并使用现有版本发布流程：

```json
{
  "agent_core": "jiuwen",
  "enable_context_manager": false,
  "provide_run_summary": false,
  "enable_planning": false,
  "enable_protocol_repair_retry": false
}
```

以上为字段片段；请求仍需携带原接口要求的智能体标识等字段。模型需要支持 OpenAI 兼容的工具调用协议。Skills 使用 Nexent 解析后的授权快照，MCP 使用 Nexent 解析后的服务器地址及认证配置。

SDK 直接调用时设置 `AgentConfig(agent_core="jiuwen", ...)`。省略该字段或设置为 `smolagents`，使用原执行链路。当前没有新增前端选择控件。

## 当前能力与边界

| 能力 | 当前实现 |
| --- | --- |
| 本地、内置及现有业务工具 | 业务函数绑定为原生 Jiuwen LocalFunction |
| MCP | 原生 Jiuwen MCPTool；只暴露已配置且可见的工具，保留认证、用户上下文注入和超时控制 |
| Skills | 原生 Rail 加载授权目录；读取与脚本通过原生工具调用，沿用 Nexent 脚本执行及沙箱后端 |
| 并行工具 | 原生工具调用及授权工具列表的 parallel_executor |
| 上下文、历史与流式结果 | 编译授权业务上下文和历史；转换为现有 MessageObserver 事件 |
| 停止与资源回收 | 每次运行独立 owner/session，取消及清理只作用于当前运行 |
| 保存、版本及导入导出 | 保留 agent_core；旧配置默认 smolagents |

首版明确拒绝：子智能体、外部 A2A、Nexent Planning/Verification/Guardrail、协议修复、运行总结、自适应上下文压缩、模型提供方 Prompt Cache 策略及非默认 smolagents 输出协议。检查会返回配置错误；不会自动回退到 smolagents。关闭上下文压缩后仍执行已解析的输入预算检查。

Skills 自动增加的宿主机 bash/read_file 能力已关闭。脚本实际运行位置沿用智能体的 Nexent 沙箱配置。同步业务函数无法被 Python 强制终止时，沿用 ThreadManager 的取消和 STUCK 标记，不能保证强制终止该函数。

## 扩展其他 Core

继承 `AgentCoreAdapter`，实现 `capabilities()`、`validate()`、`run()`，按需实现 `prepare()` 和 `close()`，随后调用 `AgentCoreFactory.register("new_core", NewCoreAdapter)`。SDK 配置支持注册名；后端 API 当前仅开放 `smolagents` 和 `jiuwen`，接入新 Core 时同时扩展其配置校验。

## 验证结果

- 新增正式 D1/D2/D3/D5 用例共 6 个，覆盖工厂、配置、事件、API 边界、原生执行、取消、MCP 超时和运行隔离。
- D3 真实调用 Jiuwen Runner、MCP 客户端、本地工具和 Skill 脚本；仅模型响应及 MCP 服务由确定性本地服务提供。
- Legacy 回归：SDK 执行 45 个、SDK 配置 69 个、数据库操作 67 个、后端配置构建 254 个测试通过。
- 外部模型服务、远端沙箱和实际数据库迁移尚未执行，不能据此宣称生产环境验收完成。

固定测试位于 `test/automation/{d1,d2,d3,d5}`；用例契约和实现绑定位于 `test/cases`、`test/manifests/agent-core-factory.yaml`。
